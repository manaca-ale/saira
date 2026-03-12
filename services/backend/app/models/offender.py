import enum
import uuid
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, Numeric,
    ForeignKey, Enum, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.timezone import now_brazil_naive


class OffenderType(str, enum.Enum):
    CARROCA = "Carroca"
    CARRO = "Carro"
    MOTO = "Moto"
    PESSOA = "Pessoa"
    OUTRO = "Outro"


class OffenderSource(str, enum.Enum):
    AI = "ai"
    MANUAL = "manual"


class Offender(Base):
    __tablename__ = "offenders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=True)
    type = Column(
        Enum(
            OffenderType,
            name="offendertype",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    plate = Column(String(20), nullable=True, index=True)
    vehicle_color = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=now_brazil_naive)
    updated_at = Column(DateTime, default=now_brazil_naive, onupdate=now_brazil_naive)

    sightings = relationship("DetectionOffender", back_populates="offender")


class DetectionOffender(Base):
    __tablename__ = "detection_offenders"
    __table_args__ = (
        Index("ix_detection_offenders_plate_detection", "plate", "detection_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    detection_id = Column(UUID(as_uuid=True), ForeignKey("detections.id", ondelete="CASCADE"), nullable=False, index=True)
    offender_id = Column(UUID(as_uuid=True), ForeignKey("offenders.id", ondelete="SET NULL"), nullable=True, index=True)
    offender_type = Column(
        Enum(
            OffenderType,
            name="offendertype",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            create_type=False,
        ),
        nullable=False,
    )
    plate = Column(String(20), nullable=True, index=True)
    vehicle_color = Column(String(50), nullable=True)
    waste_type = Column(String(100), nullable=True)
    estimated_volume_m3 = Column(Numeric(10, 2), nullable=True)
    source = Column(
        Enum(
            OffenderSource,
            name="offendersource",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    confidence_score = Column(Numeric(3, 2), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now_brazil_naive)

    detection = relationship("Detection")
    offender = relationship("Offender", back_populates="sightings")
