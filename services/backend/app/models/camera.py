from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, Float
from sqlalchemy.dialects.postgresql import JSONB
from geoalchemy2 import Geometry
from app.core.database import Base
from app.core.timezone import now_brazil


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    device_id = Column(String(64), unique=True, index=True, nullable=True)
    # Família do hardware: 'esp32' | 'pi' | 'unknown'. Fonte da verdade das
    # capacidades (comando remoto, modo ao vivo). NULL = tipo desconhecido; ver
    # r9s0t1u2v3w4_add_camera_type.py para a semântica de fallback de cada
    # consumidor (remote-control faz fail-open, live faz fail-closed).
    camera_type = Column(String(32), nullable=True)
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
    # BGSUB pre-filter config (added 2026-05-23 — see docs/bgsub_prefilter.md):
    # pile_zone_polygon = list of polygons, each a list of [x,y] points (frame 1280x720)
    pile_zone_polygon = Column(JSONB, nullable=True)
    bgsub_calibrated_at = Column(DateTime(timezone=True), nullable=True)
    # Per-camera BGSUB tuning (added 2026-05-25). All NULL = use env defaults.
    bgsub_lr_fast = Column(Float, nullable=True)
    bgsub_lr_slow = Column(Float, nullable=True)
    bgsub_mog2_history_fast = Column(Integer, nullable=True)
    bgsub_mog2_history_slow = Column(Integer, nullable=True)
    bgsub_persistence_threshold = Column(Integer, nullable=True)
    bgsub_min_persistence_frames = Column(Float, nullable=True)
    bgsub_min_px_active = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=now_brazil)
    updated_at = Column(DateTime(timezone=True), default=now_brazil, onupdate=now_brazil)
