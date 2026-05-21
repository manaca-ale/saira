from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.core.database import Base
from app.core.timezone import now_brazil


class ImageExport(Base):
    __tablename__ = "image_exports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    camera_id = Column(
        Integer,
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True), nullable=False)
    include_occurrences = Column(Boolean, nullable=False, default=True)
    include_non_occurrences = Column(Boolean, nullable=False, default=True)
    # pending | running | ready | failed | expired
    status = Column(String(16), nullable=False, default="pending", index=True)
    progress = Column(Integer, nullable=False, default=0)  # 0-100
    total_images = Column(Integer, nullable=True)
    s3_key = Column(String(512), nullable=True)
    download_url = Column(String(2048), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now_brazil, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=now_brazil,
        onupdate=now_brazil,
        nullable=False,
    )

    camera = relationship("Camera", lazy="joined")
    user = relationship("User", lazy="joined")
