# smc_analyzer.py
# Módulo para analizar datos de mercado usando Smart Money Concepts (SMC)
# (Actualizado v11.1: Función principal es analyze_m15_pending_pois)

import pandas as pd
import numpy as np
import logging
import time

# Importar configuración y módulos necesarios
try:
    import config
    import mt5_connector
    import data_manager
    from MetaTrader5 import TIMEFRAME_H1, TIMEFRAME_M15, TIMEFRAME_M5
except ImportError as e:
    print(f"FATAL: Error importando módulos en smc_analyzer: {e}")
    exit()
except AttributeError as e:
    print(f"FATAL: Falta una variable de configuración esencial en config.py: {e}")
    exit()

logger = logging.getLogger(__name__)

# --- Mapeo de Temporalidades para Logs ---
# Mover a config.py si no está ya allí
if not hasattr(config, 'TIMEFRAME_MAP') or not hasattr(config, 'timeframe_to_string'):
    print("ADVERTENCIA: TIMEFRAME_MAP o timeframe_to_string no encontrados en config.py. Definiendo localmente.")
    TIMEFRAME_MAP = { TIMEFRAME_H1: "H1", TIMEFRAME_M15: "M15", TIMEFRAME_M5: "M5" }
    def timeframe_to_string(tf_int): return TIMEFRAME_MAP.get(tf_int, f"TF_{tf_int}")
else:
    # Importar desde config si existen
    from config import timeframe_to_string, TIMEFRAME_MAP


# --- Funciones Auxiliares (Reutilizadas) ---
def find_swing_points(df, lookback=3):
    """Identifica puntos de swing básicos (v1.3). Devuelve df con columnas añadidas."""
    default_cols = ['Open','High','Low','Close','Volume','Spread','RealVolume','SwingHigh', 'SwingLow']
    if df is None or df.empty or not all(col in df.columns for col in ['High', 'Low']):
        logger.error("find_swing_points: DataFrame inválido.")
        cols = list(df.columns) + ['SwingHigh', 'SwingLow'] if df is not None and hasattr(df, 'columns') else default_cols
        return pd.DataFrame(columns=cols, index=df.index if df is not None else None)

    logger.debug(f"Buscando swings (lookback={lookback})...")
    highs = df['High']; lows = df['Low']; n = len(df)
    swing_highs_list = [np.nan] * n; swing_lows_list = [np.nan] * n

    if n < (2 * lookback + 1):
        logger.warning(f"Datos insuficientes ({n} velas) para lookback={lookback}.")
    else:
        for i in range(lookback, n - lookback):
            is_sh = True; is_sl = True
            try:
                h_i = highs.iloc[i]; l_i = lows.iloc[i]
                for j in range(1, lookback + 1):
                    if h_i <= highs.iloc[i-j] or h_i <= highs.iloc[i+j]: is_sh = False
                    if l_i >= lows.iloc[i-j] or l_i >= lows.iloc[i+j]: is_sl = False
                    if not is_sh and not is_sl: break
                if is_sh: swing_highs_list[i] = h_i
                if is_sl: swing_lows_list[i] = l_i
            except IndexError:
                logger.error(f"IndexError find_swing_points idx {i}", exc_info=True)
                # No añadir NaN, ya está inicializado

    logger.debug(f"Swings: {sum(not pd.isna(x) for x in swing_highs_list)} H, {sum(not pd.isna(x) for x in swing_lows_list)} L.")
    df_res = df.copy()
    if len(swing_highs_list) == n: df_res['SwingHigh'] = swing_highs_list
    else: logger.error(f"Longitud SwingHigh != DF"); df_res['SwingHigh'] = np.nan
    if len(swing_lows_list) == n: df_res['SwingLow'] = swing_lows_list
    else: logger.error(f"Longitud SwingLow != DF"); df_res['SwingLow'] = np.nan
    return df_res


def find_fvg(df):
    """Identifica Fair Value Gaps (v1)."""
    if df is None or df.empty or not all(col in df.columns for col in ['High', 'Low']):
        logger.error("DataFrame inválido find_fvg.")
        return []
    logger.debug("Buscando FVGs..."); fvgs = []
    if len(df) < 3:
        return fvgs
    for i in range(2, len(df)):
        try:
            low_i = df['Low'].iloc[i]; high_i_minus_2 = df['High'].iloc[i-2]
            high_i = df['High'].iloc[i]; low_i_minus_2 = df['Low'].iloc[i-2]
            # FVG Alcista (Bullish Gap)
            if low_i > high_i_minus_2:
                fvg_top = low_i; fvg_bottom = high_i_minus_2
                if fvg_top > fvg_bottom: # Asegurar espacio real
                     fvgs.append({'index': df.index[i-1], # Asociado a vela intermedia
                                  'top': fvg_top, 'bottom': fvg_bottom,
                                  'type': 'Bullish', 'mid': (fvg_top + fvg_bottom) / 2,
                                  'direction': 'Bullish'}) # Añadir dirección esperada
            # FVG Bajista (Bearish Gap)
            elif high_i < low_i_minus_2:
                fvg_top = low_i_minus_2; fvg_bottom = high_i
                if fvg_top > fvg_bottom: # Asegurar espacio real
                     fvgs.append({'index': df.index[i-1], # Asociado a vela intermedia
                                  'top': fvg_top, 'bottom': fvg_bottom,
                                  'type': 'Bearish', 'mid': (fvg_top + fvg_bottom) / 2,
                                  'direction': 'Bearish'}) # Añadir dirección esperada
        except IndexError:
            logger.error(f"IndexError find_fvg idx {i}.", exc_info=True)
            continue
    logger.debug(f"{len(fvgs)} FVGs encontrados en el DataFrame proporcionado."); return fvgs


def _check_mitigation(poi_candidate, df, poi_iloc, ignore_first_n_candles=4):
    """
    Verifica si el FVG ya ha sido mitigado por un RETORNO del precio al 50%,
    ignorando las primeras N velas después del FVG.
    (v2.5 - Adaptada para FVG)
    """
    poi_index = poi_candidate.get('index')
    # Usar la función importada o definida localmente
    tf_string = timeframe_to_string(config.TIMEFRAME_LTF)
    poi_low = poi_candidate.get('bottom') # Usar bottom/top para FVG
    poi_high = poi_candidate.get('top')
    poi_50 = poi_candidate.get('mid')
    poi_direction = poi_candidate.get('direction')
    poi_type = poi_candidate.get('type') # Aunque aquí asumimos FVG

    if poi_low is None or poi_high is None or poi_50 is None or poi_direction is None:
        logger.error(f"FVG Val({poi_index} {tf_string}): Datos insuficientes check mitigación v2.5.")
        return True

    logger.debug(f"--- Iniciando Check Mitigación (v2.5) para FVG @ {poi_index} ---")
    logger.debug(f"    Rango FVG: {poi_low:.5f} - {poi_high:.5f}, Nivel 50%: {poi_50:.5f}, Dirección: {poi_direction}")

    # El índice del FVG es la vela intermedia (i-1).
    # El escaneo de mitigación debe empezar DESPUÉS de la vela 'i' (índice i-1 + 2).
    scan_start_iloc = poi_iloc + 2
    mitigation_scan_start_iloc = scan_start_iloc + ignore_first_n_candles

    if mitigation_scan_start_iloc >= len(df):
        logger.debug(f"FVG Val({poi_index} {tf_string}): No hay suficientes velas post-FVG (después de ignorar {ignore_first_n_candles}). No Mitigado.")
        return False

    candles_to_check = df.iloc[mitigation_scan_start_iloc:]
    if candles_to_check.empty:
        logger.debug(f"FVG Val({poi_index} {tf_string}): Ventana mitigación (post-ignorar) vacía. No Mitigado.")
        return False

    mitigated = False
    try:
        for i in range(len(candles_to_check)):
            candle_high = candles_to_check['High'].iloc[i]
            candle_low = candles_to_check['Low'].iloc[i]
            mitigation_time = candles_to_check.index[i]

            if poi_direction == 'Bullish': # FVG Alcista -> Mitigado si precio VUELVE a bajar <= 50%
                if candle_low <= poi_50:
                    logger.warning(f"FVG Val({poi_index} {tf_string}): MITIGADO (Bullish FVG). Low {candle_low:.5f} <= 50% {poi_50:.5f} en {mitigation_time}")
                    mitigated = True; break
            elif poi_direction == 'Bearish': # FVG Bajista -> Mitigado si precio VUELVE a subir >= 50%
                if candle_high >= poi_50:
                    logger.warning(f"FVG Val({poi_index} {tf_string}): MITIGADO (Bearish FVG). High {candle_high:.5f} >= 50% {poi_50:.5f} en {mitigation_time}")
                    mitigated = True; break

        if not mitigated: logger.debug(f"FVG Val({poi_index} {tf_string}): No mitigado (v2.5).")

    except Exception as e:
         logger.error(f"Error durante check_mitigation v2.5 para FVG @ {poi_index}: {e}", exc_info=True)
         mitigated = True # Asumir mitigado si hay error

    logger.debug(f"--- Fin Check Mitigación (v2.5) para FVG @ {poi_index} -> Resultado: {mitigated} ---")
    return mitigated


# --- FUNCIÓN PRINCIPAL DE ANÁLISIS (v11.1 - Solo FVGs Pendientes) ---
def analyze_m15_pending_pois(m15_df, num_candles=96): # Renombrada en v11.1
    """
    Analiza las últimas N velas M15 y devuelve una lista de FVGs
    que aún no han sido mitigados.
    """
    logger.info(f"--- Iniciando Análisis FVGs Pendientes M15 (v11.1 - Rango {num_candles}) ---")
    if m15_df is None or m15_df.empty or len(m15_df) < num_candles:
        logger.warning(f"Datos M15 insuficientes ({len(m15_df) if m15_df is not None else 0} velas).")
        return [] # Devolver lista vacía

    try:
        # 1. Seleccionar el rango de análisis
        analysis_df = m15_df.iloc[-num_candles:]

        # 2. Encontrar todos los FVGs en el rango
        all_fvgs_in_range = find_fvg(analysis_df)
        if not all_fvgs_in_range:
            logger.info("No se encontraron FVGs en el rango de análisis.")
            return []

        # 3. Filtrar los FVGs que ya están mitigados
        pending_pois = []
        logger.info(f"Verificando mitigación para {len(all_fvgs_in_range)} FVGs candidatos...")
        for fvg in all_fvgs_in_range:
            try:
                # Necesitamos el iloc del FVG en el DataFrame COMPLETO (m15_df)
                fvg_iloc = m15_df.index.get_loc(fvg['index'])
                # Llamar a _check_mitigation pasando el DF completo
                if not _check_mitigation(fvg, m15_df, fvg_iloc, ignore_first_n_candles=4):
                    # Si NO está mitigado, añadirlo a la lista de pendientes
                    logger.info(f"+++ FVG Pendiente Confirmado @ {fvg['index']} ({fvg.get('direction')}) +++")
                    # Añadir claves estándar para POI si no existen
                    fvg['type'] = 'FVG_Pending' # Renombrar tipo para claridad
                    fvg['high'] = fvg.get('top')
                    fvg['low'] = fvg.get('bottom')
                    fvg['level_50'] = fvg.get('mid')
                    fvg['timeframe'] = config.TIMEFRAME_LTF # Añadir timeframe
                    pending_pois.append(fvg)
                # else: El log de mitigación ya se hizo en _check_mitigation
            except KeyError: logger.error(f"Índice FVG {fvg.get('index')} no encontrado en DF completo para check mitigación.")
            except Exception as e: logger.error(f"Error verificando mitigación para FVG @ {fvg.get('index')}: {e}", exc_info=True)

        logger.info(f"Análisis completado: {len(pending_pois)} FVGs pendientes encontrados.")
        return pending_pois # Devolver lista de FVGs pendientes

    except Exception as e:
        logger.error(f"Error CRÍTICO durante análisis M15 v11.1: {e}", exc_info=True)
        return [] # Devolver lista vacía en caso de error


# --- FUNCIONES ANTIGUAS (Comentadas o Eliminadas) ---
# def find_latest_bos_m15(...)
# def find_m15_poi_in_range(...)
# def analyze_m15_setup(...) # Reemplazada por analyze_m15_pending_pois
# def _check_liquidity_sweep(...) # No se usa en esta versión
# def determine_market_structure(...)
# def define_context(...)
# def validate_poi(...)
# def analyze_h1_context(...)
# def analyze_m15_confirmation(...)


# --- Bloque de prueba (Adaptado para v11.1) ---
if __name__ == "__main__":
    if not logging.getLogger('').hasHandlers(): logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)-15s - %(levelname)-8s - %(message)s', handlers=[logging.StreamHandler()])
    print("Ejecutando pruebas del módulo smc_analyzer (v11.1 - FVGs Pendientes)...")
    logger.info("Iniciando pruebas unitarias de smc_analyzer (v11.1)...")
    connected_mt5 = False
    try:
        if mt5_connector.connect_mt5():
            connected_mt5 = True
            print("\n--- Obteniendo datos de prueba M15 ---")
            num_candles_to_fetch = config.LOOKBACK_M15
            num_analysis_candles = config.STRATEGY_M15_RANGE_CANDLES

            if data_manager.update_data(config.TIMEFRAME_LTF):
                 m15_data = data_manager.get_data(config.TIMEFRAME_LTF)
                 if m15_data is None or len(m15_data) < num_analysis_candles:
                      logger.warning(f"Datos insuficientes ({len(m15_data)}), intentando obtener más...")
                      m15_data = mt5_connector.get_ohlc_data(config.SYMBOL, config.TIMEFRAME_LTF, num_candles_to_fetch)
            else: m15_data = None

            if m15_data is not None and not m15_data.empty and len(m15_data) >= num_analysis_candles:
                print(f"Datos M15 obtenidos: {len(m15_data)} velas.")
                print(f"\n--- Probando analyze_m15_pending_pois (últimas {num_analysis_candles} velas) ---")
                # Llamar a la nueva función principal
                pending_pois_list = analyze_m15_pending_pois(m15_data, num_candles=num_analysis_candles)

                if isinstance(pending_pois_list, list):
                    print(f"\n*** Análisis Completado: {len(pending_pois_list)} FVGs Pendientes Encontrados ***")
                    if pending_pois_list:
                        print("   (Mostrando los primeros 10)")
                        for i, poi in enumerate(pending_pois_list[:10]):
                             poi_type = poi.get('type', 'N/A'); poi_idx = poi.get('index', 'N/A'); poi_low = poi.get('low'); poi_high = poi.get('high')
                             poi_dir = poi.get('direction', 'N/A')
                             poi_low_str = f"{poi_low:.5f}" if poi_low is not None else "N/A"; poi_high_str = f"{poi_high:.5f}" if poi_high is not None else "N/A"
                             print(f"    - {i+1}) {poi_type} {poi_dir} @ {poi_idx} ({poi_low_str} - {poi_high_str})")
                    else:
                        print("   No se encontraron FVGs pendientes que cumplan los criterios.")
                else:
                    print("\n--- El análisis M15 falló o no produjo resultados (no devolvió una lista). ---")

            elif m15_data is not None:
                 logger.error(f"Fallo al obtener suficientes datos M15 ({len(m15_data)} < {num_analysis_candles}).")
                 print(f"\n--- Fallo al obtener suficientes datos M15 ({len(m15_data)} < {num_analysis_candles}) ---")
            else:
                 logger.error("Fallo al obtener datos M15 para la prueba.")
                 print("\n--- Fallo al obtener datos M15 para la prueba ---")
        else:
            logger.critical("Fallo al conectar a MT5."); print("\n--- Fallo al conectar a MT5 ---")
    except Exception as e:
         logger.critical(f"Error inesperado CRÍTICO: {e}", exc_info=True); print(f"Error inesperado: {e}")
    finally:
        if connected_mt5: logger.info("Desconectando MT5..."); mt5_connector.disconnect_mt5()
        logger.info("Pruebas smc_analyzer finalizadas."); print("\nPruebas smc_analyzer finalizadas.")