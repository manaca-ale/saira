"""Background maintenance for the image export feature.

Two recurring jobs:

- ``cleanup_expired_exports``: deletes S3 objects for exports whose presigned
  URL has expired and marks the row ``expired``. Runs every
  ``EXPORT_CLEANUP_INTERVAL_HOURS`` hours.
- ``recover_stale_exports``: re-dispatches exports stuck in ``pending`` or
  ``running`` for too long (worker restart, crash). Runs every 5 minutes.

Errors are logged but never propagate.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.timezone import now_brazil
from app.models.image_export import ImageExport
from app.services import image_export_runner, s3 as s3_service

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def cleanup_expired_exports() -> None:
    """Mark exports past their TTL as ``expired`` and delete the S3 object."""
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(ImageExport).where(
                ImageExport.status == "ready",
                ImageExport.expires_at != None,  # noqa: E711
                ImageExport.expires_at < now_brazil(),
            )
            rows = (await db.execute(stmt)).scalars().all()

            if not rows:
                return

            client = s3_service.get_s3_client() if s3_service.s3_enabled() else None
            for export in rows:
                if client and export.s3_key:
                    try:
                        s3_service.delete_object(client, export.s3_key)
                    except Exception:
                        logger.exception(
                            "cleanup_expired_exports: delete failed for %s",
                            export.s3_key,
                        )
                export.status = "expired"
                export.download_url = None
            await db.commit()
            logger.info("cleanup_expired_exports: %d exports expired", len(rows))
    except Exception:
        logger.exception("cleanup_expired_exports: unexpected error")


async def recover_stale_exports() -> None:
    """Re-dispatch exports stuck in ``pending``/``running`` for too long.

    Defensive: when uvicorn restarts mid-export, the in-memory asyncio task
    is lost but the row stays ``running``. Detect by ``updated_at`` and just
    fire ``run_export`` again — it's idempotent (S3 head/put handle dupes).
    """
    try:
        threshold = now_brazil() - timedelta(
            minutes=settings.EXPORT_STALE_RUNNING_MINUTES
        )
        async with AsyncSessionLocal() as db:
            stmt = select(ImageExport).where(
                ImageExport.status.in_(("pending", "running")),
                ImageExport.updated_at < threshold,
            )
            rows = (await db.execute(stmt)).scalars().all()

            if not rows:
                return
            ids = [r.id for r in rows]

        for export_id in ids:
            logger.info("recover_stale_exports: re-dispatching %s", export_id)
            image_export_runner.schedule_export(export_id)
    except Exception:
        logger.exception("recover_stale_exports: unexpected error")


def start_export_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        cleanup_expired_exports,
        trigger=IntervalTrigger(hours=settings.EXPORT_CLEANUP_INTERVAL_HOURS),
        id="image_exports_cleanup",
        name="Expire and delete old image exports",
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    _scheduler.add_job(
        recover_stale_exports,
        trigger=IntervalTrigger(minutes=5),
        id="image_exports_recover_stale",
        name="Re-dispatch stale image export jobs",
        coalesce=True,
        misfire_grace_time=600,
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "export_scheduler: started cleanup=%dh stale_recovery=5min",
        settings.EXPORT_CLEANUP_INTERVAL_HOURS,
    )


def stop_export_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("export_scheduler: error during shutdown")
    _scheduler = None
