"""Fake YOLO worker — polls uploads directory and creates detections in the database."""
import logging
import os
import random
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from . import config
from .db import resolve_camera, insert_detection
from .models import DetectionRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

# Waste types matching frontend Detections.tsx options
WASTE_TYPES = ["Entulho", "Lixo domiciliar", "Poda", "Plastico"]
MATERIAL_TYPES = ["Concreto", "Madeira", "Metal", "Organico", "Misto"]
OFFENDER_OPTIONS = [
    None, None, None, None, None, None, None,  # 70% chance no offender
    "Veiculo identificado",
    "Pessoa flagrada",
    "Empresa identificada",
]


def is_processed(image_path: Path) -> bool:
    """Check if an image has already been processed."""
    if config.PROCESSED_STRATEGY == "marker":
        return image_path.with_suffix(".jpg.processed").exists()
    else:
        # "move" strategy: if it's in processed/ subdir, it was processed
        return "processed" in image_path.parts


def mark_processed(image_path: Path) -> None:
    """Mark an image as processed."""
    if config.PROCESSED_STRATEGY == "marker":
        marker = image_path.with_suffix(".jpg.processed")
        marker.touch()
    else:
        processed_dir = image_path.parent / "processed"
        processed_dir.mkdir(exist_ok=True)
        image_path.rename(processed_dir / image_path.name)


def parse_timestamp_from_filename(filename: str) -> datetime:
    """Extract timestamp from filename like '2026-02-08_14-30-00.jpg'."""
    name = filename.replace(".jpg", "")
    try:
        return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return datetime.utcnow()


def build_image_url(device_id: str, rel_path: str) -> str:
    """Build the public URL for an image."""
    base = config.PUBLIC_BASE_URL.rstrip("/")
    clean_path = rel_path.replace("\\", "/")
    return f"{base}/uploads/{clean_path}"


def generate_fake_detection(camera, image_path: Path, device_id: str) -> DetectionRecord:
    """Generate a fake detection with random AI fields."""
    # Extract relative path from UPLOAD_DIR for image_url
    try:
        rel_path = str(image_path.relative_to(config.UPLOAD_DIR))
    except ValueError:
        rel_path = f"{device_id}/{image_path.name}"

    return DetectionRecord(
        id=uuid4(),
        camera_id=camera.id,
        timestamp=parse_timestamp_from_filename(image_path.name),
        logradouro=camera.logradouro,
        bairro=camera.bairro,
        rpa=camera.rpa,
        latitude=camera.latitude,
        longitude=camera.longitude,
        waste_type=random.choice(WASTE_TYPES),
        material_type=random.choice(MATERIAL_TYPES),
        volume_m3=Decimal(str(round(random.uniform(0.1, 50.0), 2))),
        offenders=random.choice(OFFENDER_OPTIONS),
        status="PENDENTE",
        image_url=build_image_url(device_id, rel_path),
        confidence_score=Decimal(str(round(random.uniform(0.50, 0.99), 2))),
    )


def scan_and_process() -> int:
    """Scan upload directory for new images and process them. Returns count of processed images."""
    upload_dir = Path(config.UPLOAD_DIR)
    if not upload_dir.exists():
        logger.warning("Upload directory does not exist: %s", upload_dir)
        return 0

    count = 0
    for device_dir in sorted(upload_dir.iterdir()):
        if not device_dir.is_dir():
            continue
        device_id = device_dir.name
        if device_id in ("processed", "unknown_device"):
            continue

        camera = resolve_camera(device_id)
        if not camera:
            logger.debug("No camera found for device_id=%s, skipping", device_id)
            continue

        for jpg in sorted(device_dir.rglob("*.jpg")):
            if is_processed(jpg):
                continue

            if config.FAKE_MODE:
                detection = generate_fake_detection(camera, jpg, device_id)
            else:
                # TODO: Replace with real YOLO inference
                logger.warning("FAKE_MODE=false but real inference not implemented")
                continue

            if insert_detection(detection):
                mark_processed(jpg)
                count += 1
                logger.info(
                    "Processed: %s -> detection %s (%s, %.2f m3)",
                    jpg.name, detection.id, detection.waste_type, detection.volume_m3,
                )

    return count


def main():
    """Main entry point — polling loop."""
    logger.info("=" * 60)
    logger.info("SAIRA Worker starting (FAKE_MODE=%s)", config.FAKE_MODE)
    logger.info("UPLOAD_DIR=%s", config.UPLOAD_DIR)
    logger.info("DATABASE_URL=%s", config.DATABASE_URL.split("@")[-1])  # hide credentials
    logger.info("PUBLIC_BASE_URL=%s", config.PUBLIC_BASE_URL)
    logger.info("POLL_INTERVAL=%ds", config.POLL_INTERVAL)
    logger.info("=" * 60)

    while True:
        try:
            processed = scan_and_process()
            if processed:
                logger.info("Cycle complete: %d images processed", processed)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception:
            logger.exception("Error in scan cycle")

        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    main()
