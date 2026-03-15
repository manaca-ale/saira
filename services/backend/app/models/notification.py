import enum
import uuid
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text,
    ForeignKey, Enum, Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.timezone import now_brazil


class NotificationType(str, enum.Enum):
    NOVA_OCORRENCIA = "nova_ocorrencia"
    LOTE_OCORRENCIAS = "lote_ocorrencias"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "is_read", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    detection_id = Column(UUID(as_uuid=True), ForeignKey("detections.id", ondelete="SET NULL"), nullable=True)
    type = Column(
        Enum(
            NotificationType,
            name="notificationtype",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=True)
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), default=now_brazil)

    user = relationship("User", back_populates="notifications")
    detection = relationship("Detection")
