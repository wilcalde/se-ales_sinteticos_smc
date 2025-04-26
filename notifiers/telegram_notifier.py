# notifiers/telegram_notifier.py
# Módulo para enviar notificaciones a Telegram
# (v1.3: Importa timeframe_to_string desde config)

import telegram
import telegram.constants
import logging
import time
import datetime
import asyncio
import html
import pandas as pd # Necesario para pd.Timestamp

# Importar la configuración y la función de utilidad
try:
    import config
    from config import timeframe_to_string # <-- IMPORTAR DESDE CONFIG
    _ = config.TELEGRAM_BOT_TOKEN
    _ = config.TELEGRAM_CHAT_ID
except ImportError: print("FATAL: config.py no encontrado."); exit()
except AttributeError as e: print(f"FATAL: Falta config esencial: {e}"); exit()

logger = logging.getLogger(__name__)

# --- Inicialización del Bot ---
bot = None
try:
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        bot = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
        logger.info("Bot de Telegram inicializado correctamente (modo Async).")
    else: logger.warning("Token/Chat ID Telegram no configurados. Notificador inactivo.")
except Exception as e: logger.error(f"Error inicializando bot Telegram: {e}")


# --- Funciones de Envío (Async - Usando HTML) ---
async def send_telegram_message_async(message, retries=3, delay=5):
    """Envía ASINCRONAMENTE un mensaje al chat de Telegram usando formato HTML."""
    # ... (Código send_telegram_message_async v1.2 sin cambios) ...
    if not bot: logger.error("Bot Telegram no inicializado."); return False
    if not config.TELEGRAM_CHAT_ID: logger.error("Chat ID Telegram no configurado."); return False
    logger.debug(f"Intentando enviar mensaje ASYNC HTML a Telegram (Chat ID: {config.TELEGRAM_CHAT_ID})")
    for i in range(retries):
        try:
            await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=message, parse_mode=telegram.constants.ParseMode.HTML)
            logger.info(f"Mensaje enviado exitosamente a Telegram (intento async {i+1}/{retries}).")
            return True
        except telegram.error.RetryAfter as e: wait_time = e.retry_after + 1; logger.warning(f"Telegram flood control: Reintentando async en {wait_time}s..."); await asyncio.sleep(wait_time); continue
        except telegram.error.BadRequest as e: logger.error(f"BadRequest Telegram (intento {i+1}/{retries}): {e}. Verificar formato HTML."); logger.error(f"Mensaje problemático:\n{message}"); return False
        except Exception as e:
            logger.error(f"Error enviando mensaje async a Telegram (intento {i+1}/{retries}): {e}")
            if i < retries - 1: logger.info(f"Reintentando envío async en {delay}s..."); await asyncio.sleep(delay)
            else: logger.critical("Máximos reintentos envío Telegram superados."); return False
    return False

# --- Función de Formateo (Usa timeframe_to_string importado) ---
def format_alert(signal_data):
    """Formatea los datos de una señal en un string HTML legible para Telegram."""
    def escape_html(text):
        if not isinstance(text, str): text = str(text)
        return html.escape(text)

    try:
        alert_type = signal_data.get('type', 'INFO')
        symbol = escape_html(signal_data.get('symbol', config.SYMBOL))
        # *** USA timeframe_to_string importado ***
        tf_int = signal_data.get('timeframe') # Obtener el entero
        tf = escape_html(timeframe_to_string(tf_int) if tf_int is not None else 'N/A') # Convertir a string
        direction = escape_html(signal_data.get('direction', 'N/A'))
        poi_type = escape_html(signal_data.get('poi_type', 'POI'))
        price_range = signal_data.get('price_range')
        poi_index = signal_data.get('index')
        msg = escape_html(signal_data.get('message', ''))
        range_str = ""
        if price_range and len(price_range) == 2 and price_range[0] is not None and price_range[1] is not None:
            low_str = f"{price_range[0]:.5f}"; high_str = f"{price_range[1]:.5f}"
            range_str = f"Zona: <code>{low_str} - {high_str}</code>"
        index_str = ""
        if isinstance(poi_index, pd.Timestamp): index_str = f" @ <code>{poi_index.strftime('%Y-%m-%d %H:%M')}</code>"
        elif poi_index: index_str = f" @ <code>{escape_html(str(poi_index))}</code>"

        header = f"🔔 <b>ALERTA {symbol}</b> 🔔\n\n"
        if alert_type == 'NEW_POI_M15':
            message = (f"{header}📈 <b>Nuevo POI {tf} Válido Identificado</b>\n   Tipo: <code>{poi_type}</code>\n   Dirección: <code>{direction}</code>\n   {range_str}\n   Origen:{index_str}\n\n⏳ <i>Monitoreando llegada...</i>")
        elif alert_type == 'PRICE_ENTERING_POI':
             current_price_str = "";
             if "Precio (" in msg and ") entrando" in msg:
                  try: price_val_str = msg.split("Precio (")[1].split(") entrando")[0]; current_price_str = f" (Actual: <code>{escape_html(price_val_str)}</code>)"
                  except Exception: pass
             message = (f"{header}🎯 <b>¡Precio Entrando en Zona POI {tf}!</b>{current_price_str}\n   Tipo: <code>{poi_type}</code>\n   Dirección: <code>{direction}</code>\n   {range_str}\n   Origen:{index_str}\n\n👀 <i>¡Buscar CHOCH en LTF (M5/M1)!</i>")
        elif alert_type == 'ERROR': message = f"{header}⚠️ <b>ERROR CRÍTICO</b>\n<code>{msg}</code>"
        else: message = f"{header}ℹ️ <b>INFO:</b> {msg}"
        return message
    except Exception as e:
        logger.error(f"Error formateando alerta HTML: {e}. Datos: {signal_data}", exc_info=True)
        return f"Error formateando alerta.\nTipo: {signal_data.get('type', 'N/A')}\nDatos: {str(signal_data)}"

# --- Bloque de prueba (Actualizado para pasar entero de TF) ---
async def main_test():
    print("Ejecutando pruebas ASYNC del módulo telegram_notifier (HTML)...")
    logger.info("Iniciando pruebas ASYNC de notificación de Telegram (HTML)...")
    print("\n--- Prueba de formateo HTML ---")
    ts = pd.Timestamp('2025-04-25 08:15:00')
    test_signal_new_poi = {'type': 'NEW_POI_M15', 'symbol': 'Volatility 75 Index', 'timeframe': config.TIMEFRAME_LTF, 'direction': 'Bullish', 'poi_type': 'OB+FVG+Sweep', 'price_range': (123450.12345, 123550.54321), 'index': ts}
    test_signal_arrival = {'type': 'PRICE_ENTERING_POI', 'symbol': 'Volatility 75 Index', 'timeframe': config.TIMEFRAME_LTF, 'direction': 'Bullish', 'poi_type': 'OB+FVG+Sweep', 'price_range': (123450.12345, 123550.54321), 'index': ts, 'message': 'Precio (123460.00000) entrando en zona POI. ¡Buscar CHOCH en LTF!'}
    test_signal_error = {'type': 'ERROR', 'message': 'Fallo conexión MT5 <simbolo> & >otros<.'}
    formatted_new = format_alert(test_signal_new_poi); formatted_arrival = format_alert(test_signal_arrival); formatted_error = format_alert(test_signal_error)
    print("Alerta NUEVO POI formateada:\n", formatted_new); print("\nAlerta LLEGADA A POI formateada:\n", formatted_arrival); print("\nAlerta ERROR formateada:\n", formatted_error)
    print("\n--- Prueba de envío a Telegram (HTML) ---"); print("Se intentará enviar mensajes de prueba formateados. ¡Revisa tu Telegram!")
    await send_telegram_message_async(formatted_new); await asyncio.sleep(1)
    await send_telegram_message_async(formatted_arrival); await asyncio.sleep(1)
    await send_telegram_message_async(formatted_error)
    logger.info("Pruebas ASYNC de notificación de Telegram finalizadas."); print("\nPruebas ASYNC del módulo telegram_notifier finalizadas.")

if __name__ == "__main__":
    if not logging.getLogger('').hasHandlers(): logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler()])
    try: asyncio.run(main_test())
    except Exception as e: print(f"Error ejecutando main_test: {e}")