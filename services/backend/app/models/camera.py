from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric
from geoalchemy2 import Geometry
from app.core.database import Base
from app.core.timezone import now_brazil


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    device_id = Column(String(64), unique=True, index=True, nullable=True)
    logradouro = Column(String(255))
    bairro = Column(String(100))
    rpa = Column(String(10), index=True)
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    geom = Column(Geometry("POINT", srid=4326))
    rtsp_url = Column(String(512))
    capture_interval_seconds = Column(Integer, default=30)
    is_active = Column(Boolean, default=True, index=True)
    last_capture_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=now_brazil)
    updated_at = Column(DateTime(timezone=True), default=now_brazil, onupdate=now_brazil)
