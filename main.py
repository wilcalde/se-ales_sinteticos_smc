# main.py
# Orquestador principal para SMC VIX Signal Bot
# (v1.8: Llama a analyze_m15_pending_pois)

import time
import asyncio
import logging
from datetime import datetime, timedelta, timezone
import pandas as pd
import html
import telegram
import re

# --- Importar Módulos ---
try:
    import config
    from config import timeframe_to_string
    import mt5_connector
    import data_manager
    import smc_analyzer # Importar el módulo completo
    from notifiers import telegram_notifier
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    print("Módulos principales importados correctamente.")
    # Configuración de Logging
    # ... (igual que v1.5) ...
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
active_pois_dict = {} # { poi_index: { poi_data..., arrival_alerted: False } }

# --- Funciones Auxiliares ---
def get_seconds_until_next_m15_candle():
    """Calcula los segundos hasta el inicio de la próxima vela M15."""
    now_utc = datetime.now(timezone.utc)
    next_minute = (now_utc.minute // 15 + 1) * 15

    # Inicializar next_candle_time con un valor base (la hora actual)
    next_candle_time = now_utc

    if next_minute >= 60:
        next_hour = now_utc.hour + 1
        next_minute = 0
        if next_hour >= 24: # Cruce de día
             next_hour = 0
             # Calcular el próximo día
             next_day = now_utc.date() + timedelta(days=1)
             # Asignar el valor calculado
             next_candle_time = datetime(next_day.year, next_day.month, next_day.day, next_hour, next_minute, 0, tzinfo=timezone.utc)
        else:
             # Asignar el valor calculado para el cambio de hora
             next_candle_time = now_utc.replace(hour=next_hour, minute=next_minute, second=0, microsecond=0)
    else:
        # Asignar el valor calculado para el cambio de minuto dentro de la misma hora
        next_candle_time = now_utc.replace(minute=next_minute, second=0, microsecond=0)

    # Ahora next_candle_time siempre tendrá un valor asignado
    delta = next_candle_time - now_utc
    wait_seconds = delta.total_seconds()

    # Manejar caso donde la próxima vela ya empezó (delta negativo)
    if wait_seconds < 0:
        # Si ya pasó, calcular hasta la *siguiente* vela de 15 min
        # (Esta lógica podría necesitar ajuste si el script tarda mucho)
        logger.warning("El cálculo inicial de next_candle_time resultó en el pasado. Recalculando para la siguiente.")
        # Volver a calcular forzando al siguiente intervalo de 15 min
        minutes_to_add = 15 - (now_utc.minute % 15)
        next_candle_time = now_utc + timedelta(minutes=minutes_to_add)
        next_candle_time = next_candle_time.replace(second=0, microsecond=0)
        delta = next_candle_time - now_utc
        wait_seconds = delta.total_seconds()

    wait_seconds += 2.0 # Añadir margen de 2 segundos
    logger.debug(f"Próxima vela M15 UTC: {next_candle_time}. Esperando {wait_seconds:.2f} segundos.")
    return max(1.0, wait_seconds) # Esperar al menos 1 segundo

# --- Funciones de Comandos de Telegram ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envía un mensaje cuando se emite el comando /start."""
    # ... (código igual que v1.6) ...
    user = update.effective_user; logger.info(f"Comando /start recibido de {user.username} (ID: {user.id})")
    await update.message.reply_html(f"¡Hola {user.mention_html()}! 👋\n\nBot SMC V{config.STRATEGY_M15_RANGE_CANDLES} Velas M15 para {html.escape(config.SYMBOL)}.\nUsa /verpoi para ver POIs.")

async def verpoi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra los POIs activos que el bot está monitoreando."""
    # ... (código igual que v1.6) ...
    global active_pois_dict; user = update.effective_user; logger.info(f"Comando /verpoi recibido de {user.username} (ID: {user.id})")
    if not active_pois_dict: await update.message.reply_text("ℹ️ No hay POIs activos monitoreados."); return
    pois_to_show = list(active_pois_dict.values()); message = f"🔎 *POIs M15 Pendientes ({len(pois_to_show)}):*\n\n"
    for i, poi in enumerate(pois_to_show):
        poi_type = poi.get('type', 'POI'); direction = poi.get('direction', 'N/A'); poi_index = poi.get('index'); poi_low = poi.get('low'); poi_high = poi.get('high'); arrival_alerted = poi.get('arrival_alerted', False)
        index_str = poi_index.strftime('%Y-%m-%d %H:%M') if isinstance(poi_index, pd.Timestamp) else str(poi_index); range_str = f"{poi_low:.5f} - {poi_high:.5f}" if poi_low is not None and poi_high is not None else "N/A"; alert_status = "🔔 Llegada Alertada" if arrival_alerted else "⏳ Esperando Llegada"
        message += (f"*{i+1}\\)* `{poi_type}` {direction} @ `{index_str}`\n   Zona: `{range_str}`\n   Estado: _{alert_status}_\n\n")
        if i >= 9: message += f"... y {len(pois_to_show) - 10} más."; break
    def escape_markdown_v2(text): escape_chars = r'_*[]()~`>#+-=|{}.!'; pattern = f"([{re.escape(escape_chars)}])"; return re.sub(pattern, r'\\\1', str(text))
    escaped_message = escape_markdown_v2(message)
    try: await update.message.reply_text(escaped_message, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2)
    except telegram.error.BadRequest as e: logger.error(f"Error BadRequest /verpoi: {e}\nMensaje Escapado:\n{escaped_message}"); await update.message.reply_text("Error formato. Sin formato:\n\n" + message)
    except Exception as e: logger.error(f"Error inesperado /verpoi: {e}"); await update.message.reply_text("Error procesando /verpoi.")

# --- Función de Bienvenida (Usa formato HTML) ---
async def send_welcome_message():
    """Envía el mensaje inicial de bienvenida e instrucciones."""
    # ... (código igual que v1.3) ...
    logger.info("Enviando mensaje de bienvenida a Telegram..."); from html import escape as escape_html
    num_candles_str = escape_html(str(config.STRATEGY_M15_RANGE_CANDLES)); symbol_str = escape_html(config.SYMBOL); tf_ltf_str = escape_html(timeframe_to_string(config.TIMEFRAME_LTF)); tf_conf_str = escape_html(timeframe_to_string(config.TIMEFRAME_CONFIRMATION))
    welcome_text = (f"🚀 <b>{symbol_str} SMC Bot Iniciado</b> 🚀\n\n" f"Analizando {tf_ltf_str} (últimas {num_candles_str} velas) buscando FVG pendientes.\n\n" f"<b>Recibirás:</b>\n- Alerta de NUEVO POI válido.\n- Alerta cuando precio LLEGUE a POI.\n\n" f"<b>Importante:</b>\n- Son <i>alertas</i>, NO señales.\n- Busca CHOCH en {tf_conf_str} y gestiona riesgo.\n- Usa /verpoi.\n- Detener con <code>Ctrl+C</code>.\n\n¡Suerte! 👍")
    success = await telegram_notifier.send_telegram_message_async(welcome_text);
    if success: logger.info("Mensaje bienvenida enviado.")
    else: logger.error("Fallo envío mensaje bienvenida.")


# --- Lógica Principal Asíncrona (Bucle de Análisis) ---
async def analysis_loop():
    """Bucle principal que ejecuta el análisis periódicamente."""
    global active_pois_dict
    logger.info("=== Iniciando Tarea de Análisis Periódico (v11.0) ===")

    while True:
        try:
            logger.info("--- Inicio del Ciclo de Análisis M15 ---"); start_time = time.time()
            # 1. Actualizar Datos M15
            logger.info("Actualizando datos M15...")
            if not data_manager.update_data(config.TIMEFRAME_LTF): logger.warning("Fallo al actualizar datos M15."); await asyncio.sleep(60); continue
            m15_data = data_manager.get_data(config.TIMEFRAME_LTF)
            num_analysis_candles = config.STRATEGY_M15_RANGE_CANDLES
            if m15_data is None or m15_data.empty or len(m15_data) < num_analysis_candles: logger.error(f"Datos M15 insuficientes."); await asyncio.sleep(60); continue

            # 2. Analizar POIs Pendientes M15
            logger.info("Ejecutando análisis de POIs pendientes M15...")
            # *** CORRECCIÓN v1.8: Llamar a la función correcta ***
            pending_pois_list = smc_analyzer.analyze_m15_pending_pois(m15_data, num_candles=num_analysis_candles)

            # 3. Procesar y Actualizar POIs Activos
            alert_messages_to_send = []
            current_active_indices = set(active_pois_dict.keys())
            found_indices = set()

            if isinstance(pending_pois_list, list):
                for poi in pending_pois_list:
                    poi_index = poi.get('index')
                    if poi_index:
                        found_indices.add(poi_index)
                        if poi_index not in current_active_indices:
                            logger.info(f"¡NUEVO POI M15 PENDIENTE IDENTIFICADO! @ {poi_index}")
                            poi['arrival_alerted'] = False
                            active_pois_dict[poi_index] = poi
                            signal_data_new_poi = { 'type': 'NEW_POI_M15', 'symbol': config.SYMBOL, 'timeframe': config.TIMEFRAME_LTF, 'direction': poi.get('direction'), 'poi_type': poi.get('type'), 'price_range': (poi.get('low'), poi.get('high')), 'index': poi.get('index'), 'message': "POI Válido Identificado."}
                            alert_msg = telegram_notifier.format_alert(signal_data_new_poi)
                            if alert_msg: logger.info(f"Generando alerta TIPO NEW_POI_M15"); alert_messages_to_send.append(alert_msg)
                indices_to_remove = current_active_indices - found_indices
                if indices_to_remove: logger.info(f"Eliminando {len(indices_to_remove)} POIs ya no válidos: {indices_to_remove}"); [active_pois_dict.pop(idx) for idx in indices_to_remove]
            else: logger.error("El análisis de POIs pendientes no devolvió una lista.")

            # 4. Verificar Llegada a POIs Activos
            if active_pois_dict:
                logger.debug(f"Monitoreando llegada a {len(active_pois_dict)} POIs activos...")
                live_price_data = data_manager.get_live_price_data()
                if live_price_data:
                    # Iterar sobre copia de items para poder modificar el diccionario
                    for poi_index, poi in list(active_pois_dict.items()):
                        arrival_alerted = poi.get('arrival_alerted', False)
                        poi_direction = poi.get('direction')
                        # Asegurarse de que poi_direction no sea None antes de la comparación
                        if poi_direction is None: continue
                        current_price = live_price_data['ask'] if poi_direction == 'Bullish' else live_price_data['bid']
                        poi_low = poi.get('low'); poi_high = poi.get('high')
                        if poi_low is not None and poi_high is not None:
                            is_inside_poi = poi_low <= current_price <= poi_high
                            if is_inside_poi and not arrival_alerted:
                                logger.info(f"¡PRECIO ENTRANDO EN ZONA POI M15 @ {poi_index}!")
                                active_pois_dict[poi_index]['arrival_alerted'] = True # Actualizar en el diccionario
                                signal_data_arrival = {'type': 'PRICE_ENTERING_POI', 'symbol': config.SYMBOL, 'timeframe': config.TIMEFRAME_LTF, 'direction': poi_direction, 'poi_type': poi.get('type'), 'price_range': (poi_low, poi_high), 'index': poi_index, 'message': f"Precio ({current_price:.5f}) entrando en zona POI. ¡Buscar CHOCH en LTF!"}
                                alert_msg = telegram_notifier.format_alert(signal_data_arrival)
                                if alert_msg: logger.info(f"Generando alerta TIPO PRICE_ENTERING_POI"); alert_messages_to_send.append(alert_msg)
                            elif not is_inside_poi and arrival_alerted:
                                 logger.debug(f"Precio salió de POI @ {poi_index}. Reseteando flag llegada.")
                                 active_pois_dict[poi_index]['arrival_alerted'] = False # Resetear en el diccionario
                        else: logger.warning(f"POI activo @ {poi_index} sin límites High/Low.")
                else: logger.warning("No se pudo obtener precio actual.")
            else: logger.debug("No hay POIs activos para monitorear.")

            # 5. Enviar Alertas Acumuladas
            if alert_messages_to_send:
                 logger.info(f"Enviando {len(alert_messages_to_send)} alertas a Telegram...")
                 for msg in alert_messages_to_send: asyncio.create_task(telegram_notifier.send_telegram_message_async(msg)); await asyncio.sleep(0.5)

            # 6. Esperar
            end_time = time.time(); cycle_duration = end_time - start_time; logger.info(f"--- Fin Ciclo M15 (Duración: {cycle_duration:.3f}s) ---")
            wait_seconds = get_seconds_until_next_m15_candle(); logger.info(f"Esperando {wait_seconds:.2f} segundos..."); await asyncio.sleep(wait_seconds)

        except KeyboardInterrupt: logger.info("Interrupción detectada en bucle de análisis."); break
        except Exception as e:
            logger.critical(f"Error CRÍTICO main_loop: {e}", exc_info=True)
            error_message = telegram_notifier.format_alert({'type': 'ERROR','message': f"Error crítico main_loop: {e}"})
            try: await asyncio.wait_for(telegram_notifier.send_telegram_message_async(error_message), timeout=10.0)
            except Exception as telegram_err: logger.error(f"Fallo adicional envío error Telegram: {telegram_err}")
            logger.info("Esperando 60s antes de reintentar..."); await asyncio.sleep(60)


# --- Punto de Entrada Principal ---
async def main():
    """Función principal async que configura y ejecuta la aplicación."""
    logger.info(f"*** Iniciando {config.SYMBOL} SMC Analyzer (v11.0 - POIs Pendientes) ***") # Actualizar versión
    if not mt5_connector.connect_mt5(): logger.critical("No se pudo conectar a MT5 al inicio. Saliendo."); return

    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("verpoi", verpoi_command))

    await send_welcome_message() # Enviar bienvenida
    analysis_task = asyncio.create_task(analysis_loop()) # Iniciar el bucle de análisis

    try:
        logger.info("Iniciando polling de Telegram y bucle de análisis...")
        await application.initialize(); await application.start(); await application.updater.start_polling()
        await analysis_task
    except KeyboardInterrupt: logger.info("Interrupción por teclado detectada en main.")
    except Exception as e: logger.critical(f"Error fatal en main: {e}", exc_info=True)
    finally:
        logger.info("Deteniendo aplicación...")
        if application.updater and application.updater.running: await application.updater.stop()
        if application.running: await application.stop()
        await application.shutdown()
        logger.info("Desconectando de MT5...")
        mt5_connector.disconnect_mt5()
        logger.info(f"*** {config.SYMBOL} SMC Analyzer Finalizado ***")


if __name__ == "__main__":
    import re # Importar re para escape_markdown_v2 en verpoi
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.info("Aplicación detenida por el usuario.")
    except Exception as e: logger.critical(f"Error fatal al ejecutar main(): {e}", exc_info=True)