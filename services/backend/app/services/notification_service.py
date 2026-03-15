import json
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.detection import Detection
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


def _as_naive_utc(value: datetime) -> datetime:
    """Normalize datetimes to naive UTC for DB columns stored without timezone."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _format_rpa_label(raw_rpa: str | None) -> str:
    value = (raw_rpa or "").strip()
    if not value:
        return "RPA ?"
    if value.lower().startswith("rpa"):
        return value
    return f"RPA {value}"


async def on_new_detection(
    detection: Detection,
    db: AsyncSession,
    redis: aioredis.Redis,
) -> None:
    """Called after a new detection is created. Creates notifications for all active users
    and publishes to Redis for SSE delivery."""
    result = await db.execute(select(User).where(User.is_active == True))
    active_users = result.scalars().all()
    whatsapp_service = WhatsAppService()
    users = [
        user for user in active_users
        if whatsapp_service.is_same_rpa(user.rpa, detection.rpa)
    ]

    if not users:
        return

    notifications = []
    rpa_label = _format_rpa_label(detection.rpa)
    for user in users:
        notif = Notification(
            user_id=user.id,
            detection_id=detection.id,
            type=NotificationType.NOVA_OCORRENCIA,
            title=f"Nova ocorrência - {rpa_label}",
            message=f"{detection.logradouro or ''}, {detection.bairro or ''}".strip(", "),
            metadata_={
                "rpa": detection.rpa,
                "detection_id": str(detection.id),
                "bairro": detection.bairro,
                "timestamp": detection.timestamp.isoformat() if detection.timestamp else None,
            },
        )
        notifications.append(notif)
    db.add_all(notifications)
    await db.flush()

    # Publish to Redis for each user (SSE listeners)
    event_data = json.dumps({
        "type": "new_detection",
        "title": f"Nova ocorrência - {rpa_label}",
        "message": f"{detection.logradouro or ''}, {detection.bairro or ''}".strip(", "),
        "detection_id": str(detection.id),
        "metadata": {
            "rpa": detection.rpa,
            "detection_id": str(detection.id),
            "bairro": detection.bairro,
            "timestamp": detection.timestamp.isoformat() if detection.timestamp else None,
        },
    })

    try:
        # Publish to per-user channels
        for user in users:
            await redis.publish(f"notifications:user:{user.id}", event_data)
        # Publish to global channel
        await redis.publish("notifications:all", event_data)
    except Exception:
        logger.exception("Failed to publish notification to Redis")

    # Dispatch WhatsApp alerts (non-blocking wrt DB writes, guarded against failures).
    try:
        delivered = await asyncio.to_thread(
            whatsapp_service.send_occurrence_alert, users, detection
        )
        logger.info(
            "WhatsApp alerts delivered for detection %s: %s",
            detection.id,
            delivered,
        )
    except Exception:
        logger.exception("Failed to send WhatsApp alerts for detection %s", detection.id)


async def get_notifications(
    user_id: int,
    db: AsyncSession,
    is_read: bool | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[Notification], int, int]:
    """Returns (items, unread_count, total) for a user."""
    query = select(Notification).where(Notification.user_id == user_id)
    if is_read is not None:
        query = query.where(Notification.is_read == is_read)

    # Total matching
    count_q = select(func.count(Notification.id)).where(Notification.user_id == user_id)
    if is_read is not None:
        count_q = count_q.where(Notification.is_read == is_read)
    total = (await db.execute(count_q)).scalar() or 0

    # Unread count (always)
    unread = (await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read == False,
        )
    )).scalar() or 0

    # Paginated items
    query = query.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
    items = (await db.execute(query)).scalars().all()

    return list(items), unread, total


async def get_summary(user: User, db: AsyncSession) -> dict:
    """Returns notification summary for login banner."""
    unread = (await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.is_read == False,
        )
    )).scalar() or 0

    # Count detections since last login
    if user.last_login_at:
        cutoff = _as_naive_utc(user.last_login_at)
        since_q = select(func.count(Detection.id)).where(
            Detection.timestamp > cutoff
        )
    else:
        # No last login: count last 24h
        cutoff = datetime.utcnow() - timedelta(hours=24)
        since_q = select(func.count(Detection.id)).where(
            Detection.timestamp > cutoff
        )
    since_last_login = (await db.execute(since_q)).scalar() or 0

    # Count by RPA since last login
    by_rpa_q = (
        select(Detection.rpa, func.count(Detection.id))
        .where(Detection.timestamp > cutoff)
        .group_by(Detection.rpa)
    )
    by_rpa_rows = (await db.execute(by_rpa_q)).all()
    by_rpa = {row[0] or "?": row[1] for row in by_rpa_rows}

    return {
        "unread_count": unread,
        "since_last_login": since_last_login,
        "last_login_at": user.last_login_at,
        "by_rpa": by_rpa,
    }


async def mark_as_read(notification_id: UUID, user_id: int, db: AsyncSession) -> bool:
    """Mark a single notification as read. Returns True if found."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        return False
    notif.is_read = True
    return True


async def mark_all_as_read(user_id: int, db: AsyncSession) -> int:
    """Mark all notifications as read. Returns count updated."""
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read == False)
        .values(is_read=True)
    )
    return result.rowcount
