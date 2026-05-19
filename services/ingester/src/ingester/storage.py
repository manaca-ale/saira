"""
Storage abstraction for Ingester.

Supports:
- S3 (legacy): s3://{bucket}/{key}
- Local filesystem (EC2 disk): file://{absolute_path}
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config


@dataclass(frozen=True)
class StorageRef:
    backend: str  # "s3" | "local"
    uri: str      # s3://... or file://...
    # extra fields (optional)
    bucket: str | None = None
    key: str | None = None
    abs_path: str | None = None
    rel_path: str | None = None


def _generate_rel_path(camera_id: str, timestamp: datetime) -> str:
    # raw/YYYY/MM/DD/camera_id_HHMMSS.jpg (same shape as previous S3 key)
    return (
        f"raw/{timestamp.strftime('%Y/%m/%d')}/"
        f"{camera_id}_{timestamp.strftime('%H%M%S')}.jpg"
    )


def store_image(camera_id: str, timestamp: datetime, jpeg_bytes: bytes) -> StorageRef:
    backend = (config.STORAGE_BACKEND or "s3").strip().lower()

    if backend == "local":
        rel = _generate_rel_path(camera_id, timestamp)
        root = Path(config.LOCAL_LANDING_ZONE_DIR)
        abs_path = root / Path(rel)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(jpeg_bytes)
        return StorageRef(
            backend="local",
            uri=f"file://{abs_path.as_posix()}",
            abs_path=str(abs_path),
            rel_path=rel,
        )

    # Default: S3
    if not config.ENABLE_S3:
        raise RuntimeError("ENABLE_S3=0 but STORAGE_BACKEND is not 'local'")

    from .s3 import upload_image_to_s3

    key = _generate_rel_path(camera_id, timestamp)
    upload_image_to_s3(data=jpeg_bytes, bucket=config.S3_LANDING_ZONE_BUCKET, key=key)
    return StorageRef(
        backend="s3",
        uri=f"s3://{config.S3_LANDING_ZONE_BUCKET}/{key}",
        bucket=config.S3_LANDING_ZONE_BUCKET,
        key=key,
    )

