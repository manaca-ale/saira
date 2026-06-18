import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from geoalchemy2.functions import ST_SetSRID, ST_MakePoint
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.camera import Camera
from app.utils.uploads import UPLOADS_ROOT, IMAGE_EXTENSIONS, find_latest_image_for_device
from app.schemas.camera import (
    CameraBgsubConfigUpdate,
    CameraCreate,
    CameraLatestImageResponse,
    CameraResponse,
    CameraUpdate,
)

router = APIRouter()

CAMERA_SORTABLE_FIELDS: dict[str, Any] = {
    "name":       Camera.name,
    "device_id":  Camera.device_id,
    "bairro":     Camera.bairro,
    "rpa":        Camera.rpa,
    "is_active":  Camera.is_active,
    "created_at": Camera.created_at,
}
CAMERA_DEFAULT_SORT = "created_at"

UPLOAD_PUBLIC_BASE_URL = os.getenv("CAMERA_UPLOAD_PUBLIC_BASE_URL", "").rstrip("/")
# esp32-server base URL — usado para enfileirar CMD_SNAPSHOT (imagem sob demanda)
# no poll do dispositivo (Pi event-driven, que não manda mais heartbeat-imagem).
ESP32_SERVER_URL = os.getenv("ESP32_SERVER_URL", "http://esp32-server:5000").rstrip("/")

# Backwards-compatible alias kept for existing call sites in this module.
# Upload-tree scanning now lives in app.utils.uploads (shared with the offline monitor).
_find_latest_image_for_device = find_latest_image_for_device


def _build_upload_image_url(relative_path: str) -> str:
    normalized = relative_path.lstrip("/").replace("\\", "/")
    if UPLOAD_PUBLIC_BASE_URL:
        return f"{UPLOAD_PUBLIC_BASE_URL}/uploads/{normalized}"
    return f"/uploads/{normalized}"


@router.get("/", response_model=List[CameraResponse])
async def get_cameras(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    rpa: Optional[str] = None,
    is_active: Optional[bool] = None,
    sort_by: Optional[str] = Query(None, description="Campo para ordenação"),
    sort_order: Optional[str] = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista câmeras com filtros e paginação"""
    query = select(Camera)

    filters = []
    if rpa:
        filters.append(Camera.rpa == rpa)
    if is_active is not None:
        filters.append(Camera.is_active == is_active)

    if filters:
        query = query.where(and_(*filters))

    col = CAMERA_SORTABLE_FIELDS.get(sort_by or CAMERA_DEFAULT_SORT, Camera.created_at)
    order = col.asc() if sort_order == "asc" else col.desc()
    query = query.offset(skip).limit(limit).order_by(order)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Busca uma câmera por ID"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found"
        )

    return camera


@router.get("/{camera_id}/latest-image", response_model=CameraLatestImageResponse)
async def get_camera_latest_image(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna a imagem mais recente na pasta da câmera (uploads/<device_id>)."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found",
        )

    device_id = (camera.device_id or "").strip() or None
    if not device_id:
        return CameraLatestImageResponse(camera_id=camera_id, device_id=None)

    latest = _find_latest_image_for_device(device_id)
    if not latest:
        return CameraLatestImageResponse(camera_id=camera_id, device_id=device_id)

    latest_path, latest_mtime = latest
    try:
        relative = latest_path.relative_to(UPLOADS_ROOT).as_posix()
    except ValueError:
        relative = f"{device_id}/{latest_path.name}"

    captured_at = datetime.fromtimestamp(latest_mtime, tz=timezone.utc)
    return CameraLatestImageResponse(
        camera_id=camera_id,
        device_id=device_id,
        image_url=_build_upload_image_url(relative),
        captured_at=captured_at,
        file_path=relative,
    )


@router.post("/{camera_id}/request-snapshot")
async def request_camera_snapshot(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pede um frame atual sob demanda (abrir painel / "atualizar agora").

    Enfileira CMD_SNAPSHOT no poll do dispositivo via esp32-server /trigger; o
    dispositivo sobe 1 frame e o frontend o lê em seguida via /latest-image.
    Best-effort: dispositivos que não tratam o comando (ex.: esp32, que já
    mandam imagem no timer) simplesmente o ignoram.
    """
    import httpx

    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    device_id = (camera.device_id or "").strip() or None
    if not device_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera has no device_id")

    url = f"{ESP32_SERVER_URL}/device/{device_id}/trigger"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json={"cmd": "CMD_SNAPSHOT"})
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"esp32-server indisponível: {exc}",
        )
    return {"status": "requested", "camera_id": camera_id, "device_id": device_id}


@router.post("/", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def create_camera(
    camera_in: CameraCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria uma nova câmera"""
    # Criar geometria PostGIS
    db_camera = Camera(
        name=camera_in.name,
        device_id=camera_in.device_id,
        logradouro=camera_in.logradouro,
        bairro=camera_in.bairro,
        rpa=camera_in.rpa,
        latitude=camera_in.latitude,
        longitude=camera_in.longitude,
        rtsp_url=camera_in.rtsp_url,
        capture_interval_seconds=camera_in.capture_interval_seconds,
        is_active=camera_in.is_active
    )

    # O trigger no banco irá criar automaticamente o campo geom

    db.add(db_camera)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        detail = str(getattr(exc, "orig", exc)).lower()
        if "device_id" in detail and "unique" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="device_id already registered"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="could not create camera"
        )
    await db.refresh(db_camera)

    return db_camera


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: int,
    camera_update: CameraUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza uma câmera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found"
        )

    # Atualizar campos
    update_data = camera_update.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(camera, key, value)

    # O trigger no banco irá atualizar automaticamente o campo geom se lat/lon mudarem

    await db.commit()
    await db.refresh(camera)

    return camera


@router.patch("/{camera_id}/bgsub_config", response_model=CameraResponse)
async def update_camera_bgsub_config(
    camera_id: int,
    payload: CameraBgsubConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atualiza só os campos BGSUB de tuning (lr_fast/slow, threshold, etc).

    Todos NULL = câmera cai pros env globais (BGSUB_LR_FAST etc).
    Endpoint dedicado pra simplicar uso (admin via curl/CLI) e isolar
    auditabilidade da config do filtro.
    """
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(camera, key, value)

    await db.commit()
    await db.refresh(camera)
    return camera


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deleta uma câmera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found"
        )

    await db.delete(camera)
    await db.commit()

    return None
