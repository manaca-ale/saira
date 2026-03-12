import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from geoalchemy2.functions import ST_SetSRID, ST_MakePoint
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.camera import Camera
from app.schemas.camera import (
    CameraCreate,
    CameraLatestImageResponse,
    CameraResponse,
    CameraUpdate,
)

router = APIRouter()
UPLOADS_ROOT = Path(os.getenv("CAMERA_UPLOADS_DIR", "/app/uploads"))
UPLOAD_PUBLIC_BASE_URL = os.getenv("CAMERA_UPLOAD_PUBLIC_BASE_URL", "").rstrip("/")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _build_upload_image_url(relative_path: str) -> str:
    normalized = relative_path.lstrip("/").replace("\\", "/")
    if UPLOAD_PUBLIC_BASE_URL:
        return f"{UPLOAD_PUBLIC_BASE_URL}/uploads/{normalized}"
    return f"/uploads/{normalized}"


def _find_latest_image_for_device(device_id: str) -> Optional[tuple[Path, float]]:
    if not device_id:
        return None

    camera_dir = UPLOADS_ROOT / device_id
    if not camera_dir.exists() or not camera_dir.is_dir():
        return None

    latest_path: Optional[Path] = None
    latest_mtime = float("-inf")

    for root, _, files in os.walk(camera_dir):
        for file_name in files:
            path = Path(root) / file_name
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_path = path

    if latest_path is None:
        return None
    return latest_path, latest_mtime


@router.get("/", response_model=List[CameraResponse])
async def get_cameras(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    rpa: Optional[str] = None,
    is_active: Optional[bool] = None,
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

    query = query.offset(skip).limit(limit).order_by(Camera.created_at.desc())
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
