"""Configuration for the YOLO worker."""
import os

# Directory where esp32-server saves uploaded images.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")

# Directory to persist per-device state (last_count).
STATE_DIR = os.getenv("STATE_DIR", "/app/state")

# YOLO model paths.
_P1_DEFAULT_CANDIDATES = (
    "/app/models/yolov8_MDM_200_n.pt",
    "/app/models/yolov8_2142.pt",  # legacy model (fallback)
)

def _resolve_default_p1_model_path() -> str:
    for candidate in _P1_DEFAULT_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return _P1_DEFAULT_CANDIDATES[0]

P1_MODEL_PATH = os.getenv("P1_MODEL_PATH", _resolve_default_p1_model_path())
P2_MODEL_PATH = os.getenv("P2_MODEL_PATH", "/app/models/yolov8_PeopleCar_200_n.pt")

# Detection confidence threshold (applied to both models).
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.25"))

# PostgreSQL connection string (sync — psycopg2).
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@db:5432/saira_db",
)

# Base URL of the esp32-server (used to build image_url for the frontend).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5002")

# How often to scan the uploads directory for new images (seconds).
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))

# Processed images strategy:
#   "two_folders" — move to ocorrencias/ or sem_ocorrencia/ based on detection outcome (default)
#   "marker"      — create .jpg.processed sibling file (legacy)
PROCESSED_STRATEGY = os.getenv("PROCESSED_STRATEGY", "two_folders")

# Redis connection string (used for real-time notifications via SSE).
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Master switch — set WORKER_ENABLED=false to keep the container alive but idle.
# Primary mechanism: use Docker Compose profile "worker" to not start it at all.
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").strip().lower() not in ("false", "0", "no")

# Google Drive daily sync settings.
# Set GDRIVE_ENABLED=true and provide GDRIVE_FOLDER_ID + GDRIVE_SA_KEY_PATH to activate.
# The worker will upload ocorrencias/ and sem_ocorrencia/ to Drive every day at GDRIVE_SYNC_HOUR,
# then delete sem_ocorrencia/ locally to free disk space.
GDRIVE_ENABLED = os.getenv("GDRIVE_ENABLED", "false").strip().lower() in ("true", "1", "yes")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")
GDRIVE_SA_KEY_PATH = os.getenv("GDRIVE_SA_KEY_PATH", "/app/gdrive-sa-key.json")
GDRIVE_SYNC_HOUR = int(os.getenv("GDRIVE_SYNC_HOUR", "3"))  # 03:00 Brasília by default

# esp32-server base URL — used to trigger history bulk-upload after detection.
# Leave empty to disable the trigger (no bulk-upload will be requested).
ESP32_SERVER_URL = os.getenv("ESP32_SERVER_URL", "").strip().rstrip("/")

# Mock mode — set MOCK_MODE=true to run without real YOLO model files.
# The mock generates random detections so the full pipeline can be tested.
# Fine-tune with: MOCK_DETECTION_PROB (0-1), MOCK_MAX_OBJECTS (int), MOCK_INFRATOR_PROB (0-1).
MOCK_MODE = os.getenv("MOCK_MODE", "false").strip().lower() in ("true", "1", "yes")

# Auto-enable mock mode when model files are missing so the pipeline runs
# end-to-end for testing even without trained weights.
if not MOCK_MODE and (not os.path.exists(P1_MODEL_PATH) or not os.path.exists(P2_MODEL_PATH)):
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "Model file(s) not found (%s, %s) — MOCK_MODE activated automatically. "
        "Provide model weights or set MOCK_MODE=true to suppress this warning.",
        P1_MODEL_PATH, P2_MODEL_PATH,
    )
    MOCK_MODE = True
