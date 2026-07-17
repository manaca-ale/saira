"""Helpers to read the camera uploads volume (the esp32-server upload tree).

Layout: {CAMERA_UPLOADS_DIR}/{device_id}/YYYY/MM/DD/*.jpg (mounted RO into the
backend container). Shared by the cameras API (latest-image preview) and the
camera offline monitor (last-upload age).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

UPLOADS_ROOT = Path(os.getenv("CAMERA_UPLOADS_DIR", "/app/uploads"))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
KEEPALIVE_MARKER = ".keepalive"
HEALTH_MARKER = ".health.json"


def find_health_for_device(device_id: str) -> Optional[dict]:
    """Return the parsed .health.json telemetry for a device, or None.

    The esp32-server writes {device_id}/.health.json from the Pi keepalive body
    (field-hardening telemetry: camera_ok, rtsp_buffer_ok, throttled, disk_low…).
    Read-only; returns None if the file is absent, unreadable, or not an object.
    Only event-driven devices (Pi relay) report it; others simply return None.
    """
    if not device_id:
        return None
    hpath = UPLOADS_ROOT / device_id / HEALTH_MARKER
    try:
        with hpath.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_last_keepalive_for_device(device_id: str) -> Optional[float]:
    """Return the mtime of the device's keepalive marker, or None.

    The esp32-server touches {device_id}/.keepalive on POST /device/<id>/keepalive.
    This lets a device stay "online" without uploading an image (e.g. the
    event-driven Pi relay, which only sends frames on real events / on demand).
    Kept separate from find_latest_image_for_device so the marker is never shown
    as a preview image.
    """
    if not device_id:
        return None
    marker = UPLOADS_ROOT / device_id / KEEPALIVE_MARKER
    try:
        return marker.stat().st_mtime
    except OSError:
        return None


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
