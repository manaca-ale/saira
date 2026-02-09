"""Database operations for the worker (sync psycopg2)."""
import psycopg2
import psycopg2.extras
from typing import Optional
import logging

from . import config
from .models import CameraInfo, DetectionRecord

logger = logging.getLogger(__name__)

# Register UUID adapter for psycopg2
psycopg2.extras.register_uuid()


def get_connection():
    """Create a new database connection."""
    return psycopg2.connect(config.DATABASE_URL)


def resolve_camera(device_id: str) -> Optional[CameraInfo]:
    """Lookup camera by device_id. Returns None if not found."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, device_id, logradouro, bairro, rpa, latitude, longitude "
            "FROM cameras WHERE device_id = %s AND is_active = true LIMIT 1",
            (device_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return CameraInfo(
            id=row[0],
            name=row[1],
            device_id=row[2],
            logradouro=row[3],
            bairro=row[4],
            rpa=row[5],
            latitude=row[6],
            longitude=row[7],
        )
    except Exception:
        logger.exception("Error resolving camera for device_id=%s", device_id)
        return None


def insert_detection(det: DetectionRecord) -> bool:
    """Insert a detection record. Returns True on success."""
    try:
        conn = get_connection()
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
        conn.close()
        logger.info("Inserted detection %s (camera=%s)", det.id, det.camera_id)
        return True
    except Exception:
        logger.exception("Error inserting detection")
        return False
