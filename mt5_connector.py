# mt5_connector.py
# Módulo para gestionar la conexión y obtención de datos de MetaTrader 5
# (Actualizado v5.1.1: Path explícito añadido como opción en config)

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import time
import logging # Para registrar información y errores

# Importar la configuración y manejar posibles errores
try:
    import config
    # Verificar variables necesarias de config al importar
    _ = config.MT5_ACCOUNT
    _ = config.MT5_PASSWORD
    _ = config.MT5_SERVER
    _ = config.LOG_LEVEL
    _ = config.LOG_FILE
    _ = config.SYMBOL # Verificar que SYMBOL también existe
except ImportError:
    print("FATAL: No se pudo encontrar el archivo config.py.")
    exit()
except AttributeError as e:
    print(f"FATAL: Falta una variable de configuración esencial en config.py: {e}")
    exit()


# Configuración básica del logging (se hará aquí si no se hizo antes)
# Si otro módulo (como test_integration o main) ya lo configuró, no tendrá efecto adicional.
logging.basicConfig(level=config.LOG_LEVEL,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    filename=config.LOG_FILE,
                    filemode='a') # 'a' para añadir al archivo
logger = logging.getLogger(__name__) # Obtener logger específico para este módulo

# Añadir handler de consola si no existe ya uno (para evitar duplicados)
if not any(isinstance(handler, logging.StreamHandler) for handler in logging.getLogger('').handlers):
    console = logging.StreamHandler()
    console.setLevel(config.LOG_LEVEL)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    logger.debug("Handler de consola añadido para logging desde mt5_connector.")


# --- Funciones de Conexión/Desconexión ---

def connect_mt5(retries=3, delay=5):
    """
    Intenta conectar e inicializar la terminal MetaTrader 5.
    Busca opcionalmente MT5_PATH en config.py.

    Args:
        retries (int): Número de intentos de conexión.
        delay (int): Segundos de espera entre reintentos.

    Returns:
        bool: True si la conexión fue exitosa, False en caso contrario.
    """
    logger.info(f"Intentando conectar a MetaTrader 5 (Cuenta: {config.MT5_ACCOUNT}, Servidor: {config.MT5_SERVER})...")
    initialized = False
    for i in range(retries):
        try:
            # --- Lógica para usar Path Opcional desde config.py ---
            mt5_path = None
            if hasattr(config, 'MT5_PATH') and config.MT5_PATH: # Verificar si existe y no está vacío
                 mt5_path = config.MT5_PATH
                 logger.debug(f"Variable MT5_PATH encontrada en config.py: {mt5_path}")
            else:
                 logger.debug("Variable MT5_PATH no definida o vacía en config.py. Intentando conexión sin path específico.")
            # --------------------------------------------------------

            # Intenta inicializar la conexión
            if mt5_path:
                 # Usar el path definido en config.py
                 initialized = mt5.initialize(
                    login=config.MT5_ACCOUNT,
                    password=config.MT5_PASSWORD,
                    server=config.MT5_SERVER,
                    path=mt5_path # Pasar el path
                 )
            else:
                 # Intentar sin path específico (la librería buscará automáticamente)
                 initialized = mt5.initialize(
                    login=config.MT5_ACCOUNT,
                    password=config.MT5_PASSWORD,
                    server=config.MT5_SERVER
                 )

            if initialized:
                # Verificar si la terminal está conectada al servidor del broker
                terminal_info = mt5.terminal_info()
                if not terminal_info:
                     logger.warning("MT5 inicializado, pero no se pudo obtener información de la terminal.")
                elif not terminal_info.connected:
                    logger.warning("MT5 inicializado, pero la terminal NO está conectada al servidor del broker.")
                    # Considerar devolver False si la conexión al broker es crítica
                    # return False

                logger.info(f"Conexión a MT5 exitosa. Cuenta: {config.MT5_ACCOUNT}, Servidor: {config.MT5_SERVER}")
                account_info = mt5.account_info()
                if account_info:
                    logger.info(f"Info Cuenta: Nombre={account_info.name}, Balance={account_info.balance} {account_info.currency}")
                else:
                    logger.warning("No se pudo obtener información de la cuenta después de conectar.")
                return True # Conexión exitosa
            else:
                # Fallo en mt5.initialize()
                error_code = mt5.last_error()
                logger.error(f"Fallo al inicializar MT5 (intento {i+1}/{retries}). Error MT5: {error_code}")
                if i < retries - 1:
                    logger.info(f"Reintentando conexión en {delay} segundos...")
                    time.sleep(delay)
                else:
                    logger.critical("Se superó el número máximo de reintentos de conexión a MT5.")
                    return False # Fallo después de reintentos
        except Exception as e:
            # Captura excepciones más generales durante la inicialización
            logger.error(f"Excepción durante la conexión a MT5 (intento {i+1}/{retries}): {e}", exc_info=False)
            if i < retries - 1:
                logger.info(f"Reintentando conexión en {delay} segundos...")
                time.sleep(delay)
            else:
                logger.critical(f"Excepción final al conectar a MT5: {e}")
                return False # Fallo por excepción después de reintentos
    return False # Devolver False si el bucle termina sin éxito

def disconnect_mt5():
    """Desconecta de la terminal MetaTrader 5."""
    logger.info("Desconectando de MetaTrader 5...")
    try:
        mt5.shutdown()
        logger.info("Desconexión de MT5 completada.")
    except Exception as e:
        logger.error(f"Excepción durante la desconexión de MT5: {e}")

# --- Funciones de Obtención de Datos ---

def get_ohlc_data(symbol, timeframe, count):
    """
    Obtiene datos históricos OHLC para un símbolo y temporalidad específicos.
    (v5.1.1 - Sin cambios lógicos internos)
    """
    if count <= 0:
        logger.error(f"Solicitud inválida de datos OHLC: count debe ser mayor que 0 (recibido: {count})")
        return None
    terminal_info = mt5.terminal_info()
    # Verificar conexión y conexión al broker
    if not terminal_info or not terminal_info.connected:
         logger.warning(f"Intento de obtener OHLC sin conexión MT5 activa o conectada al broker para {symbol}.")
         return None
    logger.debug(f"Solicitando {count} velas de {symbol} en {timeframe}...")
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None:
            error_code = mt5.last_error(); logger.error(f"No se pudieron obtener datos (rates is None) para {symbol} en {timeframe}. Error MT5: {error_code}"); return None
        if len(rates) == 0:
             logger.warning(f"Se recibieron 0 velas para {symbol} en {timeframe}. Verifica disponibilidad."); return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume', 'spread': 'Spread', 'real_volume': 'RealVolume'}, inplace=True)
        logger.info(f"Datos OHLC obtenidos para {symbol} en {timeframe}. Filas: {len(df)}, Última vela: {df.index[-1]}")
        return df
    except Exception as e:
        logger.error(f"Excepción al obtener/procesar datos OHLC para {symbol} en {timeframe}: {e}", exc_info=True)
        return None

def get_current_price(symbol):
    """
    Obtiene el precio de compra (ask) y venta (bid) actual para un símbolo.
    (v5.1.1 - Incluye pausa y check symbol_info)
    """
    terminal_info = mt5.terminal_info()
    if not terminal_info or not terminal_info.connected:
         logger.warning(f"Intento de obtener precio actual sin conexión MT5 activa o conectada al broker para {symbol}.")
         return None

    # --- Check symbol_info (Diagnóstico) ---
    logger.debug(f"Solicitando información general (symbol_info) para {symbol}...")
    try:
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            error_code = mt5.last_error()
            logger.error(f"No se pudo obtener información general (symbol_info) para {symbol}. ¿Nombre incorrecto o no disponible? Error MT5: {error_code}")
            return None
        logger.info(f"Información general obtenida para {symbol}. Visible: {symbol_info.visible}, Bid(info): {symbol_info.bid}, Ask(info): {symbol_info.ask}")
        if not symbol_info.visible:
             logger.warning(f"El símbolo {symbol} no está visible en la Observación de Mercado de MT5. Se recomienda añadirlo.")
             # Continuamos de todos modos, pero la recepción de ticks puede fallar
    except Exception as e:
        logger.error(f"Excepción al obtener symbol_info para {symbol}: {e}", exc_info=True)
        return None # Fallo crítico al obtener info general

    # --- Obtener Tick ---
    logger.debug(f"Solicitando precio actual (tick) para {symbol}...")
    try:
        # Pausa opcional (ajustar si es necesario)
        logger.debug("Añadiendo pausa de 1.0 segundo antes de solicitar el tick...")
        time.sleep(1.0)

        tick = mt5.symbol_info_tick(symbol)
        if tick:
            tick_time = pd.to_datetime(tick.time_msc, unit='ms')
            logger.debug(f"Tick obtenido para {symbol}: Time={tick_time}, Bid={tick.bid}, Ask={tick.ask}")
            if tick.bid == 0.0 and tick.ask == 0.0:
                 logger.warning(f"Tick obtenido para {symbol}, pero Bid y Ask son 0.0.")
            return {'bid': tick.bid, 'ask': tick.ask, 'time': tick_time}
        else:
            error_code = mt5.last_error()
            logger.error(f"Error al obtener symbol_info_tick para {symbol} (después de obtener symbol_info OK). Error MT5: {error_code}")
            return None
    except Exception as e:
        logger.error(f"Excepción al obtener el tick actual para {symbol}: {e}", exc_info=True)
        return None

# --- Bloque de prueba (Mantenido para pruebas unitarias) ---
if __name__ == "__main__":
    print("Ejecutando pruebas del módulo mt5_connector...")
    # Asegurar configuración de logging para la prueba
    if not logging.getLogger('').hasHandlers():
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler()])
    logger.info("Iniciando pruebas unitarias de mt5_connector...")

    if connect_mt5():
        logger.info("--- Prueba get_ohlc_data ---")
        h1_data = get_ohlc_data(config.SYMBOL, config.TIMEFRAME_HTF, 10)
        if h1_data is not None: logger.info(f"Datos H1 OK (últimas filas):\n{h1_data.tail().to_string()}")
        else: logger.error("Prueba fallida: No se obtuvieron datos H1.")

        logger.info("--- Prueba get_current_price ---")
        current_prices = get_current_price(config.SYMBOL)
        if current_prices: logger.info(f"Precio actual OK: {current_prices}")
        else: logger.error("Prueba fallida: No se obtuvo el precio actual.")

        disconnect_mt5()
    else:
        logger.critical("Prueba fallida: No se pudo conectar a MT5.")

    logger.info("Pruebas unitarias de mt5_connector finalizadas.")
    print("\nPruebas del módulo mt5_connector finalizadas. Revisa el archivo de log para detalles.")