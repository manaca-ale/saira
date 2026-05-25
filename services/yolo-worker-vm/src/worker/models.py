"""Internal data models for the worker."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo


def _brasilia_now() -> datetime:
    return datetime.now(ZoneInfo("America/Sao_Paulo"))


@dataclass
class CameraInfo:
    """Camera record from the database."""

    id: int
    name: str
    device_id: Optional[str]
    logradouro: Optional[str]
    bairro: Optional[str]
    rpa: Optional[str]
    latitude: Optional[Decimal]
    longitude: Optional[Decimal]
    # BGSUB pre-filter config (added 2026-05-23). Both None when not configured.
    pile_zone_polygon: Optional[object] = None  # JSONB → list[list[list[int]]]
    bgsub_calibrated_at: Optional[datetime] = None
    # Per-camera BGSUB tuning (added 2026-05-25). All None = fall back to env globals.
    bgsub_lr_fast: Optional[float] = None
    bgsub_lr_slow: Optional[float] = None
    bgsub_mog2_history_fast: Optional[int] = None
    bgsub_mog2_history_slow: Optional[int] = None
    bgsub_persistence_threshold: Optional[int] = None
    bgsub_min_persistence_frames: Optional[float] = None
    bgsub_min_px_active: Optional[int] = None


@dataclass
class DetectionRecord:
    """A detection row to be inserted into the detections table."""

    id: UUID = field(default_factory=uuid4)
    camera_id: Optional[int] = None
    timestamp: datetime = field(default_factory=_brasilia_now)
    logradouro: Optional[str] = None
    bairro: Optional[str] = None
    rpa: Optional[str] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    waste_type: Optional[str] = None
    material_type: Optional[str] = None
    volume_m3: Optional[Decimal] = None
    offenders: Optional[str] = None
    status: str = "PENDENTE"
    image_url: Optional[str] = None
    confidence_score: Optional[Decimal] = None
    waste_bbox: Optional[list] = None
    agent1_request_id: Optional[str] = None
    agent2_request_id: Optional[str] = None
    agent1_confidence: Optional[int] = None


@dataclass
class OffenderRecord:
    """A detection_offenders row (one per detected person/vehicle)."""

    detection_id: UUID
    offender_type: str  # Carroca | Carro | Moto | Pessoa | Outro
    plate: Optional[str] = None
    vehicle_color: Optional[str] = None
    waste_type: Optional[str] = None
    estimated_volume_m3: Optional[Decimal] = None
    confidence_score: Optional[Decimal] = None
    notes: Optional[str] = None
    offender_bbox: Optional[list] = None
    id: UUID = field(default_factory=uuid4)


@dataclass
class GeminiUsage:
    """Token usage and cost telemetry for one Gemini request."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
