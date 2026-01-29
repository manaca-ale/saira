# src/ingester/config.py
"""
Centralized configuration for the Ingester service.
"""
import os

# --- Application and Device Settings ---

# Nova premissa: o fluxo de automação assume que o aplicativo alvo já está aberto.
# Isso desativa a necessidade de navegar para a Home e abrir o app.
ASSUME_APP_OPEN = True

# Package name for the ICSee application.
ICSEE_PACKAGE_NAME = "com.icsee.pro"


# --- Camera Configurations ---
# Coordenadas para acessar a visualização da câmera dentro do app.
CAMERAS = {
    "camera_quarto_1": {
        "tap_coords": {
            "x": 833,
            "y": 480
        }
    },
    "camera_quarto_2": {
        "tap_coords": {
            "x": 250,
            "y": 480  # Coordenada Y ajustada para diferenciar da primeira câmera
        }
    }
}

# --- Ritual de Estabilização Pré-Captura ---
# Sequência de ações a serem executadas para estabilizar o stream de vídeo
# antes de realizar a captura do screenshot.
PRE_CAPTURE_WAIT_SECONDS = 2  # Tempo de espera (em segundos) entre os taps do ritual.
PRE_CAPTURE_SEQUENCE = [
    {"type": "tap", "coords": {"x": 500, "y": 500}, "label": "step_1"},
    {"type": "wait", "duration": PRE_CAPTURE_WAIT_SECONDS},
    {"type": "tap", "coords": {"x": 994, "y": 706}, "label": "step_2"},
    {"type": "wait", "duration": PRE_CAPTURE_WAIT_SECONDS},
    {"type": "tap", "coords": {"x": 500, "y": 500}, "label": "step_3"},
]

# --- Timing Delays (in seconds) ---
# Delays para garantir que a UI responda adequadamente.

# Delay entre a finalização de uma câmera e o início da próxima.
# Essencial para permitir que a UI (lista de câmeras) se estabilize.
INTER_CAMERA_DELAY_SECONDS = 1.0

# Tempo de espera para o stream da câmera carregar após selecioná-la.
WAIT_STREAM_LOAD_SECONDS = 15

# --- Ações Pós-Captura ---
# Define o comportamento ao final do fluxo.

# Número de vezes que a tecla BACK será pressionada.
POST_CAPTURE_BACK_COUNT = 2
# Delay entre os pressionamentos da tecla BACK.
POST_BACK_DELAY_SECONDS = 0.5

# --- Capture Loop (Cadence) ---
# Default cadence is 5 minutes.
CAPTURE_INTERVAL_SECONDS = 300
# Health cadence.
HEALTH_INTERVAL_SECONDS = 60
# Allow infinite loop in local mode.
RUN_FOREVER = True
# None or 0 means infinite cycles.
MAX_CYCLES = None
# Backoff after a failed cycle.
ERROR_BACKOFF_SECONDS = 30
# ADB timeouts (seconds).
CAPTURE_ADB_TIMEOUT_SECONDS = 30
HEALTH_ADB_TIMEOUT_SECONDS = 5

# Optional heavy dumpsys for debugging only.
ENABLE_CONNECTIVITY_DUMPSYS = False

# --- Logging ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
HEALTH_JSONL_FILENAME = "health.jsonl"
