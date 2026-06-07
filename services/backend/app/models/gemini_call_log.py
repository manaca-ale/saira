from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, DateTime, Date,
    Numeric, ForeignKey, Text, Computed, Index,
)
from app.core.database import Base


class GeminiCallLog(Base):
    __tablename__ = "gemini_call_log"
    __table_args__ = (
        Index("ix_gemini_call_log_date_camera", "call_date_brt", "camera_id"),
        Index("ix_gemini_call_log_date_agent", "call_date_brt", "agent"),
        Index("ix_gemini_call_log_called_at", "called_at"),
        Index("ix_gemini_call_log_request_id", "request_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    called_at = Column(DateTime(timezone=True), nullable=False)
    camera_id = Column(
        Integer,
        ForeignKey("cameras.id", ondelete="SET NULL"),
        nullable=True,
    )
    device_id = Column(String(64), nullable=True)
    agent = Column(String(16), nullable=False)
    model = Column(String(64), nullable=False)
    request_id = Column(String(64), nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Numeric(12, 8), nullable=False, default=0)
    latency_ms = Column(Integer, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)
    call_date_brt = Column(
        Date,
        Computed(
            "(called_at AT TIME ZONE 'America/Sao_Paulo')::date",
            persisted=True,
        ),
        nullable=False,
    )
