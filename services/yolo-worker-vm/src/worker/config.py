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

# Event coalescing window: when a detection is about to be persisted, if the
# same camera already has a detection within this many minutes, reuse that
# detection_id (merge frames + upgrade fields) instead of creating a new row.
# Set to 0 to disable coalescing entirely (every window becomes a new detection).
EVENT_WINDOW_MIN = int(os.getenv("EVENT_WINDOW_MIN", "10"))

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

# Prompt version selector — "current" (V1, default) or "v2" (behavioral discriminators).
# V2 adds material_flow_direction + pile_volume_change + UNIFORM IS NOT A DISCRIMINATOR.
# Default stays on V1 until campanha 11 validates V2 against the official dataset.
GEMINI_PROMPT_VERSION = os.getenv("GEMINI_PROMPT_VERSION", "current").strip().lower()
if GEMINI_PROMPT_VERSION not in ("current", "v2", "v3", "audit"):
    logging.getLogger(__name__).warning(
        "Invalid GEMINI_PROMPT_VERSION=%s. Falling back to 'current'.", GEMINI_PROMPT_VERSION,
    )
    GEMINI_PROMPT_VERSION = "current"

# Separate flag for the Detail agent (Agent-2). Allows running gate with V1
# (default, validated) while testing the audit prompt only on the detail side.
# Values: "current" (V1) | "v2" | "v3" | "audit" | "audit_v2"
# - audit: V1 adversarial reviewer, force-false unless real_dumping (camp 15 FAIL)
# - audit_v2: relaxed, force-false only for 5 unambiguous FP patterns (camp 16)
GEMINI_DETAIL_PROMPT_VERSION = os.getenv("GEMINI_DETAIL_PROMPT_VERSION", "").strip().lower()
if GEMINI_DETAIL_PROMPT_VERSION not in ("", "current", "v2", "v3", "audit", "audit_v2"):
    logging.getLogger(__name__).warning(
        "Invalid GEMINI_DETAIL_PROMPT_VERSION=%s. Falling back to GEMINI_PROMPT_VERSION.",
        GEMINI_DETAIL_PROMPT_VERSION,
    )
    GEMINI_DETAIL_PROMPT_VERSION = ""
# Empty string means "use GEMINI_PROMPT_VERSION" (back-compat).

# -----------------------------------------------------------------------------
# BGSUB pre-filter (OpenCV background subtraction) — suppresses Gemini gate
# calls for genuinely-empty windows. See docs/bgsub_prefilter.md.
# Spike validated: threshold=1000 px → 100% TP keep + 73% baseline supr.
# -----------------------------------------------------------------------------
BGSUB_PREFILTER_ENABLED = os.getenv("BGSUB_PREFILTER_ENABLED", "false").strip().lower() in ("true", "1", "yes")
BGSUB_PERSISTENCE_THRESHOLD = int(os.getenv("BGSUB_PERSISTENCE_THRESHOLD", "1000"))
BGSUB_MIN_PX_ACTIVE = int(os.getenv("BGSUB_MIN_PX_ACTIVE", "800"))
BGSUB_MIN_PERSISTENCE_FRAMES = float(os.getenv("BGSUB_MIN_PERSISTENCE_FRAMES", "0.6"))
BGSUB_MODELS_DIR = os.getenv("BGSUB_MODELS_DIR", os.path.join(STATE_DIR, "bgsub_models"))
# MOG2 training params (must match script/calibrate_bgsub.py)
BGSUB_MOG2_HISTORY = int(os.getenv("BGSUB_MOG2_HISTORY", "80"))
BGSUB_MOG2_VAR_THRESHOLD = float(os.getenv("BGSUB_MOG2_VAR_THRESHOLD", "40.0"))
# Threshold to convert MOG2 raw output to binary foreground mask.
# MOG2 outputs: 0=background, ~127=possible shadow, 255=definite foreground.
# Default 200 was filtering too aggressively — dark objects (black trash bags)
# get ambiguous MOG2 values (80-150) and were silently dropped, causing TP loss
# in esp32_002 (validated 2026-05-23 against today's 09:00:54 missed disposal
# + 7 official-dataset TPs). 100 recovers TPs without inflating FP on real
# empty windows.
BGSUB_SHADOW_THRESHOLD = int(os.getenv("BGSUB_SHADOW_THRESHOLD", "100"))

# Adaptive baseline — when enabled, the MOG2 background absorbs frames that
# the Gemini gate confirmed as "no new litter" with high confidence. This
# tolerates lighting shifts (sun angle, IR mode), pile collection by EMLURB,
# and slow changes to the scene without manual recalibration.
# Trade-off: if Gemini misclassifies a TP as negative (rare), the BGSUB will
# absorb the descarte into baseline and may filter future similar scenes.
BGSUB_ADAPTIVE_ENABLED = os.getenv("BGSUB_ADAPTIVE_ENABLED", "false").strip().lower() in ("true", "1", "yes")
BGSUB_ADAPTIVE_LEARNING_RATE = float(os.getenv("BGSUB_ADAPTIVE_LEARNING_RATE", "0.05"))
BGSUB_ADAPTIVE_MIN_CONFIDENCE = int(os.getenv("BGSUB_ADAPTIVE_MIN_CONFIDENCE", "90"))
BGSUB_ADAPTIVE_SAVE_EVERY_N = int(os.getenv("BGSUB_ADAPTIVE_SAVE_EVERY_N", "50"))

# Dual-rate MOG2 — two background models per camera (fast + slow learning).
# Combines as `static_fg = slow_mask AND NOT fast_mask`, isolating objects that
# remain stationary while filtering out moving pedestrians/vehicles. Resolves
# the case (esp32_001, 25/05) where single-MOG2 produces 0% filter rate in
# scenes with constant pedestrian traffic. Default off (kill-switch).
BGSUB_DUAL_RATE_ENABLED = os.getenv("BGSUB_DUAL_RATE_ENABLED", "false").strip().lower() in ("true", "1", "yes")
BGSUB_LR_FAST = float(os.getenv("BGSUB_LR_FAST", "0.05"))
BGSUB_LR_SLOW = float(os.getenv("BGSUB_LR_SLOW", "0.001"))
BGSUB_MOG2_HISTORY_FAST = int(os.getenv("BGSUB_MOG2_HISTORY_FAST", str(BGSUB_MOG2_HISTORY)))
BGSUB_MOG2_HISTORY_SLOW = int(os.getenv("BGSUB_MOG2_HISTORY_SLOW", "400"))
# Adapt LRs default to evaluate LRs (kept separate for tuning flexibility).
BGSUB_LR_FAST_ADAPT = float(os.getenv("BGSUB_LR_FAST_ADAPT", str(BGSUB_LR_FAST)))
BGSUB_LR_SLOW_ADAPT = float(os.getenv("BGSUB_LR_SLOW_ADAPT", str(BGSUB_LR_SLOW)))
# Slow-model warm-up: when loading a v1 npz (single-rate) or building from cold,
# replay buffer N times with LR=LR_FAST to age the slow model quickly. Without
# this the slow model would need ~1000 frames to converge to the baseline.
BGSUB_SLOW_WARMUP_PASSES = int(os.getenv("BGSUB_SLOW_WARMUP_PASSES", "5"))

# Crop MOG2 input to polygon bbox — when true, MOG2 only runs on the bbox
# crop. NOTE: requires baseline to also be calibrated with crops (MOG2 state
# is bound to input shape). Default off until baseline-recalibration flow
# is wired. Pure optimization, no behavior change once correctly bootstrapped.
BGSUB_BBOX_CROP_ENABLED = os.getenv("BGSUB_BBOX_CROP_ENABLED", "false").strip().lower() in ("true", "1", "yes")

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

# Claude Haiku 4.5 via AWS Bedrock — alternative Detail-agent provider (A/B testing).
HAIKU_AWS_REGION = os.getenv("HAIKU_AWS_REGION", "us-east-1").strip()
HAIKU_AWS_PROFILE = os.getenv("HAIKU_AWS_PROFILE", "codex-ops").strip()
HAIKU_MODEL_ID = os.getenv(
    "HAIKU_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
).strip()
HAIKU_MAX_OUTPUT_TOKENS = int(os.getenv("HAIKU_MAX_OUTPUT_TOKENS", "4096"))
HAIKU_TIMEOUT_SECONDS = int(os.getenv("HAIKU_TIMEOUT_SECONDS", "30"))
HAIKU_MAX_RETRIES = int(os.getenv("HAIKU_MAX_RETRIES", "1"))
HAIKU_THINKING_BUDGET = int(os.getenv("HAIKU_THINKING_BUDGET", "0"))  # 0 = thinking OFF
HAIKU_INPUT_TOKEN_PRICE_PER_1M = float(os.getenv("HAIKU_INPUT_TOKEN_PRICE_PER_1M", "1.00"))
HAIKU_OUTPUT_TOKEN_PRICE_PER_1M = float(os.getenv("HAIKU_OUTPUT_TOKEN_PRICE_PER_1M", "5.00"))

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
