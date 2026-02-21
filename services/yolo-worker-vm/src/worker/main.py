"""SAIRA YOLO worker — polls uploads dir, compares frames per device, writes detections to DB."""
import cv2
import json
import logging
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

BRASILIA = ZoneInfo("America/Sao_Paulo")

from . import config
from .db import (
    init_connections,
    resolve_camera,
    insert_detection,
    insert_offenders,
    update_camera_last_capture,
    publish_detection_event,
)
if config.MOCK_MODE:
    from .detector_mock import load_models, detect_garbage, detect_infrators
else:
    from .detector_yolo import load_models, detect_garbage, detect_infrators
from .models import DetectionRecord, OffenderRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

SKIP_DIRS = {"processed", "labeled"}

# ==========================================
# STATE MANAGEMENT (per device)
# ==========================================
def _state_path(device_id: str) -> Path:
    return Path(config.STATE_DIR) / f"{device_id}.json"

def load_state(device_id: str) -> dict:
    p = _state_path(device_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"last_count": 0}

def save_state(device_id: str, state: dict) -> None:
    """Atomic write via temp file + rename to prevent corruption on crash."""
    state_dir = Path(config.STATE_DIR)
    state_dir.mkdir(parents=True, exist_ok=True)
    target = _state_path(device_id)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(target)

# ==========================================
# PROCESSED MARKER
# ==========================================
def is_processed(image_path: Path) -> bool:
    if config.PROCESSED_STRATEGY == "marker":
        return image_path.with_suffix(".jpg.processed").exists()
    return "processed" in image_path.parts

def mark_processed(image_path: Path) -> None:
    if config.PROCESSED_STRATEGY == "marker":
        image_path.with_suffix(".jpg.processed").touch()
    else:
        processed_dir = image_path.parent / "processed"
        processed_dir.mkdir(exist_ok=True)
        image_path.rename(processed_dir / image_path.name)

# ==========================================
# HELPERS
# ==========================================
def parse_timestamp(filename: str) -> datetime:
    """Parse Brasília timestamp from filename (YYYY-MM-DD_HH-MM-SS). Returns naive Brasília datetime."""
    stem = Path(filename).stem
    try:
        return datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return datetime.now(BRASILIA).replace(tzinfo=None)

def estimate_volume(detections: list, img_w: int, img_h: int) -> Decimal:
    """Heuristic: bbox area ratio x scale factor. ~5% area = 1 m3."""
    if not detections:
        return Decimal("0.10")
    img_area = max(img_w * img_h, 1)
    bbox_area = sum(
        (d["bbox"][2] - d["bbox"][0]) * (d["bbox"][3] - d["bbox"][1])
        for d in detections
    )
    ratio = min(bbox_area / img_area, 1.0)
    return Decimal(str(round(max(ratio * 20.0, 0.10), 2)))

def dominant_waste_type(detections: list) -> str:
    if not detections:
        return "Entulho"
    counts: dict = {}
    for d in detections:
        wt = d["db_waste_type"]
        counts[wt] = counts.get(wt, 0) + 1
    return max(counts, key=counts.get)

def save_labeled_image(annotated_bgr, device_id: str, original: Path) -> str:
    """Save annotated image under uploads/device_id/labeled/... Return relative path."""
    device_base = Path(config.UPLOAD_DIR) / device_id
    try:
        date_parts = original.parent.relative_to(device_base)
    except ValueError:
        date_parts = Path("")
    labeled_dir = device_base / "labeled" / date_parts
    labeled_dir.mkdir(parents=True, exist_ok=True)
    labeled_path = labeled_dir / original.name
    cv2.imwrite(str(labeled_path), annotated_bgr)
    try:
        rel = labeled_path.relative_to(Path(config.UPLOAD_DIR))
    except ValueError:
        rel = Path(device_id) / "labeled" / original.name
    return str(rel).replace("\\", "/")

def build_image_url(rel_path: str) -> str:
    return f"{config.PUBLIC_BASE_URL.rstrip('/')}/uploads/{rel_path}"

# ==========================================
# CORE PROCESSING
# ==========================================
def process_image(jpg: Path, device_id: str, camera) -> bool:
    """Run inference, compare with last state. Returns True if disposal recorded."""
    garbage_dets, annotated = detect_garbage(jpg, conf=config.CONF_THRESHOLD)
    current_count = len(garbage_dets)

    state = load_state(device_id)
    last_count = state.get("last_count", 0)
    disposal = current_count > last_count

    if disposal:
        logger.info("[%s] DISPOSAL: %d->%d objects | %s", device_id, last_count, current_count, jpg.name)

        infrator_dets = detect_infrators(jpg, conf=config.CONF_THRESHOLD)

        labeled_rel = save_labeled_image(annotated, device_id, jpg)
        image_url = build_image_url(labeled_rel)

        img = cv2.imread(str(jpg))
        h, w = (img.shape[:2] if img is not None else (480, 640))
        volume = estimate_volume(garbage_dets, w, h)
        waste_type = dominant_waste_type(garbage_dets)
        max_conf = max((d["confidence"] for d in garbage_dets), default=0.0)

        offender_summary = None
        if infrator_dets:
            types = sorted(set(d["offender_type"] for d in infrator_dets))
            offender_summary = ", ".join(types)

        detection = DetectionRecord(
            id=uuid4(),
            camera_id=camera.id,
            timestamp=parse_timestamp(jpg.name),
            logradouro=camera.logradouro,
            bairro=camera.bairro,
            rpa=camera.rpa,
            latitude=camera.latitude,
            longitude=camera.longitude,
            waste_type=waste_type,
            material_type=None,
            volume_m3=volume,
            offenders=offender_summary,
            image_url=image_url,
            confidence_score=Decimal(str(round(max_conf, 2))),
        )

        if insert_detection(detection):
            publish_detection_event(detection, camera)
            if infrator_dets:
                offenders = [
                    OffenderRecord(
                        detection_id=detection.id,
                        offender_type=d["offender_type"],
                        confidence_score=Decimal(str(round(d["confidence"], 2))),
                    )
                    for d in infrator_dets
                ]
                insert_offenders(offenders)

    save_state(device_id, {"last_count": current_count})
    return disposal


def scan_and_process() -> int:
    upload_dir = Path(config.UPLOAD_DIR)
    if not upload_dir.exists():
        logger.warning("Upload directory not found: %s", upload_dir)
        return 0

    processed_count = 0
    for device_dir in sorted(upload_dir.iterdir()):
        if not device_dir.is_dir() or device_dir.name in SKIP_DIRS:
            continue
        device_id = device_dir.name

        camera = resolve_camera(device_id)
        if not camera:
            logger.debug("No camera registered for device_id=%s", device_id)
            continue

        images = sorted(
            (
                jpg for jpg in device_dir.rglob("*.jpg")
                if "labeled" not in jpg.parts and not is_processed(jpg)
            ),
            key=lambda p: p.name,
        )

        device_processed = 0
        for jpg in images:
            try:
                disposal = process_image(jpg, device_id, camera)
                mark_processed(jpg)
                processed_count += 1
                device_processed += 1
                if disposal:
                    logger.info("Disposal event recorded: %s / %s", device_id, jpg.name)
            except Exception:
                logger.exception("Error processing %s", jpg)

        if device_processed > 0:
            update_camera_last_capture(camera.id)

    return processed_count


def main():
    logger.info("=" * 60)
    logger.info("SAIRA Worker starting")
    logger.info("UPLOAD_DIR    = %s", config.UPLOAD_DIR)
    logger.info("STATE_DIR     = %s", config.STATE_DIR)
    logger.info("P1_MODEL      = %s", config.P1_MODEL_PATH)
    logger.info("P2_MODEL      = %s", config.P2_MODEL_PATH)
    logger.info("CONF          = %.2f", config.CONF_THRESHOLD)
    logger.info("POLL_INTERVAL = %ds", config.POLL_INTERVAL)
    logger.info("REDIS_URL     = %s", config.REDIS_URL)
    logger.info("WORKER_ENABLED= %s", config.WORKER_ENABLED)
    logger.info("MOCK_MODE     = %s", config.MOCK_MODE)
    logger.info("=" * 60)

    if not config.WORKER_ENABLED:
        logger.info("Worker is DISABLED (WORKER_ENABLED=false). Idling — set WORKER_ENABLED=true to activate.")
        while True:
            time.sleep(3600)

    init_connections()
    load_models(config.P1_MODEL_PATH, config.P2_MODEL_PATH)

    while True:
        try:
            n = scan_and_process()
            if n:
                logger.info("Cycle complete: %d images processed", n)
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception:
            logger.exception("Unhandled error in scan cycle")

        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    main()
