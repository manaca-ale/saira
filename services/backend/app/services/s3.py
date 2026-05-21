"""S3 client + helpers for the backend.

Mirrors the worker's storage_s3 helpers but exposes them as backend-friendly
APIs (typed paths, no DB coupling). Used by the image export feature to:

- list occurrence images already migrated for a camera/day
- check whether the daily ``descartadas`` ZIP exists for a date
- download keys to a local temp path
- upload the final export ZIP
- generate presigned URLs for browser download
- delete an export object on cleanup/manual deletion
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Client
# ------------------------------------------------------------------

def get_s3_client():
    import boto3

    kwargs = {"region_name": settings.S3_REGION}
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def s3_enabled() -> bool:
    """True when bucket is configured and we can hit S3."""
    return bool(settings.S3_BUCKET_NAME)


# ------------------------------------------------------------------
# Key building (mirrors worker storage_s3 layout)
# ------------------------------------------------------------------

def occurrence_prefix(device_id: str, day: date) -> str:
    """e.g. ocorrencias/{device_id}/YYYY/MM/DD/"""
    return f"ocorrencias/{device_id}/{day.strftime('%Y/%m/%d')}/"


def non_occurrence_zip_key(device_id: str, day: date) -> str:
    """e.g. descartadas/{device_id}/{YYYY-MM-DD}/{device_id}_{YYYY-MM-DD}.zip"""
    iso = day.isoformat()
    return f"descartadas/{device_id}/{iso}/{device_id}_{iso}.zip"


def export_key(user_id: int, export_id: str) -> str:
    """e.g. exports/{user_id}/{export_id}.zip"""
    return f"{settings.EXPORT_S3_PREFIX}/{user_id}/{export_id}.zip"


# ------------------------------------------------------------------
# Operations
# ------------------------------------------------------------------

def head_object_exists(client, key: str) -> bool:
    try:
        client.head_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
        return True
    except Exception:
        return False


def list_keys(client, prefix: str) -> list[str]:
    """List all object keys under *prefix*."""
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.S3_BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            keys.append(obj["Key"])
    return keys


def download_object(client, key: str, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(settings.S3_BUCKET_NAME, key, str(dest_path))


def upload_file(
    client,
    src_path: Path,
    key: str,
    content_type: str = "application/zip",
) -> None:
    client.upload_file(
        str(src_path),
        settings.S3_BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def delete_object(client, key: str) -> None:
    try:
        client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
    except Exception:
        logger.exception("Failed to delete s3 key %s", key)


def generate_presigned_url(
    client,
    key: str,
    expires_in: Optional[int] = None,
) -> str:
    ttl = expires_in if expires_in is not None else settings.EXPORT_PRESIGNED_TTL_SECONDS
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET_NAME, "Key": key},
        ExpiresIn=ttl,
    )
