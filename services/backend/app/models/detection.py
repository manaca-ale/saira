from sqlalchemy import Column, Integer, String, DateTime, Numeric, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from geoalchemy2 import Geometry
import uuid
import enum
from app.core.database import Base


class DetectionStatus(str, enum.Enum):
    PENDENTE = "Pendente"
    EM_ANALISE = "Em análise"
    RESOLVIDO = "Resolvido"


class Detection(Base):
    __tablename__ = "detections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"), index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
