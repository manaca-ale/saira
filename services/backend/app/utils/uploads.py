"""Helpers to read the camera uploads volume (the esp32-server upload tree).

Layout: {CAMERA_UPLOADS_DIR}/{device_id}/YYYY/MM/DD/*.jpg (mounted RO into the
backend container). Shared by the cameras API (latest-image preview) and the
camera offline monitor (last-upload age).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

UPLOADS_ROOT = Path(os.getenv("CAMERA_UPLOADS_DIR", "/app/uploads"))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def find_latest_image_for_device(device_id: str) -> Optional[tuple[Path, float]]:
    """Return (path, mtime) of the most recent image for a device, or None.

    Walks the whole device subtree and picks the newest file by mtime. Returns
    None if the device has no directory or no image files yet.
    """
    if not device_id:
        return None

    camera_dir = UPLOADS_ROOT / device_id
    if not camera_dir.exists() or not camera_dir.is_dir():
        return None

    latest_path: Optional[Path] = None
    latest_mtime = float("-inf")

    for root, _, files in os.walk(camera_dir):
        for file_name in files:
            path = Path(root) / file_name
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_path = path

    if latest_path is None:
        return None
    return latest_path, latest_mtime
