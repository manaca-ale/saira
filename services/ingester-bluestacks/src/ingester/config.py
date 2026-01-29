# src/ingester/config.py
"""
Centralized configuration for the Ingester service.
"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"), override=True)


def _parse_bool_env(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return default


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
    {"type": "tap", "coords": {"x": 994, "y": 706}, "label": "fullscreen_btn"},
    {"type": "wait", "duration": PRE_CAPTURE_WAIT_SECONDS},
    {"type": "tap", "coords": {"x": 500, "y": 500}, "label": "dismiss_controls"},
]

# --- Fullscreen Controls ---
FULLSCREEN_TAP_COORDS = {"x": 994, "y": 706}
MENU_TAP_COORDS = {"x": 500, "y": 500}

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
CAPTURE_INTERVAL_SECONDS = int(os.getenv("INGESTER_CAPTURE_INTERVAL_SECONDS", "300"))
# Health cadence.
HEALTH_INTERVAL_SECONDS = 60
# Allow infinite loop in local mode.
RUN_FOREVER = _parse_bool_env(os.getenv("INGESTER_RUN_FOREVER"), True)
# None or 0 means infinite cycles.
MAX_CYCLES = int(os.getenv("INGESTER_MAX_CYCLES", "0")) or None
# Backoff after a failed cycle.
ERROR_BACKOFF_SECONDS = 30
# ADB timeouts (seconds).
CAPTURE_ADB_TIMEOUT_SECONDS = 30
HEALTH_ADB_TIMEOUT_SECONDS = 30

# Optional heavy dumpsys for debugging only.
ENABLE_CONNECTIVITY_DUMPSYS = False

# --- Logging ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
HEALTH_JSONL_FILENAME = "health.jsonl"
CYCLES_JSONL_PATH = os.path.join(LOG_DIR, "cycles.jsonl")

# --- Output ---
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "captures")

# --- App Focus Validation ---
EXPECTED_PACKAGE = "com.xm.csee"
EXPECTED_ACTIVITIES = [
    "com.xworld.MainActivity",
    "com.xworld.activity.monitor.view.MonitorActivity",
]

# --- Screen Validation ---
MAX_SCREEN_RETRIES = 2
RETRY_DELAY_SEC = 1.5
BLACK_MEAN_THRESHOLD = 35
WHITE_MEAN_THRESHOLD = 240
LOW_STD_THRESHOLD = 20

# --- Loading Screen Detection ---
LOADING_MEAN_MAX = 60
LOADING_BRIGHT_CENTER_MIN = 0.01

# --- Error Artifacts ---
LOGCAT_LINES_ON_ERROR = 500

# --- ADB Timeouts / Logging ---
BATTERY_DUMPSYS_TIMEOUT_SECONDS = 12
ADB_TIMEOUT_RETRY_DELAY_SECONDS = 1.0
ADB_ERROR_OUTPUT_TAIL_CHARS = 800

# --- BlueStacks / ADB Device Selection ---
# If set, ingester will use this device serial only (e.g. 127.0.0.1:5555).
ADB_DEVICE_SERIAL = os.getenv("INGESTER_DEVICE_SERIAL")

# --- Health Check Flag ---
ENABLE_HEALTHCHECK = _parse_bool_env(os.getenv("INGESTER_ENABLE_HEALTHCHECK"), False)
ENABLE_FOCUS_VALIDATION = _parse_bool_env(os.getenv("INGESTER_ENABLE_FOCUS_VALIDATION"), False)

# --- Screen State Detection & Recovery ---
ENABLE_SCREEN_STATE_DETECTION = _parse_bool_env(
    os.getenv("INGESTER_ENABLE_SCREEN_STATE_DETECTION"), False
)

# App launch configuration
APP_LAUNCH_ACTIVITY = "com.xworld.MainActivity"
APP_LAUNCH_WAIT_SECONDS = 8.0
APP_ICON_TAP_COORDS = {"x": 150, "y": 1150}  # Fallback: ícone do ICSee na Home

# Recovery settings
MAX_STATE_RECOVERY_ATTEMPTS = 2
PRE_CAPTURE_RETRY_MAX = 2
STATE_CHECK_WAIT_SECONDS = 1.0

# Screen state thresholds — calibrados com dados reais de screen_profiles.json.
# Árvore de decisão (avaliada nesta ordem):
#   1. camera_normal:     dark_ratio_top >= 0.5  (topo escuro, exclusivo desta tela)
#   2. camera_fullscreen: dark_ratio_left >= 0.7  (borda esquerda escura = vídeo cheio)
#   3. home:              h_line_status_bottom <= 0.3  (sem linha de status do app)
#   4. camera_list:       h_line alto + dark ratios baixos
#   5. UNKNOWN:           nenhuma regra se encaixou → tenta voltar para HOME
SCREEN_STATE_THRESHOLDS = {
    "camera_normal": {
        "dark_ratio_top_min": 0.5,       # home=0.02, list=0.01, normal=0.76, full=0.04
    },
    "camera_fullscreen": {
        "dark_ratio_left_min": 0.7,      # home=0.004, list=0, normal=0.15, full=0.86
    },
    "home": {
        "h_line_status_bottom_max": 0.3, # home=0.11, list=0.79, normal=0.80, full=0.3-0.6
    },
    "sanity": {
        "camera_list_max_dark": 0.3,     # dark_top e dark_left devem ser < 0.3 para camera_list
    },
}
