from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from decimal import Decimal
from app.models.offender import OffenderType, OffenderSource


# ── Offender (profile) CRUD ──────────────────────────────────────────

class OffenderCreate(BaseModel):
    name: Optional[str] = None
    type: OffenderType
    plate: Optional[str] = Field(None, max_length=20)
    vehicle_color: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None


class OffenderUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[OffenderType] = None
    plate: Optional[str] = Field(None, max_length=20)
    vehicle_color: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class OffenderResponse(BaseModel):
    id: UUID
    name: Optional[str] = None
    type: OffenderType
    plate: Optional[str] = None
    vehicle_color: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    sighting_count: int = 0
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── DetectionOffender (sighting) ─────────────────────────────────────

class DetectionOffenderCreate(BaseModel):
    offender_id: Optional[UUID] = None
    offender_type: OffenderType
    plate: Optional[str] = Field(None, max_length=20)
    vehicle_color: Optional[str] = Field(None, max_length=50)
    waste_type: Optional[str] = Field(None, max_length=100)
    estimated_volume_m3: Optional[Decimal] = None
    notes: Optional[str] = None


class DetectionOffenderUpdate(BaseModel):
    offender_id: Optional[UUID] = None
    offender_type: Optional[OffenderType] = None
    plate: Optional[str] = Field(None, max_length=20)
    vehicle_color: Optional[str] = Field(None, max_length=50)
    waste_type: Optional[str] = Field(None, max_length=100)
    estimated_volume_m3: Optional[Decimal] = None
    notes: Optional[str] = None


class DetectionOffenderResponse(BaseModel):
    id: UUID
    detection_id: UUID
    offender_id: Optional[UUID] = None
    offender_type: OffenderType
    plate: Optional[str] = None
    vehicle_color: Optional[str] = None
    waste_type: Optional[str] = None
    estimated_volume_m3: Optional[Decimal] = None
    source: OffenderSource
    confidence_score: Optional[Decimal] = None
    offender_bbox: Optional[List[int]] = None
    created_by: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime
    offender: Optional[OffenderResponse] = None

    class Config:
        from_attributes = True


# ── Dashboard aggregation responses ──────────────────────────────────

class OffenderStatsResponse(BaseModel):
    total_offenders: int
    recurrent_offenders: int
    high_recurrence: int
    identified_plates: int
    estimated_volume_m3: float


class OffendersByTypeResponse(BaseModel):
    type: str
    count: int
    percentage: float


class RecidivismByTypeResponse(BaseModel):
    type: str
    recurrent_count: int


class OffenderVolumeByTypeResponse(BaseModel):
    type: str
    total_volume_m3: float


class WasteBreakdownItem(BaseModel):
    waste_type: str
    count: int


class WasteByOffenderTypeResponse(BaseModel):
    offender_type: str
    waste_breakdown: List[WasteBreakdownItem]


class TopPlateResponse(BaseModel):
    plate: str
    occurrences: int


class VehicleColorResponse(BaseModel):
    color: str
    count: int
    percentage: float
