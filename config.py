# config.py
# Módulo de configuración para la aplicación de análisis SMC VIX 75
# (v1.1: Añadido timeframe_to_string y mapeo)

import MetaTrader5 as mt5 # Necesario para las constantes y el mapeo

# --- Credenciales de MetaTrader 5 ---
# REEMPLAZA con tus datos reales
MT5_ACCOUNT = 5549411        # Tu número de cuenta MT5
MT5_PASSWORD = "Millonarios10+"  # La contraseña de tu cuenta MT5
MT5_SERVER = "Deriv-Demo"   # El nombre exacto del servidor (ej: Deriv-Demo, Deriv-Server)
MT5_PATH = r"C:\\Program Files\\MetaTrader 5 Terminal\\terminal64.exe" # O la ruta correcta


# --- Credenciales de Telegram ---
TELEGRAM_BOT_TOKEN = "7858974244:AAFGoYM-qU_nNcp7l7jXYj_2clqrnHwmOcQ"  # Token de tu bot de Telegram
TELEGRAM_CHAT_ID = "770156961"      # ID del chat donde se enviarán las alertas


# --- Parámetros de Trading ---
SYMBOL = "Volatility 75 Index"

# --- Definición de Temporalidades ---
TIMEFRAME_HTF = mt5.TIMEFRAME_H1
TIMEFRAME_LTF = mt5.TIMEFRAME_M15 # LTF principal para análisis de setup
TIMEFRAME_CONFIRMATION = mt5.TIMEFRAME_M5 # O M1, para buscar CHOCH
TIMEFRAME_SIGNAL = TIMEFRAME_CONFIRMATION # La alerta final es para esta TF

# --- Parámetros de Análisis (Cantidad de Velas Históricas) ---
LOOKBACK_H1 = 250
LOOKBACK_M15 = 350 # Suficiente para análisis de 96 velas + margen
LOOKBACK_M5 = 75
LOOKBACK_M1 = 100 # Si se usa M1 para confirmación

# --- Parámetros Estrategia M15 Rango Fijo ---
STRATEGY_M15_RANGE_CANDLES = 300 # Número de velas para definir el rango

# --- Configuración de Logging ---
LOG_LEVEL = "INFO"
LOG_FILE = "smc_analyzer.log"

# --- MAPEO Y FUNCIÓN DE UTILIDAD PARA TEMPORALIDADES ---
TIMEFRAME_MAP = {
    mt5.TIMEFRAME_H1: "H1",
    mt5.TIMEFRAME_M15: "M15",
    mt5.TIMEFRAME_M5: "M5",
    mt5.TIMEFRAME_M1: "M1",
    # Añadir otras si se usan en el futuro
}

def timeframe_to_string(tf_int):
    """Convierte un entero de temporalidad MT5 a un string legible."""
    return TIMEFRAME_MAP.get(tf_int, f"TF_{tf_int}")

print("Módulo config.py cargado (v1.1 - con timeframe_to_string).")