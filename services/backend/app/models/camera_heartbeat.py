from sqlalchemy import (
    Column, BigInteger, Integer, String, Boolean, DateTime, Date,
    ForeignKey, Computed, Index,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class CameraHeartbeat(Base):
    """Snapshot periódico de conectividade por câmera.

    Uma linha por câmera por varredura do offline_monitor (a cada
    CAMERA_OFFLINE_CHECK_INTERVAL_MINUTES). `is_online` = a câmera enviou
    imagem dentro do threshold. É a série temporal que alimenta o indicador
    I1 (Confiabilidade da vigilância): uptime% = online_checks / total_checks
    no período, por câmera; média dos pontos e pior ponto.

    `health` guarda o .health.json que o dispositivo reportou naquele ciclo
    (só os event-driven mandam; nos demais fica NULL). Existe por causa da queda
    de 08→09/09/2026 na pi-cam-001: o arquivo é sobrescrito a cada keepalive, e
    a investigação ficou com UMA amostra de `throttled` — um bitmask
    "desde o boot", que não distingue um pico no religamento de subtensão
    crônica. Sem série temporal não dá para responder se um sintoma piorou.
    """

    __tablename__ = "camera_heartbeats"
    __table_args__ = (
        Index("ix_camera_heartbeats_camera_checked", "camera_id", "checked_at"),
        Index("ix_camera_heartbeats_date", "check_date_brt"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    checked_at = Column(DateTime(timezone=True), nullable=False)
    camera_id = Column(
        Integer,
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id = Column(String(64), nullable=True)
    is_online = Column(Boolean, nullable=False)
    health = Column(JSONB, nullable=True)
    check_date_brt = Column(
        Date,
        Computed(
            "(checked_at AT TIME ZONE 'America/Sao_Paulo')::date",
            persisted=True,
        ),
        nullable=False,
    )
