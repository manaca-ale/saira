"""Daily S3 migration for processed images.

Uploads occurrence images individually (labeled/ → ocorrencias/ prefix in S3)
and non-occurrence images as daily zips (sem_ocorrencia/ → descartadas/ prefix).
Updates the database ``image_url`` references, then removes local files.

Designed to run once per day at 03:00 BRT, processing files from D-1
(yesterday).  Follows the same architecture as ``gdrive_sync.py``.
"""

import json
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from . import config

logger = logging.getLogger("worker.s3_sync")

BRASILIA = ZoneInfo("America/Sao_Paulo")


# ------------------------------------------------------------------
# S3 helpers
# ------------------------------------------------------------------

def _get_s3_client():
    import boto3

    kwargs = {"region_name": config.S3_REGION}
    if config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = config.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = config.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def _s3_key_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _upload_file(s3, local_path: Path, bucket: str, key: str, content_type: str = "image/jpeg") -> bool:
    """Upload *local_path* to S3.  Returns True on success (or already exists)."""
    if _s3_key_exists(s3, bucket, key):
        logger.debug("S3 key already exists, skipping: %s", key)
        return True
    try:
        s3.upload_file(str(local_path), bucket, key, ExtraArgs={"ContentType": content_type})
        return _s3_key_exists(s3, bucket, key)
    except Exception:
        logger.exception("Failed to upload %s → s3://%s/%s", local_path, bucket, key)
        return False


def _s3_public_url(bucket: str, region: str, key: str) -> str:
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


# ------------------------------------------------------------------
# Phase 1: Occurrence images (labeled/ → S3 ocorrencias/)
# ------------------------------------------------------------------

def _migrate_occurrences(s3, bucket: str, region: str, target_date_str: str) -> dict:
    """Upload labeled images to S3 and update DB ``image_url``."""
    from .db import _get_conn, _put_conn

    stats = {"uploaded": 0, "db_updated": 0, "frames_updated": 0, "errors": 0}
    upload_dir = Path(config.UPLOAD_DIR)
    state_dir = Path(config.STATE_DIR)

    conn = _get_conn()
    try:
        cur = conn.cursor()
        # ``timestamp`` is TIMESTAMPTZ; psycopg sessions default to Etc/UTC
        # regardless of the container TZ env, so a plain ``::date`` comparison
        # would drop detections between 21:00 and 23:59 BRT (which are already
        # the next day in UTC). Convert explicitly to America/Sao_Paulo first.
        cur.execute(
            "SELECT d.id, d.image_url, c.device_id "
            "FROM detections d "
            "JOIN cameras c ON d.camera_id = c.id "
            "WHERE d.image_url LIKE '%%/uploads/%%' "
            "  AND (d.timestamp AT TIME ZONE 'America/Sao_Paulo')::date = %s",
            (target_date_str,),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        _put_conn(conn)

    logger.info("Occurrences to migrate for %s: %d", target_date_str, len(rows))

    for det_id, image_url, device_id in rows:
        try:
            # Extract relative path from image_url
            parts = image_url.split("/uploads/", 1)
            if len(parts) < 2:
                continue
            rel_path = parts[1]  # e.g. "device-01/labeled/2026/03/14/file.jpg"
            local_path = upload_dir / rel_path

            if not local_path.exists():
                logger.warning("Local file missing for detection %s: %s", det_id, local_path)
                stats["errors"] += 1
                continue

            # Build S3 key: ocorrencias/{device_id}/YYYY/MM/DD/filename.jpg
            filename = local_path.name
            date_parts = target_date_str.replace("-", "/")  # 2026-03-14 → 2026/03/14
            s3_key = f"ocorrencias/{device_id}/{date_parts}/{filename}"

            if not _upload_file(s3, local_path, bucket, s3_key):
                stats["errors"] += 1
                continue

            stats["uploaded"] += 1
            s3_url = _s3_public_url(bucket, region, s3_key)

            # Update DB image_url
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE detections SET image_url = %s, updated_at = NOW() WHERE id = %s",
                    (s3_url, str(det_id)),
                )
                conn.commit()
                cur.close()
                stats["db_updated"] += 1
            except Exception:
                conn.rollback()
                logger.exception("DB update failed for detection %s", det_id)
                stats["errors"] += 1
                continue
            finally:
                _put_conn(conn)

            # Update detection_frames JSON
            frames_updated = _update_detection_frames(
                s3, bucket, region, state_dir, upload_dir,
                str(det_id), device_id, date_parts,
            )
            if frames_updated:
                stats["frames_updated"] += 1

            # Delete local file only after DB and S3 are consistent
            local_path.unlink(missing_ok=True)

        except Exception:
            logger.exception("Error migrating detection %s", det_id)
            stats["errors"] += 1

    return stats


def _update_detection_frames(
    s3, bucket: str, region: str,
    state_dir: Path, upload_dir: Path,
    detection_id: str, device_id: str, date_parts: str,
) -> bool:
    """Upload extra frames to S3 and rewrite URLs in the JSON index."""
    json_path = state_dir / "detection_frames" / f"{detection_id}.json"
    if not json_path.exists():
        return False

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read frames JSON %s", json_path)
        return False

    frames = data.get("frames", [])
    kept_frames = []
    changed = False

    for frame in frames:
        url = frame.get("image_url", "")
        if "/uploads/" not in url:
            kept_frames.append(frame)
            continue  # already migrated or external

        rel_path = url.split("/uploads/", 1)[1]
        local_path = upload_dir / rel_path
        filename = Path(rel_path).name
        s3_key = f"ocorrencias/{device_id}/{date_parts}/{filename}"

        if local_path.exists():
            _upload_file(s3, local_path, bucket, s3_key)
            local_path.unlink(missing_ok=True)
            frame["image_url"] = _s3_public_url(bucket, region, s3_key)
            kept_frames.append(frame)
            changed = True
        elif _s3_key_exists(s3, bucket, s3_key):
            # Local file gone but already in S3 (e.g. partial prior run)
            frame["image_url"] = _s3_public_url(bucket, region, s3_key)
            kept_frames.append(frame)
            changed = True
        else:
            # File irrecoverably lost (deleted by cleanup before migration).
            # Drop the frame from the index so the UI doesn't render a broken
            # thumbnail. The detection's main image (in labeled/) is unaffected.
            logger.warning(
                "Dropping orphaned frame for detection %s: %s (no local file, no S3 object)",
                detection_id, filename,
            )
            changed = True

    if changed:
        data["frames"] = kept_frames
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    return changed


# ------------------------------------------------------------------
# Phase 1b: Clean up ocorrencias/ originals for the target date
# ------------------------------------------------------------------

def _collect_referenced_ocorrencias(state_dir: Path, date_parts: str) -> set[str]:
    """Return absolute paths of ocorrencias/{date}/*.jpg files still referenced
    by any detection_frames/*.json whose image_url is local (i.e. the detection
    has NOT been migrated to S3 yet). Used by cleanup to avoid deleting frames
    of orphan detections that would later turn into 404 thumbnails."""
    frames_dir = state_dir / "detection_frames"
    if not frames_dir.exists():
        return set()

    referenced: set[str] = set()
    upload_dir = Path(config.UPLOAD_DIR)
    suffix = f"/ocorrencias/{date_parts}/"

    for json_path in frames_dir.glob("*.json"):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for frame in data.get("frames", []):
            url = frame.get("image_url", "")
            if "/uploads/" not in url or suffix not in url:
                continue
            rel_path = url.split("/uploads/", 1)[1]
            referenced.add(str((upload_dir / rel_path).resolve()))
    return referenced


def _cleanup_ocorrencias_originals(target_date_str: str) -> int:
    """Remove local ocorrencias/ originals for the target date, **skipping** files
    still referenced by detection_frames JSONs of detections that haven't been
    migrated yet (avoid orphaning their thumbnails)."""
    upload_dir = Path(config.UPLOAD_DIR)
    state_dir = Path(config.STATE_DIR)
    date_parts = target_date_str.replace("-", "/")
    removed = 0

    keep = _collect_referenced_ocorrencias(state_dir, date_parts)
    if keep:
        logger.info(
            "Cleanup will preserve %d files referenced by non-migrated detections", len(keep),
        )

    for device_dir in sorted(upload_dir.iterdir()):
        if not device_dir.is_dir():
            continue
        occ_day_dir = device_dir / "ocorrencias" / date_parts
        if not occ_day_dir.exists():
            continue
        for jpg in occ_day_dir.glob("*.jpg"):
            if str(jpg.resolve()) in keep:
                continue
            jpg.unlink(missing_ok=True)
            removed += 1
        _remove_empty_parents(occ_day_dir, device_dir / "ocorrencias")

    return removed


# ------------------------------------------------------------------
# Phase 2: Non-occurrence images (sem_ocorrencia/ → S3 descartadas/)
# ------------------------------------------------------------------

def _migrate_non_occurrences(s3, bucket: str, target_date_str: str) -> dict:
    """Zip and upload sem_ocorrencia images for the target date."""
    stats = {"zips_uploaded": 0, "files_zipped": 0, "errors": 0}
    upload_dir = Path(config.UPLOAD_DIR)
    date_parts = target_date_str.replace("-", "/")

    for device_dir in sorted(upload_dir.iterdir()):
        if not device_dir.is_dir():
            continue
        device_id = device_dir.name
        sem_dir = device_dir / "sem_ocorrencia" / date_parts
        if not sem_dir.exists():
            continue

        jpgs = sorted(sem_dir.glob("*.jpg"))
        if not jpgs:
            continue

        s3_key = f"descartadas/{device_id}/{target_date_str}/{device_id}_{target_date_str}.zip"

        # Already uploaded — just clean up local
        if _s3_key_exists(s3, bucket, s3_key):
            logger.debug("Zip already in S3, cleaning local: %s", s3_key)
            for jpg in jpgs:
                jpg.unlink(missing_ok=True)
            _remove_empty_parents(sem_dir, device_dir / "sem_ocorrencia")
            continue

        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for jpg in jpgs:
                    zf.write(jpg, arcname=jpg.name)
                    stats["files_zipped"] += 1

            ok = _upload_file(s3, tmp_path, bucket, s3_key, content_type="application/zip")
            if ok:
                stats["zips_uploaded"] += 1
                for jpg in jpgs:
                    jpg.unlink(missing_ok=True)
                _remove_empty_parents(sem_dir, device_dir / "sem_ocorrencia")
            else:
                stats["errors"] += 1

        except Exception:
            logger.exception("Error zipping sem_ocorrencia for %s/%s", device_id, target_date_str)
            stats["errors"] += 1
        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    return stats


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def _remove_empty_parents(path: Path, stop_at: Path) -> None:
    """Remove empty directories walking up to *stop_at*."""
    current = path
    while current != stop_at and current.exists():
        try:
            current.rmdir()  # only succeeds if empty
            current = current.parent
        except OSError:
            break


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------

def sync_uploads_to_s3() -> None:
    """Migrate D-1 images to S3, update DB URLs, and free local disk."""
    if not config.S3_BUCKET_NAME:
        logger.warning("S3_BUCKET_NAME not set — skipping S3 sync.")
        return

    target_date = (datetime.now(BRASILIA) - timedelta(days=1)).date()
    target_date_str = target_date.isoformat()  # "2026-03-14"
    bucket = config.S3_BUCKET_NAME
    region = config.S3_REGION

    logger.info("S3 sync starting for date=%s bucket=%s region=%s", target_date_str, bucket, region)

    s3 = _get_s3_client()

    # Phase 1: occurrence images
    occ_stats = _migrate_occurrences(s3, bucket, region, target_date_str)
    logger.info("S3 occurrences: %s", occ_stats)

    # Phase 1b: clean up ocorrencias/ originals
    occ_removed = _cleanup_ocorrencias_originals(target_date_str)
    if occ_removed:
        logger.info("S3 cleanup: removed %d ocorrencias/ originals", occ_removed)

    # Phase 2: non-occurrence images
    non_occ_stats = _migrate_non_occurrences(s3, bucket, target_date_str)
    logger.info("S3 non-occurrences: %s", non_occ_stats)

    logger.info("S3 sync complete for %s", target_date_str)
