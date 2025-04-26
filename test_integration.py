# test_integration.py
# Prueba básica de integración (Versión Async para Telegram)

import time
from datetime import datetime
import asyncio # Importar asyncio
import logging # Importar logging para configuración básica si es necesario

# Importar módulos
try:
    import config # Importar configuración primero
    import mt5_connector # Importar conector MT5
    from notifiers import telegram_notifier # Importar notificador desde el paquete 'notifiers'
    print("Módulos importados correctamente.")

    # Configuración básica de logging si no se hizo en otro módulo aún
    # Esto es redundante si mt5_connector ya lo hizo, pero asegura que esté configurado
    logging.basicConfig(level=config.LOG_LEVEL,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        filename=config.LOG_FILE,
                        filemode='a')
    # Añadir handler de consola si no existe ya uno (para evitar duplicados)
    if not any(isinstance(handler, logging.StreamHandler) for handler in logging.getLogger('').handlers):
        console = logging.StreamHandler()
        console.setLevel(config.LOG_LEVEL)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console.setFormatter(formatter)
        logging.getLogger('').addHandler(console)
        logging.debug("Handler de consola añadido para logging desde test_integration.")

except ImportError as e:
    # Mensaje más específico si falla la importación
    print(f"FATAL: Error importando módulos necesarios: {e}")
    print("Verifica que los archivos config.py, mt5_connector.py existan en la raíz.")
    print("Verifica que la carpeta 'notifiers' exista y contenga __init__.py y telegram_notifier.py.")
    exit()
except AttributeError as e:
    # Mensaje si falta una variable esencial en config.py
     print(f"FATAL: Falta una variable de configuración esencial en config.py: {e}")
     exit()


# La función principal de prueba AHORA es async
async def run_basic_test_async():
    """Ejecuta una prueba básica de conexión a MT5, obtención de precio y envío a Telegram (Async)."""
    print("\n--- Iniciando Prueba de Integración Básica (Async) ---")
    logger = logging.getLogger(__name__) # Obtener un logger para esta función

    # 1. Conectar a MT5 (sigue siendo síncrono)
    logger.info("Intentando conectar a MT5...")
    if not mt5_connector.connect_mt5():
        # El error ya se loggeó en mt5_connector
        logger.critical("Fallo al conectar a MT5. Abortando prueba de integración.")
        return # Salir de la función de prueba
    logger.info("Conexión a MT5 establecida.")
    # Pequeña pausa por si acaso MT5 necesita un momento tras conectar
    await asyncio.sleep(1) # Usar asyncio.sleep en función async

    # 2. Obtener Precio Actual (sigue siendo síncrono)
    logger.info(f"Obteniendo precio actual para {config.SYMBOL}...")
    # Pequeña pausa añadida dentro de get_current_price si se modificó, o añadir una aquí
    # await asyncio.sleep(0.2) # Pausa antes de pedir el tick
    current_prices = mt5_connector.get_current_price(config.SYMBOL)
    if not current_prices:
        logger.warning(f"No se pudo obtener el precio actual para {config.SYMBOL}.")
        # El error específico ya se loggeó en mt5_connector

    # 3. Desconectar de MT5 (sigue siendo síncrono)
    logger.info("Desconectando de MT5...")
    mt5_connector.disconnect_mt5()
    logger.info("Desconexión de MT5 completada.")

    # 4. Formatear Mensaje para Telegram (sigue siendo síncrono)
    logger.info("Formateando mensaje para Telegram...")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S") # Obtener hora actual

    # Crear diccionario de datos para format_alert
    signal_data = {
        'symbol': config.SYMBOL,
        # 'message': '', # Se llenará abajo
    }

    if current_prices and current_prices.get('bid', 0.0) != 0.0:
        signal_data['type'] = 'INTEGRATION_OK' # Usar un tipo para format_alert si se desea
        signal_data['current_bid'] = current_prices['bid']
        signal_data['current_ask'] = current_prices['ask']
        # Formato simple, la función format_alert podría ser más elaborada
        message = (
            f"✅ **Prueba de Integración OK** ({timestamp})\n\n"
            f"Broker: `{config.MT5_SERVER}`\n"
            f"Symbol: `{config.SYMBOL}`\n\n"
            f"**Precio Actual:**\n"
            f"  Bid: `{current_prices['bid']:.5f}`\n"
            f"  Ask: `{current_prices['ask']:.5f}`"
        )
    elif current_prices and current_prices.get('bid', -1.0) == 0.0:
         signal_data['type'] = 'INTEGRATION_WARN_PRICE'
         message = (
            f"⚠️ **Prueba de Integración Parcial** ({timestamp})\n\n"
            f"Broker: `{config.MT5_SERVER}`\n"
            f"Symbol: `{config.SYMBOL}`\n\n"
            f"Conexión MT5 OK, pero Precio Actual fue `0.0`. \n"
            f"Verificar si el mercado está activo o revisar terminal MT5."
         )
    else:
        signal_data['type'] = 'INTEGRATION_FAIL_PRICE'
        message = (
            f"❌ **Prueba de Integración Fallida** ({timestamp})\n\n"
            f"Broker: `{config.MT5_SERVER}`\n"
            f"Symbol: `{config.SYMBOL}`\n\n"
            f"No se pudo obtener el precio actual desde MT5 después de conectar."
        )

    # Opcional: Usar format_alert si existe y está adaptada
    # formatted_message = telegram_notifier.format_alert(signal_data)
    # logger.info(f"Mensaje formateado:\n{formatted_message}")
    logger.info(f"Mensaje a enviar:\n{message}")


    # 5. Enviar Mensaje a Telegram (AHORA es async)
    logger.info("Intentando enviar mensaje ASYNC a Telegram...")
    # Llamamos a la función async del notificador con await
    send_success = await telegram_notifier.send_telegram_message_async(message)

    if send_success:
        logger.info("Mensaje enviado exitosamente a Telegram (aparentemente). ¡Revisa tu chat!")
    else:
        logger.error("Fallo al enviar mensaje a Telegram. Verifica token/chat_id, la conexión a internet o los logs.")

    print("\n--- Prueba de Integración Básica (Async) Finalizada ---")

# --- Punto de Entrada Principal ---
if __name__ == "__main__":
    # Código que se ejecuta solo cuando se corre este archivo directamente
    # Ejecutar la función de prueba async usando asyncio.run()
    try:
        asyncio.run(run_basic_test_async())
    except KeyboardInterrupt:
        print("\nPrueba interrumpida por el usuario.")
    except Exception as e:
        # Captura cualquier otra excepción inesperada durante la ejecución
        logging.critical(f"Error inesperado durante la ejecución de la prueba: {e}", exc_info=True)
        print(f"Error inesperado: {e}")