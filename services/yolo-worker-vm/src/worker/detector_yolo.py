"""YOLO inference engine.

P1: garbage detection  (yolov8_2142.pt)   — classes: entulho, lixo domiciliar, restos de madeira, terra
P2: infrator detection (yolov8_PeopleCar_200_n.pt) — classes: person, car, motorcycle, ...
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ultralytics import YOLO

logger = logging.getLogger(__name__)

_p1_model: Optional[YOLO] = None
_p2_model: Optional[YOLO] = None

# Model class → DB waste_type
WASTE_TYPE_MAP = {
    "entulho":           "Entulho",
    "lixo domiciliar":   "Lixo domiciliar",
    "restos de madeira": "Entulho",
    "terra":             "Entulho",
}

# Model class → detection_offenders.offender_type
OFFENDER_TYPE_MAP = {
    "person":     "Pessoa",
    "car":        "Carro",
    "truck":      "Carro",
    "bus":        "Carro",
    "motorcycle": "Moto",
    "bicycle":    "Outro",
}


def load_models(p1_path: str, p2_path: str) -> None:
    global _p1_model, _p2_model
    logger.info("Loading P1 (garbage) model: %s", p1_path)
    _p1_model = YOLO(p1_path)
    logger.info("Loading P2 (infrator) model: %s", p2_path)
    _p2_model = YOLO(p2_path)
    logger.info("Both models loaded.")


def detect_garbage(image_path: Path, conf: float = 0.25) -> tuple[list[dict], object]:
    """Run P1. Returns (detections, annotated_bgr_array)."""
    if _p1_model is None:
        raise RuntimeError("Models not loaded.")
    results = _p1_model(str(image_path), verbose=False, conf=conf)
    detections = []
    for result in results:
        for box in result.boxes:
            class_name = _p1_model.names[int(box.cls[0])]
            detections.append({
                "class_name": class_name,
                "db_waste_type": WASTE_TYPE_MAP.get(class_name.lower(), "Entulho"),
                "confidence": float(box.conf[0]),
                "bbox": box.xyxy[0].tolist(),
            })
    return detections, results[0].plot()


def detect_infrators(image_path: Path, conf: float = 0.25) -> list[dict]:
    """Run P2. Returns list of detected infrators (filtered to relevant classes)."""
    if _p2_model is None:
        raise RuntimeError("Models not loaded.")
    results = _p2_model(str(image_path), verbose=False, conf=conf)
    infrators = []
    for result in results:
        for box in result.boxes:
            class_name = _p2_model.names[int(box.cls[0])]
            offender_type = OFFENDER_TYPE_MAP.get(class_name.lower())
            if offender_type:
                infrators.append({
                    "class_name": class_name,
                    "offender_type": offender_type,
                    "confidence": float(box.conf[0]),
                    "bbox": box.xyxy[0].tolist(),
                })
    return infrators
