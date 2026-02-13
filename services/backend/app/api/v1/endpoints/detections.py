import asyncio
import logging
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.api.deps import get_db, get_current_user
from app.core.database import AsyncSessionLocal
from app.core.redis import get_redis
from app.models.user import User
from app.models.detection import Detection, DetectionStatus
from app.schemas.detection import (
    DetectionCreate, DetectionUpdate, DetectionResponse,
    DetectionResolve, DetectionStartAnalysis,
)
from app.schemas.detection import DetectionStatus as DetectionStatusSchema
from app.services import notification_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[DetectionResponse])
async def get_detections(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    rpa: Optional[str] = None,
    status_filter: Optional[DetectionStatusSchema] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    bairro: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista detecções com filtros e paginação"""
    query = select(Detection)

    filters = []
    if rpa:
        filters.append(Detection.rpa == rpa)
    if status_filter:
        filters.append(Detection.status == status_filter)
    if start_date:
        filters.append(Detection.timestamp >= start_date)
    if end_date:
        filters.append(Detection.timestamp <= end_date)
    if bairro:
        filters.append(Detection.bairro == bairro)

    if filters:
        query = query.where(and_(*filters))

    query = query.offset(skip).limit(limit).order_by(Detection.timestamp.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{detection_id}", response_model=DetectionResponse)
async def get_detection(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Busca uma detecção por ID"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found"
        )

    return detection


@router.post("/", response_model=DetectionResponse, status_code=status.HTTP_201_CREATED)
async def create_detection(
    detection_in: DetectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria uma nova detecção"""
    db_detection = Detection(
        camera_id=detection_in.camera_id,
        timestamp=detection_in.timestamp,
        logradouro=detection_in.logradouro,
        bairro=detection_in.bairro,
        rpa=detection_in.rpa,
        latitude=detection_in.latitude,
        longitude=detection_in.longitude,
        waste_type=detection_in.waste_type,
        material_type=detection_in.material_type,
        volume_m3=detection_in.volume_m3,
        offenders=detection_in.offenders,
        status=detection_in.status,
        image_url=detection_in.image_url,
        confidence_score=detection_in.confidence_score
    )

    # O trigger no banco irá criar automaticamente o campo geom

    db.add(db_detection)
    await db.commit()
    await db.refresh(db_detection)

    # Disparar notificações em background (nova sessão para não conflitar)
    detection_id = db_detection.id
    detection_snapshot = db_detection

    async def _notify():
        try:
            async with AsyncSessionLocal() as bg_db:
                redis = get_redis()
                await notification_service.on_new_detection(detection_snapshot, bg_db, redis)
                await bg_db.commit()
        except Exception:
            logger.exception("Failed to create notifications for detection %s", detection_id)

    asyncio.create_task(_notify())

    return db_detection


@router.patch("/{detection_id}", response_model=DetectionResponse)
async def update_detection(
    detection_id: UUID,
    detection_update: DetectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza uma detecção (status, infratores, etc)"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found"
        )

    # Atualizar campos
    update_data = detection_update.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(detection, key, value)

    await db.commit()
    await db.refresh(detection)

    return detection


@router.delete("/{detection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_detection(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deleta uma detecção"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found"
        )

    await db.delete(detection)
    await db.commit()

    return None


@router.post("/{detection_id}/resolve", response_model=DetectionResponse)
async def resolve_detection(
    detection_id: UUID,
    resolve_data: DetectionResolve,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca uma detecção como resolvida"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found",
        )

    if detection.status == DetectionStatus.RESOLVIDO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Detection is already resolved",
        )

    detection.status = DetectionStatus.RESOLVIDO
    detection.resolved_at = resolve_data.resolved_at
    detection.resolved_by = current_user.id
    detection.resolution_justification = resolve_data.resolution_justification
    detection.forwarded_to_sector = resolve_data.forwarded_to_sector

    await db.commit()
    await db.refresh(detection)
    return detection


@router.post("/{detection_id}/start-analysis", response_model=DetectionResponse)
async def start_analysis(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca uma detecção como em análise"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found",
        )

    if detection.status != DetectionStatus.PENDENTE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending detections can be moved to analysis",
        )

    detection.status = DetectionStatus.EM_ANALISE
    detection.analysis_started_at = datetime.utcnow()
    detection.analysis_started_by = current_user.id

    await db.commit()
    await db.refresh(detection)
    return detection
