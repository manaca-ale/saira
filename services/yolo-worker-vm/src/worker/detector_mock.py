"""Mock inference engine — no model files required.

Simulates garbage and infrator detections for full pipeline testing.
Activate with MOCK_MODE=true in the worker environment.

Env vars:
    MOCK_DETECTION_PROB  float [0-1]  probability an image triggers a detection (default: 0.5)
    MOCK_MAX_OBJECTS     int          max garbage objects per detection (default: 5)
    MOCK_INFRATOR_PROB   float [0-1]  probability of an infrator alongside garbage (default: 0.3)
"""
from __future__ import annotations

import logging
import os
import random
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ---- tuneable via env ----
DETECTION_PROB  = float(os.getenv("MOCK_DETECTION_PROB", "0.5"))
INFRATOR_PROB   = float(os.getenv("MOCK_INFRATOR_PROB",  "0.3"))
MAX_OBJECTS     = int(os.getenv("MOCK_MAX_OBJECTS", "5"))

# ---- class tables (must mirror detector_yolo.py) ----
_WASTE_CLASSES = [
    {"class_name": "entulho",           "db_waste_type": "Entulho"},
    {"class_name": "lixo domiciliar",   "db_waste_type": "Lixo domiciliar"},
    {"class_name": "restos de madeira", "db_waste_type": "Entulho"},
    {"class_name": "terra",             "db_waste_type": "Entulho"},
]

_OFFENDER_CLASSES = [
    {"class_name": "person",     "offender_type": "Pessoa"},
    {"class_name": "car",        "offender_type": "Carro"},
    {"class_name": "motorcycle", "offender_type": "Moto"},
]

# BGR colours for annotation boxes
_COLOR_GARBAGE  = (0, 0, 220)    # red
_COLOR_INFRATOR = (220, 140, 0)  # blue-orange


def load_models(p1_path: str, p2_path: str) -> None:
    logger.info("MOCK MODE — skipping real model load.")
    logger.info("  P1 (would be): %s", p1_path)
    logger.info("  P2 (would be): %s", p2_path)


# ---- helpers ----

def _random_bbox(w: int, h: int) -> list[float]:
    """Random bbox that occupies 10-50% of each axis."""
    min_w, min_h = max(w // 10, 20), max(h // 10, 20)
    x1 = random.randint(0, w - min_w - 1)
    y1 = random.randint(0, h - min_h - 1)
    x2 = random.randint(x1 + min_w, min(x1 + w // 2, w - 1))
    y2 = random.randint(y1 + min_h, min(y1 + h // 2, h - 1))
    return [float(x1), float(y1), float(x2), float(y2)]


def _draw_boxes(img: np.ndarray, dets: list[dict], color: tuple) -> np.ndarray:
    out = img.copy()
    for d in dets:
        x1, y1, x2, y2 = (int(v) for v in d["bbox"])
        label = f"{d['class_name']} {d['confidence']:.2f}"
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(out, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(out, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    return out


# ---- public API (same signatures as detector_yolo.py) ----

def detect_garbage(image_path: Path, conf: float = 0.25) -> tuple[list[dict], object]:
    """Simulate P1 garbage detection. Returns (detections, annotated_bgr)."""
    img = cv2.imread(str(image_path))
    if img is None:
        h, w = 480, 640
        img = np.zeros((h, w, 3), dtype=np.uint8)
    else:
        h, w = img.shape[:2]

    if random.random() > DETECTION_PROB:
        return [], img.copy()

    n = random.randint(1, max(1, MAX_OBJECTS))
    dets = []
    for _ in range(n):
        cls = random.choice(_WASTE_CLASSES)
        dets.append({
            **cls,
            "confidence": round(random.uniform(max(conf, 0.25), 0.96), 2),
            "bbox": _random_bbox(w, h),
        })

    annotated = _draw_boxes(img, dets, _COLOR_GARBAGE)
    return dets, annotated


def detect_infrators(image_path: Path, conf: float = 0.25) -> list[dict]:
    """Simulate P2 infrator detection."""
    if random.random() > INFRATOR_PROB:
        return []

    img = cv2.imread(str(image_path))
    h, w = (img.shape[:2] if img is not None else (480, 640))

    n = random.randint(1, 2)
    infrators = []
    for _ in range(n):
        cls = random.choice(_OFFENDER_CLASSES)
        infrators.append({
            **cls,
            "confidence": round(random.uniform(max(conf, 0.25), 0.96), 2),
            "bbox": _random_bbox(w, h),
        })
    return infrators
