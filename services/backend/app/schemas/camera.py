from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Optional
from decimal import Decimal


# Polygon = list of [x, y] points. pile_zone_polygon = list of polygons.
PileZonePolygon = list[list[list[int]]]

# Família do hardware. Valida na borda (o banco guarda VARCHAR, então adicionar
# um tipo novo é mudança de código, sem migration). NULL = desconhecido.
CameraType = Literal["esp32", "pi", "unknown"]


class CameraBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    device_id: Optional[str] = Field(None, max_length=64)
    camera_type: Optional[CameraType] = None
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
    camera_type: Optional[CameraType] = None
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


class CameraZoomResponse(BaseModel):
    """Zoom óptico atual da lente motorizada, lido da telemetria (.health.json).

    `zoom` é 0=aberto .. 1=tele; None quando o dispositivo ainda não reportou ou
    não tem lente motorizada. `reported_at` é a marca do último health.
    """

    camera_id: int
    device_id: Optional[str] = None
    zoom: Optional[float] = None
    camera_ok: Optional[bool] = None
    reported_at: Optional[str] = None


class CameraPolygonUpdate(BaseModel):
    """Corpo do POST /cameras/{id}/polygon — a zona de interesse (pile_zone_polygon).

    Lista de polígonos aninhada `[[[x,y],...],...]` em pixels no frame de
    referência 1280×720. Lista vazia limpa o polígono (frame inteiro).
    """

    polygon: PileZonePolygon


class CameraPolygonResponse(BaseModel):
    camera_id: int
    device_id: Optional[str] = None
    saved: bool
    pushed_to_device: bool
    detail: Optional[str] = None


class CameraLiveSessionResponse(BaseModel):
    """Estado de uma sessão de modo ao vivo (ver POST /cameras/{id}/live/start).

    `hard_deadline` é ancorado no start e NUNCA é renovado — é ele que faz o teto
    ser um teto de verdade, e não uma janela deslizante infinita. `expires_at` é o
    lease curto no dispositivo, que o frontend renova enquanto o operador estiver
    presente. `renew_after_s` vem do servidor de propósito: o frontend não deve
    hardcodar a cadência de renovação (assim dá pra ajustar por env sem rebuild).
    """

    camera_id: int
    device_id: str
    status: str
    expires_at: datetime
    hard_deadline: datetime
    remaining_s: int
    lease_s: int
    renew_after_s: int
