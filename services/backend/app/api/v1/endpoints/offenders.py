from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, literal_column, String
from sqlalchemy.orm import selectinload
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.detection import Detection, DetectionStatus
from app.models.offender import Offender, DetectionOffender, OffenderType, OffenderSource
from app.schemas.offender import (
    OffenderCreate, OffenderUpdate, OffenderResponse,
    DetectionOffenderCreate, DetectionOffenderUpdate, DetectionOffenderResponse,
    OffenderStatsResponse, OffendersByTypeResponse, RecidivismByTypeResponse,
    OffenderVolumeByTypeResponse, WasteByOffenderTypeResponse, WasteBreakdownItem,
    TopPlateResponse, VehicleColorResponse,
)
from app.core.config import settings

router = APIRouter()


# ── Helper: build detection filters for dashboard queries ────────────

def _detection_filters(
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    status_filter: Optional[str],
    logradouro: Optional[str],
    bairro: Optional[str],
    rpa: Optional[str],
):
    filters = []
    if start_date:
        filters.append(Detection.timestamp >= start_date)
    if end_date:
        filters.append(Detection.timestamp <= end_date)
    if status_filter:
        filters.append(Detection.status == status_filter)
    else:
        # Rejected/indeterminate detections only surface on the camera detections
        # screen; dashboard aggregations must not count them.
        filters.append(
            Detection.status.notin_(
                [DetectionStatus.REJEITADO, DetectionStatus.INDETERMINADO]
            )
        )
    if logradouro:
        filters.append(Detection.logradouro.ilike(f"%{logradouro}%"))
    if bairro:
        filters.append(Detection.bairro.ilike(f"%{bairro}%"))
    if rpa:
        filters.append(Detection.rpa == rpa)
    return filters


# ═══════════════════════════════════════════════════════════════════════
# CRUD — Offender profiles
# ═══════════════════════════════════════════════════════════════════════

@router.get("/", response_model=List[OffenderResponse])
async def list_offenders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    type: Optional[OffenderType] = None,
    plate: Optional[str] = None,
    name: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(
            Offender,
            func.count(DetectionOffender.id).label("sighting_count"),
        )
        .outerjoin(DetectionOffender, DetectionOffender.offender_id == Offender.id)
        .group_by(Offender.id)
    )

    filters = []
    if type:
        filters.append(Offender.type == type)
    if plate:
        filters.append(Offender.plate.ilike(f"%{plate}%"))
    if name:
        filters.append(Offender.name.ilike(f"%{name}%"))
    if is_active is not None:
        filters.append(Offender.is_active == is_active)
    if filters:
        query = query.where(and_(*filters))

    query = query.order_by(Offender.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    return [
        OffenderResponse(
            id=offender.id,
            name=offender.name,
            type=offender.type,
            plate=offender.plate,
            vehicle_color=offender.vehicle_color,
            description=offender.description,
            is_active=offender.is_active,
            sighting_count=sighting_count,
            created_by=offender.created_by,
            created_at=offender.created_at,
            updated_at=offender.updated_at,
        )
        for offender, sighting_count in rows
    ]


@router.get("/{offender_id}", response_model=OffenderResponse)
async def get_offender(
    offender_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(
            Offender,
            func.count(DetectionOffender.id).label("sighting_count"),
        )
        .outerjoin(DetectionOffender, DetectionOffender.offender_id == Offender.id)
        .where(Offender.id == offender_id)
        .group_by(Offender.id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offender not found")

    offender, sighting_count = row
    return OffenderResponse(
        id=offender.id,
        name=offender.name,
        type=offender.type,
        plate=offender.plate,
        vehicle_color=offender.vehicle_color,
        description=offender.description,
        is_active=offender.is_active,
        sighting_count=sighting_count,
        created_by=offender.created_by,
        created_at=offender.created_at,
        updated_at=offender.updated_at,
    )


@router.post("/", response_model=OffenderResponse, status_code=status.HTTP_201_CREATED)
async def create_offender(
    data: OffenderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    offender = Offender(
        name=data.name,
        type=data.type,
        plate=data.plate,
        vehicle_color=data.vehicle_color,
        description=data.description,
        created_by=current_user.id,
    )
    db.add(offender)
    await db.commit()
    await db.refresh(offender)

    return OffenderResponse(
        id=offender.id,
        name=offender.name,
        type=offender.type,
        plate=offender.plate,
        vehicle_color=offender.vehicle_color,
        description=offender.description,
        is_active=offender.is_active,
        sighting_count=0,
        created_by=offender.created_by,
        created_at=offender.created_at,
        updated_at=offender.updated_at,
    )


@router.patch("/{offender_id}", response_model=OffenderResponse)
async def update_offender(
    offender_id: UUID,
    data: OffenderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Offender).where(Offender.id == offender_id))
    offender = result.scalar_one_or_none()
    if not offender:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offender not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(offender, key, value)

    await db.commit()
    await db.refresh(offender)

    # count sightings
    cnt_result = await db.execute(
        select(func.count(DetectionOffender.id)).where(DetectionOffender.offender_id == offender.id)
    )
    sighting_count = cnt_result.scalar_one()

    return OffenderResponse(
        id=offender.id,
        name=offender.name,
        type=offender.type,
        plate=offender.plate,
        vehicle_color=offender.vehicle_color,
        description=offender.description,
        is_active=offender.is_active,
        sighting_count=sighting_count,
        created_by=offender.created_by,
        created_at=offender.created_at,
        updated_at=offender.updated_at,
    )


@router.delete("/{offender_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_offender(
    offender_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Offender).where(Offender.id == offender_id))
    offender = result.scalar_one_or_none()
    if not offender:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offender not found")
    await db.delete(offender)
    await db.commit()
    return None


# ═══════════════════════════════════════════════════════════════════════
# Detection ↔ Offender sightings
# ═══════════════════════════════════════════════════════════════════════

@router.get("/detections/{detection_id}/offenders", response_model=List[DetectionOffenderResponse])
async def list_detection_offenders(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DetectionOffender)
        .options(selectinload(DetectionOffender.offender))
        .where(DetectionOffender.detection_id == detection_id)
        .order_by(DetectionOffender.created_at.desc())
    )
    return result.scalars().all()


@router.post("/detections/{detection_id}/offenders", response_model=DetectionOffenderResponse, status_code=status.HTTP_201_CREATED)
async def add_detection_offender(
    detection_id: UUID,
    data: DetectionOffenderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify detection exists
    det = await db.execute(select(Detection).where(Detection.id == detection_id))
    if not det.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")

    # If offender_id provided, verify it exists
    if data.offender_id:
        off = await db.execute(select(Offender).where(Offender.id == data.offender_id))
        if not off.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offender not found")

    sighting = DetectionOffender(
        detection_id=detection_id,
        offender_id=data.offender_id,
        offender_type=data.offender_type,
        plate=data.plate,
        vehicle_color=data.vehicle_color,
        waste_type=data.waste_type,
        estimated_volume_m3=data.estimated_volume_m3,
        source=OffenderSource.MANUAL,
        created_by=current_user.id,
        notes=data.notes,
    )
    db.add(sighting)
    await db.commit()
    await db.refresh(sighting)

    # Load offender relationship
    if sighting.offender_id:
        await db.refresh(sighting, ["offender"])

    return sighting


@router.patch("/detection-offenders/{sighting_id}", response_model=DetectionOffenderResponse)
async def update_detection_offender(
    sighting_id: UUID,
    data: DetectionOffenderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DetectionOffender)
        .options(selectinload(DetectionOffender.offender))
        .where(DetectionOffender.id == sighting_id)
    )
    sighting = result.scalar_one_or_none()
    if not sighting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sighting not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(sighting, key, value)

    await db.commit()
    await db.refresh(sighting)
    return sighting


@router.delete("/detection-offenders/{sighting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_detection_offender(
    sighting_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(DetectionOffender).where(DetectionOffender.id == sighting_id))
    sighting = result.scalar_one_or_none()
    if not sighting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sighting not found")
    await db.delete(sighting)
    await db.commit()
    return None


@router.post("/detections/{detection_id}/offenders/link/{offender_id}", response_model=DetectionOffenderResponse, status_code=status.HTTP_201_CREATED)
async def link_offender_to_detection(
    detection_id: UUID,
    offender_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    det = await db.execute(select(Detection).where(Detection.id == detection_id))
    if not det.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")

    off_result = await db.execute(select(Offender).where(Offender.id == offender_id))
    offender = off_result.scalar_one_or_none()
    if not offender:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offender not found")

    sighting = DetectionOffender(
        detection_id=detection_id,
        offender_id=offender_id,
        offender_type=offender.type,
        plate=offender.plate,
        vehicle_color=offender.vehicle_color,
        source=OffenderSource.MANUAL,
        created_by=current_user.id,
    )
    db.add(sighting)
    await db.commit()
    await db.refresh(sighting)
    await db.refresh(sighting, ["offender"])
    return sighting


# ═══════════════════════════════════════════════════════════════════════
# Dashboard — aggregation endpoints
# ═══════════════════════════════════════════════════════════════════════

@router.get("/dashboard/offender-stats", response_model=OffenderStatsResponse)
async def get_offender_stats(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    logradouro: Optional[str] = None,
    bairro: Optional[str] = None,
    rpa: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    det_filters = _detection_filters(start_date, end_date, status_filter, logradouro, bairro, rpa)

    # Base query joining detection_offenders with detections for filtering
    base = select(DetectionOffender).join(Detection, DetectionOffender.detection_id == Detection.id)
    if det_filters:
        base = base.where(and_(*det_filters))

    # Build a CTE for offender groups: each unique offender identity gets a group key
    # group_key = coalesce(offender_id::text, plate, id::text)
    group_key = func.coalesce(
        func.cast(DetectionOffender.offender_id, String),
        DetectionOffender.plate,
        func.cast(DetectionOffender.id, String),
    )

    group_query = (
        select(
            group_key.label("group_key"),
            func.count(func.distinct(DetectionOffender.detection_id)).label("detection_count"),
        )
        .join(Detection, DetectionOffender.detection_id == Detection.id)
    )
    if det_filters:
        group_query = group_query.where(and_(*det_filters))
    group_query = group_query.group_by(literal_column("group_key"))
    group_cte = group_query.cte("offender_groups")

    # Total offenders (unique groups)
    total_result = await db.execute(select(func.count()).select_from(group_cte))
    total_offenders = total_result.scalar_one()

    # Recurrent (>1 detection)
    recurrent_result = await db.execute(
        select(func.count()).select_from(group_cte).where(group_cte.c.detection_count > 1)
    )
    recurrent_offenders = recurrent_result.scalar_one()

    # High recurrence (>=threshold)
    high_result = await db.execute(
        select(func.count()).select_from(group_cte)
        .where(group_cte.c.detection_count >= settings.HIGH_RECURRENCE_THRESHOLD)
    )
    high_recurrence = high_result.scalar_one()

    # Identified plates
    plates_query = (
        select(func.count(func.distinct(DetectionOffender.plate)))
        .join(Detection, DetectionOffender.detection_id == Detection.id)
        .where(DetectionOffender.plate.isnot(None))
    )
    if det_filters:
        plates_query = plates_query.where(and_(*det_filters))
    plates_result = await db.execute(plates_query)
    identified_plates = plates_result.scalar_one()

    # Estimated volume
    vol_query = (
        select(func.coalesce(func.sum(DetectionOffender.estimated_volume_m3), 0))
        .join(Detection, DetectionOffender.detection_id == Detection.id)
    )
    if det_filters:
        vol_query = vol_query.where(and_(*det_filters))
    vol_result = await db.execute(vol_query)
    estimated_volume = float(vol_result.scalar_one())

    return OffenderStatsResponse(
        total_offenders=total_offenders,
        recurrent_offenders=recurrent_offenders,
        high_recurrence=high_recurrence,
        identified_plates=identified_plates,
        estimated_volume_m3=estimated_volume,
    )


@router.get("/dashboard/offenders-by-type", response_model=List[OffendersByTypeResponse])
async def get_offenders_by_type(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    logradouro: Optional[str] = None,
    bairro: Optional[str] = None,
    rpa: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    det_filters = _detection_filters(start_date, end_date, status_filter, logradouro, bairro, rpa)

    query = (
        select(
            DetectionOffender.offender_type.label("type"),
            func.count(DetectionOffender.id).label("count"),
        )
        .join(Detection, DetectionOffender.detection_id == Detection.id)
        .group_by(DetectionOffender.offender_type)
        .order_by(func.count(DetectionOffender.id).desc())
    )
    if det_filters:
        query = query.where(and_(*det_filters))

    result = await db.execute(query)
    rows = result.all()
    total = sum(r.count for r in rows) or 1

    return [
        OffendersByTypeResponse(
            type=row.type,
            count=row.count,
            percentage=round(row.count / total * 100, 1),
        )
        for row in rows
    ]


@router.get("/dashboard/recidivism-by-type", response_model=List[RecidivismByTypeResponse])
async def get_recidivism_by_type(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    logradouro: Optional[str] = None,
    bairro: Optional[str] = None,
    rpa: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    det_filters = _detection_filters(start_date, end_date, status_filter, logradouro, bairro, rpa)

    # Subquery: for each (offender_type, group_key), count distinct detections
    group_key = func.coalesce(
        func.cast(DetectionOffender.offender_id, String),
        DetectionOffender.plate,
        func.cast(DetectionOffender.id, String),
    )

    inner = (
        select(
            DetectionOffender.offender_type,
            group_key.label("group_key"),
            func.count(func.distinct(DetectionOffender.detection_id)).label("det_count"),
        )
        .join(Detection, DetectionOffender.detection_id == Detection.id)
        .group_by(DetectionOffender.offender_type, literal_column("group_key"))
    )
    if det_filters:
        inner = inner.where(and_(*det_filters))
    inner_cte = inner.cte("type_groups")

    # Count groups with >1 detection per type
    query = (
        select(
            inner_cte.c.offender_type.label("type"),
            func.count().label("recurrent_count"),
        )
        .where(inner_cte.c.det_count > 1)
        .group_by(inner_cte.c.offender_type)
        .order_by(func.count().desc())
    )
    result = await db.execute(query)
    return [RecidivismByTypeResponse(type=r.type, recurrent_count=r.recurrent_count) for r in result.all()]


@router.get("/dashboard/offender-volume-by-type", response_model=List[OffenderVolumeByTypeResponse])
async def get_offender_volume_by_type(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    logradouro: Optional[str] = None,
    bairro: Optional[str] = None,
    rpa: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    det_filters = _detection_filters(start_date, end_date, status_filter, logradouro, bairro, rpa)

    query = (
        select(
            DetectionOffender.offender_type.label("type"),
            func.coalesce(func.sum(DetectionOffender.estimated_volume_m3), 0).label("total_volume_m3"),
        )
        .join(Detection, DetectionOffender.detection_id == Detection.id)
        .group_by(DetectionOffender.offender_type)
        .order_by(func.sum(DetectionOffender.estimated_volume_m3).desc())
    )
    if det_filters:
        query = query.where(and_(*det_filters))

    result = await db.execute(query)
    return [
        OffenderVolumeByTypeResponse(type=r.type, total_volume_m3=float(r.total_volume_m3))
        for r in result.all()
    ]


@router.get("/dashboard/waste-by-offender-type", response_model=List[WasteByOffenderTypeResponse])
async def get_waste_by_offender_type(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    logradouro: Optional[str] = None,
    bairro: Optional[str] = None,
    rpa: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    det_filters = _detection_filters(start_date, end_date, status_filter, logradouro, bairro, rpa)

    query = (
        select(
            DetectionOffender.offender_type,
            DetectionOffender.waste_type,
            func.count(DetectionOffender.id).label("count"),
        )
        .join(Detection, DetectionOffender.detection_id == Detection.id)
        .where(DetectionOffender.waste_type.isnot(None))
        .group_by(DetectionOffender.offender_type, DetectionOffender.waste_type)
        .order_by(DetectionOffender.offender_type, func.count(DetectionOffender.id).desc())
    )
    if det_filters:
        query = query.where(and_(*det_filters))

    result = await db.execute(query)
    rows = result.all()

    # Group by offender_type
    grouped: dict = {}
    for row in rows:
        key = row.offender_type
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(WasteBreakdownItem(waste_type=row.waste_type, count=row.count))

    return [
        WasteByOffenderTypeResponse(offender_type=otype, waste_breakdown=items)
        for otype, items in grouped.items()
    ]


@router.get("/dashboard/top-plates", response_model=List[TopPlateResponse])
async def get_top_plates(
    limit: int = Query(5, ge=1, le=50),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    logradouro: Optional[str] = None,
    bairro: Optional[str] = None,
    rpa: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    det_filters = _detection_filters(start_date, end_date, status_filter, logradouro, bairro, rpa)

    query = (
        select(
            DetectionOffender.plate,
            func.count(func.distinct(DetectionOffender.detection_id)).label("occurrences"),
        )
        .join(Detection, DetectionOffender.detection_id == Detection.id)
        .where(DetectionOffender.plate.isnot(None))
        .group_by(DetectionOffender.plate)
        .order_by(func.count(func.distinct(DetectionOffender.detection_id)).desc())
        .limit(limit)
    )
    if det_filters:
        query = query.where(and_(*det_filters))

    result = await db.execute(query)
    return [TopPlateResponse(plate=r.plate, occurrences=r.occurrences) for r in result.all()]


@router.get("/dashboard/vehicle-colors", response_model=List[VehicleColorResponse])
async def get_vehicle_colors(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    logradouro: Optional[str] = None,
    bairro: Optional[str] = None,
    rpa: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    det_filters = _detection_filters(start_date, end_date, status_filter, logradouro, bairro, rpa)

    query = (
        select(
            DetectionOffender.vehicle_color.label("color"),
            func.count(DetectionOffender.id).label("count"),
        )
        .join(Detection, DetectionOffender.detection_id == Detection.id)
        .where(DetectionOffender.vehicle_color.isnot(None))
        .group_by(DetectionOffender.vehicle_color)
        .order_by(func.count(DetectionOffender.id).desc())
    )
    if det_filters:
        query = query.where(and_(*det_filters))

    result = await db.execute(query)
    rows = result.all()
    total = sum(r.count for r in rows) or 1

    return [
        VehicleColorResponse(
            color=r.color,
            count=r.count,
            percentage=round(r.count / total * 100, 1),
        )
        for r in rows
    ]
