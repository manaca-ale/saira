"""Image mosaic utilities for Gemini agents.

Composes multiple CCTV frames into a single composite image before sending
to the Gemini API, reducing the number of image tokens per call.

Functions:
    build_mosaic_2x1  -- side-by-side (Agent 1 gate: 2 frames → 1 image)
    build_mosaic_4x3  -- 4-row × 3-col grid (Agent 2: 12 frames → 1 image)
    build_mosaic_3x2_pair -- two 3×2 grids (Agent 2: 12 frames → 2 images)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np


def _resize_to_height(img: np.ndarray, height: int) -> np.ndarray:
    """Resize image maintaining aspect ratio to the given height."""
    h, w = img.shape[:2]
    if h == height:
        return img
    scale = height / h
    new_w = max(1, int(w * scale))
    return cv2.resize(img, (new_w, height), interpolation=cv2.INTER_AREA)


def _pad_to_width(img: np.ndarray, width: int) -> np.ndarray:
    """Pad image on the right with black to reach the given width."""
    h, w = img.shape[:2]
    if w >= width:
        return img
    pad = np.zeros((h, width - w, 3), dtype=np.uint8)
    return cv2.hconcat([img, pad])


def _draw_label(img: np.ndarray, text: str, x: int = 8, y: int = 28) -> np.ndarray:
    """Draw a white label with black shadow at (x, y)."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.75
    thickness = 2
    # shadow
    cv2.putText(img, text, (x + 1, y + 1), font, scale, (0, 0, 0), thickness + 1, cv2.LINE_AA)
    # white text
    cv2.putText(img, text, (x, y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)
    return img


def build_mosaic_2x1(
    frame_a: Path,
    frame_b: Path,
    cell_height: int = 360,
) -> Path:
    """Build a side-by-side mosaic for Agent 1 (gate).

    LEFT = initial frame (BEFORE), RIGHT = final frame (AFTER).
    Returns path to a temporary JPEG file. Caller is responsible for deleting it.
    """
    img_a = cv2.imread(str(frame_a))
    img_b = cv2.imread(str(frame_b))

    if img_a is None:
        raise ValueError(f"Could not read image: {frame_a}")
    if img_b is None:
        raise ValueError(f"Could not read image: {frame_b}")

    img_a = _resize_to_height(img_a, cell_height)
    img_b = _resize_to_height(img_b, cell_height)

    # Normalise widths so hconcat works
    max_w = max(img_a.shape[1], img_b.shape[1])
    img_a = _pad_to_width(img_a, max_w)
    img_b = _pad_to_width(img_b, max_w)

    _draw_label(img_a, "BEFORE")
    _draw_label(img_b, "AFTER")

    mosaic = cv2.hconcat([img_a, img_b])

    tmp = tempfile.NamedTemporaryFile(suffix="_a1_mosaic.jpg", delete=False)
    tmp.close()
    cv2.imwrite(tmp.name, mosaic, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Path(tmp.name)


def _build_grid(frames: list[Path], cols: int, rows: int, cell_height: int, label_offset: int = 0) -> np.ndarray:
    """Build a cols×rows grid image from a list of frame paths.

    label_offset shifts the numeric labels (e.g. 6 makes cells show 7-12).
    """
    n = cols * rows
    cells_paths = list(frames[:n])
    # Pad with last frame if not enough
    while len(cells_paths) < n:
        cells_paths.append(cells_paths[-1])

    # Read and resize all cells
    cells: list[np.ndarray] = []
    for i, p in enumerate(cells_paths):
        img = cv2.imread(str(p))
        if img is None:
            img = np.zeros((cell_height, cell_height, 3), dtype=np.uint8)
        img = _resize_to_height(img, cell_height)
        cells.append(img)

    # Normalise all cells to the same width
    cell_w = max(c.shape[1] for c in cells)
    cells = [_pad_to_width(c, cell_w) for c in cells]

    # Draw numeric labels
    for i, img in enumerate(cells):
        _draw_label(img, str(i + 1 + label_offset))

    # Assemble rows
    row_imgs = []
    for r in range(rows):
        row = cv2.hconcat(cells[r * cols : (r + 1) * cols])
        row_imgs.append(row)

    return cv2.vconcat(row_imgs)


def build_mosaic_4x3(
    frames: list[Path],
    cell_height: int = 240,
) -> Path:
    """Build a 4-row × 3-col mosaic for Agent 2 (12 frames → 1 image).

    Frames are numbered 1-12 left-to-right, top-to-bottom (chronological).
    Returns path to a temporary JPEG file. Caller is responsible for deleting it.
    """
    if not frames:
        raise ValueError("frames must not be empty")

    mosaic = _build_grid(frames, cols=3, rows=4, cell_height=cell_height, label_offset=0)

    tmp = tempfile.NamedTemporaryFile(suffix="_a2_mosaic_4x3.jpg", delete=False)
    tmp.close()
    cv2.imwrite(tmp.name, mosaic, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Path(tmp.name)


def build_mosaic_3x2_pair(
    frames: list[Path],
    cell_height: int = 240,
) -> tuple[Path, Path]:
    """Build two 3-col × 2-row mosaics for Agent 2 (12 frames → 2 images).

    First mosaic: frames 1-6 (labels 1-6).
    Second mosaic: frames 7-12 (labels 7-12).
    Returns (path_first, path_second). Caller is responsible for deleting both.
    """
    if not frames:
        raise ValueError("frames must not be empty")

    first_half = list(frames[:6])
    second_half = list(frames[6:12]) if len(frames) > 6 else list(frames[-1:])

    mosaic_a = _build_grid(first_half, cols=3, rows=2, cell_height=cell_height, label_offset=0)
    mosaic_b = _build_grid(second_half, cols=3, rows=2, cell_height=cell_height, label_offset=6)

    tmp_a = tempfile.NamedTemporaryFile(suffix="_a2_mosaic_3x2a.jpg", delete=False)
    tmp_a.close()
    cv2.imwrite(tmp_a.name, mosaic_a, [cv2.IMWRITE_JPEG_QUALITY, 85])

    tmp_b = tempfile.NamedTemporaryFile(suffix="_a2_mosaic_3x2b.jpg", delete=False)
    tmp_b.close()
    cv2.imwrite(tmp_b.name, mosaic_b, [cv2.IMWRITE_JPEG_QUALITY, 85])

    return Path(tmp_a.name), Path(tmp_b.name)
