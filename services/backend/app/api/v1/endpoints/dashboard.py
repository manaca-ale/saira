from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, datetime
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.detection import Detection, DetectionStatus
from app.schemas.dashboard import DashboardStats, OccurrencesByMonth, RecurrentLocation, VolumeByRPA

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna estatísticas gerais do dashboard"""

    # Total de ocorrências
    total_result = await db.execute(select(func.count(Detection.id)))
    total_occurrences = total_result.scalar_one()

    # Volume diário (hoje)
    today = date.today()
    daily_volume_result = await db.execute(
        select(func.coalesce(func.sum(Detection.volume_m3), 0))
        .where(func.date(Detection.timestamp) == today)
    )
    daily_volume_m3 = daily_volume_result.scalar_one()

    # Contar por status
    pending_result = await db.execute(
        select(func.count(Detection.id))
        .where(Detection.status == DetectionStatus.PENDENTE)
    )
    pending_count = pending_result.scalar_one()

    in_analysis_result = await db.execute(
        select(func.count(Detection.id))
        .where(Detection.status == DetectionStatus.EM_ANALISE)
    )
    in_analysis_count = in_analysis_result.scalar_one()

    resolved_result = await db.execute(
        select(func.count(Detection.id))
        .where(Detection.status == DetectionStatus.RESOLVIDO)
    )
    resolved_count = resolved_result.scalar_one()

    return DashboardStats(
        total_occurrences=total_occurrences,
        daily_volume_m3=daily_volume_m3,
        pending_count=pending_count,
        in_analysis_count=in_analysis_count,
        resolved_count=resolved_count
    )


@router.get("/occurrences-by-month", response_model=List[OccurrencesByMonth])
async def get_occurrences_by_month(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna ocorrências agrupadas por mês"""
    result = await db.execute(
        select(
            func.to_char(Detection.timestamp, 'YYYY-MM').label('month'),
            func.count(Detection.id).label('count')
        )
        .group_by(func.to_char(Detection.timestamp, 'YYYY-MM'))
        .order_by(func.to_char(Detection.timestamp, 'YYYY-MM').desc())
        .limit(12)
    )

    rows = result.all()
    return [OccurrencesByMonth(month=row.month, count=row.count) for row in rows]


@router.get("/recurrent-locations", response_model=List[RecurrentLocation])
async def get_recurrent_locations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna locais com mais ocorrências (reincidentes)"""
    result = await db.execute(
        select(
            Detection.logradouro,
            Detection.bairro,
            Detection.rpa,
            func.count(Detection.id).label('count')
        )
        .where(Detection.logradouro.isnot(None))
        .group_by(Detection.logradouro, Detection.bairro, Detection.rpa)
        .having(func.count(Detection.id) > 1)
        .order_by(func.count(Detection.id).desc())
        .limit(10)
    )

    rows = result.all()
    return [
        RecurrentLocation(
            logradouro=row.logradouro or "",
            bairro=row.bairro or "",
            rpa=row.rpa or "",
            count=row.count
        )
        for row in rows
    ]


@router.get("/volume-by-rpa", response_model=List[VolumeByRPA])
async def get_volume_by_rpa(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna volumetria agregada por RPA"""
    result = await db.execute(
        select(
            Detection.rpa,
            func.avg(Detection.volume_m3).label('avg_volume_m3'),
            func.sum(Detection.volume_m3).label('total_volume_m3'),
            func.count(Detection.id).label('count')
        )
        .where(Detection.rpa.isnot(None))
        .where(Detection.volume_m3.isnot(None))
        .group_by(Detection.rpa)
        .order_by(Detection.rpa)
    )

    rows = result.all()
    return [
        VolumeByRPA(
            rpa=row.rpa,
            avg_volume_m3=row.avg_volume_m3 or 0,
            total_volume_m3=row.total_volume_m3 or 0,
            count=row.count
        )
        for row in rows
    ]
