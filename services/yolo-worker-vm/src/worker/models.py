"""Internal data models for the worker."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo


def _brasilia_now() -> datetime:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)


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
    id: UUID = field(default_factory=uuid4)


@dataclass
class GeminiUsage:
    """Token usage and cost telemetry for one Gemini request."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
