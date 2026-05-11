"""One-shot script to shift all detection timestamps so the dataset ends at "now".

Use case: the seed (`seed_db.py`) generates detections for a fixed calendar window
(jan/2025 -> jan/2026). When the demo date moves forward, the History page (which
filters by the last 30 days) becomes empty. This script slides the entire dataset
forward by `delta = now() - max(timestamp)` without deleting rows, preserving IDs,
foreign keys (offender links, images, resolution metadata, etc).

Idempotent: re-running when max(timestamp) is already within 1 day of now is a no-op.

Usage:
    docker compose exec backend python shift_detection_timestamps.py
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import func, select, update

from app.core.database import AsyncSessionLocal
from app.core.timezone import now_brazil
from app.models.detection import Detection


async def shift_timestamps() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.max(Detection.timestamp)))
        current_max = result.scalar_one_or_none()

        if current_max is None:
            print("[shift] Nenhuma detecção encontrada — nada a fazer.")
            return

        now = now_brazil()
        delta = now - current_max

        print(f"[shift] max(timestamp) atual: {current_max.isoformat()}")
        print(f"[shift] now: {now.isoformat()}")
        print(f"[shift] delta calculado: {delta}")

        if delta < timedelta(days=1):
            print("[shift] delta < 1 dia — dataset já está atualizado, nada a fazer.")
            return

        count_result = await db.execute(select(func.count()).select_from(Detection))
        total = count_result.scalar_one()
        print(f"[shift] Atualizando {total} detecções...")

        await db.execute(
            update(Detection).values(
                timestamp=Detection.timestamp + delta,
                created_at=Detection.created_at + delta,
                updated_at=Detection.updated_at + delta,
            )
        )

        await db.execute(
            update(Detection)
            .where(Detection.resolved_at.isnot(None))
            .values(resolved_at=Detection.resolved_at + delta)
        )

        await db.execute(
            update(Detection)
            .where(Detection.analysis_started_at.isnot(None))
            .values(analysis_started_at=Detection.analysis_started_at + delta)
        )

        await db.commit()

        verify = await db.execute(select(func.max(Detection.timestamp)))
        new_max = verify.scalar_one()
        print(f"[shift] OK — novo max(timestamp): {new_max.isoformat()}")


if __name__ == "__main__":
    asyncio.run(shift_timestamps())
