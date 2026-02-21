import asyncio
import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_db, get_current_user, get_current_user_from_query
from app.core.redis import get_redis
from app.models.user import User
from app.schemas.notification import (
    NotificationListResponse,
    NotificationResponse,
    NotificationSummaryResponse,
)
from app.services import notification_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    is_read: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista notificações do usuário autenticado."""
    items, unread_count, total = await notification_service.get_notifications(
        user_id=current_user.id, db=db, is_read=is_read, skip=skip, limit=limit,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(i) for i in items],
        unread_count=unread_count,
        total=total,
    )


@router.get("/summary", response_model=NotificationSummaryResponse)
async def get_notification_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resumo de notificações para banner pós-login."""
    data = await notification_service.get_summary(current_user, db)
    return NotificationSummaryResponse(**data)


@router.get("/stream")
async def notification_stream(
    current_user: User = Depends(get_current_user_from_query),
):
    """SSE stream de notificações em tempo real."""
    redis = get_redis()

    async def event_generator():
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"notifications:user:{current_user.id}", "notifications:all")
        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=29.0),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    message = None

                if message and message["type"] == "message":
                    yield {
                        "event": "new_detection",
                        "data": message["data"],
                    }
                else:
                    yield {"event": "heartbeat", "data": ""}
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return EventSourceResponse(event_generator())


@router.patch("/{notification_id}/read", response_model=dict)
async def mark_notification_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca uma notificação como lida."""
    found = await notification_service.mark_as_read(notification_id, current_user.id, db)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    await db.commit()
    return {"status": "ok"}


@router.patch("/read-all", response_model=dict)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca todas as notificações do usuário como lidas."""
    count = await notification_service.mark_all_as_read(current_user.id, db)
    await db.commit()
    return {"status": "ok", "count": count}
