"""Indicadores de Resultado (Anexo II — SAIRA).

Painel vivo: cada endpoint deriva o indicador direto dos dados reais da
plataforma, no período pedido. Ver app/schemas/indicators.py para o mapeamento
indicador → fonte. I6 (ações/detecções) fica de fora (ação externa do fiscal).
"""
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, cast, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.core.timezone import BRAZIL_TIMEZONE, now_brazil
from app.models.user import User
from app.models.camera import Camera
from app.models.camera_heartbeat import CameraHeartbeat
from app.models.cascade_decision import CascadeDecision
from app.models.detection import Detection, DetectionStatus
from app.models.notification import Notification
from app.schemas.indicators import (
    IndicatorPeriod,
    CameraUptime,
    SurveillanceReliability,
    LatencyStat,
    AlertSpeed,
    IdentificationQuality,
    AccuracyReading,
    DetectionAccuracy,
    DossierCompleteness,
    IndicatorCard,
    IndicatorsSummary,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers de período
# ---------------------------------------------------------------------------
def _resolve_range(
    start: Optional[str], end: Optional[str], default_days: int
) -> Tuple[datetime, datetime, IndicatorPeriod]:
    """Converte start/end (YYYY-MM-DD) em [início, fim_exclusivo) tz Brasil.

    Sem parâmetros: últimos ``default_days`` dias terminando hoje (BRT).
    """
    today = now_brazil().date()
    end_date = date.fromisoformat(end) if end else today
    start_date = (
        date.fromisoformat(start) if start else end_date - timedelta(days=default_days - 1)
    )
    start_dt = datetime.combine(start_date, time.min, tzinfo=BRAZIL_TIMEZONE)
    end_excl = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=BRAZIL_TIMEZONE)
    period = IndicatorPeriod(start=start_date.isoformat(), end=end_date.isoformat())
    return start_dt, end_excl, period


def _pct(num: int, den: int) -> Optional[float]:
    if not den:
        return None
    return round(100.0 * num / den, 1)


def _parse_camera_ids(camera_id: Optional[str]) -> Optional[List[int]]:
    """CSV "1,2,3" -> [1,2,3]; None/"" -> None (= todas as câmeras)."""
    if not camera_id:
        return None
    ids = []
    for tok in camera_id.split(","):
        tok = tok.strip()
        if tok.isdigit():
            ids.append(int(tok))
    return ids or None


# ---------------------------------------------------------------------------
# I1 — Confiabilidade da vigilância (%)
# ---------------------------------------------------------------------------
@router.get("/surveillance-reliability", response_model=SurveillanceReliability)
async def surveillance_reliability(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """I1: % do tempo em que cada ponto esteve transmitindo (heartbeats).

    Reporta a média dos pontos e o pior ponto do período.
    """
    start_dt, end_excl, period = _resolve_range(start, end, default_days=7)
    camera_ids = _parse_camera_ids(camera_id)

    # Agregação por câmera: online_checks via SUM(CAST(is_online AS INT))
    online_expr = func.sum(cast(CameraHeartbeat.is_online, Integer))
    total_expr = func.count(CameraHeartbeat.id)

    where_conds = [Camera.is_active.is_(True)]
    if camera_ids is not None:
        where_conds.append(Camera.id.in_(camera_ids))

    result = await db.execute(
        select(
            Camera.id,
            Camera.name,
            Camera.device_id,
            Camera.bairro,
            online_expr.label("online_checks"),
            total_expr.label("total_checks"),
        )
        .select_from(Camera)
        .join(
            CameraHeartbeat,
            and_(
                CameraHeartbeat.camera_id == Camera.id,
                CameraHeartbeat.checked_at >= start_dt,
                CameraHeartbeat.checked_at < end_excl,
            ),
            isouter=True,
        )
        .where(and_(*where_conds))
        .group_by(Camera.id, Camera.name, Camera.device_id, Camera.bairro)
        .order_by(Camera.id)
    )

    cameras = []
    uptimes = []
    for row in result.all():
        total = int(row.total_checks or 0)
        onl = int(row.online_checks or 0)
        pct = _pct(onl, total)
        cameras.append(
            CameraUptime(
                camera_id=row.id,
                name=row.name,
                device_id=row.device_id,
                bairro=row.bairro,
                uptime_pct=pct,
                online_checks=onl,
                total_checks=total,
            )
        )
        if pct is not None:
            uptimes.append((pct, row.name or row.device_id or str(row.id)))

    has_data = len(uptimes) > 0
    avg = round(sum(u for u, _ in uptimes) / len(uptimes), 1) if has_data else None
    worst_pct, worst_name = (min(uptimes, key=lambda x: x[0]) if has_data else (None, None))

    return SurveillanceReliability(
        period=period,
        average_uptime_pct=avg,
        worst_uptime_pct=worst_pct,
        worst_camera=worst_name,
        cameras=cameras,
        has_data=has_data,
    )


# ---------------------------------------------------------------------------
# I2 — Velocidade do alerta (s)
# ---------------------------------------------------------------------------
async def _alert_speed(
    db: AsyncSession,
    start_dt: datetime,
    end_excl: datetime,
    camera_ids: Optional[List[int]] = None,
) -> Tuple[LatencyStat, LatencyStat]:
    """Retorna (latência até registro, latência até notificação)."""
    cam_filter = [Detection.camera_id.in_(camera_ids)] if camera_ids is not None else []

    # --- até registro: created_at - timestamp ---
    reg_latency = func.extract("epoch", Detection.created_at - Detection.timestamp)
    reg = await db.execute(
        select(
            func.percentile_cont(0.5).within_group(reg_latency.asc()),
            func.percentile_cont(0.95).within_group(reg_latency.asc()),
            func.count(),
        ).where(
            Detection.timestamp >= start_dt,
            Detection.timestamp < end_excl,
            Detection.created_at.isnot(None),
            Detection.created_at >= Detection.timestamp,
            *cam_filter,
        )
    )
    rp50, rp95, rn = reg.one()
    reg_stat = LatencyStat(
        label="até registro",
        p50_seconds=round(float(rp50), 1) if rp50 is not None else None,
        p95_seconds=round(float(rp95), 1) if rp95 is not None else None,
        sample_size=int(rn or 0),
    )

    # --- até notificação: primeira notificação - timestamp ---
    notif_sub = (
        select(
            Notification.detection_id.label("did"),
            func.min(Notification.created_at).label("first_notif"),
        )
        .where(Notification.detection_id.isnot(None))
        .group_by(Notification.detection_id)
        .subquery()
    )
    notif_latency = func.extract("epoch", notif_sub.c.first_notif - Detection.timestamp)
    notif = await db.execute(
        select(
            func.percentile_cont(0.5).within_group(notif_latency.asc()),
            func.percentile_cont(0.95).within_group(notif_latency.asc()),
            func.count(),
        )
        .select_from(Detection)
        .join(notif_sub, notif_sub.c.did == Detection.id)
        .where(
            Detection.timestamp >= start_dt,
            Detection.timestamp < end_excl,
            notif_sub.c.first_notif >= Detection.timestamp,
            *cam_filter,
        )
    )
    np50, np95, nn = notif.one()
    notif_stat = LatencyStat(
        label="até notificação",
        p50_seconds=round(float(np50), 1) if np50 is not None else None,
        p95_seconds=round(float(np95), 1) if np95 is not None else None,
        sample_size=int(nn or 0),
    )
    return reg_stat, notif_stat


@router.get("/alert-speed", response_model=AlertSpeed)
async def alert_speed(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """I2: segundos entre o flagrante (timestamp do frame) e o alerta. p50 e p95."""
    start_dt, end_excl, period = _resolve_range(start, end, default_days=7)
    reg_stat, notif_stat = await _alert_speed(db, start_dt, end_excl, _parse_camera_ids(camera_id))
    # Primário = notificação se houver amostra; senão registro.
    primary = notif_stat if notif_stat.sample_size > 0 else reg_stat
    return AlertSpeed(period=period, primary=primary, breakdown=[reg_stat, notif_stat])


# ---------------------------------------------------------------------------
# I3 — Qualidade da identificação (%)
# ---------------------------------------------------------------------------
@router.get("/identification-quality", response_model=IdentificationQuality)
async def identification_quality(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """I3: entre as ocorrências confirmadas com infrator presente no frame,
    fração em que o sistema extraiu o recorte (crop) do infrator."""
    start_dt, end_excl, period = _resolve_range(start, end, default_days=30)
    camera_ids = _parse_camera_ids(camera_id)

    conds = [
        CascadeDecision.evaluated_at >= start_dt,
        CascadeDecision.evaluated_at < end_excl,
        CascadeDecision.agent2_disposal.is_(True),       # ocorrência confirmada
        CascadeDecision.offender_present.is_(True),      # infrator presente no frame
    ]
    if camera_ids is not None:
        conds.append(CascadeDecision.camera_id.in_(camera_ids))
    base = and_(*conds)
    present_res = await db.execute(select(func.count()).where(base))
    present = int(present_res.scalar_one() or 0)

    crops_res = await db.execute(
        select(func.count()).where(and_(base, CascadeDecision.offender_crop_extracted.is_(True)))
    )
    crops = int(crops_res.scalar_one() or 0)

    return IdentificationQuality(
        period=period,
        quality_pct=_pct(crops, present),
        crops_extracted=crops,
        offenders_present=present,
        has_data=present > 0,
    )


# ---------------------------------------------------------------------------
# I4 — Assertividade das detecções (%) — modelo + humano
# ---------------------------------------------------------------------------
async def _accuracy_model(
    db: AsyncSession,
    start_dt: datetime,
    end_excl: datetime,
    camera_ids: Optional[List[int]] = None,
) -> AccuracyReading:
    conds = [
        CascadeDecision.evaluated_at >= start_dt,
        CascadeDecision.evaluated_at < end_excl,
        CascadeDecision.agent2_success.is_(True),
    ]
    if camera_ids is not None:
        conds.append(CascadeDecision.camera_id.in_(camera_ids))
    base = and_(*conds)
    confirmed_res = await db.execute(
        select(func.count()).where(and_(base, CascadeDecision.agent2_disposal.is_(True)))
    )
    rejected_res = await db.execute(
        select(func.count()).where(and_(base, CascadeDecision.agent2_disposal.is_(False)))
    )
    confirmed = int(confirmed_res.scalar_one() or 0)
    rejected = int(rejected_res.scalar_one() or 0)
    total = confirmed + rejected
    return AccuracyReading(
        accuracy_pct=_pct(confirmed, total),
        confirmed=confirmed,
        rejected=rejected,
        total_evaluated=total,
        has_data=total > 0,
    )


async def _accuracy_human(
    db: AsyncSession,
    start_dt: datetime,
    end_excl: datetime,
    camera_ids: Optional[List[int]] = None,
) -> AccuracyReading:
    conds = [
        Detection.timestamp >= start_dt,
        Detection.timestamp < end_excl,
    ]
    if camera_ids is not None:
        conds.append(Detection.camera_id.in_(camera_ids))
    base = and_(*conds)
    confirmed_res = await db.execute(
        select(func.count()).where(and_(base, Detection.status == DetectionStatus.CONFIRMADO))
    )
    rejected_res = await db.execute(
        select(func.count()).where(and_(base, Detection.status == DetectionStatus.REJEITADO))
    )
    confirmed = int(confirmed_res.scalar_one() or 0)
    rejected = int(rejected_res.scalar_one() or 0)
    total = confirmed + rejected
    return AccuracyReading(
        accuracy_pct=_pct(confirmed, total),
        confirmed=confirmed,
        rejected=rejected,
        total_evaluated=total,
        has_data=total > 0,
    )


@router.get("/detection-accuracy", response_model=DetectionAccuracy)
async def detection_accuracy(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """I4: assertividade do modelo (cascata Agent-1+Agent-2) e taxa de
    confirmação humana (fiscal)."""
    start_dt, end_excl, period = _resolve_range(start, end, default_days=30)
    camera_ids = _parse_camera_ids(camera_id)
    model = await _accuracy_model(db, start_dt, end_excl, camera_ids)
    human = await _accuracy_human(db, start_dt, end_excl, camera_ids)
    return DetectionAccuracy(period=period, model=model, human=human)


# ---------------------------------------------------------------------------
# I5 — Completude do dossiê (%)
# ---------------------------------------------------------------------------
async def _dossier(
    db: AsyncSession,
    start_dt: datetime,
    end_excl: datetime,
    camera_ids: Optional[List[int]] = None,
) -> DossierCompleteness:
    # Universo: ocorrências confirmadas (validadas como descarte real).
    has_photo = Detection.image_url.isnot(None)
    has_location = Detection.bairro.isnot(None) | (
        Detection.latitude.isnot(None) & Detection.longitude.isnot(None)
    )
    has_datetime = Detection.timestamp.isnot(None)
    has_type = Detection.waste_type.isnot(None)
    has_volume = Detection.volume_m3.isnot(None)

    conds = [
        Detection.timestamp >= start_dt,
        Detection.timestamp < end_excl,
        Detection.status == DetectionStatus.CONFIRMADO,
    ]
    if camera_ids is not None:
        conds.append(Detection.camera_id.in_(camera_ids))
    base = and_(*conds)

    def _count_int(expr):
        return func.sum(cast(expr, Integer))

    res = await db.execute(
        select(
            func.count().label("total"),
            _count_int(and_(has_photo, has_location, has_datetime, has_type, has_volume)).label("complete"),
            _count_int(~has_photo).label("missing_photo"),
            _count_int(~has_location).label("missing_location"),
            _count_int(~has_datetime).label("missing_datetime"),
            _count_int(~has_type).label("missing_type"),
            _count_int(~has_volume).label("missing_volume"),
        ).where(base)
    )
    row = res.one()
    total = int(row.total or 0)
    complete = int(row.complete or 0)
    return DossierCompleteness(
        period=IndicatorPeriod(start="", end=""),  # preenchido pelo caller
        completeness_pct=_pct(complete, total),
        complete=complete,
        total=total,
        missing_photo=int(row.missing_photo or 0),
        missing_location=int(row.missing_location or 0),
        missing_datetime=int(row.missing_datetime or 0),
        missing_waste_type=int(row.missing_type or 0),
        missing_volume=int(row.missing_volume or 0),
        has_data=total > 0,
    )


@router.get("/dossier-completeness", response_model=DossierCompleteness)
async def dossier_completeness(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """I5: % das ocorrências confirmadas com todos os campos do dossiê
    (foto, local, data/hora, tipo, volume)."""
    start_dt, end_excl, period = _resolve_range(start, end, default_days=30)
    out = await _dossier(db, start_dt, end_excl, _parse_camera_ids(camera_id))
    out.period = period
    return out


# ---------------------------------------------------------------------------
# Summary — snapshot para os KPI cards
# ---------------------------------------------------------------------------
@router.get("/summary", response_model=IndicatorsSummary)
async def indicators_summary(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Snapshot dos 6 indicadores para os cards do painel."""
    start_dt, end_excl, period = _resolve_range(start, end, default_days=30)
    camera_ids = _parse_camera_ids(camera_id)

    # I1
    i1 = await surveillance_reliability(
        start=period.start, end=period.end, camera_id=camera_id, db=db, current_user=current_user
    )
    # I2
    reg_stat, notif_stat = await _alert_speed(db, start_dt, end_excl, camera_ids)
    i2_primary = notif_stat if notif_stat.sample_size > 0 else reg_stat
    # I3
    i3 = await identification_quality(
        start=period.start, end=period.end, camera_id=camera_id, db=db, current_user=current_user
    )
    # I4
    model = await _accuracy_model(db, start_dt, end_excl, camera_ids)
    human = await _accuracy_human(db, start_dt, end_excl, camera_ids)
    # I5
    i5 = await _dossier(db, start_dt, end_excl, camera_ids)

    cards = [
        IndicatorCard(
            id="I1", name="Confiabilidade da vigilância", unit="%",
            polarity="higher_better", periodicity="Semanal",
            value=i1.average_uptime_pct, secondary=i1.worst_uptime_pct,
            value_label="média dos pontos", secondary_label="pior ponto",
            has_data=i1.has_data,
        ),
        IndicatorCard(
            id="I2", name="Velocidade do alerta", unit="s",
            polarity="lower_better", periodicity="Semanal",
            value=i2_primary.p50_seconds, secondary=i2_primary.p95_seconds,
            value_label=f"p50 ({i2_primary.label})", secondary_label="p95",
            has_data=i2_primary.sample_size > 0,
        ),
        IndicatorCard(
            id="I3", name="Qualidade da identificação", unit="%",
            polarity="higher_better", periodicity="Mensal",
            value=i3.quality_pct, secondary=None,
            value_label="crops / infratores presentes",
            has_data=i3.has_data,
        ),
        IndicatorCard(
            id="I4", name="Assertividade das detecções", unit="%",
            polarity="higher_better", periodicity="Mensal",
            # Humano (fiscal) em destaque; modelo (cascata) como leitura secundária.
            value=human.accuracy_pct, secondary=model.accuracy_pct,
            value_label="humano", secondary_label="modelo",
            has_data=human.has_data or model.has_data,
        ),
        IndicatorCard(
            id="I5", name="Completude do dossiê", unit="%",
            polarity="higher_better", periodicity="Mensal",
            value=i5.completeness_pct, secondary=None,
            value_label="dossiês completos",
            has_data=i5.has_data,
        ),
        IndicatorCard(
            id="I6", name="Ações realizadas / detecções", unit="%",
            polarity="higher_better", periodicity="Mensal",
            value=None, secondary=None,
            value_label="ação externa do fiscal",
            has_data=False, trackable=False,
        ),
    ]
    return IndicatorsSummary(period=period, cards=cards)
