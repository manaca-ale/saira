"""AWS Rekognition detector (standard DetectLabels, no Custom Labels)."""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

import boto3
import cv2
import numpy as np
from botocore.config import Config as BotocoreConfig

from . import config
from .mosaic_builder import build_2x2_mosaic
from .mosaic_mapper import map_instance_bbox_to_source

logger = logging.getLogger(__name__)

_rekognition = None

# Maps Rekognition labels to SAIRA offender types.
OFFENDER_TYPE_MAP = {
    "person": "Pessoa",
    "people": "Pessoa",
    "car": "Carro",
    "automobile": "Carro",
    "truck": "Carro",
    "bus": "Carro",
    "van": "Carro",
    "motorcycle": "Moto",
    "motorbike": "Moto",
    "scooter": "Moto",
    "bicycle": "Outro",
    "bike": "Outro",
}


def _parse_csv_set(raw: str) -> set[str]:
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _normalize_label(name: str) -> str:
    return (name or "").strip().lower()


def _label_or_parent_matches(label: dict, candidates: set[str]) -> bool:
    if not candidates:
        return False

    label_name = _normalize_label(label.get("Name", ""))
    if label_name in candidates:
        return True

    for parent in label.get("Parents", []) or []:
        parent_name = _normalize_label(parent.get("Name", ""))
        if parent_name in candidates:
            return True

    return False


def _bbox_from_rekognition(bbox: dict, width: int, height: int) -> list[float]:
    """Convert normalized Rekognition bbox to absolute xyxy."""
    left = float(bbox.get("Left", 0.0))
    top = float(bbox.get("Top", 0.0))
    w = float(bbox.get("Width", 0.0))
    h = float(bbox.get("Height", 0.0))

    x1 = max(0.0, min(left * width, width - 1))
    y1 = max(0.0, min(top * height, height - 1))
    x2 = max(x1, min((left + w) * width, width - 1))
    y2 = max(y1, min((top + h) * height, height - 1))
    return [x1, y1, x2, y2]


def _read_image(image_path: Path) -> tuple[np.ndarray, int, int, bytes]:
    img = cv2.imread(str(image_path))
    if img is None:
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", img)
        if not ok:
            raise RuntimeError(f"Could not encode fallback image for {image_path}")
        return img, 640, 480, encoded.tobytes()

    height, width = img.shape[:2]
    encoded = cv2.imencode(".jpg", img)[1].tobytes()
    return img, width, height, encoded


def _detect_labels(image_bytes: bytes, min_confidence: float) -> list[dict]:
    if _rekognition is None:
        raise RuntimeError("Rekognition client not initialized")

    response = _rekognition.detect_labels(
        Image={"Bytes": image_bytes},
        MinConfidence=min_confidence,
        MaxLabels=config.REKOGNITION_MAX_LABELS,
    )
    return response.get("Labels", [])


def _confidence_0_to_1(raw_conf: float) -> float:
    """Normalize confidence value to [0,1], accepting 0-100 or 0-1."""
    if raw_conf <= 1.0:
        return max(raw_conf, 0.0)
    return max(raw_conf / 100.0, 0.0)


def load_models(p1_path: str, p2_path: str) -> None:
    """Compatibility entrypoint. Rekognition does not load local models."""
    del p1_path, p2_path

    global _rekognition
    boto_cfg = BotocoreConfig(
        region_name=config.AWS_REGION,
        retries={"max_attempts": max(config.REKOGNITION_MAX_RETRIES, 1), "mode": "standard"},
        connect_timeout=max(config.REKOGNITION_TIMEOUT_SECONDS, 1),
        read_timeout=max(config.REKOGNITION_TIMEOUT_SECONDS, 1),
    )
    _rekognition = boto3.client("rekognition", region_name=config.AWS_REGION, config=boto_cfg)
    logger.info("Rekognition client initialized (region=%s)", config.AWS_REGION)


# Public API (same signatures as detector_yolo.py)
def detect_garbage(image_path: Path, conf: float = 0.25) -> tuple[list[dict], object]:
    """Binary lixo detection using standard DetectLabels (no custom labels).

    Returns one detection when lixo is found, otherwise empty list.
    """
    del conf

    image, width, height, image_bytes = _read_image(image_path)
    labels = _detect_labels(image_bytes, min_confidence=config.REKOGNITION_WASTE_MIN_CONFIDENCE)

    waste_candidates = _parse_csv_set(config.REKOGNITION_WASTE_LABELS)
    matches = [label for label in labels if _label_or_parent_matches(label, waste_candidates)]

    if not matches:
        annotated = image.copy()
        cv2.putText(
            annotated,
            "sem lixo",
            (14, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        return [], annotated

    best_label = max(matches, key=lambda item: float(item.get("Confidence", 0.0)))
    label_conf = float(best_label.get("Confidence", 0.0))

    instances = best_label.get("Instances", []) or []
    if instances:
        best_instance = max(instances, key=lambda item: float(item.get("Confidence", label_conf)))
        instance_conf = float(best_instance.get("Confidence", label_conf))
        bbox = _bbox_from_rekognition(best_instance.get("BoundingBox", {}), width, height)
        confidence = instance_conf / 100.0
    else:
        # When no instance bbox is provided, keep a tiny bbox so volume estimation
        # does not explode to the full frame area.
        bbox = [0.0, 0.0, 1.0, 1.0]
        confidence = label_conf / 100.0

    # Binary output: only one detection when lixo is present.
    detection = {
        "class_name": best_label.get("Name", "Waste"),
        "db_waste_type": config.REKOGNITION_WASTE_TYPE_VALUE,
        "confidence": round(confidence, 4),
        "bbox": bbox,
    }

    annotated = image.copy()
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
    label_text = f"lixo:{detection['class_name']} {detection['confidence']:.2f}"
    cv2.putText(
        annotated,
        label_text,
        (max(10, x1), max(25, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )

    return [detection], annotated


def detect_infrators(image_path: Path, conf: float = 0.25) -> list[dict]:
    """Detect infractors using standard DetectLabels (no custom labels)."""
    del conf

    if config.REKOGNITION_OFFENDER_MODE == "disabled":
        return []

    _, width, height, image_bytes = _read_image(image_path)
    labels = _detect_labels(image_bytes, min_confidence=config.REKOGNITION_OFFENDER_MIN_CONFIDENCE)

    offender_candidates = _parse_csv_set(config.REKOGNITION_OFFENDER_LABELS)
    infrators: list[dict] = []

    for label in labels:
        label_name = label.get("Name", "")
        normalized = _normalize_label(label_name)

        if offender_candidates and normalized not in offender_candidates:
            continue

        offender_type = OFFENDER_TYPE_MAP.get(normalized)
        if not offender_type:
            continue

        label_conf = float(label.get("Confidence", 0.0))
        instances = label.get("Instances", []) or []

        if instances:
            for inst in instances:
                inst_conf = float(inst.get("Confidence", label_conf)) / 100.0
                bbox = _bbox_from_rekognition(inst.get("BoundingBox", {}), width, height)
                infrators.append(
                    {
                        "class_name": label_name,
                        "offender_type": offender_type,
                        "confidence": round(inst_conf, 4),
                        "bbox": bbox,
                    }
                )
        else:
            infrators.append(
                {
                    "class_name": label_name,
                    "offender_type": offender_type,
                    "confidence": round(label_conf / 100.0, 4),
                    "bbox": [0.0, 0.0, float(width - 1), float(height - 1)],
                }
            )

    return infrators


def detect_mosaic_batch(image_paths: list[Path], conf: float = 0.25) -> dict:
    """Run Rekognition once on a 2x2 mosaic and map detections back per image.

    Returns:
        {
          "per_image": [
             {"garbage_dets": [...], "infrator_dets": [...]},
             ...
          ],
          "requires_single_fallback": bool,
          "meta": {...}
        }
    """
    del conf

    if not image_paths:
        return {
            "per_image": [],
            "requires_single_fallback": False,
            "meta": {"reason": "empty_batch"},
        }

    mosaic = build_2x2_mosaic(
        image_paths=image_paths,
        tile_w=config.REKOGNITION_MOSAIC_TILE_WIDTH,
        tile_h=config.REKOGNITION_MOSAIC_TILE_HEIGHT,
        max_payload_bytes=config.REKOGNITION_MOSAIC_MAX_PAYLOAD_BYTES,
        jpeg_quality_start=config.REKOGNITION_MOSAIC_JPEG_QUALITY_START,
        jpeg_quality_min=config.REKOGNITION_MOSAIC_JPEG_QUALITY_MIN,
        min_downscale_factor=config.REKOGNITION_MOSAIC_MIN_DOWNSCALE_FACTOR,
    )

    min_conf = min(config.REKOGNITION_WASTE_MIN_CONFIDENCE, config.REKOGNITION_OFFENDER_MIN_CONFIDENCE)
    labels = _detect_labels(mosaic.encoded_bytes, min_confidence=min_conf)

    waste_candidates = _parse_csv_set(config.REKOGNITION_WASTE_LABELS)
    offender_candidates = _parse_csv_set(config.REKOGNITION_OFFENDER_LABELS)
    by_source: dict[int, dict] = defaultdict(lambda: {"garbage_dets": [], "infrator_dets": []})
    requires_single_fallback = False

    for label in labels:
        label_name = label.get("Name", "")
        normalized = _normalize_label(label_name)
        label_conf = float(label.get("Confidence", 0.0))
        instances = label.get("Instances", []) or []

        is_waste = _label_or_parent_matches(label, waste_candidates)
        is_offender = (
            config.REKOGNITION_OFFENDER_MODE != "disabled"
            and normalized in offender_candidates
            and normalized in OFFENDER_TYPE_MAP
        )

        if is_waste and label_conf >= config.REKOGNITION_WASTE_MIN_CONFIDENCE:
            if not instances:
                # Ambiguous at mosaic level (no bbox to map to source tile).
                requires_single_fallback = True
                continue
            for inst in instances:
                mapped = map_instance_bbox_to_source(inst.get("BoundingBox", {}), mosaic)
                if not mapped:
                    continue
                source_idx, mapped_bbox = mapped
                conf01 = _confidence_0_to_1(float(inst.get("Confidence", label_conf)))
                by_source[source_idx]["garbage_dets"].append(
                    {
                        "class_name": label_name,
                        "db_waste_type": config.REKOGNITION_WASTE_TYPE_VALUE,
                        "confidence": round(conf01, 4),
                        "bbox": mapped_bbox,
                    }
                )

        if is_offender and label_conf >= config.REKOGNITION_OFFENDER_MIN_CONFIDENCE:
            offender_type = OFFENDER_TYPE_MAP.get(normalized)
            if not offender_type:
                continue
            if not instances:
                continue
            for inst in instances:
                mapped = map_instance_bbox_to_source(inst.get("BoundingBox", {}), mosaic)
                if not mapped:
                    continue
                source_idx, mapped_bbox = mapped
                conf01 = _confidence_0_to_1(float(inst.get("Confidence", label_conf)))
                by_source[source_idx]["infrator_dets"].append(
                    {
                        "class_name": label_name,
                        "offender_type": offender_type,
                        "confidence": round(conf01, 4),
                        "bbox": mapped_bbox,
                    }
                )

    per_image: list[dict] = []
    for idx in range(len(image_paths)):
        payload = by_source.get(idx, {"garbage_dets": [], "infrator_dets": []})
        per_image.append(
            {
                "garbage_dets": payload.get("garbage_dets", []),
                "infrator_dets": payload.get("infrator_dets", []),
            }
        )

    return {
        "per_image": per_image,
        "requires_single_fallback": requires_single_fallback,
        "meta": {
            "mosaic_width": mosaic.width,
            "mosaic_height": mosaic.height,
            "jpeg_quality": mosaic.jpeg_quality,
            "encoded_size_bytes": mosaic.encoded_size_bytes,
            "downscale_factor": mosaic.downscale_factor,
            "labels_count": len(labels),
        },
    }
