# src/ingester/config.py
"""
Configuração centralizada para o Ingester service (modo RTSP/AWS).
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


# ---------------------------------------------------------------------------
# AWS Configuration
# ---------------------------------------------------------------------------
AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
S3_LANDING_ZONE_BUCKET: str = os.getenv("S3_LANDING_ZONE_BUCKET", "saira-landing-zone")
SQS_INGESTION_QUEUE_URL: str = os.getenv("SQS_INGESTION_QUEUE_URL", "")

# ---------------------------------------------------------------------------
# Storage backend (S3 or local filesystem)
# ---------------------------------------------------------------------------
STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "s3").strip().lower()
LOCAL_LANDING_ZONE_DIR: str = os.getenv(
    "LOCAL_LANDING_ZONE_DIR",
    os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "data", "landing-zone"),
)

# Optional toggles (useful when running everything inside a single EC2 without AWS)
ENABLE_S3: bool = _parse_bool_env(os.getenv("ENABLE_S3"), STORAGE_BACKEND == "s3")
ENABLE_SQS: bool = _parse_bool_env(os.getenv("ENABLE_SQS"), True)

# ---------------------------------------------------------------------------
# RTSP Capture Configuration
# ---------------------------------------------------------------------------
CAMERAS_CONFIG_PATH: str = os.getenv("CAMERAS_CONFIG_PATH", "config/cameras.yaml")
CAPTURE_INTERVAL_SECONDS: int = int(os.getenv("INGESTER_CAPTURE_INTERVAL_SECONDS", "300"))

# ---------------------------------------------------------------------------
# Loop Control
# ---------------------------------------------------------------------------
RUN_FOREVER: bool = _parse_bool_env(os.getenv("INGESTER_RUN_FOREVER"), True)
MAX_CYCLES: int | None = int(os.getenv("INGESTER_MAX_CYCLES", "0")) or None

# ---------------------------------------------------------------------------
# Circuit Breaker Configuration
# ---------------------------------------------------------------------------
CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = int(os.getenv("INGESTER_CB_FAILURE_THRESHOLD", "5"))
CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = int(os.getenv("INGESTER_CB_RECOVERY_TIMEOUT", "300"))

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
