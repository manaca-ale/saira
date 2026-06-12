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

# Event-driven devices (Pi relay with on-device motion gate): these devices
# upload frames tagged with an event_id and the esp32-server writes a JSON
# manifest per event. The worker processes the manifest's frame set the
# moment the event closes (skipping _collect_time_windows entirely), cutting
# disposal->detection latency from the fixed 120s window to ~one poll cycle.
EVENT_DRIVEN_DEVICES = {
    d.strip()
    for d in os.getenv("EVENT_DRIVEN_DEVICES", "").split(",")
    if d.strip()
}
# Manifest stuck in state=open with no update for this long is treated as
# closed (device died mid-event / lost end-frame).
EVENT_STALE_SECONDS = int(os.getenv("EVENT_STALE_SECONDS", "180"))
# Events with fewer resolved frames than this skip Gemini (GC only).
EVENT_MIN_FRAMES = int(os.getenv("EVENT_MIN_FRAMES", "3"))
# Frames of an event-driven device not referenced by any pending manifest
# (heartbeats, late spool retries) are marked processed without Gemini calls
# once older than this grace period.
ORPHAN_GRACE_SECONDS = int(os.getenv("ORPHAN_GRACE_SECONDS", "300"))

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
# Vertex AI (keyless via Workload Identity Federation). When true, the worker
# authenticates to Gemini through Vertex (Cloud Billing pay-as-you-go) instead
# of an AI Studio API key. project/location come from env (location "global").
# Ported from prod (main 788ed7e) so test mirrors prod; activation is via the
# server .env (GEMINI_USE_VERTEX=true + GCP_PROJECT). Default off keeps the
# AI Studio key path until the WIF cred-config is wired.
GEMINI_USE_VERTEX = os.getenv("GEMINI_USE_VERTEX", "false").strip().lower() in ("true", "1", "yes")
GCP_PROJECT = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "")).strip()
GCP_LOCATION = os.getenv("GCP_LOCATION", os.getenv("GOOGLE_CLOUD_LOCATION", "global")).strip()
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

# Dual gate (full-frame + pile-crop) — runs Agent-1 a SECOND time on a crop of the
# pile zone (cameras.pile_zone_polygon) and escalates if EITHER pass triggers.
# Catches small/zoom-dependent dumps (handcart) that the full frame misses, while the
# full frame keeps the context-dependent ones. Campaign 19: 92% TP recall / 15%
# baseline for esp32_002 (vs 76%/13% full-only). Scoped per-device; default OFF.
GEMINI_GATE_PILECROP_ENABLED = os.getenv("GEMINI_GATE_PILECROP_ENABLED", "false").strip().lower() in ("true", "1", "yes")
GATE_PILECROP_DEVICES = {
    d.strip().lower()
    for d in os.getenv("GATE_PILECROP_DEVICES", "esp32_002").split(",")
    if d.strip()
}
GEMINI_GATE_PILECROP_UPSCALE = int(os.getenv("GEMINI_GATE_PILECROP_UPSCALE", "2"))

# Detail-side pile-crop augmentation (Agent-2). Adds N hi-res crops of the pile
# zone alongside the standard 48 global frames, plus a per-camera prompt
# (MANGABEIRA_E_WITH_PILECROPS). Campaign 24 (2026-05-30) result for esp32_002:
# recall 91.7% (matches V1 baseline), specificity 35% (1.6× the 21% of V1),
# accuracy 67.5% (vs 53.8% V1). +30% input tokens (~$0.015/event vs $0.010).
# Scoped per-device via DETAIL_PILECROP_DEVICES; default OFF.
GEMINI_DETAIL_PILECROP_ENABLED = os.getenv("GEMINI_DETAIL_PILECROP_ENABLED", "false").strip().lower() in ("true", "1", "yes")
DETAIL_PILECROP_DEVICES = {
    d.strip().lower()
    for d in os.getenv("DETAIL_PILECROP_DEVICES", "esp32_002").split(",")
    if d.strip()
}
GEMINI_DETAIL_PILECROP_UPSCALE = int(os.getenv("GEMINI_DETAIL_PILECROP_UPSCALE", "2"))
GEMINI_DETAIL_PILECROP_N_FRAMES = int(os.getenv("GEMINI_DETAIL_PILECROP_N_FRAMES", "12"))

# -----------------------------------------------------------------------------
# Sliding-window SHADOW A/B (Camp 36, 2026-06-05). Runs an overlapping sliding
# window (window_s, stride) alongside the live fixed-window pipeline and ONLY
# LOGS what it would do — never creates detections/notifications nor mutates the
# prod cascade state / BGSUB baseline. Goal: measure FP/latency of the sliding
# strategy WITH the real BGSUB pre-filter, on live data, to compare vs the fixed
# pipeline. BGSUB suppresses empty windows BEFORE the gate, so the extra Gemini
# cost is proportional to scene activity (near-zero on idle cameras).
# Offline sim (camp 36) picked slide_120/stride60 as the best latency↔FP Pareto.
# Decisions persisted to STATE_DIR/sliding_shadow_audit/{date}/{device}.jsonl
# (survives container recreate — same pattern as DINOv2 shadow). Default OFF.
GEMINI_SLIDING_SHADOW_ENABLED = os.getenv("GEMINI_SLIDING_SHADOW_ENABLED", "false").strip().lower() in ("true", "1", "yes")
SLIDING_SHADOW_DEVICES = {
    d.strip().lower()
    for d in os.getenv("SLIDING_SHADOW_DEVICES", "esp32_002").split(",")
    if d.strip()
}
GEMINI_SLIDING_WINDOW_SECONDS = int(os.getenv("GEMINI_SLIDING_WINDOW_SECONDS", "120"))
GEMINI_SLIDING_STRIDE_SECONDS = int(os.getenv("GEMINI_SLIDING_STRIDE_SECONDS", "60"))
GEMINI_SLIDING_MIN_FRAMES = int(os.getenv("GEMINI_SLIDING_MIN_FRAMES", "12"))
GEMINI_SLIDING_MAX_FRAMES = int(os.getenv("GEMINI_SLIDING_MAX_FRAMES", "24"))
# Coalescing window for operator-facing FP counting (mirrors EVENT_WINDOW_MIN).
GEMINI_SLIDING_COALESCE_SECONDS = int(os.getenv("GEMINI_SLIDING_COALESCE_SECONDS", "600"))

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

# Morphological post-processing mode (added 2026-05-25 smoke test).
# Modes:
#   "open_close" (default, preserva comportamento atual): MORPH_OPEN + MORPH_CLOSE
#       — reduz speckle noise mas pode eliminar objetos pequenos.
#   "area_min": substitui morpho por filtro de área mínima por contour (BGSUB_AREA_MIN).
#       Smoke test 25/05 com area_min=400 filtrou +2 FPs (tráfico esp32_001 09:30,
#       10:00) preservando 3/3 TPs. Recomendação Deep Research (paper Porikli):
#       morpho mata objetos <5% ROI.
#   "off": sem pós-processamento (modo experimental, alta noise).
BGSUB_MORPHO_MODE = os.getenv("BGSUB_MORPHO_MODE", "open_close").strip().lower()
BGSUB_AREA_MIN = int(os.getenv("BGSUB_AREA_MIN", "400"))

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
# Per-camera opt-out of the adaptive baseline. Cameras listed here keep the
# static (calibrated) baseline and never absorb gate-confirmed-empty windows,
# avoiding adaptive drift on chronic/busy points (e.g. esp32_005 Arruda, where
# the drift pinned persistence to 0.0 and suppressed real disposals — see camp
# 33). Such cameras rely on a frozen fresh baseline + periodic recalibration
# instead. Default empty → global BGSUB_ADAPTIVE_ENABLED behaviour unchanged.
BGSUB_ADAPTIVE_DISABLE_DEVICES = {
    d.strip().lower()
    for d in os.getenv("BGSUB_ADAPTIVE_DISABLE_DEVICES", "").split(",")
    if d.strip()
}

# Clean-zone-only adaptive (esp32_005 Arruda, 2026-06-10). Cameras listed here
# run the adaptive baseline BUT only absorb a window when the gate confirms the
# pile zone is genuinely CLEAN (no pre-existing pile AND no litter in the last
# frame) — not merely "no NEW litter". This makes drop-and-stay drift
# structurally impossible on chronic/busy points (the litter never enters the
# baseline), while still adapting during genuinely-empty intervals. Pair with a
# frequent mix-night re-anchor so the baseline stays fresh even when the zone is
# rarely clean. A device here must NOT also be in BGSUB_ADAPTIVE_DISABLE_DEVICES.
# Default empty → no behaviour change.
BGSUB_ADAPTIVE_CLEAN_ZONE_ONLY_DEVICES = {
    d.strip().lower()
    for d in os.getenv("BGSUB_ADAPTIVE_CLEAN_ZONE_ONLY_DEVICES", "").split(",")
    if d.strip()
}

# BGSUB shadow (log-only) devices. For cameras here, BGSUB still EVALUATES (and
# the adaptive baseline still updates), but a should_suppress decision is only
# LOGGED with "shadow": true — the window always proceeds to the Gemini gate (no
# enforcement). Lets us validate a new BGSUB config on real prod traffic with
# ZERO recall risk before flipping to enforce (same off/shadow/enforce pattern as
# DINOv2). Remove the device from this set to enforce. Default empty → enforce.
BGSUB_SHADOW_DEVICES = {
    d.strip().lower()
    for d in os.getenv("BGSUB_SHADOW_DEVICES", "").split(",")
    if d.strip()
}

# Weekly recalibration: night-frame mixing (item 6, 2026-06-09). esp32_005 (Arruda)
# has a frozen baseline biased to daytime — nighttime persistence sits near the
# threshold → spurious baseline alarms. For devices listed here, the recalibration
# samples across the last LOOKBACK_DAYS and forces a NIGHT_FRACTION of frames from
# NIGHT_HOURS so the baseline isn't day-biased. Empty set = legacy behavior
# (single latest day-dir, evenly spaced). Runs inside the worker container, so set
# this in the worker env (the cron does `docker exec ... python -m worker.recalibrate_bgsub`).
BGSUB_RECAL_MIX_NIGHT_DEVICES = {
    d.strip().lower()
    for d in os.getenv("BGSUB_RECAL_MIX_NIGHT_DEVICES", "").split(",")
    if d.strip()
}
BGSUB_RECAL_NIGHT_FRACTION = float(os.getenv("BGSUB_RECAL_NIGHT_FRACTION", "0.4"))
BGSUB_RECAL_NIGHT_HOURS = {
    int(h.strip())
    for h in os.getenv("BGSUB_RECAL_NIGHT_HOURS", "0,1,2,3,4,5").split(",")
    if h.strip().isdigit()
}
BGSUB_RECAL_LOOKBACK_DAYS = int(os.getenv("BGSUB_RECAL_LOOKBACK_DAYS", "7"))

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

# -----------------------------------------------------------------------------
# DINOv2 post-detail FP filter (rejection-only) — re-julga um CON do Agent-2 e
# pode revertê-lo a REJ. Ortogonal ao BGSUB (que é supressão pré-Agent-1).
# Validado offline em cam_10 Imbiribeira (Camp 26/27): pile-zone separável por
# embedding (RepeatedSKF 95,6%, AUC 0,945). ⚠️ Camp 27 expôs DRIFT temporal →
# nasce em SHADOW + exige retreino periódico. Ver detector_dinov2.py.
#
# Modos:
#   "off"     — inerte (default).
#   "shadow"  — computa p_con e LOGA o que rejeitaria; NÃO altera a decisão.
#   "enforce" — p_con<threshold ⇒ disposal=False (evento não vira ocorrência).
# -----------------------------------------------------------------------------
DINOV2_FILTER_MODE = os.getenv("DINOV2_FILTER_MODE", "off").strip().lower()
if DINOV2_FILTER_MODE not in ("off", "shadow", "enforce"):
    DINOV2_FILTER_MODE = "off"
DINOV2_FILTER_DEVICES = {
    d.strip().lower()
    for d in os.getenv("DINOV2_FILTER_DEVICES", "esp32_001").split(",")
    if d.strip()
}
DINOV2_MODELS_DIR = os.getenv("DINOV2_MODELS_DIR", os.path.join(STATE_DIR, "dinov2_models"))
DINOV2_VARIANT = os.getenv("DINOV2_VARIANT", "dinov2_vits14").strip()
DINOV2_INPUT_SIZE = int(os.getenv("DINOV2_INPUT_SIZE", "224"))
DINOV2_N_FRAMES = int(os.getenv("DINOV2_N_FRAMES", "3"))
# Threshold operacional. Vazio ⇒ usa o threshold gravado no artefato (.npz).
# Camp 27: platô t≈0,4–0,5 domina o t=0,2 da Camp 26 (mesmo 1 TP de custo, +spec).
_dino_thr = os.getenv("DINOV2_THRESHOLD", "").strip()
DINOV2_THRESHOLD = float(_dino_thr) if _dino_thr else None
DINOV2_TORCH_THREADS = int(os.getenv("DINOV2_TORCH_THREADS", "2"))
# Retreino semanal (worker.retrain_dinov2). Refita o classifier nos rótulos atuais
# e promove só se passar o gate (AUC>=min E n não encolheu). Default = devices do filtro.
DINOV2_RETRAIN_DEVICES = {
    d.strip().lower()
    for d in os.getenv("DINOV2_RETRAIN_DEVICES", ",".join(sorted(DINOV2_FILTER_DEVICES))).split(",")
    if d.strip()
}
DINOV2_RETRAIN_MIN_AUC = float(os.getenv("DINOV2_RETRAIN_MIN_AUC", "0.85"))

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

# Auto-enable mock mode when the YOLO model files are missing so the pipeline runs
# end-to-end for testing. Only relevant when AI_MODE uses local YOLO ("yolo"/"shadow");
# in "gemini" mode the P1/P2 weights are never loaded, so a missing model must NOT flip
# MOCK_MODE on — doing so was harmless but misleading in prod logs (the worker runs the
# Gemini cascade regardless). Guarded on AI_MODE so gemini-mode prod no longer auto-mocks.
if (
    not MOCK_MODE
    and AI_MODE in {"yolo", "shadow"}
    and (not os.path.exists(P1_MODEL_PATH) or not os.path.exists(P2_MODEL_PATH))
):
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
