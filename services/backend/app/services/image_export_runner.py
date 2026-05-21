"""Async runner that builds image export ZIPs.

Each ``ImageExport`` row triggered by ``POST /api/v1/exports`` is processed here:

1. Resolve fontes por dia: local uploads (``ocorrencias/`` and ``sem_ocorrencia/``)
   + S3 (``ocorrencias/`` flat keys e ``descartadas/`` daily zip).
2. Filtra arquivos pelo nome (``YYYY-MM-DD_HH-MM-SS.jpg``) para respeitar a
   janela horária dentro de cada dia.
3. Empacota tudo num único ZIP estruturado por dia / tipo, faz upload pro S3,
   gera presigned URL com TTL configurável e atualiza o status no DB.
4. Limpa qualquer arquivo temporário em disco mesmo em caso de erro.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Iterator, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.timezone import now_brazil
from app.models.camera import Camera
from app.models.image_export import ImageExport
from app.services import s3 as s3_service

logger = logging.getLogger(__name__)
BRT = ZoneInfo("America/Sao_Paulo")

# ESP32 file naming: 2026-05-20_14-37-22.jpg
_FILENAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _uploads_root() -> Path:
    return Path(settings.EXPORT_UPLOADS_DIR)


def _iter_days_brt(start_at: datetime, end_at: datetime) -> Iterator[date]:
    """Yield every BRT calendar date that the [start_at, end_at] window touches."""
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=BRT)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=BRT)
    start_day = start_at.astimezone(BRT).date()
    end_day = end_at.astimezone(BRT).date()
    cur = start_day
    while cur <= end_day:
        yield cur
        cur = cur + timedelta(days=1)


def _filename_in_window(
    filename: str,
    start_at: datetime,
    end_at: datetime,
) -> bool:
    """Parse YYYY-MM-DD_HH-MM-SS.jpg and check it falls inside the window.

    Files whose names don't match the expected pattern are included by default
    (better to over-collect than to silently drop frames).
    """
    m = _FILENAME_RE.match(filename)
    if not m:
        return True
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    try:
        ts = datetime(y, mo, d, h, mi, s, tzinfo=BRT)
    except ValueError:
        return True
    return start_at <= ts <= end_at


def _local_occurrences(device_id: str, day: date) -> list[Path]:
    base = _uploads_root() / device_id / "ocorrencias" / day.strftime("%Y/%m/%d")
    return sorted(base.glob("*.jpg")) if base.exists() else []


def _local_non_occurrences(device_id: str, day: date) -> list[Path]:
    base = _uploads_root() / device_id / "sem_ocorrencia" / day.strftime("%Y/%m/%d")
    return sorted(base.glob("*.jpg")) if base.exists() else []


def _local_unprocessed(device_id: str, day: date) -> list[Path]:
    """Files that the worker still hasn't classified (today's recent uploads).

    Listed under {device_id}/YYYY/MM/DD/*.jpg without the ocorrencias/ or
    sem_ocorrencia/ prefix. We include them only when caller asked for
    non-occurrences (since they're, by definition, not detections — they may
    become occurrences later, but at the moment we know nothing about them).
    """
    base = _uploads_root() / device_id / day.strftime("%Y/%m/%d")
    return sorted(base.glob("*.jpg")) if base.exists() else []


# ------------------------------------------------------------------
# Core
# ------------------------------------------------------------------

def _build_zip(
    export: ImageExport,
    device_id: str,
    tmp_dir: Path,
    progress_cb,
) -> tuple[Path, dict]:
    """Synchronous heavy work — called inside ``asyncio.to_thread``."""
    zip_path = tmp_dir / f"export_{export.id}.zip"
    manifest = {
        "export_id": str(export.id),
        "camera_id": export.camera_id,
        "camera_device_id": device_id,
        "start_at": export.start_at.isoformat(),
        "end_at": export.end_at.isoformat(),
        "include_occurrences": export.include_occurrences,
        "include_non_occurrences": export.include_non_occurrences,
        "days": {},
        "total_images": 0,
    }

    client = s3_service.get_s3_client() if s3_service.s3_enabled() else None
    s3_workdir = tmp_dir / "s3"
    s3_workdir.mkdir(parents=True, exist_ok=True)

    days = list(_iter_days_brt(export.start_at, export.end_at))
    total_days = max(len(days), 1)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, day in enumerate(days):
            day_str = day.isoformat()
            day_stats = {"ocorrencias": 0, "sem_ocorrencia": 0}

            if export.include_occurrences:
                seen: set[str] = set()
                for src in _local_occurrences(device_id, day):
                    if not _filename_in_window(src.name, export.start_at, export.end_at):
                        continue
                    if src.name in seen:
                        continue
                    zf.write(src, arcname=f"{day_str}/ocorrencias/{src.name}")
                    seen.add(src.name)
                    day_stats["ocorrencias"] += 1

                if client is not None:
                    prefix = s3_service.occurrence_prefix(device_id, day)
                    try:
                        keys = s3_service.list_keys(client, prefix)
                    except Exception:
                        logger.exception(
                            "S3 list failed for prefix %s (export %s)", prefix, export.id,
                        )
                        keys = []
                    for key in keys:
                        name = Path(key).name
                        if not name.lower().endswith(".jpg"):
                            continue
                        if not _filename_in_window(name, export.start_at, export.end_at):
                            continue
                        if name in seen:
                            continue
                        dest = s3_workdir / "occ" / day_str / name
                        try:
                            s3_service.download_object(client, key, dest)
                        except Exception:
                            logger.exception(
                                "S3 download failed key=%s (export %s)", key, export.id,
                            )
                            continue
                        zf.write(dest, arcname=f"{day_str}/ocorrencias/{name}")
                        seen.add(name)
                        day_stats["ocorrencias"] += 1
                        dest.unlink(missing_ok=True)

            if export.include_non_occurrences:
                seen_no: set[str] = set()
                # 1. Local classificado como sem_ocorrencia
                for src in _local_non_occurrences(device_id, day):
                    if not _filename_in_window(src.name, export.start_at, export.end_at):
                        continue
                    if src.name in seen_no:
                        continue
                    zf.write(src, arcname=f"{day_str}/sem_ocorrencia/{src.name}")
                    seen_no.add(src.name)
                    day_stats["sem_ocorrencia"] += 1

                # 2. Local ainda não processado (representa o "agora" — pode virar
                # ocorrência depois, mas ainda não é). Útil principalmente para
                # exportar o dia atual.
                for src in _local_unprocessed(device_id, day):
                    if not _filename_in_window(src.name, export.start_at, export.end_at):
                        continue
                    if src.name in seen_no:
                        continue
                    zf.write(src, arcname=f"{day_str}/sem_ocorrencia/{src.name}")
                    seen_no.add(src.name)
                    day_stats["sem_ocorrencia"] += 1

                # 3. S3 daily zip (descartadas/) — extrair e re-empacotar.
                if client is not None:
                    zip_key = s3_service.non_occurrence_zip_key(device_id, day)
                    if s3_service.head_object_exists(client, zip_key):
                        local_zip = s3_workdir / "no" / day_str / Path(zip_key).name
                        try:
                            s3_service.download_object(client, zip_key, local_zip)
                            with zipfile.ZipFile(local_zip) as inner:
                                for info in inner.infolist():
                                    name = Path(info.filename).name
                                    if not name.lower().endswith(".jpg"):
                                        continue
                                    if not _filename_in_window(
                                        name, export.start_at, export.end_at
                                    ):
                                        continue
                                    if name in seen_no:
                                        continue
                                    with inner.open(info) as src_file:
                                        data = src_file.read()
                                    zf.writestr(f"{day_str}/sem_ocorrencia/{name}", data)
                                    seen_no.add(name)
                                    day_stats["sem_ocorrencia"] += 1
                        except Exception:
                            logger.exception(
                                "Failed to process S3 daily zip %s (export %s)",
                                zip_key, export.id,
                            )
                        finally:
                            local_zip.unlink(missing_ok=True)

            manifest["days"][day_str] = day_stats
            manifest["total_images"] += day_stats["ocorrencias"] + day_stats["sem_ocorrencia"]

            pct = int(((idx + 1) / total_days) * 90)  # leave 10% for upload
            progress_cb(pct, manifest["total_images"])

        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    return zip_path, manifest


async def _persist_progress(export_id: UUID, *, progress: int, total_images: int) -> None:
    async with AsyncSessionLocal() as db:
        export = await db.get(ImageExport, export_id)
        if export is None:
            return
        export.progress = progress
        export.total_images = total_images
        db.add(export)
        await db.commit()


async def run_export(export_id: UUID) -> None:
    """Generate the ZIP for *export_id*, upload to S3 and update the row."""
    async with AsyncSessionLocal() as db:
        stmt = (
            select(ImageExport)
            .where(ImageExport.id == export_id)
            .options(selectinload(ImageExport.camera))
        )
        result = await db.execute(stmt)
        export = result.scalar_one_or_none()
        if export is None:
            logger.warning("run_export: export %s not found", export_id)
            return
        if export.status not in ("pending", "running"):
            logger.info(
                "run_export: export %s already in terminal state (%s) — skipping",
                export_id, export.status,
            )
            return
        if not export.camera or not export.camera.device_id:
            export.status = "failed"
            export.error_message = "Câmera sem device_id"
            export.completed_at = now_brazil()
            await db.commit()
            return

        device_id = export.camera.device_id
        user_id = export.user_id
        export.status = "running"
        export.started_at = now_brazil()
        export.error_message = None
        export.progress = 0
        await db.commit()

    if not s3_service.s3_enabled():
        async with AsyncSessionLocal() as db:
            export = await db.get(ImageExport, export_id)
            if export:
                export.status = "failed"
                export.error_message = "S3_BUCKET_NAME não configurado no backend"
                export.completed_at = now_brazil()
                await db.commit()
        return

    progress_state = {"pct": 0, "total": 0}

    def _progress_cb(pct: int, total: int) -> None:
        progress_state["pct"] = pct
        progress_state["total"] = total

    tmp_root: Optional[tempfile.TemporaryDirectory] = None
    try:
        tmp_root = tempfile.TemporaryDirectory(prefix="saira_export_")
        tmp_path = Path(tmp_root.name)

        # Re-fetch a detached snapshot to pass to the thread (avoids holding
        # the session across to_thread).
        async with AsyncSessionLocal() as db:
            stmt = (
                select(ImageExport)
                .where(ImageExport.id == export_id)
                .options(selectinload(ImageExport.camera))
            )
            export_snapshot = (await db.execute(stmt)).scalar_one()

        # Periodically push progress to the DB while build runs.
        stop_progress = asyncio.Event()

        async def _progress_pusher() -> None:
            while not stop_progress.is_set():
                try:
                    await _persist_progress(
                        export_id,
                        progress=progress_state["pct"],
                        total_images=progress_state["total"],
                    )
                except Exception:
                    logger.exception("Failed to persist progress for %s", export_id)
                try:
                    await asyncio.wait_for(stop_progress.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass

        pusher = asyncio.create_task(_progress_pusher())
        try:
            zip_path, manifest = await asyncio.to_thread(
                _build_zip, export_snapshot, device_id, tmp_path, _progress_cb,
            )
        finally:
            stop_progress.set()
            try:
                await pusher
            except Exception:
                pass

        # Upload + presign + finalize
        client = s3_service.get_s3_client()
        key = s3_service.export_key(user_id, str(export_id))
        await asyncio.to_thread(s3_service.upload_file, client, zip_path, key)
        url = s3_service.generate_presigned_url(client, key)

        async with AsyncSessionLocal() as db:
            export = await db.get(ImageExport, export_id)
            if export is None:
                return
            export.s3_key = key
            export.download_url = url
            export.expires_at = now_brazil() + timedelta(
                seconds=settings.EXPORT_PRESIGNED_TTL_SECONDS
            )
            export.status = "ready"
            export.progress = 100
            export.total_images = manifest.get("total_images", 0)
            export.completed_at = now_brazil()
            await db.commit()
        logger.info(
            "run_export: %s ready (total=%s)",
            export_id, manifest.get("total_images"),
        )
    except Exception as exc:
        logger.exception("run_export: failure for %s", export_id)
        async with AsyncSessionLocal() as db:
            export = await db.get(ImageExport, export_id)
            if export is not None:
                export.status = "failed"
                export.error_message = str(exc)[:1000]
                export.completed_at = now_brazil()
                await db.commit()
    finally:
        if tmp_root is not None:
            tmp_root.cleanup()


def schedule_export(export_id: UUID) -> None:
    """Fire-and-forget: dispatch ``run_export`` on the running event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (e.g. cron sweep from a non-async context).
        # Run synchronously in a new loop.
        asyncio.run(run_export(export_id))
        return
    loop.create_task(run_export(export_id))
