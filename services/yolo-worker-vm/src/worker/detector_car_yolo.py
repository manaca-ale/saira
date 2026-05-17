"""YOLO inference for parked-vehicle detection (shadow mode).

Single-class model `yolov8_Car_tesi_100_n.pt` ported from
https://github.com/GabrielCande/CarDetectionModule.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
from ultralytics import YOLO

logger = logging.getLogger(__name__)

_car_model: Optional[YOLO] = None


def load_model(model_path: str) -> None:
    global _car_model
    logger.info("Loading car-stopped model: %s", model_path)
    _car_model = YOLO(model_path)
    logger.info("Car-stopped model loaded.")


def is_loaded() -> bool:
    return _car_model is not None


def analyze_image(image_path: Path, conf: float = 0.35) -> list[dict]:
    """Run inference on a single frame, return list of {class_name, confidence, bbox}.

    bbox is [x1, y1, x2, y2] in pixel coordinates of the original image.
    """
    if _car_model is None:
        raise RuntimeError("Car-stopped model not loaded.")

    results = _car_model(str(image_path), verbose=False, conf=conf)
    detections: list[dict] = []
    for result in results:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            detections.append(
                {
                    "class_name": _car_model.names[cls_id],
                    "confidence": float(box.conf[0]),
                    "bbox": [float(v) for v in box.xyxy[0].tolist()],
                }
            )
    return detections


def analyze_array(img_array: np.ndarray, conf: float = 0.35) -> list[dict]:
    """Same as analyze_image but takes an in-memory BGR array (used in tests)."""
    if _car_model is None:
        raise RuntimeError("Car-stopped model not loaded.")

    results = _car_model(img_array, verbose=False, conf=conf)
    detections: list[dict] = []
    for result in results:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            detections.append(
                {
                    "class_name": _car_model.names[cls_id],
                    "confidence": float(box.conf[0]),
                    "bbox": [float(v) for v in box.xyxy[0].tolist()],
                }
            )
    return detections
