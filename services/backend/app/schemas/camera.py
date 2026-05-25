from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from decimal import Decimal


# Polygon = list of [x, y] points. pile_zone_polygon = list of polygons.
PileZonePolygon = list[list[list[int]]]


class CameraBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    device_id: Optional[str] = Field(None, max_length=64)
    logradouro: Optional[str] = Field(None, max_length=255)
    bairro: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    latitude: Decimal
    longitude: Decimal
    rtsp_url: Optional[str] = Field(None, max_length=512)
    capture_interval_seconds: int = Field(default=30, ge=1)
    is_active: bool = True
    pile_zone_polygon: Optional[PileZonePolygon] = None
    bgsub_calibrated_at: Optional[datetime] = None
    # Per-camera BGSUB tuning overrides — NULL = fall back to env globals.
    bgsub_lr_fast: Optional[float] = Field(None, ge=0.0, le=1.0)
    bgsub_lr_slow: Optional[float] = Field(None, ge=0.0, le=1.0)
    bgsub_mog2_history_fast: Optional[int] = Field(None, ge=1, le=10000)
    bgsub_mog2_history_slow: Optional[int] = Field(None, ge=1, le=10000)
    bgsub_persistence_threshold: Optional[int] = Field(None, ge=0)
    bgsub_min_persistence_frames: Optional[float] = Field(None, ge=0.0, le=1.0)
    bgsub_min_px_active: Optional[int] = Field(None, ge=0)


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    device_id: Optional[str] = Field(None, max_length=64)
    logradouro: Optional[str] = Field(None, max_length=255)
    bairro: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    rtsp_url: Optional[str] = Field(None, max_length=512)
    capture_interval_seconds: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    pile_zone_polygon: Optional[PileZonePolygon] = None
    bgsub_calibrated_at: Optional[datetime] = None
    bgsub_lr_fast: Optional[float] = Field(None, ge=0.0, le=1.0)
    bgsub_lr_slow: Optional[float] = Field(None, ge=0.0, le=1.0)
    bgsub_mog2_history_fast: Optional[int] = Field(None, ge=1, le=10000)
    bgsub_mog2_history_slow: Optional[int] = Field(None, ge=1, le=10000)
    bgsub_persistence_threshold: Optional[int] = Field(None, ge=0)
    bgsub_min_persistence_frames: Optional[float] = Field(None, ge=0.0, le=1.0)
    bgsub_min_px_active: Optional[int] = Field(None, ge=0)


class CameraBgsubConfigUpdate(BaseModel):
    """Subset for PATCH /api/v1/cameras/{id}/bgsub_config — BGSUB tuning only."""

    bgsub_lr_fast: Optional[float] = Field(None, ge=0.0, le=1.0)
    bgsub_lr_slow: Optional[float] = Field(None, ge=0.0, le=1.0)
    bgsub_mog2_history_fast: Optional[int] = Field(None, ge=1, le=10000)
    bgsub_mog2_history_slow: Optional[int] = Field(None, ge=1, le=10000)
    bgsub_persistence_threshold: Optional[int] = Field(None, ge=0)
    bgsub_min_persistence_frames: Optional[float] = Field(None, ge=0.0, le=1.0)
    bgsub_min_px_active: Optional[int] = Field(None, ge=0)


class CameraResponse(CameraBase):
    id: int
    last_capture_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CameraLatestImageResponse(BaseModel):
    camera_id: int
    device_id: Optional[str] = None
    image_url: Optional[str] = None
    captured_at: Optional[datetime] = None
    file_path: Optional[str] = None
