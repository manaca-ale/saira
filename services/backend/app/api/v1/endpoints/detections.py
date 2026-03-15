import asyncio
import logging
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, or_
from app.api.deps import get_db, get_current_user
from app.core.database import AsyncSessionLocal
from app.core.redis import get_redis
from app.models.user import User
from app.models.detection import Detection, DetectionStatus
from app.schemas.detection import (
    DetectionCreate, DetectionUpdate, DetectionResponse,
    DetectionResolve, DetectionStartAnalysis, DetectionListResponse,
)
from app.schemas.detection import DetectionStatus as DetectionStatusSchema
from app.services import notification_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _parse_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_status_filter(value: str) -> Optional[DetectionStatus]:
    normalized = value.strip().lower()
    if normalized == "pendente":
        return DetectionStatus.PENDENTE
    if normalized in {"em analise", "em análise"}:
        return DetectionStatus.EM_ANALISE
    if normalized == "resolvido":
        return DetectionStatus.RESOLVIDO
    return None


def _expand_waste_type_aliases(values: List[str]) -> List[str]:
    aliases = {
        "entulho": {"entulho"},
        "lixo domiciliar": {"lixo domiciliar", "household waste"},
        "poda": {"poda", "pruning"},
        "plástico": {"plástico", "plastico", "plastic"},
        "plastico": {"plástico", "plastico", "plastic"},
    }
    expanded = set()
    for value in values:
        key = value.strip().lower()
        expanded.update(aliases.get(key, {key}))
    return list(expanded)


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


@router.get("/search", response_model=DetectionListResponse)
async def search_detections(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    rpa: Optional[str] = None,
    status_filter: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    bairro: Optional[str] = None,
    logradouro: Optional[str] = None,
    waste_type: Optional[str] = None,
    has_offender: Optional[bool] = None,
    volume_min: Optional[float] = Query(None, ge=0),
    volume_max: Optional[float] = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista deteções paginadas com total e filtros para o frontend."""
    if volume_min is not None and volume_max is not None and volume_min > volume_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="volume_min cannot be greater than volume_max",
        )

    filters = []

    rpa_values = _parse_csv(rpa)
    if rpa_values:
        filters.append(Detection.rpa.in_(rpa_values))

    raw_status_values = _parse_csv(status_filter)
    status_values = [
        parsed
        for parsed in (_normalize_status_filter(value) for value in raw_status_values)
        if parsed is not None
    ]
    if raw_status_values and not status_values:
        return DetectionListResponse(items=[], total=0, skip=skip, limit=limit)
    if status_values:
        filters.append(Detection.status.in_(status_values))

    if start_date:
        filters.append(Detection.timestamp >= start_date)
    if end_date:
        filters.append(Detection.timestamp <= end_date)

    if bairro and bairro.strip():
        filters.append(Detection.bairro.ilike(f"%{bairro.strip()}%"))
    if logradouro and logradouro.strip():
        filters.append(Detection.logradouro.ilike(f"%{logradouro.strip()}%"))

    waste_type_values = _expand_waste_type_aliases(_parse_csv(waste_type))
    if waste_type_values:
        filters.append(func.lower(Detection.waste_type).in_(waste_type_values))

    if has_offender is True:
        filters.append(
            and_(
                Detection.offenders.is_not(None),
                func.length(func.trim(Detection.offenders)) > 0,
            )
        )
    elif has_offender is False:
        filters.append(
            or_(
                Detection.offenders.is_(None),
                func.length(func.trim(Detection.offenders)) == 0,
            )
        )

    if volume_min is not None:
        filters.append(Detection.volume_m3 >= volume_min)
    if volume_max is not None:
        filters.append(Detection.volume_m3 <= volume_max)

    filter_expression = and_(*filters) if filters else None

    count_query = select(func.count(Detection.id))
    if filter_expression is not None:
        count_query = count_query.where(filter_expression)
    total = (await db.execute(count_query)).scalar_one()

    query = select(Detection)
    if filter_expression is not None:
        query = query.where(filter_expression)
    query = query.order_by(Detection.timestamp.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return DetectionListResponse(items=items, total=total, skip=skip, limit=limit)


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
