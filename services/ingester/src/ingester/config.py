# src/ingester/config.py
"""
Centralized configuration for the Ingester service.

Device-specific data (cameras, coordinates, thresholds) is loaded from
config/device_profile.yaml when available; otherwise built-in defaults are used.
"""
import logging
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"), override=True)

logger = logging.getLogger(__name__)


def _parse_bool_env(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return default


# ---------------------------------------------------------------------------
# Device profile loader (YAML)
# ---------------------------------------------------------------------------

_DEVICE_PROFILE_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
    "config",
    "device_profile.yaml",
)


def _load_device_profile() -> dict:
    """Load device_profile.yaml if it exists. Returns empty dict on failure."""
    if not os.path.isfile(_DEVICE_PROFILE_PATH):
        logger.info("device_profile.yaml not found; using built-in defaults.")
        return {}
    try:
        import yaml
        with open(_DEVICE_PROFILE_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        logger.info(f"Loaded device profile from {_DEVICE_PROFILE_PATH}")
        return data
    except ImportError:
        logger.warning("pyyaml not installed; using built-in defaults.")
        return {}
    except Exception as exc:
        logger.warning(f"Failed to load device_profile.yaml: {exc}; using built-in defaults.")
        return {}


_profile = _load_device_profile()

# ---------------------------------------------------------------------------
# Built-in defaults (used when YAML is absent or incomplete)
# ---------------------------------------------------------------------------

_DEFAULT_CAMERAS = {
    "camera_quarto_1": {
        "tap_coords": {"x": 833, "y": 480}
    },
    "camera_quarto_2": {
        "tap_coords": {"x": 250, "y": 480}
    }
}

_DEFAULT_UI_COORDS = {
    "fullscreen_btn": {"x": 994, "y": 706},
    "dismiss_controls": {"x": 500, "y": 500},
    "app_icon": {"x": 150, "y": 1150},
}

_DEFAULT_SCREEN_THRESHOLDS = {
    "camera_normal": {"dark_ratio_top_min": 0.5},
    "camera_fullscreen": {"dark_ratio_left_min": 0.7},
    "home": {"h_line_status_bottom_max": 0.3},
    "sanity": {"camera_list_max_dark": 0.3},
}

# ---------------------------------------------------------------------------
# Application and Device Settings
# ---------------------------------------------------------------------------

ASSUME_APP_OPEN = True
ICSEE_PACKAGE_NAME = "com.icsee.pro"

# --- Camera Configurations (from YAML or defaults) ---
CAMERAS = _profile.get("cameras", _DEFAULT_CAMERAS)

# --- UI Coordinates (from YAML or defaults) ---
_ui = _profile.get("ui_coords", _DEFAULT_UI_COORDS)
FULLSCREEN_TAP_COORDS = _ui.get("fullscreen_btn", _DEFAULT_UI_COORDS["fullscreen_btn"])
MENU_TAP_COORDS = _ui.get("dismiss_controls", _DEFAULT_UI_COORDS["dismiss_controls"])
APP_ICON_TAP_COORDS = _ui.get("app_icon", _DEFAULT_UI_COORDS["app_icon"])

# --- Pre-capture sequence (derived from UI coords) ---
PRE_CAPTURE_WAIT_SECONDS = 2
PRE_CAPTURE_SEQUENCE = [
    {"type": "tap", "coords": FULLSCREEN_TAP_COORDS, "label": "fullscreen_btn"},
    {"type": "wait", "duration": PRE_CAPTURE_WAIT_SECONDS},
    {"type": "tap", "coords": MENU_TAP_COORDS, "label": "dismiss_controls"},
]

# --- Timing Delays (in seconds) ---
INTER_CAMERA_DELAY_SECONDS = 1.0
WAIT_STREAM_LOAD_SECONDS = 25

# --- Post-capture ---
POST_CAPTURE_BACK_COUNT = 2
POST_BACK_DELAY_SECONDS = 0.5

# --- Capture Loop (Cadence) ---
CAPTURE_INTERVAL_SECONDS = int(os.getenv("INGESTER_CAPTURE_INTERVAL_SECONDS", "300"))
HEALTH_INTERVAL_SECONDS = 60
RUN_FOREVER = _parse_bool_env(os.getenv("INGESTER_RUN_FOREVER"), True)
MAX_CYCLES = int(os.getenv("INGESTER_MAX_CYCLES", "0")) or None
# Legacy fixed backoff (replaced by exponential backoff — see ERROR_BACKOFF_BASE_SECONDS).
ERROR_BACKOFF_SECONDS = 30
CAPTURE_ADB_TIMEOUT_SECONDS = 30
HEALTH_ADB_TIMEOUT_SECONDS = 15

ENABLE_CONNECTIVITY_DUMPSYS = False

# --- Logging ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
HEALTH_JSONL_FILENAME = "health.jsonl"
CYCLES_JSONL_PATH = os.path.join(LOG_DIR, "cycles.jsonl")
CONTROL_JSON_PATH = os.path.join(LOG_DIR, "control.json")

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

# Recovery settings
MAX_STATE_RECOVERY_ATTEMPTS = 2
PRE_CAPTURE_RETRY_MAX = 2
STATE_CHECK_WAIT_SECONDS = 1.0

# Periodic app restart to prevent memory leaks (ICSee heap exhaustion).
APP_RESTART_EVERY_N_CYCLES = int(os.getenv("INGESTER_APP_RESTART_EVERY_N_CYCLES", "50"))

# Circuit breaker: after N consecutive cycle failures, force-stop the app.
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("INGESTER_CIRCUIT_BREAKER_THRESHOLD", "3"))

# Exponential backoff on consecutive failures (seconds).
ERROR_BACKOFF_BASE_SECONDS = 10
ERROR_BACKOFF_MAX_SECONDS = 300

# Max consecutive failures before stopping the loop entirely.
MAX_CONSECUTIVE_FAILURES = int(os.getenv("INGESTER_MAX_CONSECUTIVE_FAILURES", "10"))

# Number of BACK presses after app launch to dismiss overlays (CloudWebActivity, ads, etc.)
APP_LAUNCH_DISMISS_BACK_PRESSES = 2
APP_LAUNCH_DISMISS_DELAY_SECONDS = 1.0

# --- Per-camera circuit breaker ---
CAMERA_CB_FAILURE_THRESHOLD = int(os.getenv("INGESTER_CAMERA_CB_FAILURE_THRESHOLD", "3"))
CAMERA_CB_COOLDOWN_SECONDS = int(os.getenv("INGESTER_CAMERA_CB_COOLDOWN_SECONDS", "600"))

# --- Cycle watchdog (global timeout per cycle) ---
CYCLE_TIMEOUT_SECONDS = int(os.getenv("INGESTER_CYCLE_TIMEOUT_SECONDS", "180"))

# --- Health check total timeout budget ---
HEALTH_CHECK_TOTAL_TIMEOUT_SECONDS = int(os.getenv("INGESTER_HEALTH_TOTAL_TIMEOUT", "60"))

# --- App recovery: known launcher packages ---
LAUNCHER_PACKAGES = ["com.android.launcher", "com.android.launcher3", "com.sec.android.app.launcher"]

# Screen state thresholds (from YAML or defaults)
SCREEN_STATE_THRESHOLDS = _profile.get("screen_thresholds", _DEFAULT_SCREEN_THRESHOLDS)

