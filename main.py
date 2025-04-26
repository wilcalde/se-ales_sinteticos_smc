# main.py
# Orquestador principal para SMC VIX Signal Bot (Estrategia M15 Rango Fijo)
# (v1.3: Importa timeframe_to_string desde config)

import time
import asyncio
import logging
from datetime import datetime, timedelta, timezone
import pandas as pd # Necesario para isinstance(poi_index, pd.Timestamp) en format_alert
import html # Necesario para escape_html en send_welcome_message

# --- Importar Módulos ---
try:
    import config
    from config import timeframe_to_string # <-- Importar desde config
    import mt5_connector
    import data_manager
    import smc_analyzer
    from notifiers import telegram_notifier
    print("Módulos principales importados correctamente.")

    # Configuración de Logging
    # ... (igual que v1.2) ...
    log_level_map = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR, 'CRITICAL': logging.CRITICAL}
    effective_log_level = log_level_map.get(config.LOG_LEVEL.upper(), logging.INFO)
    log_formatter = logging.Formatter('%(asctime)s - %(name)-15s - %(levelname)-8s - %(message)s')
    log_file_handler = logging.FileHandler(config.LOG_FILE, mode='a'); log_file_handler.setFormatter(log_formatter)
    log_console_handler = logging.StreamHandler(); log_console_handler.setFormatter(log_formatter)
    root_logger = logging.getLogger('');
    for handler in root_logger.handlers[:]: root_logger.removeHandler(handler)
    root_logger.addHandler(log_file_handler); root_logger.addHandler(log_console_handler)
    root_logger.setLevel(effective_log_level)
    logger = logging.getLogger(__name__)

except ImportError as e: print(f"FATAL: Error importando módulos en main.py: {e}"); exit()
except AttributeError as e: print(f"FATAL: Falta config esencial: {e}"); exit()
except Exception as e: print(f"FATAL: Error inicializando logging: {e}"); exit()


# --- Estado Global ---
last_valid_poi = None
arrival_alert_sent = False

# --- Funciones Auxiliares ---
def get_seconds_until_next_m15_candle():
    """Calcula los segundos hasta el inicio de la próxima vela M15."""
    # ... (código igual que v1.2) ...
    now_utc = datetime.now(timezone.utc); next_minute = (now_utc.minute // 15 + 1) * 15
    if next_minute >= 60:
        next_hour = now_utc.hour + 1; next_minute = 0
        if next_hour >= 24: next_hour = 0; next_day = now_utc.date() + timedelta(days=1); next_candle_time = datetime(next_day.year, next_day.month, next_day.day, next_hour, next_minute, 0, tzinfo=timezone.utc)
        else: next_candle_time = now_utc.replace(hour=next_hour, minute=next_minute, second=0, microsecond=0)
    else: next_candle_time = now_utc.replace(minute=next_minute, second=0, microsecond=0)
    delta = next_candle_time - now_utc; wait_seconds = delta.total_seconds() + 2.0
    logger.debug(f"Próxima vela M15 UTC: {next_candle_time}. Esperando {wait_seconds:.2f} segundos.")
    return max(1.0, wait_seconds)

# --- Función de Bienvenida (Usa formato HTML) ---
async def send_welcome_message():
    """Envía el mensaje inicial de bienvenida e instrucciones."""
    logger.info("Enviando mensaje de bienvenida a Telegram...")
    # Necesitamos importar escape_html aquí
    from html import escape as escape_html
    # Usar el parámetro de config para el número de velas
    num_candles_str = escape_html(str(config.STRATEGY_M15_RANGE_CANDLES))
    symbol_str = escape_html(config.SYMBOL)
    tf_ltf_str = escape_html(timeframe_to_string(config.TIMEFRAME_LTF)) # M15
    tf_conf_str = escape_html(timeframe_to_string(config.TIMEFRAME_CONFIRMATION)) # M5/M1

    welcome_text = (
        f"🚀 <b>{symbol_str} SMC Signal Bot Iniciado</b> 🚀\n\n"
        f"¡Hola! Estoy listo para analizar el mercado {tf_ltf_str} de {symbol_str} buscando setups de alta probabilidad basados en Smart Money Concepts (estrategia de Rango Fijo + Último BOS).\n\n"
        f"<b>¿Qué haré?</b>\n"
        f"1. Analizaré las últimas {num_candles_str} velas {tf_ltf_str} cada 15 minutos.\n"
        f"2. Identificaré el Trading Range (High/Low) de ese período.\n"
        f"3. Buscaré el último BOS (Break of Structure) para determinar el sesgo (Bias).\n"
        f"4. Si encuentro un POI válido (OB+FVG+Sweep no mitigado) en la zona correcta (Premium/Discount), te enviaré una alerta.\n"
        f"5. Cuando el precio llegue a un POI válido identificado, te enviaré otra alerta sugiriendo buscar confirmación (CHOCH) en {tf_conf_str}.\n\n"
        f"<b>Importante:</b>\n"
        f"- Estas son <i>alertas</i>, NO señales de entrada directa.\n"
        f"- <b>Tú eres responsable</b> de analizar la confirmación en LTF y gestionar tu riesgo.\n"
        f"- El bot se ejecuta en segundo plano. Puedes detenerlo con <code>Ctrl+C</code> en la terminal.\n\n"
        f"¡Mucha suerte! 👍"
    )
    success = await telegram_notifier.send_telegram_message_async(welcome_text)
    if success: logger.info("Mensaje de bienvenida enviado correctamente.")
    else: logger.error("Fallo al enviar el mensaje de bienvenida.")


# --- Lógica Principal Asíncrona ---
async def main_loop():
    """Bucle principal asíncrono de la aplicación."""
    # ... (Lógica del bucle principal igual que v1.2) ...
    global last_valid_poi, arrival_alert_sent
    logger.info("=== Iniciando Bucle Principal del Analizador SMC (Estrategia M15 Rango Fijo) ===")
    await send_welcome_message() # Enviar bienvenida
    while True:
        try:
            logger.info("--- Inicio del Ciclo de Análisis M15 ---"); start_time = time.time()
            # 1. Actualizar Datos M15
            logger.info("Actualizando datos M15...")
            if not data_manager.update_data(config.TIMEFRAME_LTF): logger.warning("Fallo al actualizar datos M15."); await asyncio.sleep(60); continue
            m15_data = data_manager.get_data(config.TIMEFRAME_LTF)
            num_analysis_candles = config.STRATEGY_M15_RANGE_CANDLES # Usar valor de config
            if m15_data is None or m15_data.empty or len(m15_data) < num_analysis_candles: logger.error(f"Datos M15 insuficientes."); await asyncio.sleep(60); continue
            # 2. Analizar Setup M15
            logger.info("Ejecutando análisis de setup M15...")
            analysis_result = smc_analyzer.analyze_m15_setup(m15_data, num_candles=num_analysis_candles)
            # 3. Procesar Resultado
            new_poi_found = False; alert_message = None
            if analysis_result:
                current_poi = analysis_result.get('high_probability_poi'); current_bias = analysis_result.get('bias_m15')
                if current_poi and (last_valid_poi is None or current_poi.get('index') != last_valid_poi.get('index')):
                    logger.info(f"¡NUEVO POI M15 VÁLIDO IDENTIFICADO! @ {current_poi.get('index')}")
                    last_valid_poi = current_poi.copy(); arrival_alert_sent = False; new_poi_found = True
                    signal_data_new_poi = { 'type': 'NEW_POI_M15', 'symbol': config.SYMBOL, 'timeframe': config.TIMEFRAME_LTF, 'direction': last_valid_poi.get('direction'), 'poi_type': last_valid_poi.get('type'), 'price_range': (last_valid_poi.get('low'), last_valid_poi.get('high')), 'index': last_valid_poi.get('index'), 'message': "POI Válido Identificado."}
                    alert_message = telegram_notifier.format_alert(signal_data_new_poi)
                    if alert_message: logger.info(f"Generando alerta TIPO NEW_POI_M15")
                elif last_valid_poi and current_bias != last_valid_poi.get('direction') and current_bias != 'Undetermined': logger.info(f"Bias M15 cambió a {current_bias}. Invalidando POI anterior."); last_valid_poi = None; arrival_alert_sent = False
                elif not current_poi and last_valid_poi: logger.debug("Análisis sin POI, manteniendo monitoreo anterior.")
                elif not current_poi and not last_valid_poi: logger.debug("Análisis sin POI y sin POI previo.")
            else: logger.error("El análisis M15 falló o devolvió None.")
            # 4. Verificar Llegada a POI
            if last_valid_poi and not new_poi_found:
                logger.debug(f"Monitoreando llegada a POI @ {last_valid_poi.get('index')}")
                live_price_data = data_manager.get_live_price_data()
                if live_price_data:
                    current_price = live_price_data['ask'] if last_valid_poi.get('direction') == 'Bullish' else live_price_data['bid']
                    poi_low = last_valid_poi.get('low'); poi_high = last_valid_poi.get('high')
                    if poi_low is not None and poi_high is not None:
                        is_inside_poi = poi_low <= current_price <= poi_high
                        if is_inside_poi and not arrival_alert_sent:
                            logger.info(f"¡PRECIO ENTRANDO EN ZONA POI M15 @ {last_valid_poi.get('index')}!")
                            arrival_alert_sent = True
                            signal_data_arrival = {'type': 'PRICE_ENTERING_POI', 'symbol': config.SYMBOL, 'timeframe': config.TIMEFRAME_LTF, 'direction': last_valid_poi.get('direction'), 'poi_type': last_valid_poi.get('type'), 'price_range': (poi_low, poi_high), 'index': last_valid_poi.get('index'), 'message': f"Precio ({current_price:.5f}) entrando en zona POI. ¡Buscar CHOCH en LTF!"}
                            alert_message = telegram_notifier.format_alert(signal_data_arrival)
                            if alert_message: logger.info(f"Generando alerta TIPO PRICE_ENTERING_POI")
                        elif not is_inside_poi and arrival_alert_sent: logger.debug(f"Precio salió de POI. Reseteando alerta llegada."); arrival_alert_sent = False
                    else: logger.warning("POI activo sin límites High/Low.")
                else: logger.warning("No se pudo obtener precio actual.")
            elif not last_valid_poi: logger.debug("No hay POI activo.")
            # 5. Enviar Alerta
            if alert_message: logger.info(f"Enviando alerta a Telegram..."); asyncio.create_task(telegram_notifier.send_telegram_message_async(alert_message))
            # 6. Esperar
            end_time = time.time(); cycle_duration = end_time - start_time; logger.info(f"--- Fin Ciclo M15 (Duración: {cycle_duration:.3f}s) ---")
            wait_seconds = get_seconds_until_next_m15_candle(); logger.info(f"Esperando {wait_seconds:.2f} segundos..."); await asyncio.sleep(wait_seconds)
        except KeyboardInterrupt: logger.info("Interrupción por teclado."); break
        except Exception as e:
            logger.critical(f"Error CRÍTICO main_loop: {e}", exc_info=True)
            error_message = telegram_notifier.format_alert({'type': 'ERROR','message': f"Error crítico main_loop: {e}"})
            try: await asyncio.wait_for(telegram_notifier.send_telegram_message_async(error_message), timeout=10.0)
            except Exception as telegram_err: logger.error(f"Fallo adicional envío error Telegram: {telegram_err}")
            logger.info("Esperando 60s antes de reintentar..."); await asyncio.sleep(60)


# --- Punto de Entrada Principal ---
if __name__ == "__main__":
    # ... (Código if __name__ == "__main__" igual que v1.2) ...
    logger.info(f"*** Iniciando {config.SYMBOL} SMC Analyzer (v10.3 - Estrategia M15 Rango Fijo) ***") # Actualizar versión
    if not mt5_connector.connect_mt5(): logger.critical("No se pudo conectar a MT5 al inicio. Saliendo."); exit()
    try: asyncio.run(main_loop())
    except KeyboardInterrupt: logger.info("Aplicación interrumpida (fuera del bucle).")
    except Exception as e: logger.critical(f"Error fatal fuera del bucle: {e}", exc_info=True)
    finally:
        logger.info("Finalizando y desconectando MT5...")
        mt5_connector.disconnect_mt5()
        logger.info(f"*** {config.SYMBOL} SMC Analyzer Finalizado ***")