"""Configuration for the worker (YOLO and Gemini modes)."""
import logging
import os

# Directory where esp32-server saves uploaded images.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")

# Directory to persist per-device state (last_count + audits).
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

# Detection confidence threshold (applies to YOLO detectors).
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.25"))

# Inference mode:
#   yolo   -> YOLO only (legacy behavior)
#   shadow -> YOLO persists detections, Gemini runs only for audit/metrics
#   gemini -> Gemini persists detections
AI_MODE = os.getenv("AI_MODE", "yolo").strip().lower()
if AI_MODE not in {"yolo", "shadow", "gemini"}:
    logging.getLogger(__name__).warning("Invalid AI_MODE=%s. Falling back to 'yolo'.", AI_MODE)
    AI_MODE = "yolo"

# PostgreSQL connection string (sync - psycopg2).
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@db:5432/saira_db",
)

# Base URL of the esp32-server (used to build image_url for the frontend).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5002")

# How often to scan the uploads directory for new images (seconds).
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))

# Prometheus metrics endpoint exposed by the worker process.
WORKER_METRICS_ENABLED = os.getenv("WORKER_METRICS_ENABLED", "true").strip().lower() in ("true", "1", "yes")
WORKER_METRICS_HOST = os.getenv("WORKER_METRICS_HOST", "0.0.0.0").strip()
WORKER_METRICS_PORT = int(os.getenv("WORKER_METRICS_PORT", "9108"))

# Processed images strategy:
#   "two_folders" - move to ocorrencias/ or sem_ocorrencia/ based on detection outcome (default)
#   "marker"      - create .jpg.processed sibling file (legacy)
PROCESSED_STRATEGY = os.getenv("PROCESSED_STRATEGY", "two_folders")

# Redis connection string (used for real-time notifications via SSE).
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Master switch - set WORKER_ENABLED=false to keep the container alive but idle.
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").strip().lower() not in ("false", "0", "no")

# Google Drive daily sync settings.
GDRIVE_ENABLED = os.getenv("GDRIVE_ENABLED", "false").strip().lower() in ("true", "1", "yes")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")
GDRIVE_SA_KEY_PATH = os.getenv("GDRIVE_SA_KEY_PATH", "/app/gdrive-sa-key.json")
GDRIVE_SYNC_HOUR = int(os.getenv("GDRIVE_SYNC_HOUR", "3"))  # 03:00 Brasilia by default

# esp32-server base URL - used to trigger history bulk-upload after detection.
ESP32_SERVER_URL = os.getenv("ESP32_SERVER_URL", "").strip().rstrip("/")

# Mock mode - set MOCK_MODE=true to run without real YOLO model files.
MOCK_MODE = os.getenv("MOCK_MODE", "false").strip().lower() in ("true", "1", "yes")

# Gemini settings.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "2"))
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.0"))
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "4096"))
GEMINI_SEQUENCE_SIZE = int(os.getenv("GEMINI_SEQUENCE_SIZE", "5"))
GEMINI_SEQUENCE_MAX_SPAN_SECONDS = int(os.getenv("GEMINI_SEQUENCE_MAX_SPAN_SECONDS", "4"))
GEMINI_ENABLE_BATCH = os.getenv("GEMINI_ENABLE_BATCH", "false").strip().lower() in ("true", "1", "yes")
GEMINI_DRY_RUN = os.getenv("GEMINI_DRY_RUN", "false").strip().lower() in ("true", "1", "yes")
GEMINI_MAX_PAYLOAD_BYTES = int(os.getenv("GEMINI_MAX_PAYLOAD_BYTES", "8000000"))
GEMINI_CASCADE_ENABLED = os.getenv("GEMINI_CASCADE_ENABLED", "false").strip().lower() in ("true", "1", "yes")
GEMINI_CASCADE_WINDOW_SECONDS = int(os.getenv("GEMINI_CASCADE_WINDOW_SECONDS", "120"))
GEMINI_CASCADE_MAX_FRAMES = int(os.getenv("GEMINI_CASCADE_MAX_FRAMES", "12"))
GEMINI_CASCADE_MIN_FRAMES = int(os.getenv("GEMINI_CASCADE_MIN_FRAMES", "6"))
GEMINI_AGENT1_MODEL = os.getenv("GEMINI_AGENT1_MODEL", GEMINI_MODEL).strip()
GEMINI_AGENT1_TIMEOUT_SECONDS = int(os.getenv("GEMINI_AGENT1_TIMEOUT_SECONDS", str(GEMINI_TIMEOUT_SECONDS)))
GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE = int(os.getenv("GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE", "85"))
GEMINI_AGENT1_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_AGENT1_MAX_OUTPUT_TOKENS", "4096"))
GEMINI_AGENT1_THINKING_BUDGET = int(os.getenv("GEMINI_AGENT1_THINKING_BUDGET", "2048"))

# Mosaic mode — compose frames into a single image before sending to Gemini.
# GEMINI_MOSAIC_AGENT1: "true"/"false" — 2x1 side-by-side for the gate.
# GEMINI_MOSAIC_AGENT2: "off" | "4x3" | "3x2split" — grid layout for detail agent.
GEMINI_MOSAIC_AGENT1: bool = os.getenv("GEMINI_MOSAIC_AGENT1", "false").strip().lower() in ("true", "1", "yes")
GEMINI_MOSAIC_AGENT2: str = os.getenv("GEMINI_MOSAIC_AGENT2", "off").strip().lower()

# Visual grounding — require bounding box for Agent 2 infraction confirmation.
GEMINI_REQUIRE_BBOX = os.getenv("GEMINI_REQUIRE_BBOX", "true").strip().lower() in ("true", "1", "yes")

# Token cost estimation (USD per 1M tokens) — gemini-2.5-flash pricing (non-thinking).
GEMINI_INPUT_TOKEN_PRICE_PER_1M = float(os.getenv("GEMINI_INPUT_TOKEN_PRICE_PER_1M", "0.15"))
GEMINI_OUTPUT_TOKEN_PRICE_PER_1M = float(os.getenv("GEMINI_OUTPUT_TOKEN_PRICE_PER_1M", "0.60"))

# S3 daily migration settings.
S3_ENABLED = os.getenv("S3_ENABLED", "false").strip().lower() in ("true", "1", "yes")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "").strip()
S3_REGION = os.getenv("S3_REGION", "sa-east-1").strip()
S3_SYNC_HOUR = int(os.getenv("S3_SYNC_HOUR", "3"))  # 03:00 Brasilia by default
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()

# Auto-enable mock mode when model files are missing so the pipeline runs end-to-end for testing.
if not MOCK_MODE and (not os.path.exists(P1_MODEL_PATH) or not os.path.exists(P2_MODEL_PATH)):
    logging.getLogger(__name__).warning(
        "Model file(s) not found (%s, %s) - MOCK_MODE activated automatically. "
        "Provide model weights or set MOCK_MODE=true to suppress this warning.",
        P1_MODEL_PATH,
        P2_MODEL_PATH,
    )
    MOCK_MODE = True

# -----------------------------------------------------------------------------
# Car-stopped shadow detector (Gabriel's CarDetectionModule, ported).
# Runs in parallel with the Gemini cascade for comparison; never persists to
# the `detections` table. Audit goes to STATE_DIR/car_shadow_audit/.
# -----------------------------------------------------------------------------
CAR_SHADOW_ENABLED = os.getenv("CAR_SHADOW_ENABLED", "false").strip().lower() in ("true", "1", "yes")
CAR_MODEL_PATH = os.getenv("CAR_MODEL_PATH", "/app/models/yolov8_Car_tesi_100_n.pt")
CAR_CONF_THRESHOLD = float(os.getenv("CAR_CONF_THRESHOLD", "0.35"))
CAR_STATIONARY_PIXELS = float(os.getenv("CAR_STATIONARY_PIXELS", "50.0"))
CAR_LOW_FRAMES = int(os.getenv("CAR_LOW_FRAMES", "3"))
CAR_MED_FRAMES = int(os.getenv("CAR_MED_FRAMES", "6"))
CAR_HIGH_FRAMES = int(os.getenv("CAR_HIGH_FRAMES", "12"))
CAR_TRACK_TTL_SECONDS = int(os.getenv("CAR_TRACK_TTL_SECONDS", "300"))
CAR_MAX_BUFFER_FRAMES = int(os.getenv("CAR_MAX_BUFFER_FRAMES", "12"))

# If the car model is missing, disable the shadow detector instead of crashing
# the worker on startup. The Gemini cascade keeps working unaffected.
if CAR_SHADOW_ENABLED and not os.path.exists(CAR_MODEL_PATH):
    logging.getLogger(__name__).warning(
        "CAR_SHADOW_ENABLED=true but model not found at %s — disabling car shadow.",
        CAR_MODEL_PATH,
    )
    CAR_SHADOW_ENABLED = False
