"""Database operations for the worker (sync psycopg2 pool + Redis notifications)."""
import json
import logging
import time
from typing import Optional
from uuid import uuid4

import psycopg2
import psycopg2.extras
import psycopg2.pool
import redis

from . import config
from .models import CameraInfo, DetectionRecord, OffenderRecord

logger = logging.getLogger(__name__)

psycopg2.extras.register_uuid()

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_redis: Optional[redis.Redis] = None


def init_connections(max_retries: int = 12, base_delay: float = 2.0) -> None:
    """Initialize DB connection pool and Redis client.

    Retries with exponential backoff (up to 60 s per attempt) so the worker
    survives a slow DB startup without crashing the container.
    """
    global _pool, _redis

    for attempt in range(1, max_retries + 1):
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=config.DATABASE_URL,
            )
            logger.info("DB connection pool initialized (min=1, max=5).")
            break
        except Exception as exc:
            delay = min(base_delay * (2 ** (attempt - 1)), 60.0)
            if attempt == max_retries:
                logger.error(
                    "Could not connect to DB after %d attempts — giving up: %s",
                    max_retries, exc,
                )
                raise
            logger.warning(
                "DB connection failed (attempt %d/%d): %s — retrying in %.0fs",
                attempt, max_retries, exc, delay,
            )
            time.sleep(delay)

    try:
        _redis = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)
        _redis.ping()
        logger.info("Redis connected: %s", config.REDIS_URL)
    except Exception:
        logger.warning("Redis unavailable — real-time notifications will be skipped.")
        _redis = None


def _get_conn():
    return _pool.getconn()


def _put_conn(conn) -> None:
    _pool.putconn(conn)


# ==========================================
# CAMERA
# ==========================================

def resolve_camera(device_id: str) -> Optional[CameraInfo]:
    """Lookup camera by device_id. Returns None if not found."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, device_id, logradouro, bairro, rpa, latitude, longitude "
            "FROM cameras WHERE device_id = %s AND is_active = true LIMIT 1",
            (device_id,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        return CameraInfo(
            id=row[0], name=row[1], device_id=row[2],
            logradouro=row[3], bairro=row[4], rpa=row[5],
            latitude=row[6], longitude=row[7],
        )
    except Exception:
        logger.exception("Error resolving camera for device_id=%s", device_id)
        return None
    finally:
        _put_conn(conn)


def update_camera_last_capture(camera_id: int) -> None:
    """Update cameras.last_capture_at to NOW() for the given camera."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cameras SET last_capture_at = NOW() WHERE id = %s",
            (camera_id,),
        )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        logger.exception("Error updating last_capture_at for camera_id=%s", camera_id)
    finally:
        _put_conn(conn)


# ==========================================
# DETECTIONS
# ==========================================

def insert_detection(det: DetectionRecord) -> bool:
    """Insert a detection record. Returns True on success."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO detections (
                id, camera_id, timestamp, logradouro, bairro, rpa,
                latitude, longitude, waste_type, material_type,
                volume_m3, offenders, status, image_url, confidence_score,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                NOW(), NOW()
            )
            """,
            (
                det.id, det.camera_id, det.timestamp,
                det.logradouro, det.bairro, det.rpa,
                det.latitude, det.longitude,
                det.waste_type, det.material_type,
                det.volume_m3, det.offenders,
                det.status, det.image_url, det.confidence_score,
            ),
        )
        conn.commit()
        cur.close()
        logger.info("Inserted detection %s (camera=%s, waste=%s)", det.id, det.camera_id, det.waste_type)
        return True
    except Exception:
        conn.rollback()
        logger.exception("Error inserting detection")
        return False
    finally:
        _put_conn(conn)


def insert_offenders(offenders: list[OffenderRecord]) -> None:
    """Insert rows into detection_offenders (one per detected person/vehicle)."""
    if not offenders:
        return
    conn = _get_conn()
    try:
        cur = conn.cursor()
        for o in offenders:
            cur.execute(
                """
                INSERT INTO detection_offenders (
                    id, detection_id, offender_type,
                    source, confidence_score, created_at
                ) VALUES (%s, %s, %s, 'ai', %s, NOW())
                """,
                (o.id, o.detection_id, o.offender_type, o.confidence_score),
            )
        conn.commit()
        cur.close()
        logger.info("Inserted %d offender(s) for detection %s", len(offenders), offenders[0].detection_id)
    except Exception:
        conn.rollback()
        logger.exception("Error inserting offenders")
    finally:
        _put_conn(conn)


# ==========================================
# REDIS NOTIFICATIONS
# ==========================================

def insert_notifications(detection: DetectionRecord, camera: CameraInfo) -> int:
    """Insert Notification records for all active users that share the same RPA.

    Mirrors the logic in backend/app/services/notification_service.py so that
    worker-created detections produce persistent notification history.
    Returns the number of rows inserted.
    """
    conn = _get_conn()
    count = 0
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, rpa FROM users WHERE is_active = true")
        users = cur.fetchall()

        def _rpa_key(value: Optional[str]) -> str:
            raw = (value or "").strip().lower()
            digits = "".join(ch for ch in raw if ch.isdigit())
            return digits if digits else raw.replace(" ", "").replace("-", "")

        det_key = _rpa_key(camera.rpa)
        rpa_label = f"RPA {camera.rpa}" if camera.rpa else "RPA ?"
        location = ", ".join(filter(None, [camera.logradouro, camera.bairro]))
        meta = json.dumps({
            "rpa": camera.rpa,
            "detection_id": str(detection.id),
            "bairro": camera.bairro,
            "timestamp": detection.timestamp.isoformat() if detection.timestamp else None,
        })

        for user_id, user_rpa in users:
            if _rpa_key(user_rpa) != det_key:
                continue
            cur.execute(
                """
                INSERT INTO notifications (
                    id, user_id, detection_id, type,
                    title, message, metadata, is_read, created_at
                ) VALUES (
                    %s, %s, %s, 'nova_ocorrencia',
                    %s, %s, %s::jsonb, false, NOW()
                )
                """,
                (uuid4(), user_id, detection.id,
                 f"Nova ocorrência - {rpa_label}", location, meta),
            )
            count += 1

        conn.commit()
        cur.close()
        if count:
            logger.info("Inserted %d notification(s) for detection %s", count, detection.id)
    except Exception:
        conn.rollback()
        logger.exception("Error inserting notifications for detection %s", detection.id)
    finally:
        _put_conn(conn)
    return count


def publish_detection_event(detection: DetectionRecord, camera: CameraInfo) -> None:
    """Publish a new_detection event to Redis so the backend SSE stream delivers
    it to the frontend NotificationToastContainer."""
    if _redis is None:
        return

    rpa_label = f"RPA {camera.rpa}" if camera.rpa else "RPA ?"
    location = ", ".join(filter(None, [camera.logradouro, camera.bairro]))

    payload = json.dumps({
        "type": "new_detection",
        "title": f"Nova ocorrência - {rpa_label}",
        "message": location,
        "detection_id": str(detection.id),
        "metadata": {
            "rpa": camera.rpa,
            "detection_id": str(detection.id),
            "bairro": camera.bairro,
            "timestamp": detection.timestamp.isoformat() if detection.timestamp else None,
        },
    })

    try:
        _redis.publish("notifications:all", payload)
        logger.info("Redis event published for detection %s", detection.id)
    except Exception:
        logger.exception("Failed to publish detection event to Redis")
