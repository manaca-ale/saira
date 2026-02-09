"""Configuration for the YOLO worker (fake or real)."""
import os

# Directory where esp32-server saves uploaded images.
# Must match the UPLOAD_DIR / volume mount of esp32-server.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")

# PostgreSQL connection string (sync — psycopg2).
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/saira_db",
)

# Base URL of the esp32-server (used to build image_url for the frontend).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5001")

# How often to scan the uploads directory for new images (seconds).
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))

# When true, generate fake detections instead of running YOLO.
FAKE_MODE = os.getenv("FAKE_MODE", "true").lower() == "true"

# Processed images marker strategy: "marker" (create .processed file) or "move" (move to processed/ subdir)
PROCESSED_STRATEGY = os.getenv("PROCESSED_STRATEGY", "marker")
