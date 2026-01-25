from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from decimal import Decimal


class CameraBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    logradouro: Optional[str] = Field(None, max_length=255)
    bairro: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    latitude: Decimal
    longitude: Decimal
    rtsp_url: Optional[str] = Field(None, max_length=512)
    capture_interval_seconds: int = Field(default=30, ge=1)
    is_active: bool = True


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    logradouro: Optional[str] = Field(None, max_length=255)
    bairro: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    rtsp_url: Optional[str] = Field(None, max_length=512)
    capture_interval_seconds: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None


class CameraResponse(CameraBase):
    id: int
    last_capture_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
