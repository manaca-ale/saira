"""Configuration for the worker."""
import logging
import os

logger = logging.getLogger(__name__)

# Directory where esp32-server saves uploaded images.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")

# Directory to persist per-device state (last_count).
STATE_DIR = os.getenv("STATE_DIR", "/app/state")

# YOLO model paths.
P1_MODEL_PATH = os.getenv("P1_MODEL_PATH", "/app/models/yolov8_2142.pt")
P2_MODEL_PATH = os.getenv("P2_MODEL_PATH", "/app/models/yolov8_PeopleCar_200_n.pt")

# Detection confidence threshold (applied to YOLO/mock).
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.25"))

# PostgreSQL connection string (sync, psycopg2).
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@db:5432/saira_db",
)

# Base URL of the esp32-server (used to build image_url for the frontend).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5002")

# How often to scan the uploads directory for new images (seconds).
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))

# Processed images strategy:
#   "two_folders" -> move to ocorrencias/ or sem_ocorrencia/ based on detection outcome (default)
#   "marker"      -> create .jpg.processed sibling file (legacy)
PROCESSED_STRATEGY = os.getenv("PROCESSED_STRATEGY", "two_folders")

# Redis connection string (used for real-time notifications via SSE).
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Legacy toggle (kept for backwards compatibility).
MOCK_MODE = os.getenv("MOCK_MODE", "false").strip().lower() in ("true", "1", "yes")

# Select inference provider: yolo | rekognition | mock
# Backwards compatibility:
# - if AI_MODEL_PROVIDER is unset and MOCK_MODE=true, provider becomes "mock".
AI_MODEL_PROVIDER = os.getenv("AI_MODEL_PROVIDER", "").strip().lower()
if not AI_MODEL_PROVIDER:
    AI_MODEL_PROVIDER = "mock" if MOCK_MODE else "yolo"

if AI_MODEL_PROVIDER not in {"yolo", "rekognition", "mock"}:
    raise ValueError(
        f"Invalid AI_MODEL_PROVIDER='{AI_MODEL_PROVIDER}'. "
        "Expected one of: yolo, rekognition, mock."
    )

# Optional fallback provider used when the primary provider fails.
AI_FALLBACK_PROVIDER = os.getenv("AI_FALLBACK_PROVIDER", "none").strip().lower()
if AI_FALLBACK_PROVIDER in {"", "none"}:
    AI_FALLBACK_PROVIDER = ""
elif AI_FALLBACK_PROVIDER not in {"yolo", "rekognition", "mock"}:
    raise ValueError(
        f"Invalid AI_FALLBACK_PROVIDER='{AI_FALLBACK_PROVIDER}'. "
        "Expected one of: none, yolo, rekognition, mock."
    )
elif AI_FALLBACK_PROVIDER == AI_MODEL_PROVIDER:
    logger.warning(
        "AI_FALLBACK_PROVIDER equals AI_MODEL_PROVIDER (%s). Ignoring fallback.",
        AI_MODEL_PROVIDER,
    )
    AI_FALLBACK_PROVIDER = ""

# AWS / Rekognition settings (used when AI_MODEL_PROVIDER=rekognition).
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
REKOGNITION_WASTE_DECISION_MODE = os.getenv("REKOGNITION_WASTE_DECISION_MODE", "binary").strip().lower()
REKOGNITION_WASTE_LABELS = os.getenv(
    "REKOGNITION_WASTE_LABELS",
    "Garbage,Trash,Waste,Debris,Litter,Junk,Refuse,Landfill",
)
REKOGNITION_WASTE_MIN_CONFIDENCE = float(os.getenv("REKOGNITION_WASTE_MIN_CONFIDENCE", "70"))
REKOGNITION_WASTE_TYPE_VALUE = os.getenv("REKOGNITION_WASTE_TYPE_VALUE", "Entulho")
REKOGNITION_OFFENDER_MODE = os.getenv("REKOGNITION_OFFENDER_MODE", "detect_labels").strip().lower()
REKOGNITION_OFFENDER_LABELS = os.getenv(
    "REKOGNITION_OFFENDER_LABELS",
    "Person,Car,Truck,Bus,Motorcycle,Bicycle",
)
REKOGNITION_OFFENDER_MIN_CONFIDENCE = float(os.getenv("REKOGNITION_OFFENDER_MIN_CONFIDENCE", "70"))
REKOGNITION_MAX_LABELS = int(os.getenv("REKOGNITION_MAX_LABELS", "50"))
REKOGNITION_MAX_RETRIES = int(os.getenv("REKOGNITION_MAX_RETRIES", "3"))
REKOGNITION_TIMEOUT_SECONDS = int(os.getenv("REKOGNITION_TIMEOUT_SECONDS", "10"))
REKOGNITION_MOSAIC_ENABLED = os.getenv("REKOGNITION_MOSAIC_ENABLED", "true").strip().lower() in ("true", "1", "yes")
REKOGNITION_MOSAIC_BATCH_SIZE = int(os.getenv("REKOGNITION_MOSAIC_BATCH_SIZE", "4"))
REKOGNITION_MOSAIC_TIMEOUT_SECONDS = int(os.getenv("REKOGNITION_MOSAIC_TIMEOUT_SECONDS", "8"))
REKOGNITION_MOSAIC_TILE_WIDTH = int(os.getenv("REKOGNITION_MOSAIC_TILE_WIDTH", "960"))
REKOGNITION_MOSAIC_TILE_HEIGHT = int(os.getenv("REKOGNITION_MOSAIC_TILE_HEIGHT", "720"))
REKOGNITION_MOSAIC_MAX_PAYLOAD_BYTES = int(os.getenv("REKOGNITION_MOSAIC_MAX_PAYLOAD_BYTES", "5242880"))
REKOGNITION_MOSAIC_JPEG_QUALITY_START = int(os.getenv("REKOGNITION_MOSAIC_JPEG_QUALITY_START", "90"))
REKOGNITION_MOSAIC_JPEG_QUALITY_MIN = int(os.getenv("REKOGNITION_MOSAIC_JPEG_QUALITY_MIN", "45"))
REKOGNITION_MOSAIC_MIN_DOWNSCALE_FACTOR = float(os.getenv("REKOGNITION_MOSAIC_MIN_DOWNSCALE_FACTOR", "0.5"))
REKOGNITION_MOSAIC_PARTIAL_MODE = os.getenv("REKOGNITION_MOSAIC_PARTIAL_MODE", "pad").strip().lower()

if REKOGNITION_MOSAIC_BATCH_SIZE < 1:
    REKOGNITION_MOSAIC_BATCH_SIZE = 1
if REKOGNITION_MOSAIC_BATCH_SIZE > 4:
    REKOGNITION_MOSAIC_BATCH_SIZE = 4
if REKOGNITION_MOSAIC_TIMEOUT_SECONDS < 1:
    REKOGNITION_MOSAIC_TIMEOUT_SECONDS = 1
if REKOGNITION_MOSAIC_PARTIAL_MODE not in {"pad", "single_fallback"}:
    REKOGNITION_MOSAIC_PARTIAL_MODE = "pad"

# Master switch: set WORKER_ENABLED=false to keep the container alive but idle.
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").strip().lower() not in ("false", "0", "no")

# Google Drive daily sync settings.
GDRIVE_ENABLED = os.getenv("GDRIVE_ENABLED", "false").strip().lower() in ("true", "1", "yes")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")
GDRIVE_SA_KEY_PATH = os.getenv("GDRIVE_SA_KEY_PATH", "/app/gdrive-sa-key.json")
GDRIVE_SYNC_HOUR = int(os.getenv("GDRIVE_SYNC_HOUR", "3"))  # 03:00 Brasilia by default

# Auto-switch to mock when YOLO weights are missing.
if AI_MODEL_PROVIDER == "yolo" and (not os.path.exists(P1_MODEL_PATH) or not os.path.exists(P2_MODEL_PATH)):
    logger.warning(
        "Model file(s) not found (%s, %s). Switching provider to mock.",
        P1_MODEL_PATH,
        P2_MODEL_PATH,
    )
    AI_MODEL_PROVIDER = "mock"
    MOCK_MODE = True
