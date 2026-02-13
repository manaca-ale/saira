from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from decimal import Decimal
from uuid import UUID
from enum import Enum


class DetectionStatus(str, Enum):
    PENDENTE = "Pendente"
    EM_ANALISE = "Em analise"
    RESOLVIDO = "Resolvido"


class DetectionBase(BaseModel):
    camera_id: Optional[int] = None
    timestamp: datetime
    logradouro: Optional[str] = Field(None, max_length=255)
    bairro: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    latitude: Decimal
    longitude: Decimal
    waste_type: Optional[str] = Field(None, max_length=100)
    material_type: Optional[str] = Field(None, max_length=100)
    volume_m3: Optional[Decimal] = None
    offenders: Optional[str] = Field(None, max_length=255)
    status: DetectionStatus = DetectionStatus.PENDENTE
    image_url: Optional[str] = Field(None, max_length=512)
    confidence_score: Optional[Decimal] = Field(None, ge=0, le=1)


class DetectionCreate(DetectionBase):
    pass


class DetectionUpdate(BaseModel):
    status: Optional[DetectionStatus] = None
    offenders: Optional[str] = Field(None, max_length=255)
    waste_type: Optional[str] = Field(None, max_length=100)
    material_type: Optional[str] = Field(None, max_length=100)
    volume_m3: Optional[Decimal] = None


class DetectionResolve(BaseModel):
    resolved_at: datetime
    forwarded_to_sector: str = Field(..., max_length=100)
    resolution_justification: str = Field(..., max_length=400)


class DetectionStartAnalysis(BaseModel):
    pass


class DetectionResponse(DetectionBase):
    id: UUID
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = None
    resolution_justification: Optional[str] = None
    forwarded_to_sector: Optional[str] = None
    analysis_started_at: Optional[datetime] = None
    analysis_started_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
