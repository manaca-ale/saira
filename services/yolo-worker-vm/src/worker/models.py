"""Internal data models for the worker."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4


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
    """A detection to be inserted into the database."""
    id: UUID = field(default_factory=uuid4)
    camera_id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
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
