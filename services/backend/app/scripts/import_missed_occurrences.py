"""Import manually reviewed missed occurrences into the platform.

This script is intended for operational backfills: events from the Google Sheet
"Ocorrências Não Capturadas" that should appear in the platform like normal
detections, with S3-backed frames available through /analyzed-frames.

Run inside the backend container, for example:
  python -m app.scripts.import_missed_occurrences \
    --manifest /tmp/missed_manifest.json \
    --frames-root /tmp/missed_frames

IMPORTANTE — o índice de frames e o volume read-only:

Em produção o backend monta `WORKER_STATE_DIR` (/app/yolo_state) como READ-ONLY; quem
escreve nele é o worker. Como o índice `detection_frames/{id}.json` é o que alimenta
`/analyzed-frames`, sem ele a ocorrência aparece com um único frame.

Por isso o script agora VALIDA a gravabilidade do state dir ANTES de subir qualquer coisa
ao S3 (04/08/2026: a versão anterior subia os 38 frames, falhava ao gravar o índice e
deixava os objetos órfãos no bucket, com o banco em rollback).

No prod, aponte para um diretório gravável e depois publique o índice pelo worker, que
monta o mesmo volume em modo escrita:

  docker exec -e WORKER_STATE_DIR=/tmp/state saira-backend-prod \\
    python -m app.scripts.import_missed_occurrences --manifest ... --frames-root ...
  docker cp saira-backend-prod:/tmp/state/detection_frames/<id>.json /tmp/
  docker cp /tmp/<id>.json saira-yolo-worker-prod:/app/state/detection_frames/<id>.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.timezone import now_brazil
from app.models.camera import Camera
from app.models.detection import Detection, DetectionStatus
from app.services.s3 import get_s3_client, upload_file


BRASILIA = ZoneInfo("America/Sao_Paulo")
FRAME_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})")


@dataclass
class ImportedEvent:
    detection_id: str
    event_id: str
    timestamp: str
    action: str
    frame_count: int
    image_url: str | None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--frames-root", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--status",
        choices=["PENDENTE", "CONFIRMADO", "INDETERMINADO"],
        default="PENDENTE",
        help="Initial platform status for imported detections.",
    )
    parser.add_argument(
        "--s3-prefix",
        default="ocorrencias",
        help="Root S3 prefix. Defaults to the same prefix used by worker uploads.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help=(
            "Onde gravar o índice detection_frames/. Default: WORKER_STATE_DIR. "
            "Em prod esse volume é read-only no backend — use um path gravável e "
            "publique o índice pelo worker (ver docstring)."
        ),
    )
    return parser.parse_args()


def _ensure_state_dir_writable(state_dir: Path) -> Path:
    """Falha ANTES de qualquer upload se o índice não puder ser gravado.

    O índice é o que faz `/analyzed-frames` devolver a sequência inteira; sem ele a
    ocorrência aparece com um frame só. Descobrir isso depois do upload deixa objetos
    órfãos no S3 (o banco faz rollback, o bucket não).
    """
    frames_dir = state_dir / "detection_frames"
    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
        probe = frames_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise RuntimeError(
            f"não é possível gravar o índice em {frames_dir} ({exc.strerror}). "
            "Em produção o backend monta WORKER_STATE_DIR read-only: rode com "
            "-e WORKER_STATE_DIR=/tmp/state (ou --state-dir /tmp/state) e depois copie "
            "o JSON para o worker, que monta o volume em modo escrita."
        ) from exc
    return frames_dir


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("manifest must be a JSON array")
    return payload


def _parse_datetime(value: str) -> datetime:
    raw = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return datetime.strptime(raw, fmt).astimezone(BRASILIA)
        except ValueError:
            pass
    for fmt in ("%d/%m/%Y, %H:%M:%S", "%d/%m/%Y, %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=BRASILIA)
        except ValueError:
            pass
    # Google Sheet sometimes has non-zero-padded hours/minutes/seconds.
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4}),\s*(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?", raw)
    if match:
        day, month, year, hour, minute, second = match.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
            tzinfo=BRASILIA,
        )
    raise ValueError(f"unsupported datetime format: {value!r}")


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower().replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _public_s3_url(key: str) -> str:
    region = settings.S3_REGION
    bucket = settings.S3_BUCKET_NAME
    if region == "us-east-1":
        return f"https://{bucket}.s3.amazonaws.com/{key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def _frame_timestamp(path: Path) -> datetime | None:
    match = FRAME_TS_RE.search(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M-%S").replace(tzinfo=BRASILIA)
    except ValueError:
        return None


def _select_default_frame(frames: list[Path], event_ts: datetime) -> Path:
    dated = [(abs((ts - event_ts).total_seconds()), frame) for frame in frames if (ts := _frame_timestamp(frame))]
    if dated:
        return min(dated, key=lambda item: (item[0], item[1].name))[1]
    return frames[0]


def _resolve_frames(root: Path, event: dict[str, Any]) -> list[Path]:
    event_id = str(event["event_id"]).strip()
    frame_dir = root / event_id
    if not frame_dir.exists():
        frame_dir = root / str(event.get("frames_dir") or "").strip()
    if not frame_dir.exists():
        raise FileNotFoundError(f"frames directory not found for event {event_id}: {frame_dir}")
    frames = sorted(
        [p for p in frame_dir.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}],
        key=lambda p: p.name,
    )
    if not frames:
        raise FileNotFoundError(f"no frames found for event {event_id}: {frame_dir}")
    return frames


async def _find_camera(event: dict[str, Any]) -> Camera:
    device_id = str(event.get("device_id") or "").strip()
    camera_id = event.get("camera_id")
    async with AsyncSessionLocal() as db:
        query = select(Camera)
        if camera_id:
            query = query.where(Camera.id == int(camera_id))
        elif device_id:
            query = query.where(Camera.device_id == device_id)
        else:
            raise ValueError(f"event {event.get('event_id')} needs camera_id or device_id")
        camera = (await db.execute(query)).scalar_one_or_none()
        if camera is None:
            raise RuntimeError(f"camera not found for event {event.get('event_id')}")
        return camera


async def _import_event(
    event: dict[str, Any],
    *,
    frames_root: Path,
    s3_client,
    s3_prefix: str,
    status: DetectionStatus,
    dry_run: bool,
    frames_index_dir: Path,
) -> ImportedEvent:
    event_id = str(event["event_id"]).strip()
    event_ts = _parse_datetime(str(event["timestamp"]))
    camera = await _find_camera(event)
    device_id = str(event.get("device_id") or camera.device_id or f"camera-{camera.id}")
    frames = _resolve_frames(frames_root, event)
    default_frame = _select_default_frame(frames, event_ts)

    date_prefix = event_ts.strftime("%Y/%m/%d")
    key_prefix = f"{s3_prefix.rstrip('/')}/{device_id}/{date_prefix}/manual-missed/{event_id}"
    frame_payload: list[dict[str, Any]] = []
    image_url: str | None = None

    if not dry_run:
        for frame in frames:
            key = f"{key_prefix}/{frame.name}"
            content_type = mimetypes.guess_type(frame.name)[0] or "image/jpeg"
            upload_file(s3_client, frame, key, content_type=content_type)
            url = _public_s3_url(key)
            if frame == default_frame:
                image_url = url
            frame_payload.append(
                {
                    "frame_name": frame.name,
                    "image_url": url,
                    "is_default": frame == default_frame,
                }
            )
    else:
        image_url = _public_s3_url(f"{key_prefix}/{default_frame.name}")
        frame_payload = [
            {
                "frame_name": frame.name,
                "image_url": _public_s3_url(f"{key_prefix}/{frame.name}"),
                "is_default": frame == default_frame,
            }
            for frame in frames
        ]

    latitude = _decimal_or_none(event.get("latitude")) or camera.latitude
    longitude = _decimal_or_none(event.get("longitude")) or camera.longitude
    if latitude is None or longitude is None:
        raise ValueError(f"event {event_id} has no coordinates and camera lacks coordinates")

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(Detection).where(
                    Detection.camera_id == camera.id,
                    Detection.timestamp == event_ts,
                )
            )
        ).scalar_one_or_none()

        action = "updated"
        detection = existing
        if detection is None:
            action = "created"
            detection = Detection(
                camera_id=camera.id,
                timestamp=event_ts,
                logradouro=event.get("logradouro") or camera.logradouro,
                bairro=event.get("bairro") or camera.bairro,
                rpa=event.get("rpa") or camera.rpa,
                latitude=latitude,
                longitude=longitude,
                geom=from_shape(Point(float(longitude), float(latitude)), srid=4326),
                waste_type=event.get("waste_type") or event.get("tipo_residuo"),
                material_type=event.get("material_type") or "Misto",
                volume_m3=_decimal_or_none(event.get("volume_m3") or event.get("volumetria")),
                offenders=event.get("offenders"),
                status=status,
                image_url=image_url,
                confidence_score=_decimal_or_none(event.get("confidence_score")) or Decimal("0.95"),
            )
            db.add(detection)
            await db.flush()
        else:
            detection.image_url = image_url or detection.image_url
            detection.status = detection.status or status
            detection.updated_at = now_brazil()

        detection_id = str(detection.id)
        index = {
            "detection_id": detection_id,
            "device_id": device_id,
            "selected_frame_name": default_frame.name,
            "evidence_summary": event.get("justificativa") or event.get("evidence_summary"),
            "frames": frame_payload,
            "created_at": now_brazil().isoformat(),
            "updated_at": now_brazil().isoformat(),
            "source": {
                "kind": "manual_missed_import",
                "event_id": event_id,
                "source_sheet": event.get("source_sheet") or "Ocorrências Não Capturadas",
                "source_sheet_row": event.get("source_sheet_row"),
            },
        }

        if not dry_run:
            (frames_index_dir / f"{detection_id}.json").write_text(
                json.dumps(index, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            await db.commit()
        else:
            await db.rollback()

        return ImportedEvent(
            detection_id=detection_id,
            event_id=event_id,
            timestamp=event_ts.isoformat(),
            action="dry_run" if dry_run else action,
            frame_count=len(frame_payload),
            image_url=image_url,
        )


async def _main() -> None:
    args = _parse_args()
    if not settings.S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME is required")

    events = _load_manifest(args.manifest)
    # ANTES do S3: se o índice não puder ser gravado, falhar aqui evita subir frames que
    # ficariam órfãos no bucket (o banco faz rollback, o S3 não).
    state_dir = args.state_dir or Path(settings.WORKER_STATE_DIR)
    frames_index_dir = _ensure_state_dir_writable(state_dir)

    s3_client = get_s3_client()
    status = DetectionStatus[args.status]
    imported: list[ImportedEvent] = []
    for event in events:
        imported.append(
            await _import_event(
                event,
                frames_root=args.frames_root,
                s3_client=s3_client,
                s3_prefix=args.s3_prefix,
                status=status,
                dry_run=args.dry_run,
                frames_index_dir=frames_index_dir,
            )
        )

    print(json.dumps([item.__dict__ for item in imported], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
