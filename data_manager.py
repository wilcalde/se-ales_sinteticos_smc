# data_manager.py
# Módulo para gestionar la obtención y almacenamiento de datos de mercado

import pandas as pd
import logging
import time

# Importar configuración y conector
try:
    import config
    import mt5_connector
    # Verificar variables de config usadas aquí
    _ = config.SYMBOL
    _ = config.TIMEFRAME_HTF
    _ = config.TIMEFRAME_LTF
    _ = config.TIMEFRAME_SIGNAL
    _ = config.LOOKBACK_H1
    _ = config.LOOKBACK_M15
    _ = config.LOOKBACK_M5
except ImportError as e:
    print(f"FATAL: Error importando módulos necesarios en data_manager: {e}")
    exit()
except AttributeError as e:
    print(f"FATAL: Falta una variable de configuración esencial en config.py: {e}")
    exit()

# Obtener logger (asumiendo que ya está configurado por mt5_connector o main)
logger = logging.getLogger(__name__)

# --- Almacén de Datos Interno ---
# Usaremos un diccionario para guardar los DataFrames de cada temporalidad
data_store = {
    config.TIMEFRAME_HTF: None,    # H1
    config.TIMEFRAME_LTF: None,    # M15
    config.TIMEFRAME_SIGNAL: None, # M5
}

# Guardar la última hora de actualización para evitar llamadas excesivas (opcional)
last_update_time = {
    config.TIMEFRAME_HTF: 0,
    config.TIMEFRAME_LTF: 0,
    config.TIMEFRAME_SIGNAL: 0,
}
# UPDATE_INTERVAL_SECONDS = 60 # Ejemplo: No actualizar más de una vez por minuto

# --- Funciones de Gestión de Datos ---

def _get_lookback_for_timeframe(timeframe):
    """Función auxiliar para obtener el lookback correcto desde config."""
    if timeframe == config.TIMEFRAME_HTF:
        return config.LOOKBACK_H1
    elif timeframe == config.TIMEFRAME_LTF:
        return config.LOOKBACK_M15
    elif timeframe == config.TIMEFRAME_SIGNAL:
        return config.LOOKBACK_M5
    else:
        logger.error(f"Temporalidad desconocida solicitada para lookback: {timeframe}")
        return 0 # O lanzar un error

def update_data(timeframe):
    """
    Actualiza los datos OHLC para una temporalidad específica llamando a mt5_connector.

    Args:
        timeframe (mt5.TIMEFRAME_*): La temporalidad a actualizar.

    Returns:
        bool: True si la actualización fue exitosa (o no necesaria), False si hubo un error.
    """
    symbol = config.SYMBOL
    lookback = _get_lookback_for_timeframe(timeframe)

    if lookback <= 0:
        return False # Error ya loggeado en _get_lookback_for_timeframe

    # --- Lógica opcional de intervalo de actualización ---
    # current_time = time.time()
    # if current_time - last_update_time.get(timeframe, 0) < UPDATE_INTERVAL_SECONDS:
    #     logger.debug(f"Datos para {timeframe} ya actualizados recientemente. Saltando.")
    #     return True
    # --- Fin de lógica opcional ---

    logger.info(f"Actualizando datos para {symbol} en {timeframe} (Lookback: {lookback})...")
    df = mt5_connector.get_ohlc_data(symbol, timeframe, lookback)

    if df is not None and not df.empty:
        data_store[timeframe] = df
        last_update_time[timeframe] = time.time() # Actualizar hora si se usa intervalo
        logger.info(f"Datos para {timeframe} actualizados correctamente. {len(df)} velas.")
        return True
    else:
        # El error específico ya fue loggeado por get_ohlc_data
        logger.error(f"Fallo al actualizar datos para {timeframe}. Los datos anteriores (si existen) se conservarán.")
        # No sobreescribimos data_store[timeframe] si falla la actualización
        return False

def update_all_data():
    """
    Actualiza los datos para todas las temporalidades configuradas (H1, M15, M5).

    Returns:
        bool: True si todas las actualizaciones fueron exitosas, False si alguna falló.
    """
    logger.info("Iniciando actualización de datos para todas las temporalidades...")
    success_h1 = update_data(config.TIMEFRAME_HTF)
    success_m15 = update_data(config.TIMEFRAME_LTF)
    success_m5 = update_data(config.TIMEFRAME_SIGNAL)
    all_success = success_h1 and success_m15 and success_m5
    if all_success:
        logger.info("Actualización de datos para todas las temporalidades completada exitosamente.")
    else:
        logger.warning("Actualización de datos completada con uno o más fallos.")
    return all_success

def get_data(timeframe):
    """
    Devuelve el último DataFrame de datos OHLC actualizado para la temporalidad solicitada.

    Args:
        timeframe (mt5.TIMEFRAME_*): La temporalidad deseada.

    Returns:
        pd.DataFrame or None: El DataFrame almacenado, o None si no está disponible.
    """
    df = data_store.get(timeframe)
    if df is None:
        logger.warning(f"Solicitud de datos para {timeframe}, pero no hay datos disponibles. ¿Se ejecutó update_all_data()?")
    elif df.empty:
         logger.warning(f"Solicitud de datos para {timeframe}, pero el DataFrame almacenado está vacío.")
    # else:
        # logger.debug(f"Devolviendo datos cacheados para {timeframe}.")
    return df

def get_live_price_data():
    """
    Obtiene el precio actual (bid/ask) directamente desde mt5_connector.

    Returns:
        dict or None: Diccionario con {'bid': float, 'ask': float, 'time': datetime} o None.
    """
    # Llama directamente a la función del conector
    live_price = mt5_connector.get_current_price(config.SYMBOL)
    if not live_price:
        logger.warning("get_live_price_data no pudo obtener el precio actual desde mt5_connector.")
    return live_price


# --- Bloque de prueba (opcional) ---
if __name__ == "__main__":
    print("Ejecutando pruebas del módulo data_manager...")
    logger.info("Iniciando pruebas unitarias de data_manager...")

    # Necesitamos conectar a MT5 para que las funciones de obtención de datos funcionen
    if mt5_connector.connect_mt5():
        print("\n--- Prueba update_all_data ---")
        success = update_all_data()
        if success:
            print("update_all_data ejecutado con éxito.")
        else:
            print("update_all_data ejecutado con al menos un fallo (revisar logs).")

        print("\n--- Prueba get_data ---")
        h1_df = get_data(config.TIMEFRAME_HTF)
        if h1_df is not None:
            print(f"Datos H1 obtenidos (primeras 5 filas):\n{h1_df.head().to_string()}")
            print(f"Número de velas H1: {len(h1_df)}")
        else:
            print("No se pudieron obtener datos H1 cacheados.")

        m15_df = get_data(config.TIMEFRAME_LTF)
        if m15_df is not None:
            # print(f"Datos M15 obtenidos:\n{m15_df.tail().to_string()}") # Mostrar cola es más útil
             print(f"Número de velas M15: {len(m15_df)}")
        else:
            print("No se pudieron obtener datos M15 cacheados.")

        print("\n--- Prueba get_live_price_data ---")
        live_price = get_live_price_data()
        if live_price:
            print(f"Precio en vivo obtenido: {live_price}")
        else:
            print("No se pudo obtener el precio en vivo.")

        mt5_connector.disconnect_mt5()
    else:
        logger.critical("Prueba fallida: No se pudo conectar a MT5 para probar data_manager.")
        print("No se pudo conectar a MT5 para realizar las pruebas.")

    logger.info("Pruebas unitarias de data_manager finalizadas.")
    print("\nPruebas del módulo data_manager finalizadas. Revisa el archivo de log.")