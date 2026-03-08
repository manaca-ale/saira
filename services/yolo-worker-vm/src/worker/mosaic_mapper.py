"""Map Rekognition mosaic detections back to source-image coordinates."""
from __future__ import annotations

from typing import Optional

from .mosaic_builder import MosaicBuildResult, MosaicSlot


def _relative_bbox_to_mosaic_pixels(
    rel_bbox: dict,
    mosaic_w: int,
    mosaic_h: int,
) -> tuple[float, float, float, float]:
    left = float(rel_bbox.get("Left", 0.0))
    top = float(rel_bbox.get("Top", 0.0))
    width = float(rel_bbox.get("Width", 0.0))
    height = float(rel_bbox.get("Height", 0.0))

    x1 = left * mosaic_w
    y1 = top * mosaic_h
    x2 = (left + width) * mosaic_w
    y2 = (top + height) * mosaic_h
    return x1, y1, x2, y2


def _slot_index_from_centroid(x1: float, y1: float, x2: float, y2: float, mosaic_w: int, mosaic_h: int) -> int:
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    col = 0 if cx < (mosaic_w / 2.0) else 1
    row = 0 if cy < (mosaic_h / 2.0) else 1
    return row * 2 + col


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))


def _unletterbox_to_original(
    x_tile: float,
    y_tile: float,
    slot: MosaicSlot,
) -> tuple[float, float]:
    x = (x_tile - slot.pad_x) / max(slot.scale_x, 1e-6)
    y = (y_tile - slot.pad_y) / max(slot.scale_y, 1e-6)
    return x, y


def map_instance_bbox_to_source(
    rel_bbox: dict,
    mosaic: MosaicBuildResult,
) -> Optional[tuple[int, list[float]]]:
    """Map one Rekognition instance bbox from mosaic space to source image space.

    Returns `(source_index, [x1, y1, x2, y2])` or None if not mappable.
    """
    x1m, y1m, x2m, y2m = _relative_bbox_to_mosaic_pixels(rel_bbox, mosaic.width, mosaic.height)
    if x2m <= x1m or y2m <= y1m:
        return None

    slot_idx = _slot_index_from_centroid(x1m, y1m, x2m, y2m, mosaic.width, mosaic.height)
    if slot_idx < 0 or slot_idx >= len(mosaic.slots):
        return None

    slot = mosaic.slots[slot_idx]
    if slot.source_index is None or slot.orig_w <= 0 or slot.orig_h <= 0:
        return None

    x1t = _clip(x1m - slot.x0, 0.0, slot.tile_w)
    y1t = _clip(y1m - slot.y0, 0.0, slot.tile_h)
    x2t = _clip(x2m - slot.x0, 0.0, slot.tile_w)
    y2t = _clip(y2m - slot.y0, 0.0, slot.tile_h)
    if x2t <= x1t or y2t <= y1t:
        return None

    x1o, y1o = _unletterbox_to_original(x1t, y1t, slot)
    x2o, y2o = _unletterbox_to_original(x2t, y2t, slot)

    x1o = _clip(x1o, 0.0, float(slot.orig_w - 1))
    y1o = _clip(y1o, 0.0, float(slot.orig_h - 1))
    x2o = _clip(x2o, 0.0, float(slot.orig_w - 1))
    y2o = _clip(y2o, 0.0, float(slot.orig_h - 1))

    if x2o <= x1o or y2o <= y1o:
        return None

    return slot.source_index, [x1o, y1o, x2o, y2o]
