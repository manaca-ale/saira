"""Build and encode 2x2 mosaics for Rekognition batch inference."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


@dataclass
class MosaicSlot:
    index: int
    row: int
    col: int
    x0: float
    y0: float
    tile_w: float
    tile_h: float
    source_index: Optional[int]
    source_path: Optional[str]
    orig_w: int
    orig_h: int
    pad_x: float
    pad_y: float
    scale_x: float
    scale_y: float


@dataclass
class MosaicBuildResult:
    mosaic_bgr: np.ndarray
    encoded_bytes: bytes
    encoded_size_bytes: int
    width: int
    height: int
    jpeg_quality: int
    downscale_factor: float
    slots: list[MosaicSlot]


def _letterbox_to_tile(image: np.ndarray, tile_w: int, tile_h: int) -> tuple[np.ndarray, dict]:
    orig_h, orig_w = image.shape[:2]
    scale = min(tile_w / max(orig_w, 1), tile_h / max(orig_h, 1))
    resized_w = max(1, int(round(orig_w * scale)))
    resized_h = max(1, int(round(orig_h * scale)))
    resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_AREA)

    tile = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)
    pad_x = (tile_w - resized_w) / 2.0
    pad_y = (tile_h - resized_h) / 2.0
    x0 = int(round(pad_x))
    y0 = int(round(pad_y))
    tile[y0 : y0 + resized_h, x0 : x0 + resized_w] = resized

    meta = {
        "orig_w": orig_w,
        "orig_h": orig_h,
        "pad_x": float(x0),
        "pad_y": float(y0),
        "scale_x": float(resized_w / max(orig_w, 1)),
        "scale_y": float(resized_h / max(orig_h, 1)),
    }
    return tile, meta


def _encode_jpeg(image_bgr: np.ndarray, quality: int) -> tuple[bytes, int]:
    ok, encoded = cv2.imencode(
        ".jpg",
        image_bgr,
        [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)],
    )
    if not ok:
        raise RuntimeError("Failed to JPEG-encode mosaic image")
    data = encoded.tobytes()
    return data, len(data)


def _scale_slots(slots: list[MosaicSlot], sx: float, sy: float) -> list[MosaicSlot]:
    scaled: list[MosaicSlot] = []
    for s in slots:
        scaled.append(
            MosaicSlot(
                index=s.index,
                row=s.row,
                col=s.col,
                x0=s.x0 * sx,
                y0=s.y0 * sy,
                tile_w=s.tile_w * sx,
                tile_h=s.tile_h * sy,
                source_index=s.source_index,
                source_path=s.source_path,
                orig_w=s.orig_w,
                orig_h=s.orig_h,
                pad_x=s.pad_x * sx,
                pad_y=s.pad_y * sy,
                scale_x=s.scale_x * sx,
                scale_y=s.scale_y * sy,
            )
        )
    return scaled


def build_2x2_mosaic(
    image_paths: list[Path],
    tile_w: int,
    tile_h: int,
    max_payload_bytes: int,
    jpeg_quality_start: int,
    jpeg_quality_min: int,
    min_downscale_factor: float,
) -> MosaicBuildResult:
    """Create 2x2 mosaic from up to 4 images and ensure JPEG payload <= limit."""
    if not image_paths:
        raise ValueError("image_paths cannot be empty")
    if len(image_paths) > 4:
        raise ValueError("2x2 mosaic supports at most 4 images per batch")

    tile_w = max(int(tile_w), 64)
    tile_h = max(int(tile_h), 64)
    jpeg_quality_start = min(max(int(jpeg_quality_start), 1), 100)
    jpeg_quality_min = min(max(int(jpeg_quality_min), 1), jpeg_quality_start)
    max_payload_bytes = max(int(max_payload_bytes), 1_000_000)
    min_downscale_factor = float(max(min_downscale_factor, 0.1))

    base_h = tile_h * 2
    base_w = tile_w * 2
    base_mosaic = np.zeros((base_h, base_w, 3), dtype=np.uint8)
    base_slots: list[MosaicSlot] = []

    for idx in range(4):
        row = idx // 2
        col = idx % 2
        x0 = col * tile_w
        y0 = row * tile_h

        if idx < len(image_paths):
            p = image_paths[idx]
            img = cv2.imread(str(p))
            if img is None:
                raise RuntimeError(f"Could not read image for mosaic: {p}")
            tile, meta = _letterbox_to_tile(img, tile_w, tile_h)
            base_mosaic[y0 : y0 + tile_h, x0 : x0 + tile_w] = tile
            base_slots.append(
                MosaicSlot(
                    index=idx,
                    row=row,
                    col=col,
                    x0=float(x0),
                    y0=float(y0),
                    tile_w=float(tile_w),
                    tile_h=float(tile_h),
                    source_index=idx,
                    source_path=str(p),
                    orig_w=int(meta["orig_w"]),
                    orig_h=int(meta["orig_h"]),
                    pad_x=float(meta["pad_x"]),
                    pad_y=float(meta["pad_y"]),
                    scale_x=float(meta["scale_x"]),
                    scale_y=float(meta["scale_y"]),
                )
            )
        else:
            base_slots.append(
                MosaicSlot(
                    index=idx,
                    row=row,
                    col=col,
                    x0=float(x0),
                    y0=float(y0),
                    tile_w=float(tile_w),
                    tile_h=float(tile_h),
                    source_index=None,
                    source_path=None,
                    orig_w=0,
                    orig_h=0,
                    pad_x=0.0,
                    pad_y=0.0,
                    scale_x=1.0,
                    scale_y=1.0,
                )
            )

    qualities = list(range(jpeg_quality_start, jpeg_quality_min - 1, -5))
    if qualities[-1] != jpeg_quality_min:
        qualities.append(jpeg_quality_min)

    # Try without downscale first.
    for q in qualities:
        payload, size = _encode_jpeg(base_mosaic, q)
        if size <= max_payload_bytes:
            return MosaicBuildResult(
                mosaic_bgr=base_mosaic,
                encoded_bytes=payload,
                encoded_size_bytes=size,
                width=base_w,
                height=base_h,
                jpeg_quality=q,
                downscale_factor=1.0,
                slots=base_slots,
            )

    # If still too large, downscale and retry quality sweep.
    scale = 0.90
    while scale >= min_downscale_factor:
        out_w = max(64, int(round(base_w * scale)))
        out_h = max(64, int(round(base_h * scale)))
        resized = cv2.resize(base_mosaic, (out_w, out_h), interpolation=cv2.INTER_AREA)
        sx = out_w / base_w
        sy = out_h / base_h
        scaled_slots = _scale_slots(base_slots, sx, sy)

        for q in qualities:
            payload, size = _encode_jpeg(resized, q)
            if size <= max_payload_bytes:
                return MosaicBuildResult(
                    mosaic_bgr=resized,
                    encoded_bytes=payload,
                    encoded_size_bytes=size,
                    width=out_w,
                    height=out_h,
                    jpeg_quality=q,
                    downscale_factor=scale,
                    slots=scaled_slots,
                )

        scale = round(scale - 0.10, 4)

    raise RuntimeError(
        "Could not build a 2x2 mosaic under payload limit. "
        f"max_payload_bytes={max_payload_bytes}"
    )
