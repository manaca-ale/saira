from sqlalchemy import Column, Integer, String, DateTime, Numeric, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from geoalchemy2 import Geometry
import uuid
import enum
from app.core.database import Base
from app.core.timezone import now_brazil


class DetectionStatus(str, enum.Enum):
    PENDENTE = "Pendente"
    CONFIRMADO = "Confirmado"
    REJEITADO = "Rejeitado"
    INDETERMINADO = "Indeterminado"


class Detection(Base):
    __tablename__ = "detections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"), index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    logradouro = Column(String(255))
    bairro = Column(String(100))
    rpa = Column(String(10), index=True)
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    geom = Column(Geometry("POINT", srid=4326))
    waste_type = Column(String(100))
    material_type = Column(String(100))
    volume_m3 = Column(Numeric(10, 2))
    offenders = Column(String(255))
    status = Column(Enum(DetectionStatus), default=DetectionStatus.PENDENTE, index=True)
    image_url = Column(String(512))
    confidence_score = Column(Numeric(3, 2))
    waste_bbox = Column(JSONB, nullable=True)
    classified_at = Column(DateTime(timezone=True), nullable=True)
    classified_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    validity_comment = Column(Text, nullable=True)
    # Evento de movimento no dispositivo (clipe de 2min correlacionado).
    # Preenchido pelo worker para dispositivos event-driven (Pi relay).
    event_ref = Column(String(64), nullable=True, index=True)
    video_status = Column(String(16), nullable=True)  # requested | available | unavailable
    video_requested_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now_brazil)
    updated_at = Column(DateTime(timezone=True), default=now_brazil, onupdate=now_brazil)
