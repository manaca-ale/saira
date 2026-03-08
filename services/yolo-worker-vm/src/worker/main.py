"""SAIRA worker: polls uploads dir, runs inference, writes detections to DB."""
import cv2
import importlib
import json
import logging
import numpy as np
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from . import config
from .db import (
    init_connections,
    resolve_camera,
    insert_detection,
    insert_offenders,
    insert_notifications,
    update_camera_last_capture,
    publish_detection_event,
)
from .models import DetectionRecord, OffenderRecord

BRASILIA = ZoneInfo("America/Sao_Paulo")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

SKIP_DIRS = {"processed", "labeled"}
COLOR_GARBAGE = (0, 0, 220)    # red
COLOR_INFRATOR = (220, 140, 0)  # blue-orange

# Tracks the last day the Google Drive sync ran (reset on container restart).
_last_sync_day = None

# Runtime detector modules.
_detector_module = None
_fallback_detector_module = None


def _import_detector(provider: str):
    module_map = {
        "yolo": ".detector_yolo",
        "mock": ".detector_mock",
        "rekognition": ".detector_rekognition",
    }
    module_name = module_map.get(provider)
    if not module_name:
        raise RuntimeError(f"Unsupported AI provider: {provider}")
    return importlib.import_module(module_name, package=__package__)


def _setup_detectors() -> None:
    global _detector_module, _fallback_detector_module

    _detector_module = _import_detector(config.AI_MODEL_PROVIDER)
    logger.info("Primary AI provider loaded: %s", config.AI_MODEL_PROVIDER)

    if config.AI_FALLBACK_PROVIDER:
        _fallback_detector_module = _import_detector(config.AI_FALLBACK_PROVIDER)
        logger.info("Fallback AI provider loaded: %s", config.AI_FALLBACK_PROVIDER)


def _load_models() -> None:
    if _detector_module is None:
        raise RuntimeError("Detector module not initialized")

    _detector_module.load_models(config.P1_MODEL_PATH, config.P2_MODEL_PATH)

    if _fallback_detector_module is not None:
        try:
            _fallback_detector_module.load_models(config.P1_MODEL_PATH, config.P2_MODEL_PATH)
        except Exception:
            logger.exception(
                "Failed loading fallback provider '%s'. Continuing without fallback.",
                config.AI_FALLBACK_PROVIDER,
            )


def _run_inference(method_name: str, *args, **kwargs):
    if _detector_module is None:
        raise RuntimeError("Detector module not initialized")

    method = getattr(_detector_module, method_name)
    try:
        return method(*args, **kwargs)
    except Exception:
        if _fallback_detector_module is None:
            raise

        logger.exception(
            "Primary provider '%s' failed in %s. Falling back to '%s'.",
            config.AI_MODEL_PROVIDER,
            method_name,
            config.AI_FALLBACK_PROVIDER,
        )
        fallback_method = getattr(_fallback_detector_module, method_name)
        return fallback_method(*args, **kwargs)


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
    if config.PROCESSED_STRATEGY == "two_folders":
        return any(part in {"sem_ocorrencia", "ocorrencias"} for part in image_path.parts)
    return "processed" in image_path.parts


def mark_processed(image_path: Path, device_base: Path, disposal: bool) -> None:
    """Move image to the appropriate subfolder based on detection outcome."""
    if config.PROCESSED_STRATEGY == "marker":
        image_path.with_suffix(".jpg.processed").touch()
    elif config.PROCESSED_STRATEGY == "two_folders":
        subfolder = "ocorrencias" if disposal else "sem_ocorrencia"
        try:
            date_parts = image_path.parent.relative_to(device_base)
        except ValueError:
            date_parts = Path("")
        dest_dir = device_base / subfolder / date_parts
        dest_dir.mkdir(parents=True, exist_ok=True)
        image_path.rename(dest_dir / image_path.name)
    else:
        processed_dir = image_path.parent / "processed"
        processed_dir.mkdir(exist_ok=True)
        image_path.rename(processed_dir / image_path.name)


# ==========================================
# HELPERS
# ==========================================
def parse_timestamp(filename: str) -> datetime:
    """Parse Brasilia timestamp from filename (YYYY-MM-DD_HH-MM-SS)."""
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


def _annotate_from_mapped_detections(jpg: Path, garbage_dets: list[dict], infrator_dets: list[dict]):
    """Draw mapped detections on top of the original image."""
    img = cv2.imread(str(jpg))
    if img is None:
        img = np.zeros((480, 640, 3), dtype=np.uint8)

    annotated = img.copy()

    for d in garbage_dets:
        x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
        label = f"{d.get('class_name', 'waste')} {d.get('confidence', 0.0):.2f}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), COLOR_GARBAGE, 2)
        cv2.putText(
            annotated,
            label,
            (max(8, x1), max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            COLOR_GARBAGE,
            2,
            cv2.LINE_AA,
        )

    for d in infrator_dets:
        x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
        label = f"{d.get('offender_type', 'infrator')} {d.get('confidence', 0.0):.2f}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), COLOR_INFRATOR, 2)
        cv2.putText(
            annotated,
            label,
            (max(8, x1), min(annotated.shape[0] - 8, y2 + 16)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            COLOR_INFRATOR,
            2,
            cv2.LINE_AA,
        )

    return annotated


def _state_disposal_transition(device_id: str, current_count: int) -> tuple[bool, int]:
    state = load_state(device_id)
    last_count = int(state.get("last_count", 0))
    return current_count > last_count, last_count


def _persist_detection_if_needed(
    jpg: Path,
    device_id: str,
    camera,
    garbage_dets: list[dict],
    infrator_dets: list[dict],
    annotated,
    last_count: int,
    current_count: int,
) -> bool:
    disposal = current_count > last_count
    if not disposal:
        return False

    logger.info("[%s] DISPOSAL: %d->%d objects | %s", device_id, last_count, current_count, jpg.name)

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
        insert_notifications(detection, camera)
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

    return True


# ==========================================
# CORE PROCESSING
# ==========================================
def process_image(jpg: Path, device_id: str, camera) -> bool:
    """Run inference, compare with last state. Returns True if disposal recorded."""
    garbage_dets, annotated = _run_inference("detect_garbage", jpg, conf=config.CONF_THRESHOLD)
    current_count = len(garbage_dets)
    disposal, last_count = _state_disposal_transition(device_id, current_count)
    infrator_dets = _run_inference("detect_infrators", jpg, conf=config.CONF_THRESHOLD) if disposal else []

    persisted = _persist_detection_if_needed(
        jpg=jpg,
        device_id=device_id,
        camera=camera,
        garbage_dets=garbage_dets,
        infrator_dets=infrator_dets,
        annotated=annotated,
        last_count=last_count,
        current_count=current_count,
    )
    save_state(device_id, {"last_count": int(current_count)})
    return persisted


def _collect_pending_images(upload_dir: Path) -> list[dict]:
    pending: list[dict] = []
    for device_dir in sorted(upload_dir.iterdir()):
        if not device_dir.is_dir() or device_dir.name in SKIP_DIRS:
            continue
        device_id = device_dir.name

        camera = resolve_camera(device_id)
        if not camera:
            logger.debug("No camera registered for device_id=%s", device_id)
            continue

        images = [
            jpg
            for jpg in device_dir.rglob("*.jpg")
            if "labeled" not in jpg.parts and not is_processed(jpg)
        ]

        for jpg in images:
            try:
                st = jpg.stat()
                mtime = st.st_mtime
            except OSError:
                mtime = time.time()
            pending.append(
                {
                    "jpg": jpg,
                    "device_id": device_id,
                    "camera": camera,
                    "device_base": device_dir,
                    "mtime": mtime,
                }
            )
    pending.sort(key=lambda item: (item["mtime"], str(item["jpg"])))
    return pending


def _process_rekognition_batch(batch: list[dict]) -> tuple[int, set[int]]:
    """Process one batch of up to 4 images with Rekognition mosaic."""
    image_paths = [item["jpg"] for item in batch]
    result = _run_inference("detect_mosaic_batch", image_paths, conf=config.CONF_THRESHOLD)
    per_image = result.get("per_image", []) if isinstance(result, dict) else []
    requires_fallback = bool(result.get("requires_single_fallback")) if isinstance(result, dict) else False

    if requires_fallback:
        logger.warning(
            "Mosaic batch returned ambiguous labels without instances. "
            "Falling back to single-image calls for %d image(s).",
            len(batch),
        )
        processed = 0
        updated_ids: set[int] = set()
        for item in batch:
            jpg = item["jpg"]
            device_id = item["device_id"]
            camera = item["camera"]
            device_base = item["device_base"]
            disposal = process_image(jpg, device_id, camera)
            mark_processed(jpg, device_base, disposal)
            processed += 1
            updated_ids.add(camera.id)
        return processed, updated_ids

    processed = 0
    updated_ids: set[int] = set()
    for idx, item in enumerate(batch):
        jpg = item["jpg"]
        device_id = item["device_id"]
        camera = item["camera"]
        device_base = item["device_base"]

        payload = per_image[idx] if idx < len(per_image) else {}
        garbage_dets = payload.get("garbage_dets", []) if isinstance(payload, dict) else []
        infrator_dets = payload.get("infrator_dets", []) if isinstance(payload, dict) else []
        current_count = len(garbage_dets)
        disposal, last_count = _state_disposal_transition(device_id, current_count)

        annotated = _annotate_from_mapped_detections(jpg, garbage_dets, infrator_dets)
        persisted = _persist_detection_if_needed(
            jpg=jpg,
            device_id=device_id,
            camera=camera,
            garbage_dets=garbage_dets,
            infrator_dets=infrator_dets if disposal else [],
            annotated=annotated,
            last_count=last_count,
            current_count=current_count,
        )
        save_state(device_id, {"last_count": int(current_count)})

        mark_processed(jpg, device_base, persisted)
        processed += 1
        updated_ids.add(camera.id)
        if persisted:
            logger.info("Disposal event recorded: %s / %s", device_id, jpg.name)

    return processed, updated_ids


def scan_and_process() -> int:
    upload_dir = Path(config.UPLOAD_DIR)
    if not upload_dir.exists():
        logger.warning("Upload directory not found: %s", upload_dir)
        return 0

    pending = _collect_pending_images(upload_dir)
    if not pending:
        return 0

    use_mosaic = (
        config.AI_MODEL_PROVIDER == "rekognition"
        and config.REKOGNITION_MOSAIC_ENABLED
        and config.REKOGNITION_MOSAIC_BATCH_SIZE > 1
    )

    processed_count = 0
    updated_camera_ids: set[int] = set()

    if not use_mosaic:
        for item in pending:
            jpg = item["jpg"]
            device_id = item["device_id"]
            camera = item["camera"]
            device_base = item["device_base"]
            try:
                disposal = process_image(jpg, device_id, camera)
                mark_processed(jpg, device_base, disposal)
                processed_count += 1
                updated_camera_ids.add(camera.id)
                if disposal:
                    logger.info("Disposal event recorded: %s / %s", device_id, jpg.name)
            except Exception:
                logger.exception("Error processing %s", jpg)
    else:
        batch_size = config.REKOGNITION_MOSAIC_BATCH_SIZE
        timeout_s = config.REKOGNITION_MOSAIC_TIMEOUT_SECONDS
        partial_mode = config.REKOGNITION_MOSAIC_PARTIAL_MODE
        now_ts = time.time()

        idx = 0
        total = len(pending)
        while idx < total:
            remaining = total - idx
            if remaining >= batch_size:
                batch = pending[idx : idx + batch_size]
                idx += batch_size
            else:
                oldest_age = now_ts - float(pending[idx]["mtime"])
                if oldest_age < timeout_s:
                    break
                if partial_mode == "single_fallback":
                    batch = pending[idx : idx + 1]
                    idx += 1
                else:
                    batch = pending[idx:total]
                    idx = total

            try:
                if len(batch) == 1:
                    item = batch[0]
                    disposal = process_image(item["jpg"], item["device_id"], item["camera"])
                    mark_processed(item["jpg"], item["device_base"], disposal)
                    processed_count += 1
                    updated_camera_ids.add(item["camera"].id)
                    if disposal:
                        logger.info("Disposal event recorded: %s / %s", item["device_id"], item["jpg"].name)
                else:
                    batch_processed, camera_ids = _process_rekognition_batch(batch)
                    processed_count += batch_processed
                    updated_camera_ids.update(camera_ids)
            except Exception:
                logger.exception("Error processing Rekognition mosaic batch with %d image(s)", len(batch))
                # Fallback to single-image processing for resiliency.
                for item in batch:
                    try:
                        disposal = process_image(item["jpg"], item["device_id"], item["camera"])
                        mark_processed(item["jpg"], item["device_base"], disposal)
                        processed_count += 1
                        updated_camera_ids.add(item["camera"].id)
                        if disposal:
                            logger.info("Disposal event recorded: %s / %s", item["device_id"], item["jpg"].name)
                    except Exception:
                        logger.exception("Error processing fallback single image %s", item["jpg"])

    for camera_id in sorted(updated_camera_ids):
        update_camera_last_capture(camera_id)

    return processed_count


def _maybe_run_drive_sync() -> None:
    """Run Google Drive sync once per day at or after GDRIVE_SYNC_HOUR."""
    global _last_sync_day
    if not config.GDRIVE_ENABLED:
        return
    today = date.today()
    now_hour = datetime.now(BRASILIA).hour
    if _last_sync_day == today or now_hour < config.GDRIVE_SYNC_HOUR:
        return
    _last_sync_day = today
    logger.info("Starting daily Google Drive sync (hour=%d)...", now_hour)
    try:
        from .gdrive_sync import sync_uploads_to_drive

        sync_uploads_to_drive()
        logger.info("Google Drive sync completed.")
    except Exception:
        logger.exception("Google Drive sync failed")


def main():
    logger.info("=" * 60)
    logger.info("SAIRA Worker starting")
    logger.info("UPLOAD_DIR            = %s", config.UPLOAD_DIR)
    logger.info("STATE_DIR             = %s", config.STATE_DIR)
    logger.info("AI_MODEL_PROVIDER     = %s", config.AI_MODEL_PROVIDER)
    logger.info("AI_FALLBACK_PROVIDER  = %s", config.AI_FALLBACK_PROVIDER or "none")
    logger.info("P1_MODEL              = %s", config.P1_MODEL_PATH)
    logger.info("P2_MODEL              = %s", config.P2_MODEL_PATH)
    logger.info("CONF                  = %.2f", config.CONF_THRESHOLD)
    logger.info("POLL_INTERVAL         = %ds", config.POLL_INTERVAL)
    logger.info("REDIS_URL             = %s", config.REDIS_URL)
    logger.info("PROCESSED_STRATEGY    = %s", config.PROCESSED_STRATEGY)
    logger.info("WORKER_ENABLED        = %s", config.WORKER_ENABLED)
    logger.info("MOCK_MODE (legacy)    = %s", config.MOCK_MODE)
    logger.info("GDRIVE_ENABLED        = %s", config.GDRIVE_ENABLED)
    if config.AI_MODEL_PROVIDER == "rekognition":
        logger.info("AWS_REGION            = %s", config.AWS_REGION)
        logger.info("REKOGNITION_WASTE_MODE= %s", config.REKOGNITION_WASTE_DECISION_MODE)
        logger.info("REKOGNITION_OFF_MODE  = %s", config.REKOGNITION_OFFENDER_MODE)
        logger.info("MOSAIC_ENABLED        = %s", config.REKOGNITION_MOSAIC_ENABLED)
        logger.info("MOSAIC_BATCH_SIZE     = %d", config.REKOGNITION_MOSAIC_BATCH_SIZE)
        logger.info("MOSAIC_TIMEOUT_S      = %d", config.REKOGNITION_MOSAIC_TIMEOUT_SECONDS)
        logger.info(
            "MOSAIC_TILE           = %dx%d",
            config.REKOGNITION_MOSAIC_TILE_WIDTH,
            config.REKOGNITION_MOSAIC_TILE_HEIGHT,
        )
        logger.info("MOSAIC_MAX_PAYLOAD    = %d", config.REKOGNITION_MOSAIC_MAX_PAYLOAD_BYTES)
    if config.GDRIVE_ENABLED:
        logger.info("GDRIVE_FOLDER_ID      = %s", config.GDRIVE_FOLDER_ID)
        logger.info("GDRIVE_SYNC_HOUR      = %d", config.GDRIVE_SYNC_HOUR)
    logger.info("=" * 60)

    if not config.WORKER_ENABLED:
        logger.info("Worker is DISABLED (WORKER_ENABLED=false). Idling.")
        while True:
            time.sleep(3600)

    _setup_detectors()
    init_connections()
    _load_models()

    while True:
        try:
            n = scan_and_process()
            if n:
                logger.info("Cycle complete: %d images processed", n)
            _maybe_run_drive_sync()
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception:
            logger.exception("Unhandled error in scan cycle")

        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    main()
