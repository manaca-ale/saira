"""SAIRA worker - supports YOLO, SHADOW and GEMINI modes."""
from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import cv2
import requests

from . import config
from . import bgsub_filter
from . import detector_dinov2
from .db import (
    find_recent_detection_for_camera,
    init_connections,
    insert_detection,
    insert_notifications,
    insert_offenders,
    publish_detection_event,
    resolve_camera,
    update_camera_last_capture,
    update_detection_on_merge,
)
from .detector_gemini import (
    analyze_new_litter_with_gemini,
    analyze_with_gemini,
    normalize_offender_types,
)
from .metrics import (
    classify_gemini_error,
    observe_bgsub_adaptive_update,
    observe_bgsub_evaluation,
    observe_car_shadow_comparison,
    observe_car_shadow_error,
    observe_car_shadow_events,
    observe_car_shadow_window,
    observe_gemini_call,
    observe_gemini_error,
    observe_gemini_success,
    observe_scan_cycle,
    observe_scan_error,
    set_gemini_avg_latency_ms,
    start_metrics_server,
)
from .models import DetectionRecord, GeminiUsage, OffenderRecord

if config.CAR_SHADOW_ENABLED:
    from . import detector_car_stopped, detector_car_yolo

if config.AI_MODE in {"yolo", "shadow"}:
    if config.MOCK_MODE:
        from .detector_mock import detect_garbage, detect_infrators, load_models
    else:
        from .detector_yolo import detect_garbage, detect_infrators, load_models
else:

    def load_models(*_args, **_kwargs) -> None:
        return None

    def detect_garbage(*_args, **_kwargs):
        raise RuntimeError("YOLO detector is disabled when AI_MODE=gemini")

    def detect_infrators(*_args, **_kwargs):
        raise RuntimeError("YOLO detector is disabled when AI_MODE=gemini")


BRASILIA = ZoneInfo("America/Sao_Paulo")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

SKIP_DIRS = {"processed", "labeled", "ocorrencias", "sem_ocorrencia"}

GEMINI_METRICS: dict[str, float] = {
    "gemini_calls_total": 0,
    "gemini_errors_total": 0,
    "gemini_timeout_total": 0,
    "gemini_parse_fail_total": 0,
    "gemini_latency_ms_total": 0,
    "gemini_input_tokens": 0,
    "gemini_output_tokens": 0,
}

# Tracks the last day the Google Drive sync ran (reset on container restart - acceptable).
_last_sync_day = None


def _camera_label(camera) -> str:
    """Stringify camera.id for Prometheus labels. Bounded cardinality (one per camera)."""
    cid = getattr(camera, "id", None)
    return str(cid) if cid is not None else "unknown"


def _register_gemini_call(*, agent: str = "detail", camera=None) -> None:
    GEMINI_METRICS["gemini_calls_total"] += 1
    observe_gemini_call(agent=agent, camera_id=_camera_label(camera))


def _register_gemini_success(
    latency_ms: int, usage: GeminiUsage, *, agent: str = "detail", camera=None
) -> None:
    GEMINI_METRICS["gemini_latency_ms_total"] += int(latency_ms)
    GEMINI_METRICS["gemini_input_tokens"] += int(usage.input_tokens)
    GEMINI_METRICS["gemini_output_tokens"] += int(usage.output_tokens)
    observe_gemini_success(
        latency_ms=int(latency_ms),
        input_tokens=int(usage.input_tokens),
        output_tokens=int(usage.output_tokens),
        estimated_cost_usd=float(usage.estimated_cost_usd),
        agent=agent,
        camera_id=_camera_label(camera),
    )


def _register_gemini_error(error_message: str, *, agent: str = "detail", camera=None) -> None:
    msg = str(error_message).lower()
    timeout = "timeout" in msg
    parse_fail = "validation" in msg or "json" in msg
    error_type = classify_gemini_error(msg)
    GEMINI_METRICS["gemini_errors_total"] += 1
    if timeout:
        GEMINI_METRICS["gemini_timeout_total"] += 1
    if parse_fail:
        GEMINI_METRICS["gemini_parse_fail_total"] += 1
    observe_gemini_error(
        timeout=timeout,
        parse_fail=parse_fail,
        agent=agent,
        camera_id=_camera_label(camera),
        error_type=error_type,
    )


def _register_bgsub_evaluation(result, *, camera=None) -> None:
    """Record metric for a bgsub pre-filter evaluation."""
    try:
        observe_bgsub_evaluation(
            camera_id=_camera_label(camera),
            reason=result.reason,
            mode=getattr(result, "mode", "single"),
        )
    except NameError:
        # observe_bgsub_evaluation not yet imported — degrade silently.
        # Will be added when metrics.py is updated.
        pass


def _log_gemini_call(
    *,
    camera,
    device_id: Optional[str],
    agent: str,
    model: str,
    request_id: Optional[str],
    usage: Optional[GeminiUsage],
    latency_ms: Optional[int],
    success: bool,
    error_message: Optional[str] = None,
) -> None:
    """Best-effort dispatch of a gemini_call_log row. Never raises."""
    try:
        from . import db as _db
        _db.insert_gemini_call_log(
            camera_id=getattr(camera, "id", None),
            device_id=device_id,
            agent=agent,
            model=model,
            request_id=request_id,
            input_tokens=(usage.input_tokens if usage else 0),
            output_tokens=(usage.output_tokens if usage else 0),
            total_tokens=(usage.total_tokens if usage else 0),
            estimated_cost_usd=(usage.estimated_cost_usd if usage else 0.0),
            latency_ms=latency_ms,
            success=success,
            error_message=error_message,
        )
    except Exception:
        logger.exception("gemini call log dispatch failed (non-fatal)")


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


def mark_processed(image_path: Path, device_base: Path, disposal: bool) -> Path:
    """Move image to the appropriate subfolder based on detection outcome."""
    if config.PROCESSED_STRATEGY == "marker":
        image_path.with_suffix(".jpg.processed").touch()
        return image_path
    elif config.PROCESSED_STRATEGY == "two_folders":
        subfolder = "ocorrencias" if disposal else "sem_ocorrencia"
        try:
            date_parts = image_path.parent.relative_to(device_base)
        except ValueError:
            date_parts = Path("")
        dest_dir = device_base / subfolder / date_parts
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / image_path.name
        image_path.rename(dest)
        return dest
    else:
        processed_dir = image_path.parent / "processed"
        processed_dir.mkdir(exist_ok=True)
        dest = processed_dir / image_path.name
        image_path.rename(dest)
        return dest


def _to_upload_relative(path: Path) -> Optional[Path]:
    try:
        return path.relative_to(Path(config.UPLOAD_DIR))
    except Exception:
        return None


def _build_image_url_from_upload_path(path: Path) -> Optional[str]:
    rel = _to_upload_relative(path)
    if rel is None:
        return None
    return build_image_url(rel.as_posix())


def _persist_detection_frame_index(
    detection_id: str,
    device_id: str,
    moved_frames: list[Path],
    selected_frame_name: Optional[str],
    evidence_summary: Optional[str] = None,
) -> None:
    if not detection_id or not moved_frames:
        return

    ordered = sorted(moved_frames, key=lambda p: (parse_timestamp(p.name), p.name))
    frames_payload: list[dict[str, Any]] = []
    for frame_path in ordered:
        image_url = _build_image_url_from_upload_path(frame_path)
        if not image_url:
            continue
        frames_payload.append(
            {
                "frame_name": frame_path.name,
                "image_url": image_url,
                "is_default": bool(selected_frame_name and frame_path.name == selected_frame_name),
            }
        )

    if not frames_payload:
        return

    target_dir = Path(config.STATE_DIR) / "detection_frames"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{detection_id}.json"

    # Merge with previous index if the detection was coalesced (same camera,
    # within EVENT_WINDOW_MIN). Preserve original selected_frame_name and
    # evidence_summary unless the caller explicitly provides a new one.
    existing_frames: list[dict] = []
    preserved_summary: Optional[str] = evidence_summary
    preserved_selected: Optional[str] = selected_frame_name
    preserved_created_at: Optional[str] = None
    if target.exists():
        try:
            prev = json.loads(target.read_text(encoding="utf-8"))
            existing_frames = list(prev.get("frames") or [])
            preserved_created_at = prev.get("created_at")
            if not selected_frame_name:
                preserved_selected = prev.get("selected_frame_name")
            if not evidence_summary:
                preserved_summary = prev.get("evidence_summary")
        except Exception:
            logger.warning("detection_frames index unreadable, overwriting (%s)", target.name)

    known_names = {f.get("frame_name") for f in existing_frames}
    merged = list(existing_frames) + [
        f for f in frames_payload if f.get("frame_name") not in known_names
    ]
    # Chronological order — filenames are BRT timestamps (YYYY-MM-DD_HH-MM-SS).
    merged.sort(key=lambda f: str(f.get("frame_name") or ""))

    # Ensure exactly one default. Prefer the previously-selected frame if it
    # still exists in the merged list; otherwise fall back to the first frame.
    default_name = preserved_selected
    has_default = False
    for f in merged:
        f["is_default"] = bool(default_name and f.get("frame_name") == default_name)
        has_default = has_default or f["is_default"]
    if not has_default and merged:
        merged[0]["is_default"] = True
        default_name = merged[0].get("frame_name")

    index = {
        "detection_id": detection_id,
        "device_id": device_id,
        "selected_frame_name": default_name,
        "evidence_summary": preserved_summary,
        "frames": merged,
        "created_at": preserved_created_at or datetime.now(BRASILIA).isoformat(),
        "updated_at": datetime.now(BRASILIA).isoformat(),
    }
    target.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _persist_detection_summary(
    detection_id: str,
    *,
    device_id: str,
    evidence_summary: Optional[str],
    request_id: Optional[str],
    event_frame_name: Optional[str],
    offender_frame_name: Optional[str],
    offender_detected: bool,
) -> None:
    if not detection_id:
        return
    payload = {
        "detection_id": detection_id,
        "device_id": device_id,
        "evidence_summary": evidence_summary,
        "request_id": request_id,
        "event_frame_name": event_frame_name,
        "offender_frame_name": offender_frame_name,
        "offender_detected": bool(offender_detected),
        "created_at": datetime.now(BRASILIA).isoformat(),
    }
    target_dir = Path(config.STATE_DIR) / "detection_summaries"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{detection_id}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ==========================================
# HELPERS
# ==========================================
def trigger_history_upload(device_id: str) -> None:
    """POST to esp32-server to request a bulk history upload from the device via SSE."""
    base = config.ESP32_SERVER_URL
    if not base:
        return
    url = f"{base}/device/{device_id}/trigger"
    try:
        resp = requests.post(url, json={"cmd": "CMD_BULK_UPLOAD"}, timeout=5)
        logger.info("trigger_history_upload device=%s -> HTTP %d", device_id, resp.status_code)
    except Exception as exc:
        logger.warning("trigger_history_upload device=%s failed: %s", device_id, exc)


def parse_timestamp(filename: str) -> datetime:
    """Parse Brasilia timestamp from filename (YYYY-MM-DD_HH-MM-SS)."""
    stem = Path(filename).stem
    try:
        naive = datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S")
        return naive.replace(tzinfo=BRASILIA)
    except ValueError:
        return datetime.now(BRASILIA)


def estimate_volume(detections: list[dict], img_w: int, img_h: int) -> Decimal:
    """Heuristic: bbox area ratio x scale factor. Approx: 5% area ~= 1 m3."""
    if not detections:
        return Decimal("0.10")
    img_area = max(img_w * img_h, 1)
    bbox_area = sum(
        (d["bbox"][2] - d["bbox"][0]) * (d["bbox"][3] - d["bbox"][1])
        for d in detections
    )
    ratio = min(bbox_area / img_area, 1.0)
    return Decimal(str(round(max(ratio * 20.0, 0.10), 2)))


def dominant_waste_type(detections: list[dict]) -> str:
    if not detections:
        return "Entulho"
    counts: dict[str, int] = {}
    for det in detections:
        wt = det.get("db_waste_type")
        if not wt:
            continue
        counts[wt] = counts.get(wt, 0) + 1
    return max(counts, key=counts.get) if counts else "Entulho"


def save_labeled_image(annotated_bgr, device_id: str, original: Path) -> str:
    """Save annotated image under uploads/device_id/labeled/. Return relative path."""
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


def save_evidence_copy(device_id: str, original: Path) -> str:
    """Copy original frame to labeled/ so image_url remains stable after moving input file."""
    device_base = Path(config.UPLOAD_DIR) / device_id
    try:
        date_parts = original.parent.relative_to(device_base)
    except ValueError:
        date_parts = Path("")

    labeled_dir = device_base / "labeled" / date_parts
    labeled_dir.mkdir(parents=True, exist_ok=True)
    labeled_path = labeled_dir / original.name
    shutil.copy2(original, labeled_path)

    try:
        rel = labeled_path.relative_to(Path(config.UPLOAD_DIR))
    except ValueError:
        rel = Path(device_id) / "labeled" / original.name
    return str(rel).replace("\\", "/")


def build_image_url(rel_path: str) -> str:
    return f"{config.PUBLIC_BASE_URL.rstrip('/')}/uploads/{rel_path}"


def _to_decimal(value: Optional[float], places: int = 2) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(round(float(value), places)))
    except Exception:
        return None


def _confidence_100_to_01(score_0_100: int) -> Decimal:
    return Decimal(str(round(max(0, min(100, int(score_0_100))) / 100.0, 2)))


def _build_offender_summary(types: list[str], plate: Optional[str]) -> Optional[str]:
    parts = sorted(set(types))
    if plate:
        parts.append(f"Placa: {plate}")
    return ", ".join(parts) if parts else None


def _collect_frame_sequence(images: list[Path], current_index: int) -> list[Path]:
    """Build temporal sequence around the current frame without edge pre-filtering."""
    if not images:
        return []

    current = images[current_index]
    current_ts = parse_timestamp(current.name)

    candidates: list[tuple[float, datetime, Path]] = []
    for path in images:
        ts = parse_timestamp(path.name)
        dt = abs((ts - current_ts).total_seconds())
        if dt <= config.GEMINI_SEQUENCE_MAX_SPAN_SECONDS:
            candidates.append((dt, ts, path))

    if not candidates:
        return [current]

    # Select nearest frames first, then restore chronological order for model input.
    candidates.sort(key=lambda item: (item[0], item[1], item[2].name))
    selected = [item[2] for item in candidates[: max(1, config.GEMINI_SEQUENCE_SIZE)]]

    if current not in selected:
        selected.append(current)

    # Deduplicate by full path.
    unique: dict[str, Path] = {str(path): path for path in selected}
    ordered = sorted(unique.values(), key=lambda p: (parse_timestamp(p.name), p.name))

    # Hard limit to sequence size after ordering.
    if len(ordered) > config.GEMINI_SEQUENCE_SIZE:
        ordered = ordered[-config.GEMINI_SEQUENCE_SIZE :]

    return ordered or [current]


def _collect_time_windows(images: list[Path]) -> list[list[Path]]:
    """Group chronological images into non-overlapping configurable time windows."""
    if not images:
        return []

    ordered = sorted(images, key=lambda p: (parse_timestamp(p.name), p.name))
    windows: list[list[Path]] = []
    current: list[Path] = []
    window_start = parse_timestamp(ordered[0].name)

    for img in ordered:
        ts = parse_timestamp(img.name)
        exceeds_time = (ts - window_start).total_seconds() >= config.GEMINI_CASCADE_WINDOW_SECONDS
        exceeds_count = len(current) >= config.GEMINI_CASCADE_MAX_FRAMES
        if current and (exceeds_time or exceeds_count):
            if len(current) >= max(2, config.GEMINI_CASCADE_MIN_FRAMES):
                windows.append(current)
            current = [img]
            window_start = ts
            continue
        if not current:
            window_start = ts
        current.append(img)

    if len(current) >= max(2, config.GEMINI_CASCADE_MIN_FRAMES):
        windows.append(current)

    return windows


def _record_detection(
    jpg: Path,
    device_id: str,
    camera,
    waste_type: Optional[str],
    material_type: Optional[str],
    volume_m3: Optional[Decimal],
    offenders_summary: Optional[str],
    confidence_score: Decimal,
    offender_rows: list[OffenderRecord],
    annotated_bgr=None,
    evidence_summary: Optional[str] = None,
    waste_bbox: Optional[list] = None,
    agent1_request_id: Optional[str] = None,
    agent2_request_id: Optional[str] = None,
    agent1_confidence: Optional[int] = None,
) -> Optional[str]:
    if annotated_bgr is not None:
        labeled_rel = save_labeled_image(annotated_bgr, device_id, jpg)
    else:
        labeled_rel = save_evidence_copy(device_id, jpg)

    image_url = build_image_url(labeled_rel)

    # --- Event coalescing -----------------------------------------------------
    # If the same camera already has a detection inside the coalescing window,
    # reuse that detection_id (silent merge): upgrade fields when the new
    # window classifies the event with higher confidence/volume, append
    # offenders, and skip notifications + SSE event. The frame index is
    # appended downstream by _persist_detection_frame_index.
    existing = find_recent_detection_for_camera(camera.id, config.EVENT_WINDOW_MIN)
    if existing:
        upgrade_kwargs: dict = {}
        prev_conf = existing.get("confidence_score")
        if confidence_score is not None and (prev_conf is None or confidence_score > prev_conf):
            upgrade_kwargs.update({
                "confidence_score": confidence_score,
                "waste_type": waste_type,
                "material_type": material_type,
                "image_url": image_url,
                "waste_bbox": waste_bbox,
            })
        prev_vol = existing.get("volume_m3")
        if volume_m3 is not None and (prev_vol is None or volume_m3 > prev_vol):
            upgrade_kwargs["volume_m3"] = volume_m3
        if upgrade_kwargs:
            update_detection_on_merge(existing["id"], **upgrade_kwargs)
        if offender_rows:
            for row in offender_rows:
                row.detection_id = existing["id"]
            insert_offenders(offender_rows)
        logger.info(
            json.dumps(
                {
                    "event": "detection_coalesced",
                    "detection_id": str(existing["id"]),
                    "device_id": device_id,
                    "camera_id": camera.id,
                    "upgraded_fields": list(upgrade_kwargs.keys()),
                    "offender_rows_count": len(offender_rows),
                    "evidence_summary": evidence_summary,
                },
                ensure_ascii=False,
            )
        )
        return str(existing["id"])
    # --------------------------------------------------------------------------

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
        material_type=material_type,
        volume_m3=volume_m3,
        offenders=offenders_summary,
        image_url=image_url,
        confidence_score=confidence_score,
        waste_bbox=waste_bbox,
        agent1_request_id=agent1_request_id,
        agent2_request_id=agent2_request_id,
        agent1_confidence=agent1_confidence,
    )

    if insert_detection(detection):
        insert_notifications(detection, camera)
        publish_detection_event(detection, camera)
        trigger_history_upload(device_id)

        if offender_rows:
            for row in offender_rows:
                row.detection_id = detection.id
            insert_offenders(offender_rows)
        logger.info(
            json.dumps(
                {
                    "event": "detection_persisted",
                    "detection_id": str(detection.id),
                    "device_id": device_id,
                    "camera_id": camera.id,
                    "offender_rows_count": len(offender_rows),
                    "evidence_summary": evidence_summary,
                },
                ensure_ascii=False,
            )
        )
        return str(detection.id)

    return None


def _process_with_yolo(jpg: Path, device_id: str, camera, persist: bool = True) -> tuple[bool, dict[str, Any]]:
    """Run YOLO inference and optionally persist resulting occurrence."""
    garbage_dets, annotated = detect_garbage(jpg, conf=config.CONF_THRESHOLD)
    current_count = len(garbage_dets)

    state = load_state(device_id)
    last_count = state.get("last_count", 0)
    disposal = current_count > last_count
    save_state(device_id, {"last_count": current_count})

    payload: dict[str, Any] = {
        "provider": "yolo",
        "disposal": disposal,
        "garbage_count": current_count,
        "last_count": last_count,
    }

    if not disposal:
        return False, payload

    infrator_dets = detect_infrators(jpg, conf=config.CONF_THRESHOLD)

    img = cv2.imread(str(jpg))
    h, w = (img.shape[:2] if img is not None else (480, 640))
    volume = estimate_volume(garbage_dets, w, h)
    waste_type = dominant_waste_type(garbage_dets)
    max_conf = max((det["confidence"] for det in garbage_dets), default=0.0)

    offender_types = sorted(set(det["offender_type"] for det in infrator_dets))
    offenders_summary = _build_offender_summary(offender_types, None)

    offender_rows = [
        OffenderRecord(
            detection_id=uuid4(),  # replaced on insert
            offender_type=det["offender_type"],
            waste_type=waste_type,
            estimated_volume_m3=volume,
            confidence_score=Decimal(str(round(det["confidence"], 2))),
        )
        for det in infrator_dets
    ]

    if persist:
        _record_detection(
            jpg=jpg,
            device_id=device_id,
            camera=camera,
            waste_type=waste_type,
            material_type=None,
            volume_m3=volume,
            offenders_summary=offenders_summary,
            confidence_score=Decimal(str(round(max_conf, 2))),
            offender_rows=offender_rows,
            annotated_bgr=annotated,
        )

    payload.update(
        {
            "waste_type": waste_type,
            "volume_m3": float(volume),
            "confidence_0_1": round(max_conf, 2),
            "offender_types": offender_types,
        }
    )
    return True, payload


def _process_with_gemini(
    jpg: Path,
    device_id: str,
    camera,
    sequence_paths: list[Path],
    persist: bool,
    prior_window_context: Optional[str] = None,
    agent1_request_id: Optional[str] = None,
    agent1_confidence: Optional[int] = None,
) -> tuple[Optional[bool], dict[str, Any]]:
    """Run Gemini inference and optionally persist resulting occurrence."""
    request_id = str(uuid4())
    _register_gemini_call(camera=camera)

    camera_context = {
        "camera_name": camera.name,
        "device_id": device_id,
        "logradouro": camera.logradouro or "",
        "bairro": camera.bairro or "",
        "rpa": camera.rpa or "",
    }

    # ------------------------------------------------------------------------
    # Detail-side pile-crop augmentation (campaign 24 winner for esp32_002).
    # When enabled + device + polygon present, compute N hi-res crops of the
    # pile zone and pass them alongside the global sequence. Selects the
    # MANGABEIRA_E_WITH_PILECROPS per-camera prompt. Fails open on any error.
    # ------------------------------------------------------------------------
    pile_crops_paths: list[Path] = []
    pilecrop_tmp_dir: Optional[Path] = None
    use_pilecrops_prompt = False
    if (
        config.GEMINI_DETAIL_PILECROP_ENABLED
        and device_id in config.DETAIL_PILECROP_DEVICES
        and len(sequence_paths) >= 2
    ):
        pile_poly = getattr(camera, "pile_zone_polygon", None)
        bbox = _pile_bbox(pile_poly) if pile_poly else None
        if bbox:
            n_target = min(
                max(1, config.GEMINI_DETAIL_PILECROP_N_FRAMES),
                len(sequence_paths),
            )
            if n_target > 1:
                idxs = [
                    int(round(i * (len(sequence_paths) - 1) / (n_target - 1)))
                    for i in range(n_target)
                ]
            else:
                idxs = [0]
            crop_inputs = [sequence_paths[k] for k in idxs]
            try:
                pilecrop_tmp_dir = Path(tempfile.mkdtemp(prefix="detail_pilecrop_"))
                pile_crops_paths = _make_pile_crops(
                    crop_inputs,
                    bbox,
                    config.GEMINI_DETAIL_PILECROP_UPSCALE,
                    pilecrop_tmp_dir,
                )
                if pile_crops_paths:
                    use_pilecrops_prompt = True
                    logger.info(
                        "detail_pilecrops device=%s n_crops=%d bbox=%s request_id=%s",
                        device_id, len(pile_crops_paths), bbox, request_id,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "detail_pilecrops failed device=%s err=%s — falling back to standard detail",
                    device_id, exc,
                )
                pile_crops_paths = []
                use_pilecrops_prompt = False

    selected_prompt_version = (
        "mangabeira_with_pilecrops" if use_pilecrops_prompt else config.GEMINI_PROMPT_VERSION
    )

    def _cleanup_pilecrops() -> None:
        if pilecrop_tmp_dir is not None:
            shutil.rmtree(pilecrop_tmp_dir, ignore_errors=True)

    try:
        result = analyze_with_gemini(
            image_paths=sequence_paths,
            camera_context=camera_context,
            request_id=request_id,
            mosaic_mode=config.GEMINI_MOSAIC_AGENT2,
            prior_window_context=prior_window_context,
            prompt_version=selected_prompt_version,
            pile_crops=pile_crops_paths if use_pilecrops_prompt else None,
        )

        report = result.report
        usage: GeminiUsage = result.usage

        _register_gemini_success(result.latency_ms, usage, camera=camera)
        _log_gemini_call(
            camera=camera,
            device_id=device_id,
            agent="detail",
            model=result.model,
            request_id=request_id,
            usage=usage,
            latency_ms=result.latency_ms,
            success=True,
        )

        # Resolve "frame_N" labels (used in mosaic mode) back to real filenames
        if report.event_frame_name and report.event_frame_name.startswith("frame_"):
            try:
                idx = int(report.event_frame_name.split("_")[1]) - 1
                if 0 <= idx < len(sequence_paths):
                    report.event_frame_name = sequence_paths[idx].name
            except (ValueError, IndexError):
                pass
        if report.offender_frame_name and report.offender_frame_name.startswith("frame_"):
            try:
                idx = int(report.offender_frame_name.split("_")[1]) - 1
                if 0 <= idx < len(sequence_paths):
                    report.offender_frame_name = sequence_paths[idx].name
            except (ValueError, IndexError):
                pass

        disposal = bool(report.infraction_confirmed)

        # --------------------------------------------------------------------
        # DINOv2 post-detail FP filter (rejection-only, orthogonal to BGSUB).
        # Só roda quando o Agent-2 confirmou (disposal=True). Em shadow apenas
        # loga o que rejeitaria; em enforce reverte disposal=False (o guard de
        # persistência em `if disposal and persist...` cai sozinho). Fail-open.
        # --------------------------------------------------------------------
        dino_result: Optional[detector_dinov2.DinoFilterResult] = None
        if config.DINOV2_FILTER_MODE != "off" and disposal and device_id in config.DINOV2_FILTER_DEVICES:
            pile_poly = getattr(camera, "pile_zone_polygon", None)
            dino_result = detector_dinov2.evaluate(sequence_paths, device_id, pile_poly, camera)
            # Persist every scored decision so the shadow track record survives
            # container recreate (worker stdout does not) — see Camp 35.
            detector_dinov2.record_shadow_decision(
                request_id=request_id,
                device_id=device_id,
                result=dino_result,
                gemini_disposal=True,
            )
            if dino_result.should_reject:
                logger.info(
                    json.dumps(
                        {
                            "event": "dinov2_shadow_would_reject"
                            if config.DINOV2_FILTER_MODE == "shadow"
                            else "dinov2_enforce_reject",
                            "request_id": request_id,
                            "device_id": device_id,
                            "p_con": round(dino_result.p_con, 4),
                            "threshold": dino_result.threshold,
                            "reason": dino_result.reason,
                            "n_frames_used": dino_result.n_frames_used,
                            "latency_ms": round(dino_result.latency_ms, 1),
                            "gemini_disposal": True,
                        },
                        ensure_ascii=False,
                    )
                )
                if config.DINOV2_FILTER_MODE == "enforce":
                    disposal = False
            else:
                logger.info(
                    json.dumps(
                        {
                            "event": "dinov2_pass",
                            "request_id": request_id,
                            "device_id": device_id,
                            "p_con": round(dino_result.p_con, 4),
                            "reason": dino_result.reason,
                            "mode": config.DINOV2_FILTER_MODE,
                        },
                        ensure_ascii=False,
                    )
                )

        offender_types = normalize_offender_types(report.offender_types)
        if report.offender_detected and not offender_types:
            offender_types = ["Outro"]

        offenders_summary = _build_offender_summary(offender_types, report.vehicle_plate)
        volume = _to_decimal(report.volume_m3)
        confidence = _confidence_100_to_01(report.confidence_0_100)

        payload: dict[str, Any] = {
            "provider": "gemini",
            "success": True,
            "disposal": disposal,
            "request_id": request_id,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "sequence_size": len(sequence_paths),
            "waste_type": report.waste_type,
            "material_type": report.material_type,
            "volume_m3": float(volume) if volume is not None else None,
            "offender_types": offender_types,
            "vehicle_plate": report.vehicle_plate,
            "vehicle_color": report.vehicle_color,
            "vehicle_model": report.vehicle_model,
            "plate_pattern": report.plate_pattern,
            "event_frame_name": report.event_frame_name,
            "offender_frame_name": report.offender_frame_name,
            "confidence_0_100": report.confidence_0_100,
            "evidence_summary": report.evidence_summary,
            "raw_reason_codes": report.raw_reason_codes,
            "has_waste_bbox": bool(report.waste_bbox),
            "has_offender_bbox": bool(report.offender_bbox),
            "dino_p_con": (round(dino_result.p_con, 4)
                           if dino_result is not None and dino_result.p_con >= 0 else None),
            "dino_would_reject": (bool(dino_result.should_reject)
                                  if dino_result is not None else None),
            "dino_mode": config.DINOV2_FILTER_MODE,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "estimated_cost_usd": usage.estimated_cost_usd,
            },
        }

        logger.info(
            json.dumps(
                {
                    "event": "gemini_decision",
                    "request_id": request_id,
                    "disposal": disposal,
                    "offender_detected": bool(report.offender_detected),
                    "offender_types_count": len(offender_types),
                    "event_frame_name": report.event_frame_name,
                    "sequence_size": len(sequence_paths),
                    "window_size": len(sequence_paths),
                    "evidence_summary": report.evidence_summary,
                },
                ensure_ascii=False,
            )
        )

        detection_id: Optional[str] = None
        if disposal and persist and not config.GEMINI_DRY_RUN:
            evidence_jpg = next((p for p in sequence_paths if p.name == report.event_frame_name), jpg)
            offender_rows = [
                OffenderRecord(
                    detection_id=uuid4(),  # replaced on insert
                    offender_type=otype,
                    plate=report.vehicle_plate,
                    vehicle_color=report.vehicle_color,
                    waste_type=report.waste_type,
                    estimated_volume_m3=volume,
                    confidence_score=confidence,
                    notes=report.evidence_summary,
                    offender_bbox=report.offender_bbox,
                )
                for otype in offender_types
            ]

            detection_id = _record_detection(
                jpg=evidence_jpg,
                device_id=device_id,
                camera=camera,
                waste_type=report.waste_type,
                material_type=report.material_type,
                volume_m3=volume,
                offenders_summary=offenders_summary,
                confidence_score=confidence,
                offender_rows=offender_rows,
                annotated_bgr=None,
                evidence_summary=report.evidence_summary,
                waste_bbox=report.waste_bbox,
                agent1_request_id=agent1_request_id,
                agent2_request_id=request_id,
                agent1_confidence=agent1_confidence,
            )
            if detection_id:
                payload["detection_id"] = detection_id
                _persist_detection_summary(
                    detection_id=detection_id,
                    device_id=device_id,
                    evidence_summary=report.evidence_summary,
                    request_id=request_id,
                    event_frame_name=report.event_frame_name,
                    offender_frame_name=report.offender_frame_name,
                    offender_detected=bool(report.offender_detected),
                )
                logger.info(
                    json.dumps(
                        {
                            "event": "gemini_occurrence_persisted",
                            "request_id": request_id,
                            "detection_id": detection_id,
                            "disposal": True,
                            "offender_detected": bool(report.offender_detected),
                            "offender_types_count": len(offender_types),
                            "event_frame_name": report.event_frame_name,
                            "offender_frame_name": report.offender_frame_name,
                            "evidence_summary": report.evidence_summary,
                        },
                        ensure_ascii=False,
                    )
                )

        _cleanup_pilecrops()
        return disposal, payload

    except Exception as exc:  # noqa: BLE001
        _cleanup_pilecrops()
        error_message = str(exc)
        _register_gemini_error(error_message, camera=camera)
        _log_gemini_call(
            camera=camera,
            device_id=device_id,
            agent="detail",
            model=config.GEMINI_MODEL,
            request_id=request_id,
            usage=None,
            latency_ms=None,
            success=False,
            error_message=error_message,
        )

        logger.error(
            json.dumps(
                {
                    "event": "gemini_inference_error",
                    "request_id": request_id,
                    "error": error_message,
                    "sequence_size": len(sequence_paths),
                },
                ensure_ascii=False,
            )
        )

        return None, {
            "provider": "gemini",
            "success": False,
            "request_id": request_id,
            "sequence_size": len(sequence_paths),
            "error": error_message,
        }


def _pile_bbox(polygon) -> Optional[tuple[int, int, int, int]]:
    """Bounding box (x0, y0, x1, y1) of a pile_zone_polygon ([[[x, y], ...], ...])."""
    try:
        pts = [pt for poly in polygon for pt in poly]
        xs = [int(p[0]) for p in pts]
        ys = [int(p[1]) for p in pts]
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)
    except Exception:
        return None


def _make_pile_crops(
    frame_paths: list[Path], bbox: tuple[int, int, int, int], upscale: int, out_dir: Path
) -> list[Path]:
    """Crop frames to the pile bbox (+ optional upscale) into out_dir. Returns crop paths."""
    x0, y0, x1, y1 = bbox
    crops: list[Path] = []
    for fp in frame_paths:
        img = cv2.imread(str(fp))
        if img is None:
            continue
        h, w = img.shape[:2]
        cx0, cy0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
        cx1, cy1 = max(cx0 + 1, min(x1, w)), max(cy0 + 1, min(y1, h))
        crop = img[cy0:cy1, cx0:cx1]
        if crop.size == 0:
            continue
        if upscale and upscale != 1:
            crop = cv2.resize(
                crop, (crop.shape[1] * upscale, crop.shape[0] * upscale),
                interpolation=cv2.INTER_LANCZOS4,
            )
        dst = out_dir / fp.name
        cv2.imwrite(str(dst), crop)
        crops.append(dst)
    return crops


def _process_with_gemini_cascade_window(
    window_paths: list[Path],
    device_id: str,
    camera,
    persist: bool,
) -> tuple[Optional[bool], dict[str, Any]]:
    """
    Two-stage Gemini cascade:
    1) Agent-1 compares first/last frame for new litter.
    2) Agent-2 (full sequence) runs only when gate is triggered.
    """
    if not window_paths:
        return False, {"provider": "gemini_cascade", "success": False, "error": "empty_window"}

    last_frame = window_paths[-1]
    gate_request_id = str(uuid4())
    _register_gemini_call(agent="gate", camera=camera)

    # --- Load prior-window state ---
    state = load_state(device_id)
    prior_had_litter: bool = bool(state.get("last_window_had_litter", False))
    prior_waste_type: Optional[str] = state.get("last_window_waste_type")

    # Correction 2: use last frame of previous window as reference to avoid post-deposit blindness
    prev_last_frame_path = state.get("last_window_last_frame")
    if prev_last_frame_path and Path(prev_last_frame_path).exists():
        first_frame = Path(prev_last_frame_path)
        logger.info(
            "gate_reference device=%s frame=%s prev_window=True",
            device_id,
            first_frame.name,
        )
    else:
        first_frame = window_paths[0]

    prior_window_context: Optional[str] = None
    if prior_had_litter:
        waste_label = f" (type: {prior_waste_type})" if prior_waste_type else ""
        prior_window_context = (
            f"- The previous 2-minute window ALREADY had waste at this location{waste_label}. "
            "Confirm NEW_SOLID_WASTE only if a NEW object appeared or the volume visibly increased."
        )

    # Inject local time for time-of-day awareness (long shadows at dawn/dusk)
    last_frame_ts = parse_timestamp(last_frame.name)
    local_time_hhmm = last_frame_ts.strftime("%H:%M")

    camera_context = {
        "camera_name": camera.name,
        "device_id": device_id,
        "logradouro": camera.logradouro or "",
        "bairro": camera.bairro or "",
        "rpa": camera.rpa or "",
        "horario_local": local_time_hhmm,
    }

    # When pre-existing litter is known, require higher confidence to trigger Stage 2
    effective_threshold = (
        max(config.GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE, 80)
        if prior_had_litter
        else config.GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE
    )

    # Select mid-window frames at 25%/50%/75% to detect ghost events (arrive-dump-leave)
    mid_frames: Optional[list[Path]] = None
    n = len(window_paths)
    if n >= 5:
        mid_frames = [
            window_paths[n // 4],       # ~25%
            window_paths[n // 2],       # ~50%
            window_paths[3 * n // 4],   # ~75%
        ]
    elif n >= 4:
        mid_frames = [window_paths[n // 2]]

    # ------------------------------------------------------------------------
    # BGSUB pre-filter (added 2026-05-23 — see docs/bgsub_prefilter.md).
    # Fails open in any error path. Caller-side flag check avoids cost
    # when the feature is globally disabled.
    # ------------------------------------------------------------------------
    if config.BGSUB_PREFILTER_ENABLED:
        bgsub_result = bgsub_filter.evaluate(
            frame_paths=window_paths,
            device_id=device_id,
            pile_zone_polygon=getattr(camera, "pile_zone_polygon", None),
            camera=camera,
        )
        _register_bgsub_evaluation(bgsub_result, camera=camera)
        if bgsub_result.should_suppress:
            logger.info(
                json.dumps({
                    "event": "bgsub_suppressed",
                    "device_id": device_id,
                    "camera_id": camera.id,
                    "gate_request_id": gate_request_id,
                    "persistence": bgsub_result.persistence,
                    "n_frames_ok": bgsub_result.n_frames_ok,
                    "n_frames_total": bgsub_result.n_frames_total,
                    "threshold": config.BGSUB_PERSISTENCE_THRESHOLD,
                }, ensure_ascii=False)
            )
            return False, {
                "provider": "gemini_cascade",
                "success": True,
                "skipped": True,
                "skip_reason": "bgsub_filtered",
                "bgsub_persistence": bgsub_result.persistence,
            }

    try:
        gate = analyze_new_litter_with_gemini(
            first_frame=first_frame,
            last_frame=last_frame,
            camera_context=camera_context,
            request_id=gate_request_id,
            prior_window_context=prior_window_context,
            use_mosaic=config.GEMINI_MOSAIC_AGENT1,
            mid_frames=mid_frames,
            prompt_version=config.GEMINI_PROMPT_VERSION,
        )
        _register_gemini_success(gate.latency_ms, gate.usage, agent="gate", camera=camera)
        _log_gemini_call(
            camera=camera,
            device_id=device_id,
            agent="gate",
            model=gate.model,
            request_id=gate_request_id,
            usage=gate.usage,
            latency_ms=gate.latency_ms,
            success=True,
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        _register_gemini_error(message, agent="gate", camera=camera)
        _log_gemini_call(
            camera=camera,
            device_id=device_id,
            agent="gate",
            model=(config.GEMINI_AGENT1_MODEL or config.GEMINI_MODEL),
            request_id=gate_request_id,
            usage=None,
            latency_ms=None,
            success=False,
            error_message=message,
        )
        return None, {
            "provider": "gemini_cascade",
            "success": False,
            "stage": "agent1_new_litter",
            "request_id": gate_request_id,
            "error": message,
            "window_size": len(window_paths),
            "window_frames": [p.name for p in window_paths],
        }

    gate_report = gate.report

    # Persist litter state and last-frame reference for next window (Correction 2)
    save_state(device_id, {
        **state,
        "last_window_had_litter": bool(gate_report.last_frame_has_litter),
        "last_window_waste_type": gate_report.waste_type,
        "last_window_last_frame": str(last_frame),
    })

    # Adaptive baseline — when the gate confirms no new litter with high
    # confidence, absorb these frames into MOG2 so subsequent identical
    # scenes get filtered. Gated by BGSUB_ADAPTIVE_ENABLED (default false).
    # Cameras in BGSUB_ADAPTIVE_DISABLE_DEVICES opt out (frozen baseline +
    # periodic recalibration) to avoid drift — see config + camp 33.
    adaptive_on = (
        config.BGSUB_PREFILTER_ENABLED
        and device_id not in config.BGSUB_ADAPTIVE_DISABLE_DEVICES
    )
    if adaptive_on and not bool(gate_report.new_litter_detected):
        adapt_result = bgsub_filter.update_baseline_with_frames(
            device_id=device_id,
            frame_paths=window_paths,
            gate_confidence=int(gate_report.confidence_0_100),
            camera=camera,
        )
        observe_bgsub_adaptive_update(
            camera_id=_camera_label(camera),
            reason=adapt_result.reason,
        )
    elif adaptive_on and bool(gate_report.new_litter_detected):
        # Skip update when descarte detected — we don't want to absorb TPs.
        observe_bgsub_adaptive_update(
            camera_id=_camera_label(camera),
            reason="skipped_positive",
        )

    gate_trigger = (
        bool(gate_report.new_litter_detected)
        and int(gate_report.confidence_0_100) >= effective_threshold
    )

    # --- Dual gate: second Agent-1 pass on a crop of the pile zone ------------
    # Catches small/zoom-dependent dumps (e.g. handcart) the full frame misses.
    # Lazy OR: only run when the full-frame pass did NOT already trigger, and only
    # for configured cameras (esp32_002). Crop failure fails open (keeps full result).
    crop_gate_trigger = False
    crop_gate_info: Optional[dict[str, Any]] = None
    pile_poly = getattr(camera, "pile_zone_polygon", None)
    if (
        config.GEMINI_GATE_PILECROP_ENABLED
        and not gate_trigger
        and device_id in config.GATE_PILECROP_DEVICES
        and pile_poly
    ):
        bbox = _pile_bbox(pile_poly)
        if bbox:
            crop_request_id = f"{gate_request_id}-crop"
            tmp_dir = Path(tempfile.mkdtemp(prefix="pilecrop_"))
            try:
                up = config.GEMINI_GATE_PILECROP_UPSCALE
                crop_first = _make_pile_crops([first_frame], bbox, up, tmp_dir)
                crop_last = _make_pile_crops([last_frame], bbox, up, tmp_dir)
                crop_mids = _make_pile_crops(mid_frames, bbox, up, tmp_dir) if mid_frames else []
                if crop_first and crop_last:
                    _register_gemini_call(agent="gate", camera=camera)
                    crop_gate = analyze_new_litter_with_gemini(
                        first_frame=crop_first[0],
                        last_frame=crop_last[0],
                        camera_context=camera_context,
                        request_id=crop_request_id,
                        prior_window_context=prior_window_context,
                        use_mosaic=config.GEMINI_MOSAIC_AGENT1,
                        mid_frames=crop_mids or None,
                        prompt_version=config.GEMINI_PROMPT_VERSION,
                    )
                    _register_gemini_success(crop_gate.latency_ms, crop_gate.usage, agent="gate", camera=camera)
                    _log_gemini_call(
                        camera=camera, device_id=device_id, agent="gate", model=crop_gate.model,
                        request_id=crop_request_id, usage=crop_gate.usage,
                        latency_ms=crop_gate.latency_ms, success=True,
                    )
                    cr = crop_gate.report
                    crop_gate_trigger = (
                        bool(cr.new_litter_detected)
                        and int(cr.confidence_0_100) >= effective_threshold
                    )
                    crop_gate_info = {
                        "request_id": crop_request_id,
                        "new_litter_detected": bool(cr.new_litter_detected),
                        "confidence_0_100": int(cr.confidence_0_100),
                        "scene_type": getattr(cr, "scene_type", "") or "",
                        "triggered": crop_gate_trigger,
                    }
            except Exception as exc:  # noqa: BLE001
                _register_gemini_error(str(exc), agent="gate", camera=camera)
                _log_gemini_call(
                    camera=camera, device_id=device_id, agent="gate",
                    model=(config.GEMINI_AGENT1_MODEL or config.GEMINI_MODEL),
                    request_id=f"{gate_request_id}-crop", usage=None, latency_ms=None,
                    success=False, error_message=str(exc),
                )
                logger.warning("pile-crop gate failed device=%s: %s", device_id, exc)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    gate_trigger = gate_trigger or crop_gate_trigger

    gate_payload = {
        "success": True,
        "pilecrop_gate": crop_gate_info,
        "stage": "agent1_new_litter",
        "request_id": gate_request_id,
        "model": gate.model,
        "latency_ms": gate.latency_ms,
        "first_frame": first_frame.name,
        "last_frame": last_frame.name,
        "window_size": len(window_paths),
        "new_litter_detected": bool(gate_report.new_litter_detected),
        "confidence_0_100": int(gate_report.confidence_0_100),
        "effective_threshold": effective_threshold,
        "prior_had_litter": prior_had_litter,
        "scene_delta_analysis": gate_report.scene_delta_analysis or "",
        "first_frame_has_litter": bool(gate_report.first_frame_has_litter),
        "last_frame_has_litter": bool(gate_report.last_frame_has_litter),
        "waste_type": gate_report.waste_type,
        "evidence_summary": gate_report.evidence_summary,
        "raw_reason_codes": gate_report.raw_reason_codes,
        "triggered_agent2": gate_trigger,
        "usage": {
            "input_tokens": gate.usage.input_tokens,
            "output_tokens": gate.usage.output_tokens,
            "total_tokens": gate.usage.total_tokens,
            "estimated_cost_usd": gate.usage.estimated_cost_usd,
        },
    }

    logger.info(
        json.dumps(
            {
                "event": "gemini_cascade_gate_decision",
                "request_id": gate_request_id,
                "window_size": len(window_paths),
                "first_frame": first_frame.name,
                "last_frame": last_frame.name,
                "triggered_agent2": gate_trigger,
                "new_litter_detected": bool(gate_report.new_litter_detected),
                "confidence_0_100": int(gate_report.confidence_0_100),
                "effective_threshold": effective_threshold,
                "prior_had_litter": prior_had_litter,
                "scene_delta_analysis": gate_report.scene_delta_analysis or "",
                "evidence_summary": gate_report.evidence_summary,
            },
            ensure_ascii=False,
        )
    )

    def _audit_record(
        *,
        agent2_ran: bool,
        agent2_payload_obj: Optional[dict],
        disposal_value: Optional[bool],
    ) -> dict[str, Any]:
        ap = agent2_payload_obj or {}
        ap_usage = ap.get("usage") or {}
        return {
            "device_id": device_id,
            "camera_id": getattr(camera, "id", None),
            "window_first_frame": first_frame.name,
            "window_last_frame": last_frame.name,
            "window_size": len(window_paths),
            "agent1_triggered": bool(gate_trigger),
            "agent1_new_litter_detected": bool(gate_report.new_litter_detected),
            "agent1_confidence": int(gate_report.confidence_0_100),
            "agent1_threshold": int(effective_threshold),
            "agent1_request_id": gate_request_id,
            "agent2_ran": bool(agent2_ran),
            "agent2_success": bool(ap.get("success")) if agent2_ran else False,
            "agent2_disposal": bool(disposal_value) if disposal_value is not None else None,
            "agent2_offender_detected": bool(ap.get("offender_types")) if agent2_ran else None,
            "agent2_has_offender_bbox": bool(ap.get("has_offender_bbox")) if agent2_ran else None,
            "agent2_has_waste_bbox": bool(ap.get("has_waste_bbox")) if agent2_ran else None,
            "agent2_request_id": ap.get("request_id") if agent2_ran else None,
            "detection_id": ap.get("detection_id") if agent2_ran else None,
            "agent2_cost_usd": float(ap_usage.get("estimated_cost_usd") or 0.0) if agent2_ran else 0.0,
            "agent1_cost_usd": float((gate_payload.get("usage") or {}).get("estimated_cost_usd") or 0.0),
            "created_at": datetime.now(BRASILIA).isoformat(),
        }

    if not gate_trigger:
        car_payload = (
            _run_car_shadow_for_window(window_paths, device_id, camera, gemini_disposal=False)
            if config.CAR_SHADOW_ENABLED
            else None
        )
        _append_cascade_audit(device_id, _audit_record(
            agent2_ran=False, agent2_payload_obj=None, disposal_value=False,
        ))
        return False, {
            "provider": "gemini_cascade",
            "success": True,
            "window_size": len(window_paths),
            "window_frames": [p.name for p in window_paths],
            "disposal": False,
            "agent1_result": gate_payload,
            "agent2_result": None,
            "car_shadow_result": car_payload,
        }

    disposal, agent2_payload = _process_with_gemini(
        jpg=last_frame,
        device_id=device_id,
        camera=camera,
        sequence_paths=window_paths,
        persist=persist,
        prior_window_context=prior_window_context,
        agent1_request_id=gate_request_id,
        agent1_confidence=int(gate_report.confidence_0_100),
    )

    success = bool(agent2_payload.get("success"))
    if not success:
        _append_cascade_audit(device_id, _audit_record(
            agent2_ran=True, agent2_payload_obj=agent2_payload, disposal_value=None,
        ))
        return None, {
            "provider": "gemini_cascade",
            "success": False,
            "window_size": len(window_paths),
            "window_frames": [p.name for p in window_paths],
            "disposal": None,
            "agent1_result": gate_payload,
            "agent2_result": agent2_payload,
        }

    logger.info(
        json.dumps(
            {
                "event": "gemini_cascade_decision",
                "window_size": len(window_paths),
                "first_frame": first_frame.name,
                "last_frame": last_frame.name,
                "disposal": bool(disposal),
                "agent2_request_id": agent2_payload.get("request_id"),
                "event_frame_name": agent2_payload.get("event_frame_name"),
                "offender_detected": bool((agent2_payload.get("offender_types") or [])),
                "offender_types_count": len(agent2_payload.get("offender_types") or []),
                "evidence_summary": agent2_payload.get("evidence_summary"),
            },
            ensure_ascii=False,
        )
    )

    car_payload = (
        _run_car_shadow_for_window(window_paths, device_id, camera, gemini_disposal=bool(disposal))
        if config.CAR_SHADOW_ENABLED
        else None
    )
    _append_cascade_audit(device_id, _audit_record(
        agent2_ran=True, agent2_payload_obj=agent2_payload, disposal_value=bool(disposal),
    ))
    return bool(disposal), {
        "provider": "gemini_cascade",
        "success": True,
        "window_size": len(window_paths),
        "window_frames": [p.name for p in window_paths],
        "disposal": bool(disposal),
        "agent1_result": gate_payload,
        "agent2_result": agent2_payload,
        "car_shadow_result": car_payload,
    }


def _append_shadow_audit(device_id: str, record: dict[str, Any]) -> None:
    day = datetime.now(BRASILIA).strftime("%Y-%m-%d")
    day_dir = Path(config.STATE_DIR) / "shadow_audit" / day
    day_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = day_dir / f"{device_id}.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    _update_shadow_metrics(day_dir, record)


def _append_cascade_audit(device_id: str, record: dict[str, Any]) -> None:
    """Persist Agent-1 + Agent-2 cascade decisions for I4 (assertividade) reporting.

    Writes one JSONL line per processed window, regardless of AI_MODE, so the
    daily KPI report can compute Agent-1 vs Agent-2 agreement rate from this file.
    """
    try:
        day = datetime.now(BRASILIA).strftime("%Y-%m-%d")
        day_dir = Path(config.STATE_DIR) / "gemini_cascade_audit" / day
        day_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = day_dir / f"{device_id}.jsonl"
        with jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("Failed to append gemini_cascade_audit for device=%s", device_id)


# ==========================================
# SLIDING-WINDOW SHADOW A/B (Camp 36) — logs only, never mutates prod state
# ==========================================
def _shadow_state_path(device_id: str) -> Path:
    return Path(config.STATE_DIR) / "sliding_shadow_state" / f"{device_id}.json"


def _load_shadow_state(device_id: str) -> dict[str, Any]:
    try:
        p = _shadow_state_path(device_id)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("sliding_shadow: failed to load state device=%s", device_id)
    return {}


def _save_shadow_state(device_id: str, state: dict[str, Any]) -> None:
    try:
        p = _shadow_state_path(device_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        logger.warning("sliding_shadow: failed to save state device=%s", device_id)


def _append_sliding_shadow_audit(device_id: str, record: dict[str, Any]) -> None:
    try:
        day = datetime.now(BRASILIA).strftime("%Y-%m-%d")
        day_dir = Path(config.STATE_DIR) / "sliding_shadow_audit" / day
        day_dir.mkdir(parents=True, exist_ok=True)
        with (day_dir / f"{device_id}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("sliding_shadow: failed to append audit device=%s", device_id)


def _gather_recent_frames(device_dir: Path, since_epoch: float) -> list[Path]:
    """All frames (unprocessed + already-moved to sem_ocorrencia/ocorrencias) with
    timestamp >= since_epoch. Lets the shadow see history regardless of two_folders moves."""
    out: list[tuple[float, Path]] = []
    for jpg in device_dir.rglob("*.jpg"):
        if "labeled" in jpg.parts:
            continue
        try:
            ts = parse_timestamp(jpg.name).timestamp()
        except Exception:
            continue
        if ts >= since_epoch:
            out.append((ts, jpg))
    out.sort(key=lambda x: x[0])
    return [p for _, p in out]


def _shadow_camera_context(camera, device_id: str, last_frame_name: str) -> dict[str, str]:
    try:
        hhmm = parse_timestamp(last_frame_name).strftime("%H:%M")
    except Exception:
        hhmm = ""
    return {
        "camera_name": camera.name, "device_id": device_id,
        "logradouro": camera.logradouro or "", "bairro": camera.bairro or "",
        "rpa": camera.rpa or "", "horario_local": hhmm,
    }


def _shadow_prior_ctx(prior_had: bool, prior_waste: Optional[str]) -> Optional[str]:
    if not prior_had:
        return None
    wl = f" (type: {prior_waste})" if prior_waste else ""
    return (f"- The previous 2-minute window ALREADY had waste at this location{wl}. "
            "Confirm NEW_SOLID_WASTE only if a NEW object appeared or the volume visibly increased.")


def _shadow_detail(window: list[Path], device_id: str, camera, prior_had: bool,
                   prior_waste: Optional[str]) -> tuple[bool, float]:
    """Faithful detail (Agent-2) for the shadow: same pile-crop logic as prod, no DB write."""
    cam_ctx = _shadow_camera_context(camera, device_id, window[-1].name)
    prior_ctx = _shadow_prior_ctx(prior_had, prior_waste)
    pile_crops = None
    prompt_v = config.GEMINI_PROMPT_VERSION
    tmp_dir: Optional[Path] = None
    if (config.GEMINI_DETAIL_PILECROP_ENABLED and device_id in config.DETAIL_PILECROP_DEVICES
            and len(window) >= 2):
        poly = getattr(camera, "pile_zone_polygon", None)
        bbox = _pile_bbox(poly) if poly else None
        if bbox:
            n_target = min(max(1, config.GEMINI_DETAIL_PILECROP_N_FRAMES), len(window))
            idxs = ([int(round(i * (len(window) - 1) / (n_target - 1))) for i in range(n_target)]
                    if n_target > 1 else [0])
            tmp_dir = Path(tempfile.mkdtemp(prefix="shadow_pilecrop_"))
            crops = _make_pile_crops([window[k] for k in idxs], bbox,
                                     config.GEMINI_DETAIL_PILECROP_UPSCALE, tmp_dir)
            if crops:
                pile_crops = crops
                prompt_v = "mangabeira_with_pilecrops"
    try:
        res = analyze_with_gemini(
            image_paths=window, camera_context=cam_ctx, mosaic_mode=config.GEMINI_MOSAIC_AGENT2,
            prior_window_context=prior_ctx, prompt_version=prompt_v, pile_crops=pile_crops)
        return bool(res.report.infraction_confirmed), float(res.usage.estimated_cost_usd or 0.0)
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_sliding_shadow(device_dir: Path, device_id: str, camera) -> None:
    """Evaluate overlapping sliding windows in SHADOW (log-only). Runs AFTER the live
    fixed pipeline so it never delays prod; uses its own state + audit. BGSUB-gated cost."""
    if not config.GEMINI_SLIDING_SHADOW_ENABLED or device_id not in config.SLIDING_SHADOW_DEVICES:
        return
    try:
        win_s = config.GEMINI_SLIDING_WINDOW_SECONDS
        stride = max(1, config.GEMINI_SLIDING_STRIDE_SECONDS)
        min_f = config.GEMINI_SLIDING_MIN_FRAMES
        max_f = config.GEMINI_SLIDING_MAX_FRAMES
        st = _load_shadow_state(device_id)
        last_eval = float(st.get("last_eval_epoch") or 0.0)

        frames = _gather_recent_frames(device_dir, since_epoch=last_eval - win_s)
        if len(frames) < min_f:
            return
        epochs = {p: parse_timestamp(p.name).timestamp() for p in frames}
        ordered = sorted(frames, key=lambda p: epochs[p])
        latest = epochs[ordered[-1]]
        earliest = epochs[ordered[0]]

        # stride grid anchored on the epoch axis (deterministic); evaluate T in (last_eval, latest]
        k = (int(last_eval // stride) + 1) if last_eval else int((earliest + win_s) // stride)
        T = k * stride
        prior_had = bool(st.get("prior_had_litter", False))
        prior_waste = st.get("prior_waste")
        last_confirm = st.get("last_confirm_epoch")
        evaluated_to = last_eval
        n_eval = 0
        MAX_PER_POLL = 16  # safety cap against backlog blowups

        while T <= latest and n_eval < MAX_PER_POLL:
            window = [p for p in ordered if (T - win_s) < epochs[p] <= T]
            if len(window) > max_f:
                window = window[-max_f:]
            if len(window) >= max(2, min_f):
                rec: dict[str, Any] = {
                    "stride_epoch": round(T, 1),
                    "stride_iso": datetime.fromtimestamp(T, BRASILIA).isoformat(),
                    "window_first": window[0].name, "window_last": window[-1].name,
                    "window_size": len(window),
                    "created_at": datetime.now(BRASILIA).isoformat(),
                }
                bg = bgsub_filter.evaluate(window, device_id,
                                           getattr(camera, "pile_zone_polygon", None), camera)
                rec["bgsub_suppressed"] = bool(bg.should_suppress)
                rec["bgsub_persistence"] = float(getattr(bg, "persistence", 0.0))
                if bg.should_suppress:
                    rec.update({"gate_ran": False, "would_confirm": False})
                    _append_sliding_shadow_audit(device_id, rec)
                else:
                    n = len(window)
                    mids = ([window[n // 4], window[n // 2], window[3 * n // 4]] if n >= 5
                            else [window[n // 2]] if n >= 4 else None)
                    gate = analyze_new_litter_with_gemini(
                        first_frame=window[0], last_frame=window[-1],
                        camera_context=_shadow_camera_context(camera, device_id, window[-1].name),
                        prior_window_context=_shadow_prior_ctx(prior_had, prior_waste),
                        use_mosaic=config.GEMINI_MOSAIC_AGENT1, mid_frames=mids,
                        prompt_version=config.GEMINI_PROMPT_VERSION)
                    gr = gate.report
                    prior_had = bool(getattr(gr, "last_frame_has_litter", False))
                    prior_waste = getattr(gr, "waste_type", None)
                    trigger = (bool(gr.new_litter_detected)
                               and int(gr.confidence_0_100) >= config.GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE)
                    rec.update({
                        "gate_ran": True, "gate_new_litter": bool(gr.new_litter_detected),
                        "gate_conf": int(gr.confidence_0_100), "gate_triggered": trigger,
                        "gate_waste_type": prior_waste,
                        "gate_cost_usd": float(gate.usage.estimated_cost_usd or 0.0),
                    })
                    if trigger:
                        disposal, dcost = _shadow_detail(window, device_id, camera, prior_had, prior_waste)
                        is_new = disposal and (last_confirm is None
                                               or (T - float(last_confirm)) > config.GEMINI_SLIDING_COALESCE_SECONDS)
                        if disposal:
                            last_confirm = T
                        rec.update({"detail_ran": True, "detail_cost_usd": dcost,
                                    "would_confirm": bool(disposal),
                                    "is_coalesced_new_fp": bool(is_new)})
                    else:
                        rec.update({"detail_ran": False, "would_confirm": False})
                    _append_sliding_shadow_audit(device_id, rec)
                n_eval += 1
            evaluated_to = T
            T += stride

        st.update({"last_eval_epoch": evaluated_to, "prior_had_litter": prior_had,
                   "prior_waste": prior_waste, "last_confirm_epoch": last_confirm})
        _save_shadow_state(device_id, st)
        if n_eval:
            logger.info(json.dumps({"event": "sliding_shadow_poll", "device_id": device_id,
                                    "windows_evaluated": n_eval, "up_to": evaluated_to},
                                   ensure_ascii=False))
    except Exception:
        logger.exception("sliding_shadow failed device=%s", device_id)


def _update_shadow_metrics(day_dir: Path, record: dict[str, Any]) -> None:
    metrics_path = day_dir / "metrics.json"
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:
            metrics = {}
    else:
        metrics = {}

    metrics.setdefault("events_total", 0)
    metrics.setdefault("parse_valid_total", 0)
    metrics.setdefault("divergence_total", 0)
    metrics.setdefault("gemini_error_total", 0)
    metrics.setdefault("latency_samples_ms", [])
    metrics.setdefault("cost_usd_total", 0.0)

    metrics["events_total"] += 1

    gemini = record.get("gemini_result") or {}
    if gemini.get("success"):
        metrics["parse_valid_total"] += 1
        latency = gemini.get("latency_ms")
        if isinstance(latency, (int, float)):
            metrics["latency_samples_ms"].append(int(latency))

        usage = gemini.get("usage") or {}
        metrics["cost_usd_total"] += float(usage.get("estimated_cost_usd") or 0.0)
    else:
        metrics["gemini_error_total"] += 1

    if record.get("divergence") is True:
        metrics["divergence_total"] += 1

    samples = sorted(int(v) for v in metrics.get("latency_samples_ms", []) if isinstance(v, (int, float)))
    if samples:
        p95_index = max(0, int(round(0.95 * len(samples) + 0.4999)) - 1)
        metrics["p95_latency_ms"] = samples[min(p95_index, len(samples) - 1)]
    else:
        metrics["p95_latency_ms"] = None

    events = max(1, metrics["events_total"])
    metrics["avg_cost_usd_per_event"] = round(metrics["cost_usd_total"] / events, 8)
    metrics["divergence_rate"] = round(metrics["divergence_total"] / events, 6)
    metrics["parse_valid_rate"] = round(metrics["parse_valid_total"] / events, 6)

    # Keep metrics file compact over long runs.
    if len(metrics["latency_samples_ms"]) > 5000:
        metrics["latency_samples_ms"] = metrics["latency_samples_ms"][-5000:]

    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


# ==========================================
# CAR-STOPPED SHADOW DETECTOR (parallel to Gemini, never persists to DB)
# ==========================================
def _car_config() -> "detector_car_stopped.CarConfig":
    return detector_car_stopped.CarConfig(
        stationary_pixels=config.CAR_STATIONARY_PIXELS,
        low_frames=config.CAR_LOW_FRAMES,
        med_frames=config.CAR_MED_FRAMES,
        high_frames=config.CAR_HIGH_FRAMES,
        track_ttl_seconds=config.CAR_TRACK_TTL_SECONDS,
        max_buffer_frames=config.CAR_MAX_BUFFER_FRAMES,
    )


def _run_car_shadow_for_window(
    window_paths: list[Path],
    device_id: str,
    camera,
    gemini_disposal: Optional[bool],
) -> dict[str, Any]:
    """Run the stopped-vehicle detector on the same window Gemini just judged.

    Side-effects: persists tracker state into STATE_DIR/{device_id}.json under
    the `car_tracker` key, writes a JSONL audit record, updates Prometheus
    metrics. Returns a payload dict for inclusion in the cascade result.

    Never raises — any internal error is captured, logged, counted, and
    returned in the payload so the Gemini path stays unaffected.
    """
    cam_label = str(camera.id) if camera is not None else "unknown"
    t0 = time.time()
    try:
        # 1. YOLO inference per frame.
        detections_per_frame: list[list[dict]] = []
        frame_timestamps: list[datetime] = []
        for path in window_paths:
            try:
                dets = detector_car_yolo.analyze_image(path, conf=config.CAR_CONF_THRESHOLD)
            except Exception as exc:  # noqa: BLE001
                logger.warning("car_shadow YOLO error on %s: %s", path.name, exc)
                dets = []
            detections_per_frame.append(dets)
            frame_timestamps.append(parse_timestamp(path.name))

        # 2. Centroid tracker over the window, with cross-window state.
        state = load_state(device_id)
        prior_car_state = state.get("car_tracker")
        new_car_state, events = detector_car_stopped.process_window(
            detections_per_frame=detections_per_frame,
            frame_timestamps=frame_timestamps,
            prior_state=prior_car_state,
            config=_car_config(),
        )
        state["car_tracker"] = new_car_state
        save_state(device_id, state)

        # 3. Comparison classification + metrics.
        car_max = detector_car_stopped.max_level(events)
        comparison_class = (
            detector_car_stopped.classify_comparison(bool(gemini_disposal), car_max)
            if gemini_disposal is not None
            else "no_gemini_decision"
        )
        levels = [ev.level for ev in events]
        observe_car_shadow_window(cam_label, time.time() - t0)
        observe_car_shadow_events(cam_label, levels)
        if comparison_class != "no_gemini_decision":
            observe_car_shadow_comparison(cam_label, comparison_class)

        events_payload = [
            {
                "level": ev.level,
                "frames_stayed": ev.frames_stayed,
                "occurrence_id": ev.occurrence_id,
                "track_id": ev.track_id,
                "last_bbox": ev.last_bbox,
                "last_confidence": round(ev.last_confidence, 3),
                "first_seen_ts": ev.first_seen_ts,
                "last_seen_ts": ev.last_seen_ts,
            }
            for ev in events
        ]

        payload = {
            "success": True,
            "comparison_class": comparison_class,
            "car_max_level": car_max,
            "events": events_payload,
            "window_size": len(window_paths),
            "first_frame": window_paths[0].name if window_paths else None,
            "last_frame": window_paths[-1].name if window_paths else None,
            "inference_seconds": round(time.time() - t0, 3),
            "active_tracks_remaining": len(new_car_state.get("active_tracks", {})),
        }

        # 4. JSONL audit.
        audit_record = {
            "device_id": device_id,
            "camera_id": cam_label,
            "window_first_frame": payload["first_frame"],
            "window_last_frame": payload["last_frame"],
            "window_size": payload["window_size"],
            "gemini_disposal": gemini_disposal,
            "car_max_level": car_max,
            "comparison_class": comparison_class,
            "events": events_payload,
            "inference_seconds": payload["inference_seconds"],
            "created_at": datetime.now(BRASILIA).isoformat(),
        }
        _append_car_shadow_audit(device_id, audit_record)

        logger.info(
            json.dumps(
                {
                    "event": "car_shadow_decision",
                    "device_id": device_id,
                    "camera_id": cam_label,
                    "gemini_disposal": gemini_disposal,
                    "car_max_level": car_max,
                    "comparison_class": comparison_class,
                    "events_count": len(events),
                    "levels": levels,
                    "window_size": len(window_paths),
                },
                ensure_ascii=False,
            )
        )
        return payload

    except Exception as exc:  # noqa: BLE001
        observe_car_shadow_error(cam_label)
        logger.exception("car_shadow failed for device=%s", device_id)
        return {
            "success": False,
            "error": str(exc),
            "window_size": len(window_paths),
        }


def _append_car_shadow_audit(device_id: str, record: dict[str, Any]) -> None:
    """Mirror of `_append_shadow_audit` writing to `car_shadow_audit/`."""
    day = datetime.now(BRASILIA).strftime("%Y-%m-%d")
    day_dir = Path(config.STATE_DIR) / "car_shadow_audit" / day
    day_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = day_dir / f"{device_id}.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    _update_car_shadow_metrics(day_dir, record)


def _update_car_shadow_metrics(day_dir: Path, record: dict[str, Any]) -> None:
    """Aggregated daily metrics for the car-shadow audit (mirrors shadow_audit)."""
    metrics_path = day_dir / "metrics.json"
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:
            metrics = {}
    else:
        metrics = {}

    metrics.setdefault("windows_total", 0)
    metrics.setdefault("events_total", 0)
    metrics.setdefault("events_by_level", {"LOW": 0, "MED": 0, "HIGH": 0})
    metrics.setdefault("comparison_counts", {
        "both_positive": 0, "gemini_only": 0,
        "car_only": 0, "both_negative": 0,
        "no_gemini_decision": 0,
    })
    metrics.setdefault("inference_seconds_samples", [])

    metrics["windows_total"] += 1
    for ev in record.get("events", []) or []:
        lvl = ev.get("level")
        if lvl in metrics["events_by_level"]:
            metrics["events_by_level"][lvl] += 1
            metrics["events_total"] += 1

    comp = record.get("comparison_class")
    if comp in metrics["comparison_counts"]:
        metrics["comparison_counts"][comp] += 1

    latency = record.get("inference_seconds")
    if isinstance(latency, (int, float)):
        metrics["inference_seconds_samples"].append(float(latency))

    samples = sorted(metrics.get("inference_seconds_samples", []))
    if samples:
        p95_idx = max(0, int(round(0.95 * len(samples) + 0.4999)) - 1)
        metrics["p95_inference_seconds"] = round(samples[min(p95_idx, len(samples) - 1)], 3)
    else:
        metrics["p95_inference_seconds"] = None

    # Keep the samples list bounded.
    if len(metrics["inference_seconds_samples"]) > 5000:
        metrics["inference_seconds_samples"] = metrics["inference_seconds_samples"][-5000:]

    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _log_gemini_metrics_snapshot() -> None:
    calls = GEMINI_METRICS["gemini_calls_total"]
    avg_latency = round(GEMINI_METRICS["gemini_latency_ms_total"] / calls, 2) if calls else 0.0
    set_gemini_avg_latency_ms(avg_latency)
    logger.info(
        json.dumps(
            {
                "event": "gemini_metrics_snapshot",
                "gemini_calls_total": GEMINI_METRICS["gemini_calls_total"],
                "gemini_errors_total": GEMINI_METRICS["gemini_errors_total"],
                "gemini_timeout_total": GEMINI_METRICS["gemini_timeout_total"],
                "gemini_parse_fail_total": GEMINI_METRICS["gemini_parse_fail_total"],
                "gemini_input_tokens": GEMINI_METRICS["gemini_input_tokens"],
                "gemini_output_tokens": GEMINI_METRICS["gemini_output_tokens"],
                "gemini_avg_latency_ms": avg_latency,
            },
            ensure_ascii=False,
        )
    )


# ==========================================
# CORE PROCESSING
# ==========================================
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
                jpg
                for jpg in device_dir.rglob("*.jpg")
                if "labeled" not in jpg.parts and not is_processed(jpg)
            ),
            key=lambda p: (parse_timestamp(p.name), p.name),
        )

        if not images:
            continue

        device_processed = 0

        if config.AI_MODE == "gemini" and config.GEMINI_CASCADE_ENABLED:
            windows = _collect_time_windows(images)
            if not windows:
                continue

            for window_paths in windows:
                try:
                    disposal, cascade_payload = _process_with_gemini_cascade_window(
                        window_paths=window_paths,
                        device_id=device_id,
                        camera=camera,
                        persist=True,
                    )

                    if not cascade_payload.get("success"):
                        logger.warning(
                            "Gemini cascade failed for window device=%s first=%s last=%s. Keeping files for retry.",
                            device_id,
                            window_paths[0].name,
                            window_paths[-1].name,
                        )
                        continue

                    final_disposal = bool(disposal)
                    moved_frames: list[Path] = []
                    for frame in window_paths:
                        moved = mark_processed(frame, device_dir, final_disposal)
                        moved_frames.append(moved)
                        processed_count += 1
                        device_processed += 1

                    if final_disposal:
                        agent2_result = cascade_payload.get("agent2_result") or {}
                        detection_id = agent2_result.get("detection_id")
                        if detection_id:
                            _persist_detection_frame_index(
                                detection_id=detection_id,
                                device_id=device_id,
                                moved_frames=moved_frames,
                                selected_frame_name=agent2_result.get("event_frame_name"),
                                evidence_summary=agent2_result.get("evidence_summary"),
                            )
                        logger.info(
                            "Disposal event recorded (Gemini cascade): %s / window %s -> %s",
                            device_id,
                            window_paths[0].name,
                            window_paths[-1].name,
                        )
                except Exception:
                    logger.exception(
                        "Error processing window device=%s first=%s last=%s",
                        device_id,
                        window_paths[0].name if window_paths else "-",
                        window_paths[-1].name if window_paths else "-",
                    )
            if device_processed > 0:
                update_camera_last_capture(camera.id)
            # Sliding-window shadow A/B (Camp 36) — log-only, runs after the live
            # pipeline so it never delays prod; no-op unless flag+device enabled.
            _run_sliding_shadow(device_dir, device_id, camera)
            continue

        for idx, jpg in enumerate(images):
            try:
                if config.AI_MODE == "yolo":
                    disposal, _ = _process_with_yolo(jpg, device_id, camera, persist=True)
                    mark_processed(jpg, device_dir, disposal)
                    processed_count += 1
                    device_processed += 1
                    if disposal:
                        logger.info("Disposal event recorded (YOLO): %s / %s", device_id, jpg.name)
                    continue

                sequence_paths = _collect_frame_sequence(images, idx)

                if config.AI_MODE == "shadow":
                    yolo_disposal, yolo_payload = _process_with_yolo(jpg, device_id, camera, persist=True)
                    gemini_disposal, gemini_payload = _process_with_gemini(
                        jpg=jpg,
                        device_id=device_id,
                        camera=camera,
                        sequence_paths=sequence_paths,
                        persist=False,
                    )

                    divergence = None
                    if gemini_payload.get("success") and gemini_disposal is not None:
                        divergence = bool(yolo_disposal) != bool(gemini_disposal)

                    audit_record = {
                        "image_set_id": str(uuid4()),
                        "device_id": device_id,
                        "camera_id": camera.id,
                        "timestamp": parse_timestamp(jpg.name).isoformat(),
                        "image": jpg.name,
                        "sequence": [p.name for p in sequence_paths],
                        "yolo_result": yolo_payload,
                        "gemini_result": gemini_payload,
                        "divergence": divergence,
                    }
                    _append_shadow_audit(device_id, audit_record)

                    mark_processed(jpg, device_dir, yolo_disposal)
                    processed_count += 1
                    device_processed += 1

                    if yolo_disposal:
                        logger.info("Disposal event recorded (shadow/yolo): %s / %s", device_id, jpg.name)
                    continue

                # AI_MODE == gemini
                gemini_disposal, gemini_payload = _process_with_gemini(
                    jpg=jpg,
                    device_id=device_id,
                    camera=camera,
                    sequence_paths=sequence_paths,
                    persist=True,
                )

                if not gemini_payload.get("success"):
                    # Keep image unprocessed for retry in next cycle.
                    logger.warning("Gemini failed for %s. File kept for retry.", jpg)
                    continue

                disposal = bool(gemini_disposal)
                mark_processed(jpg, device_dir, disposal)
                processed_count += 1
                device_processed += 1

                if disposal:
                    logger.info("Disposal event recorded (Gemini): %s / %s", device_id, jpg.name)

            except Exception:
                logger.exception("Error processing %s", jpg)

        if device_processed > 0:
            update_camera_last_capture(camera.id)

    return processed_count


# ==========================================
# OPTIONAL DAILY DRIVE SYNC
# ==========================================
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


# ==========================================
# OPTIONAL DAILY S3 SYNC
# ==========================================
_last_s3_sync_day: Optional[date] = None


def _maybe_run_s3_sync() -> None:
    """Run S3 migration once per day at or after S3_SYNC_HOUR."""
    global _last_s3_sync_day
    if not config.S3_ENABLED:
        return

    today = date.today()
    now_hour = datetime.now(BRASILIA).hour
    if _last_s3_sync_day == today or now_hour < config.S3_SYNC_HOUR:
        return

    _last_s3_sync_day = today
    logger.info("Starting daily S3 sync (hour=%d)...", now_hour)
    try:
        from .storage_s3 import sync_uploads_to_s3

        sync_uploads_to_s3()
        logger.info("S3 sync completed.")
    except Exception:
        logger.exception("S3 sync failed")


# ==========================================
# ENTRYPOINT
# ==========================================
def main() -> None:
    logger.info("=" * 60)
    logger.info("SAIRA Worker starting")
    logger.info("AI_MODE            = %s", config.AI_MODE)
    logger.info("UPLOAD_DIR         = %s", config.UPLOAD_DIR)
    logger.info("STATE_DIR          = %s", config.STATE_DIR)
    logger.info("CONF               = %.2f", config.CONF_THRESHOLD)
    logger.info("POLL_INTERVAL      = %ds", config.POLL_INTERVAL)
    logger.info("METRICS_ENABLED    = %s", config.WORKER_METRICS_ENABLED)
    logger.info("METRICS_ENDPOINT   = %s:%s", config.WORKER_METRICS_HOST, config.WORKER_METRICS_PORT)
    logger.info("REDIS_URL          = %s", config.REDIS_URL)
    logger.info("PROCESSED_STRATEGY = %s", config.PROCESSED_STRATEGY)
    logger.info("WORKER_ENABLED     = %s", config.WORKER_ENABLED)
    logger.info("MOCK_MODE          = %s", config.MOCK_MODE)

    if config.AI_MODE in {"shadow", "gemini"}:
        logger.info("GEMINI_MODEL       = %s", config.GEMINI_MODEL)
        logger.info("GEMINI_TIMEOUT     = %ss", config.GEMINI_TIMEOUT_SECONDS)
        logger.info("GEMINI_RETRIES     = %d", config.GEMINI_MAX_RETRIES)
        logger.info("GEMINI_SEQ_SIZE    = %d", config.GEMINI_SEQUENCE_SIZE)
        logger.info("GEMINI_MAX_SPAN_S  = %d", config.GEMINI_SEQUENCE_MAX_SPAN_SECONDS)
        logger.info("GEMINI_DRY_RUN     = %s", config.GEMINI_DRY_RUN)
        logger.info("GEMINI_CASCADE     = %s", config.GEMINI_CASCADE_ENABLED)
        logger.info("GEMINI_CAS_WINDOW  = %ss", config.GEMINI_CASCADE_WINDOW_SECONDS)
        logger.info("GEMINI_CAS_FRAMES  = max=%d min=%d", config.GEMINI_CASCADE_MAX_FRAMES, config.GEMINI_CASCADE_MIN_FRAMES)
        logger.info("GEMINI_AGENT1_MODEL= %s", config.GEMINI_AGENT1_MODEL)
        logger.info("GEMINI_AGENT1_TOUT = %ss", config.GEMINI_AGENT1_TIMEOUT_SECONDS)
        logger.info("GEMINI_AGENT1_CONF = %d", config.GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE)

    logger.info("GDRIVE_ENABLED     = %s", config.GDRIVE_ENABLED)
    if config.GDRIVE_ENABLED:
        logger.info("GDRIVE_FOLDER_ID   = %s", config.GDRIVE_FOLDER_ID)
        logger.info("GDRIVE_SYNC_HOUR   = %d", config.GDRIVE_SYNC_HOUR)
    logger.info("S3_ENABLED         = %s", config.S3_ENABLED)
    if config.S3_ENABLED:
        logger.info("S3_BUCKET_NAME     = %s", config.S3_BUCKET_NAME)
        logger.info("S3_REGION          = %s", config.S3_REGION)
        logger.info("S3_SYNC_HOUR       = %d", config.S3_SYNC_HOUR)
    logger.info("CAR_SHADOW_ENABLED = %s", config.CAR_SHADOW_ENABLED)
    if config.CAR_SHADOW_ENABLED:
        logger.info("CAR_MODEL_PATH     = %s", config.CAR_MODEL_PATH)
        logger.info("CAR_CONF_THRESHOLD = %.2f", config.CAR_CONF_THRESHOLD)
        logger.info("CAR_STATIONARY_PIX = %.1f", config.CAR_STATIONARY_PIXELS)
        logger.info("CAR_FRAMES         = LOW=%d MED=%d HIGH=%d",
                    config.CAR_LOW_FRAMES, config.CAR_MED_FRAMES, config.CAR_HIGH_FRAMES)
        logger.info("CAR_TRACK_TTL_SEC  = %d", config.CAR_TRACK_TTL_SECONDS)
    logger.info("=" * 60)

    if not config.WORKER_ENABLED:
        logger.info("Worker is disabled (WORKER_ENABLED=false). Idling.")
        while True:
            time.sleep(3600)

    if config.AI_MODE in {"shadow", "gemini"} and not config.GEMINI_API_KEY and not getattr(config, "GEMINI_USE_VERTEX", False):
        raise RuntimeError("GEMINI_API_KEY is required when AI_MODE is shadow or gemini (or set GEMINI_USE_VERTEX=true)")

    start_metrics_server()
    init_connections()

    if config.AI_MODE in {"yolo", "shadow"}:
        load_models(config.P1_MODEL_PATH, config.P2_MODEL_PATH)

    if config.CAR_SHADOW_ENABLED:
        try:
            detector_car_yolo.load_model(config.CAR_MODEL_PATH)
        except Exception:
            logger.exception(
                "Failed to load car-shadow model at %s — disabling car shadow.",
                config.CAR_MODEL_PATH,
            )
            config.CAR_SHADOW_ENABLED = False

    while True:
        try:
            n = scan_and_process()
            observe_scan_cycle(n)
            if n:
                logger.info("Cycle complete: %d images processed", n)

            if config.AI_MODE in {"shadow", "gemini"}:
                _log_gemini_metrics_snapshot()

            _maybe_run_drive_sync()
            _maybe_run_s3_sync()

        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception:
            observe_scan_error()
            logger.exception("Unhandled error in scan cycle")

        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    main()
