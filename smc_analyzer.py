# smc_analyzer.py
# Módulo para analizar datos de mercado usando Smart Money Concepts (SMC)
# (Actualizado v10.3: Eliminada verificación mitigación inicial en find_m15_poi)

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
TIMEFRAME_MAP = { TIMEFRAME_H1: "H1", TIMEFRAME_M15: "M15", TIMEFRAME_M5: "M5" }
def timeframe_to_string(tf_int): return TIMEFRAME_MAP.get(tf_int, f"TF_{tf_int}")

# --- Funciones Auxiliares de Análisis de Velas ---
def find_swing_points(df, lookback=3):
    """Identifica puntos de swing básicos (v1.3). Devuelve df con columnas añadidas."""
    # ... (Código find_swing_points v1.3 igual que v7.5) ...
    default_cols = ['Open','High','Low','Close','Volume','Spread','RealVolume','SwingHigh', 'SwingLow']
    if df is None or df.empty or not all(col in df.columns for col in ['High', 'Low']): logger.error("find_swing_points: DataFrame inválido."); cols = list(df.columns) + ['SwingHigh', 'SwingLow'] if df is not None and hasattr(df, 'columns') else default_cols; return pd.DataFrame(columns=cols, index=df.index if df is not None else None)
    logger.debug(f"Buscando swings (lookback={lookback})..."); highs = df['High']; lows = df['Low']; n = len(df); swing_highs_list = [np.nan] * n; swing_lows_list = [np.nan] * n
    if n < (2 * lookback + 1): logger.warning(f"Datos insuficientes ({n} velas) para lookback={lookback}.")
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
            except IndexError: logger.error(f"IndexError find_swing_points idx {i}", exc_info=True)
    logger.debug(f"Swings: {sum(not pd.isna(x) for x in swing_highs_list)} H, {sum(not pd.isna(x) for x in swing_lows_list)} L.")
    df_res = df.copy()
    if len(swing_highs_list) == n: df_res['SwingHigh'] = swing_highs_list
    else: logger.error(f"Longitud SwingHigh != DF"); df_res['SwingHigh'] = np.nan
    if len(swing_lows_list) == n: df_res['SwingLow'] = swing_lows_list
    else: logger.error(f"Longitud SwingLow != DF"); df_res['SwingLow'] = np.nan
    return df_res

def find_fvg(df):
    """Identifica Fair Value Gaps (v1)."""
    # ... (Código find_fvg v1 sin cambios) ...
    if df is None or df.empty or not all(col in df.columns for col in ['High', 'Low']): logger.error("DataFrame inválido find_fvg."); return []
    logger.debug("Buscando FVGs..."); fvgs = []
    if len(df) < 3: return fvgs
    for i in range(2, len(df)):
        try:
            low_i = df['Low'].iloc[i]; high_i_minus_2 = df['High'].iloc[i-2]; high_i = df['High'].iloc[i]; low_i_minus_2 = df['Low'].iloc[i-2]
            if low_i > high_i_minus_2: # Bullish FVG
                 if low_i > high_i_minus_2: fvgs.append({'index': df.index[i-1], 'top': low_i, 'bottom': high_i_minus_2, 'type': 'Bullish', 'mid': (low_i + high_i_minus_2) / 2})
            elif high_i < low_i_minus_2: # Bearish FVG
                 if low_i_minus_2 > high_i: fvgs.append({'index': df.index[i-1], 'top': low_i_minus_2, 'bottom': high_i, 'type': 'Bearish', 'mid': (low_i_minus_2 + high_i) / 2})
        except IndexError: logger.error(f"IndexError find_fvg idx {i}.", exc_info=True); continue
    logger.debug(f"{len(fvgs)} FVGs encontrados."); return fvgs

def _check_mitigation(poi_candidate, df, poi_iloc):
    """Verifica si el POI ya ha sido mitigado (v1 básica - toca 50%)."""
    # ... (Código _check_mitigation v1.1 sin cambios) ...
    poi_index = poi_candidate.get('index'); tf_string = timeframe_to_string(poi_candidate.get('timeframe'))
    poi_low = poi_candidate.get('low'); poi_high = poi_candidate.get('high'); poi_50 = poi_candidate.get('level_50')
    if poi_low is None or poi_high is None or poi_50 is None: logger.error(f"POI Val({poi_index} {tf_string}): Datos insuficientes."); return True
    mitigation_scan_start_iloc = poi_iloc + 1 if poi_candidate.get('type') != 'FVG' else poi_iloc
    if mitigation_scan_start_iloc >= len(df): logger.debug(f"POI Val({poi_index} {tf_string}): No hay velas post-POI."); return False
    candles_after_poi = df.iloc[mitigation_scan_start_iloc:]
    if candles_after_poi.empty: logger.debug(f"POI Val({poi_index} {tf_string}): Ventana mitigación vacía."); return False
    mitigated = False; poi_direction = poi_candidate.get('direction'); min_low_after = candles_after_poi['Low'].min(); max_high_after = candles_after_poi['High'].max()
    if poi_direction == 'Bearish':
        if min_low_after <= poi_50: logger.warning(f"POI Val({poi_index} {tf_string}): MITIGADO (Bearish)"); mitigated = True
        else: logger.debug(f"POI Val({poi_index} {tf_string}): No mitigado (Bearish).")
    elif poi_direction == 'Bullish':
        if max_high_after >= poi_50: logger.warning(f"POI Val({poi_index} {tf_string}): MITIGADO (Bullish)"); mitigated = True
        else: logger.debug(f"POI Val({poi_index} {tf_string}): No mitigado (Bullish).")
    return mitigated

def _check_liquidity_sweep(poi_candidate, df, poi_iloc, lookback=10):
    """Verifica barrido de liquidez local ANTES/DURANTE formación del POI (v2.1)."""
    # ... (Código _check_liquidity_sweep v2.1 sin cambios) ...
    poi_index = poi_candidate.get('index'); tf_string = timeframe_to_string(poi_candidate.get('timeframe'))
    logger.debug(f"--- Iniciando Check Barrido Liquidez Local (v2.1) para POI @ {poi_index} ---")
    if poi_iloc < lookback: logger.debug(f"POI Val({poi_index} {tf_string}): Insuficientes velas previas ({poi_iloc})."); return False
    sweep_scan_start_iloc = max(0, poi_iloc - lookback); sweep_scan_end_iloc = poi_iloc -1
    if sweep_scan_start_iloc >= sweep_scan_end_iloc: logger.debug(f"POI Val({poi_index} {tf_string}): Ventana escaneo barrido inválida."); return False
    window_before_poi = df.iloc[sweep_scan_start_iloc:sweep_scan_end_iloc + 1]
    if window_before_poi.empty: logger.debug(f"POI Val({poi_index} {tf_string}): Ventana previa vacía."); return False
    target_high_before = window_before_poi['High'].max(); target_low_before = window_before_poi['Low'].min()
    poi_type = poi_candidate.get('type')
    if poi_type == 'OB': poi_formation_start_iloc = poi_iloc; poi_formation_end_iloc = poi_iloc
    elif poi_type == 'FVG': poi_formation_start_iloc = max(0, poi_iloc - 1); poi_formation_end_iloc = min(len(df) - 1, poi_iloc + 1)
    else: poi_formation_start_iloc = poi_iloc; poi_formation_end_iloc = poi_iloc
    poi_formation_candles = df.iloc[poi_formation_start_iloc : poi_formation_end_iloc + 1]
    if poi_formation_candles.empty: logger.debug(f"POI Val({poi_index} {tf_string}): Velas formación POI vacías."); return False
    poi_direction = poi_candidate.get('direction'); swept = False
    if poi_direction == 'Bearish':
        sweep_price = poi_formation_candles['High'].max()
        if sweep_price > target_high_before: logger.info(f"POI Val({poi_index} {tf_string}): BARRIDO LIQ ALCISTA OK (Local)."); swept = True
        else: logger.debug(f"POI Val({poi_index} {tf_string}): Sin barrido Liq Alcista (Local).")
    elif poi_direction == 'Bullish':
        sweep_price = poi_formation_candles['Low'].min()
        if sweep_price < target_low_before: logger.info(f"POI Val({poi_index} {tf_string}): BARRIDO LIQ BAJISTA OK (Local)."); swept = True
        else: logger.debug(f"POI Val({poi_index} {tf_string}): Sin barrido Liq Bajista (Local).")
    else: logger.warning(f"POI Val({poi_index} {tf_string}): Dirección POI desconocida."); swept = False
    logger.debug(f"--- Fin Check Barrido Liquidez Local para POI @ {poi_index} -> Resultado: {swept} ---"); return swept


# --- LÓGICA ESTRATEGIA RANGO FIJO + ÚLTIMO BOS RELATIVO (v10.0) ---

def find_last_bos_in_range(df_with_swings, range_high_idx, range_low_idx):
    """
    Encuentra el último BOS (alcista o bajista) que ocurrió ANTES
    de que se formaran el High o Low máximo del rango.
    (v10.0)
    """
    # ... (Código find_last_bos_in_range v10.0 sin cambios) ...
    logger.debug(f"Buscando último BOS relativo al rango {range_low_idx} - {range_high_idx}...")
    if df_with_swings is None or df_with_swings.empty: return None
    swing_highs = df_with_swings['SwingHigh'].dropna(); swing_lows = df_with_swings['SwingLow'].dropna()
    last_bos_up = None; last_bos_down = None
    if len(swing_highs) >= 2:
        highs_before_range_max = swing_highs[swing_highs.index < range_high_idx]
        if len(highs_before_range_max) >= 2:
            for i in range(len(highs_before_range_max) - 1, 0, -1):
                last_h_idx = highs_before_range_max.index[i]; last_h_price = highs_before_range_max.iloc[i]
                prev_h_idx = highs_before_range_max.index[i-1]; prev_h_price = highs_before_range_max.iloc[i-1]
                intervening_lows = swing_lows[(swing_lows.index > prev_h_idx) & (swing_lows.index < last_h_idx)]
                if last_h_price > prev_h_price and not intervening_lows.empty:
                    last_bos_up = {'type': 'BOS_Up', 'index': last_h_idx, 'broken_level': prev_h_price, 'price': last_h_price}
                    logger.debug(f"  - Último BOS_Up encontrado @ {last_bos_up['index']}")
                    break
    if len(swing_lows) >= 2:
        lows_before_range_min = swing_lows[swing_lows.index < range_low_idx]
        if len(lows_before_range_min) >= 2:
             for i in range(len(lows_before_range_min) - 1, 0, -1):
                last_l_idx = lows_before_range_min.index[i]; last_l_price = lows_before_range_min.iloc[i]
                prev_l_idx = lows_before_range_min.index[i-1]; prev_l_price = lows_before_range_min.iloc[i-1]
                intervening_highs = swing_highs[(swing_highs.index > prev_l_idx) & (swing_highs.index < last_l_idx)]
                if last_l_price < prev_l_price and not intervening_highs.empty:
                    last_bos_down = {'type': 'BOS_Down', 'index': last_l_idx, 'broken_level': prev_l_price, 'price': last_l_price}
                    logger.debug(f"  - Último BOS_Down encontrado @ {last_bos_down['index']}")
                    break
    final_bos = None
    if last_bos_up and last_bos_down: final_bos = last_bos_up if last_bos_up['index'] > last_bos_down['index'] else last_bos_down
    elif last_bos_up: final_bos = last_bos_up
    elif last_bos_down: final_bos = last_bos_down
    if final_bos: logger.info(f"Último BOS M15 relativo al rango: {final_bos['type']} @ {final_bos['index']}")
    else: logger.info("No se detectó BOS M15 relevante dentro del rango.")
    return final_bos


def find_m15_poi_in_range(df, tr_range, bias, fvgs):
    """
    Busca el POI específico (OB+Sweep+FVG) en la zona correcta del TR definido.
    (v10.3: Eliminada verificación de mitigación inicial).
    """
    if not bias or bias == 'Undetermined' or not isinstance(tr_range, dict):
        logger.debug(f"Bias ({bias}) no válido o TR no definido para buscar POI.")
        return None

    timeframe = config.TIMEFRAME_LTF # M15
    tf_string = timeframe_to_string(timeframe)
    logger.info(f"Buscando POI M15 ({bias}) en TR {tr_range['low']:.5f}-{tr_range['high']:.5f}...")

    premium_threshold = tr_range['eq']; discount_threshold = tr_range['eq']
    search_zone_low = discount_threshold if bias == 'Bearish' else tr_range['low']
    search_zone_high = tr_range['high'] if bias == 'Bearish' else premium_threshold
    logger.debug(f"Buscando POI M15 en Zona {bias}: {search_zone_low:.5f} - {search_zone_high:.5f}")

    poi = None
    num_candles_in_df = len(df)
    start_iloc = num_candles_in_df - 2
    end_iloc = max(0, num_candles_in_df - 96 - 1) # Buscar en las últimas 96 velas

    relevant_fvgs = [fvg for fvg in fvgs if (bias=='Bullish' and fvg['type']=='Bullish') or (bias=='Bearish' and fvg['type']=='Bearish')]

    for i in range(start_iloc, end_iloc, -1):
        if i < 1: break
        try:
            candle = df.iloc[i]; candle_index = df.index[i]
            is_bullish_candle = candle['Close'] > candle['Open']; is_bearish_candle = candle['Close'] < candle['Open']
            candle_high = candle['High']; candle_low = candle['Low']

            # Condición 1: Tipo Correcto
            is_correct_type = (bias == 'Bearish' and is_bullish_candle) or (bias == 'Bullish' and is_bearish_candle)
            if not is_correct_type: continue

            # Condición 2: Dentro de Zona Premium/Discount
            is_in_zone = (bias == 'Bearish' and candle_low >= search_zone_low and candle_high <= search_zone_high) or \
                         (bias == 'Bullish' and candle_high <= search_zone_high and candle_low >= search_zone_low)
            if not is_in_zone: continue

            logger.debug(f"OB Candidato M15 @ {candle_index}. Verificando FVG y Sweep...")

            # Condición 3: FVG Asociado (Flexible)
            fvg_found = False; fvg_details = None
            fvg_search_limit = 5; fvg_scan_start_iloc = i + 1; fvg_scan_end_iloc = min(len(df), fvg_scan_start_iloc + fvg_search_limit)
            fvg_check_indices = df.index[fvg_scan_start_iloc:fvg_scan_end_iloc]
            if not fvg_check_indices.empty:
                for fvg in relevant_fvgs:
                    if fvg['index'] in fvg_check_indices: fvg_found = True; fvg_details = fvg; logger.debug(f"  - FVG Asociado OK @ {fvg['index']}"); break
            if not fvg_found: logger.debug("  - FVG Asociado NO encontrado."); continue

            # Condición 4: Barrido de Liquidez Local
            ob_candidate_dict = {'index': candle_index, 'type': 'OB', 'direction': bias, 'timeframe': timeframe}
            if _check_liquidity_sweep(ob_candidate_dict, df, i, lookback=5):
                logger.info(f"¡POI M15 Encontrado! OB @ {candle_index} (barrió liq + FVG cercano)")
                poi_high = candle['High'] if bias == 'Bearish' else candle['Open']
                poi_low = candle['Open'] if bias == 'Bearish' else candle['Low']
                poi = {'type': 'OB+FVG+Sweep', 'timeframe': timeframe, 'index': candle_index, 'high': poi_high, 'low': poi_low, 'level_50': (poi_high + poi_low) / 2, 'direction': bias, 'fvg_details': fvg_details}
                # NO verificar mitigación aquí, devolver el primer candidato válido encontrado hacia atrás
                break
            else: logger.debug("  - Barrido Liquidez NO encontrado."); continue
        except Exception as e: logger.error(f"Error buscando POI M15 específico idx {i}: {e}", exc_info=True); continue

    # Devolver el POI encontrado (sin check de mitigación aquí)
    if poi:
        logger.info(f"POI M15 (OB+Sweep+FVG) final seleccionado @ {poi['index']}.")
        return poi
    else:
        logger.info("No se encontró POI M15 (OB+Sweep+FVG) en la zona.");
        return None


# --- FUNCIÓN PRINCIPAL DE ANÁLISIS (v10.1) ---
def analyze_m15_setup(m15_df, num_candles=96):
    """
    Analiza las últimas N velas M15: Define Rango, encuentra último BOS INTERNO para Bias,
    y busca el POI específico (OB+Sweep+FVG) en la zona correcta.
    (v10.3: Llama a find_m15_poi_in_range v10.3)
    """
    logger.info(f"--- Iniciando Análisis de Setup M15 (v10.3 - Rango {num_candles}) ---")
    if m15_df is None or m15_df.empty or len(m15_df) < num_candles:
        logger.warning(f"Datos M15 insuficientes ({len(m15_df) if m15_df is not None else 0} velas).")
        return None

    try:
        # 1. Seleccionar Rango y Encontrar Swings
        range_df = m15_df.iloc[-num_candles:]
        df_with_swings = find_swing_points(range_df, lookback=3)

        # 2. Definir TR de 24h y obtener índices de High/Low
        high_maximo_price = range_df['High'].max(); low_minimo_price = range_df['Low'].min()
        high_maximo_idx = range_df['High'].idxmax(); low_minimo_idx = range_df['Low'].idxmin()
        if pd.isna(high_maximo_price) or pd.isna(low_minimo_price): raise ValueError("NaN en max/min rango")
        eq_range = (high_maximo_price + low_minimo_price) / 2
        tr_24h = {'low': low_minimo_price, 'high': high_maximo_price, 'eq': eq_range}
        logger.info(f"TR {num_candles} velas: L={tr_24h['low']:.5f} @ {low_minimo_idx}, H={tr_24h['high']:.5f} @ {high_maximo_idx}, EQ={tr_24h['eq']:.5f}")

        # 3. Determinar Bias por Último BOS DENTRO del Rango y ANTES de los extremos
        latest_bos = find_last_bos_in_range(df_with_swings, high_maximo_idx, low_minimo_idx)
        bias = 'Undetermined'
        if latest_bos: bias = 'Bullish' if latest_bos['type'] == 'BOS_Up' else 'Bearish'
        logger.info(f"Bias M15 determinado por último BOS interno: {bias}")

        # 4. Encontrar FVGs en el rango
        recent_fvgs = find_fvg(range_df)

        # 5. Buscar POI específico si hay Bias y TR
        high_prob_poi = None
        if bias != 'Undetermined' and tr_24h:
            high_prob_poi = find_m15_poi_in_range(m15_df, tr_24h, bias, recent_fvgs) # Llama a v10.3

        # 6. Preparar y devolver resultados
        analysis_result = {'trading_range_24h': tr_24h, 'last_bos_m15': latest_bos, 'bias_m15': bias, 'high_probability_poi': high_prob_poi}
        if high_prob_poi: logger.info(f"*** ¡Setup M15 Encontrado! POI: {high_prob_poi['type']} @ {high_prob_poi['index']} ***")
        elif bias != 'Undetermined': logger.info(f"Bias M15 es {bias}, pero no se encontró POI válido.")
        else: logger.info("Bias M15 indeterminado.")
        return analysis_result

    except Exception as e:
        logger.error(f"Error CRÍTICO durante análisis M15 v10.3: {e}", exc_info=True)
        return None


# --- FUNCIONES ANTIGUAS (Comentadas o Eliminadas) ---
# ...

# --- Bloque de prueba (Adaptado para v10.3) ---
if __name__ == "__main__":
    if not logging.getLogger('').hasHandlers(): logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)-15s - %(levelname)-8s - %(message)s', handlers=[logging.StreamHandler()])
    print("Ejecutando pruebas del módulo smc_analyzer (v10.3 - Rango Fijo M15)...")
    logger.info("Iniciando pruebas unitarias de smc_analyzer (v10.3)...")
    connected_mt5 = False
    try:
        if mt5_connector.connect_mt5():
            connected_mt5 = True; print("\n--- Obteniendo datos de prueba M15 ---")
            num_candles_to_fetch = 150
            if data_manager.update_data(config.TIMEFRAME_LTF):
                 m15_data = data_manager.get_data(config.TIMEFRAME_LTF)
                 if m15_data is None or len(m15_data) < 96:
                      logger.warning("Intentando obtener más datos M15...")
                      m15_data = mt5_connector.get_ohlc_data(config.SYMBOL, config.TIMEFRAME_LTF, num_candles_to_fetch)
            else: m15_data = None
            if m15_data is not None and not m15_data.empty and len(m15_data) >= 96:
                print(f"Datos M15 obtenidos: {len(m15_data)} velas.")
                print("\n--- Probando analyze_m15_setup ---")
                analysis_result = analyze_m15_setup(m15_data, num_candles=96)
                if analysis_result:
                    print("\n*** Resultado del Análisis M15 ***")
                    print(f"  Rango 96 Velas: {analysis_result.get('trading_range_24h')}")
                    print(f"  Último BOS M15: {analysis_result.get('last_bos_m15')}")
                    print(f"  Sesgo M15: {analysis_result.get('bias_m15')}")
                    poi = analysis_result.get('high_probability_poi')
                    if poi:
                        print("\n  --- POI de Alta Probabilidad Encontrado ---")
                        print(f"     Tipo: {poi.get('type')}") # ... (resto del print) ...
                    else: print("\n  --- No se encontró POI de Alta Probabilidad ---")
                else: print("\n--- El análisis M15 falló o no produjo resultados. ---")
            elif m15_data is not None: logger.error(f"Fallo al obtener suficientes datos M15 ({len(m15_data)} < 96)."); print(f"\n--- Fallo al obtener suficientes datos M15 ({len(m15_data)} < 96) ---")
            else: logger.error("Fallo al obtener datos M15."); print("\n--- Fallo al obtener datos M15 ---")
        else: logger.critical("Fallo al conectar a MT5."); print("\n--- Fallo al conectar a MT5 ---")
    except Exception as e: logger.critical(f"Error inesperado CRÍTICO: {e}", exc_info=True); print(f"Error inesperado: {e}")
    finally:
        if connected_mt5: logger.info("Desconectando MT5..."); mt5_connector.disconnect_mt5()
        logger.info("Pruebas smc_analyzer finalizadas."); print("\nPruebas smc_analyzer finalizadas.")