"""Configuration for the YOLO worker."""
import os

# Directory where esp32-server saves uploaded images.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")

# Directory to persist per-device state (last_count).
STATE_DIR = os.getenv("STATE_DIR", "/app/state")

# YOLO model paths.
P1_MODEL_PATH = os.getenv("P1_MODEL_PATH", "/app/models/yolov8_2142.pt")
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

# Processed images marker strategy: "marker" (create .processed file) or "move"
PROCESSED_STRATEGY = os.getenv("PROCESSED_STRATEGY", "marker")

# Redis connection string (used for real-time notifications via SSE).
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Master switch — set WORKER_ENABLED=false to keep the container alive but idle.
# Primary mechanism: use Docker Compose profile "worker" to not start it at all.
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").strip().lower() not in ("false", "0", "no")

# Mock mode — set MOCK_MODE=true to run without real YOLO model files.
# The mock generates random detections so the full pipeline can be tested.
# Fine-tune with: MOCK_DETECTION_PROB (0-1), MOCK_MAX_OBJECTS (int), MOCK_INFRATOR_PROB (0-1).
MOCK_MODE = os.getenv("MOCK_MODE", "false").strip().lower() in ("true", "1", "yes")
