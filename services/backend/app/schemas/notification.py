from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel
from app.models.notification import NotificationType


class NotificationResponse(BaseModel):
    id: UUID
    user_id: int
    detection_id: Optional[UUID] = None
    type: NotificationType
    title: str
    message: str
    metadata_: Optional[Dict[str, Any]] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse]
    unread_count: int
    total: int


class NotificationSummaryResponse(BaseModel):
    unread_count: int
    since_last_login: int
    last_login_at: Optional[datetime] = None
    by_rpa: Dict[str, int]
