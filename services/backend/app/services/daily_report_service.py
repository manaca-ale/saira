"""Compute the 5 daily KPIs (I1-I5) of the SAÍRA MVP report for a given date.

Indicators (from Indicadores_MVP_SAIRA_Manaca.pptx):
  I1  Confiabilidade da vigilância  — % uptime per camera (target ≥ 90%)
  I2  Velocidade do alerta          — p50/p95 capture→DB latency (target p95 ≤ 60s)
  I3  Qualidade da identificação    — % detections with offender bbox (target ≥ 80%)
  I4  Assertividade das detecções   — Agent-1 vs Agent-2 agreement rate (target ≥ 80%)
  I5  Completude do dossiê          — % alerts with all required fields (target 100%)

Sources:
  - I1: file system /app/uploads/{device_id}/YYYY/MM/DD/*.jpg + esp32-server timer_delay_ms
  - I2: detections.created_at vs detections.timestamp (SQL)
  - I3: detection_offenders.offender_bbox after migration h9c0d1e2f3a4 (SQL)
  - I4: /app/yolo_state/gemini_cascade_audit/YYYY-MM-DD/{device_id}.jsonl
  - I5: detections fields (image_url, latitude, longitude, bairro, waste_type, volume_m3) (SQL)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
import numpy as np
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.camera import Camera
from app.models.detection import Detection
from app.schemas.report import (
    ActivityByRpa,
    CameraUptime,
    DailyActivity,
    DailyKPIReport,
    HotspotLocation,
    IndicatorResult,
    IndicatorStatus,
)

logger = logging.getLogger(__name__)

BRT = ZoneInfo("America/Sao_Paulo")
FILENAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})\.jpg$")
ESP32_SERVER_BASE = "http://saira-esp32-server:5000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _day_bounds_brt(d: date_cls) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=BRT)
    return start, start + timedelta(days=1)


def _parse_upload_filename(name: str) -> Optional[datetime]:
    m = FILENAME_RE.match(name)
    if not m:
        return None
    y, mo, d, hh, mm, ss = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, hh, mm, ss, tzinfo=BRT)
    except ValueError:
        return None


def _format_pct(v: Optional[float], decimals: int = 0) -> str:
    if v is None:
        return "n/d"
    return f"{v:.{decimals}f}%"


def _classify(value: Optional[float], target: float, lower_is_better: bool = False) -> IndicatorStatus:
    """OK if meets target; ATENCAO if within band; ABAIXO if worse."""
    if value is None:
        return IndicatorStatus.SEM_DADOS
    band = settings.KPI_ATENCAO_BAND_PCT
    if lower_is_better:
        if value <= target:
            return IndicatorStatus.OK
        if value <= target * (1 + band / 100):
            return IndicatorStatus.ATENCAO
        return IndicatorStatus.ABAIXO
    else:
        if value >= target:
            return IndicatorStatus.OK
        if value >= target * (1 - band / 100):
            return IndicatorStatus.ATENCAO
        return IndicatorStatus.ABAIXO


async def _fetch_capture_interval_seconds(camera: Camera) -> int:
    """Pull timer_delay_ms from esp32-server config; fall back to DB then default."""
    default = camera.capture_interval_seconds or settings.REPORT_DEFAULT_CAPTURE_INTERVAL_S
    if not camera.device_id:
        return int(default)
    url = f"{ESP32_SERVER_BASE}/device/{camera.device_id}/config.txt"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url)
        if r.status_code == 200:
            for line in r.text.splitlines():
                if line.startswith("timer_delay_ms="):
                    try:
                        ms = int(line.split("=", 1)[1].strip())
                        return max(1, ms // 1000)
                    except (ValueError, IndexError):
                        pass
    except Exception:
        logger.debug("esp32-server config fetch failed for %s", camera.device_id, exc_info=True)
    return int(default)


# ---------------------------------------------------------------------------
# I1 — Confiabilidade da vigilância (uptime per camera)
# ---------------------------------------------------------------------------

async def _compute_i1(db: AsyncSession, day: date_cls) -> tuple[IndicatorResult, list[CameraUptime]]:
    day_start, day_end = _day_bounds_brt(day)
    uploads_root = Path(settings.REPORT_UPLOADS_DIR)

    cams_result = await db.execute(
        select(Camera).where(Camera.is_active == True).order_by(Camera.id)  # noqa: E712
    )
    cameras: list[Camera] = list(cams_result.scalars())

    per_camera: list[CameraUptime] = []
    for cam in cameras:
        bucket_s = await _fetch_capture_interval_seconds(cam)
        expected = max(1, 86400 // bucket_s)
        received = 0

        if cam.device_id:
            day_dir = uploads_root / cam.device_id / day.strftime("%Y/%m/%d")
            if day_dir.exists():
                buckets: set[int] = set()
                for entry in day_dir.iterdir():
                    if entry.is_file() and entry.suffix.lower() == ".jpg":
                        ts = _parse_upload_filename(entry.name)
                        if ts is None or not (day_start <= ts < day_end):
                            continue
                        idx = int((ts - day_start).total_seconds() // bucket_s)
                        buckets.add(idx)
                received = len(buckets)

        uptime = min(100.0, 100.0 * received / expected)
        per_camera.append(CameraUptime(
            camera_id=cam.id,
            device_id=cam.device_id,
            name=cam.name,
            uptime_pct=round(uptime, 1),
            expected_buckets=expected,
            received_buckets=received,
            capture_interval_seconds=bucket_s,
        ))

    if per_camera:
        i1_value = round(sum(c.uptime_pct for c in per_camera) / len(per_camera), 1)
        i1_text = f"{i1_value:.0f}%"
    else:
        i1_value = None
        i1_text = "n/d"

    rolling_7d = await _rolling_uptime(db, day, days=7)
    rolling_30d = await _rolling_uptime(db, day, days=30)

    return IndicatorResult(
        code="I1",
        name="Confiabilidade da vigilância",
        target_text=f"≥ {settings.KPI_I1_TARGET:.0f}%",
        value=i1_value,
        value_text=i1_text,
        status=_classify(i1_value, settings.KPI_I1_TARGET),
        rolling_7d=rolling_7d,
        rolling_30d=rolling_30d,
        rolling_7d_text=_format_pct(rolling_7d),
        rolling_30d_text=_format_pct(rolling_30d),
        extra={"per_camera": [c.model_dump() for c in per_camera]},
    ), per_camera


async def _rolling_uptime(db: AsyncSession, day: date_cls, days: int) -> Optional[float]:
    """Mean daily uptime over the last N days (inclusive of `day`)."""
    values: list[float] = []
    for i in range(days):
        d = day - timedelta(days=i)
        try:
            day_start, day_end = _day_bounds_brt(d)
            cams_result = await db.execute(
                select(Camera).where(Camera.is_active == True)  # noqa: E712
            )
            cameras: list[Camera] = list(cams_result.scalars())
            if not cameras:
                continue
            daily_uptimes: list[float] = []
            for cam in cameras:
                bucket_s = cam.capture_interval_seconds or settings.REPORT_DEFAULT_CAPTURE_INTERVAL_S
                expected = max(1, 86400 // bucket_s)
                received = 0
                if cam.device_id:
                    day_dir = Path(settings.REPORT_UPLOADS_DIR) / cam.device_id / d.strftime("%Y/%m/%d")
                    if day_dir.exists():
                        buckets: set[int] = set()
                        for entry in day_dir.iterdir():
                            if entry.is_file() and entry.suffix.lower() == ".jpg":
                                ts = _parse_upload_filename(entry.name)
                                if ts is None or not (day_start <= ts < day_end):
                                    continue
                                idx = int((ts - day_start).total_seconds() // bucket_s)
                                buckets.add(idx)
                        received = len(buckets)
                daily_uptimes.append(min(100.0, 100.0 * received / expected))
            if daily_uptimes:
                values.append(sum(daily_uptimes) / len(daily_uptimes))
        except Exception:
            logger.debug("rolling uptime calc failed for %s", d, exc_info=True)
    return round(sum(values) / len(values), 1) if values else None


# ---------------------------------------------------------------------------
# I2 — Velocidade do alerta (latency)
# ---------------------------------------------------------------------------

async def _compute_i2(db: AsyncSession, day: date_cls) -> IndicatorResult:
    day_start, day_end = _day_bounds_brt(day)
    result = await db.execute(
        text("""
            SELECT EXTRACT(EPOCH FROM (created_at - timestamp)) AS latency_s
            FROM detections
            WHERE timestamp >= :day_start AND timestamp < :day_end
              AND created_at IS NOT NULL AND timestamp IS NOT NULL
        """),
        {"day_start": day_start, "day_end": day_end},
    )
    latencies = [float(row[0]) for row in result if row[0] is not None and row[0] >= 0]

    if latencies:
        arr = np.array(latencies)
        p50 = float(np.percentile(arr, 50))
        p95 = float(np.percentile(arr, 95))
        value = p95
        value_text = f"p50={p50:.0f}s · p95={p95:.0f}s"
    else:
        value = None
        p50 = None
        p95 = None
        value_text = "n/d"

    rolling_7d = await _rolling_p95(db, day, days=7)
    rolling_30d = await _rolling_p95(db, day, days=30)

    return IndicatorResult(
        code="I2",
        name="Velocidade do alerta",
        target_text=f"p95 ≤ {settings.KPI_I2_P95_TARGET_S:.0f}s",
        value=value,
        value_text=value_text,
        status=_classify(value, settings.KPI_I2_P95_TARGET_S, lower_is_better=True),
        rolling_7d=rolling_7d,
        rolling_30d=rolling_30d,
        rolling_7d_text=f"{rolling_7d:.0f}s" if rolling_7d is not None else None,
        rolling_30d_text=f"{rolling_30d:.0f}s" if rolling_30d is not None else None,
        extra={"p50": p50, "p95": p95, "n_samples": len(latencies)},
    )


async def _rolling_p95(db: AsyncSession, day: date_cls, days: int) -> Optional[float]:
    start, end = _day_bounds_brt(day - timedelta(days=days - 1))
    end = _day_bounds_brt(day)[1]
    result = await db.execute(
        text("""
            SELECT EXTRACT(EPOCH FROM (created_at - timestamp))
            FROM detections
            WHERE timestamp >= :start AND timestamp < :end
              AND created_at IS NOT NULL AND timestamp IS NOT NULL
        """),
        {"start": start, "end": end},
    )
    latencies = [float(row[0]) for row in result if row[0] is not None and row[0] >= 0]
    if not latencies:
        return None
    return round(float(np.percentile(np.array(latencies), 95)), 1)


# ---------------------------------------------------------------------------
# I3 — Qualidade da identificação (bbox extraction)
# ---------------------------------------------------------------------------

async def _compute_i3(db: AsyncSession, day: date_cls) -> IndicatorResult:
    day_start, day_end = _day_bounds_brt(day)
    sql = text("""
        WITH today AS (
          SELECT id FROM detections
          WHERE timestamp >= :day_start AND timestamp < :day_end
        ),
        agg AS (
          SELECT
            d.id,
            BOOL_OR(o.id IS NOT NULL)             AS has_offender,
            BOOL_OR(o.offender_bbox IS NOT NULL)  AS has_bbox
          FROM today d
          LEFT JOIN detection_offenders o ON o.detection_id = d.id
          GROUP BY d.id
        )
        SELECT
          COUNT(*) FILTER (WHERE has_offender)              AS dets_with_offender,
          COUNT(*) FILTER (WHERE has_offender AND has_bbox) AS dets_with_bbox
        FROM agg
    """)
    result = await db.execute(sql, {"day_start": day_start, "day_end": day_end})
    row = result.first()
    with_off = int(row[0] or 0)
    with_bbox = int(row[1] or 0)

    value = (100.0 * with_bbox / with_off) if with_off else None
    value_text = f"{value:.0f}%" if value is not None else "n/d"

    rolling_7d = await _rolling_i3(db, day, days=7)
    rolling_30d = await _rolling_i3(db, day, days=30)

    return IndicatorResult(
        code="I3",
        name="Qualidade da identificação",
        target_text=f"≥ {settings.KPI_I3_TARGET:.0f}%",
        value=value,
        value_text=value_text,
        status=_classify(value, settings.KPI_I3_TARGET),
        rolling_7d=rolling_7d,
        rolling_30d=rolling_30d,
        rolling_7d_text=_format_pct(rolling_7d),
        rolling_30d_text=_format_pct(rolling_30d),
        extra={"dets_with_offender": with_off, "dets_with_bbox": with_bbox},
    )


async def _rolling_i3(db: AsyncSession, day: date_cls, days: int) -> Optional[float]:
    start, _ = _day_bounds_brt(day - timedelta(days=days - 1))
    _, end = _day_bounds_brt(day)
    sql = text("""
        WITH today AS (
          SELECT id FROM detections
          WHERE timestamp >= :start AND timestamp < :end
        ),
        agg AS (
          SELECT
            d.id,
            BOOL_OR(o.id IS NOT NULL)             AS has_offender,
            BOOL_OR(o.offender_bbox IS NOT NULL)  AS has_bbox
          FROM today d
          LEFT JOIN detection_offenders o ON o.detection_id = d.id
          GROUP BY d.id
        )
        SELECT
          COUNT(*) FILTER (WHERE has_offender),
          COUNT(*) FILTER (WHERE has_offender AND has_bbox)
        FROM agg
    """)
    result = await db.execute(sql, {"start": start, "end": end})
    row = result.first()
    with_off = int(row[0] or 0)
    with_bbox = int(row[1] or 0)
    return round(100.0 * with_bbox / with_off, 1) if with_off else None


# ---------------------------------------------------------------------------
# I4 — Assertividade (Agent-1 vs Agent-2)
# ---------------------------------------------------------------------------

def _read_cascade_audit_day(day: date_cls) -> tuple[int, int]:
    """Return (agent1_triggered_count, both_agreed_count) for the given BRT day."""
    day_dir = Path(settings.WORKER_STATE_DIR) / "gemini_cascade_audit" / day.strftime("%Y-%m-%d")
    if not day_dir.exists():
        return 0, 0
    agent1_yes = 0
    both_yes = 0
    for jsonl in day_dir.glob("*.jsonl"):
        try:
            with jsonl.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("agent1_triggered"):
                        agent1_yes += 1
                        if r.get("agent2_ran") and r.get("agent2_disposal"):
                            both_yes += 1
        except OSError:
            logger.debug("cascade audit read failed for %s", jsonl, exc_info=True)
    return agent1_yes, both_yes


async def _compute_i4(day: date_cls) -> IndicatorResult:
    agent1_yes, both_yes = _read_cascade_audit_day(day)
    value = (100.0 * both_yes / agent1_yes) if agent1_yes else None
    value_text = f"{value:.0f}%" if value is not None else "n/d"

    def _rolling(days: int) -> Optional[float]:
        a, b = 0, 0
        for i in range(days):
            d = day - timedelta(days=i)
            x, y = _read_cascade_audit_day(d)
            a += x
            b += y
        return round(100.0 * b / a, 1) if a else None

    rolling_7d = _rolling(7)
    rolling_30d = _rolling(30)

    return IndicatorResult(
        code="I4",
        name="Assertividade das detecções",
        target_text=f"≥ {settings.KPI_I4_TARGET:.0f}%",
        value=value,
        value_text=value_text,
        status=_classify(value, settings.KPI_I4_TARGET),
        rolling_7d=rolling_7d,
        rolling_30d=rolling_30d,
        rolling_7d_text=_format_pct(rolling_7d),
        rolling_30d_text=_format_pct(rolling_30d),
        extra={"agent1_triggered": agent1_yes, "both_agreed": both_yes},
    )


# ---------------------------------------------------------------------------
# I5 — Completude do dossiê
# ---------------------------------------------------------------------------

async def _compute_i5(db: AsyncSession, day: date_cls) -> IndicatorResult:
    day_start, day_end = _day_bounds_brt(day)
    sql = text("""
        SELECT
          COUNT(*) AS total,
          COUNT(*) FILTER (
            WHERE image_url IS NOT NULL AND image_url <> ''
              AND latitude IS NOT NULL AND longitude IS NOT NULL
              AND bairro IS NOT NULL
              AND waste_type IS NOT NULL
              AND volume_m3 IS NOT NULL AND volume_m3 > 0
          ) AS complete
        FROM detections
        WHERE timestamp >= :day_start AND timestamp < :day_end
    """)
    result = await db.execute(sql, {"day_start": day_start, "day_end": day_end})
    row = result.first()
    total = int(row[0] or 0)
    complete = int(row[1] or 0)
    value = (100.0 * complete / total) if total else None
    value_text = f"{value:.0f}%" if value is not None else "n/d"

    async def _rolling(days: int) -> Optional[float]:
        start, _ = _day_bounds_brt(day - timedelta(days=days - 1))
        _, end = _day_bounds_brt(day)
        r = await db.execute(sql.bindparams(day_start=start, day_end=end))
        rr = r.first()
        t = int(rr[0] or 0)
        c = int(rr[1] or 0)
        return round(100.0 * c / t, 1) if t else None

    rolling_7d = await _rolling(7)
    rolling_30d = await _rolling(30)

    return IndicatorResult(
        code="I5",
        name="Completude do dossiê",
        target_text=f"{settings.KPI_I5_TARGET:.0f}%",
        value=value,
        value_text=value_text,
        status=_classify(value, settings.KPI_I5_TARGET),
        rolling_7d=rolling_7d,
        rolling_30d=rolling_30d,
        rolling_7d_text=_format_pct(rolling_7d),
        rolling_30d_text=_format_pct(rolling_30d),
        extra={"total": total, "complete": complete},
    )


# ---------------------------------------------------------------------------
# Activity block
# ---------------------------------------------------------------------------

async def _compute_activity(
    db: AsyncSession, day: date_cls, cameras_uptime: list[CameraUptime]
) -> DailyActivity:
    day_start, day_end = _day_bounds_brt(day)

    total_result = await db.execute(
        select(func.count(Detection.id))
        .where(Detection.timestamp >= day_start)
        .where(Detection.timestamp < day_end)
    )
    total = int(total_result.scalar_one() or 0)

    rpa_result = await db.execute(
        select(
            Detection.rpa,
            func.count(Detection.id).label("count"),
            func.array_agg(func.distinct(Detection.bairro)).label("bairros"),
        )
        .where(Detection.timestamp >= day_start)
        .where(Detection.timestamp < day_end)
        .group_by(Detection.rpa)
        .order_by(func.count(Detection.id).desc())
    )
    by_rpa = [
        ActivityByRpa(
            rpa=row.rpa,
            bairros=[b for b in (row.bairros or []) if b],
            count=int(row.count),
        )
        for row in rpa_result
    ]

    thirty_days_ago_start = _day_bounds_brt(day - timedelta(days=29))[0]
    hot_result = await db.execute(
        select(
            Detection.logradouro,
            Detection.bairro,
            Detection.rpa,
            func.count(Detection.id).label("count"),
        )
        .where(Detection.timestamp >= thirty_days_ago_start)
        .where(Detection.timestamp < day_end)
        .where(Detection.logradouro.isnot(None))
        .group_by(Detection.logradouro, Detection.bairro, Detection.rpa)
        .having(func.count(Detection.id) > 1)
        .order_by(func.count(Detection.id).desc())
        .limit(5)
    )
    hotspots = [
        HotspotLocation(
            logradouro=row.logradouro,
            bairro=row.bairro,
            rpa=row.rpa,
            count=int(row.count),
        )
        for row in hot_result
    ]

    worst = min(cameras_uptime, key=lambda c: c.uptime_pct) if cameras_uptime else None

    return DailyActivity(
        total_detections=total,
        by_rpa=by_rpa,
        top_hotspots_30d=hotspots,
        worst_camera=worst,
        cameras_uptime=cameras_uptime,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def build_daily_report(db: AsyncSession, day: date_cls) -> DailyKPIReport:
    i1, cameras_uptime = await _compute_i1(db, day)
    i2 = await _compute_i2(db, day)
    i3 = await _compute_i3(db, day)
    i4 = await _compute_i4(day)
    i5 = await _compute_i5(db, day)
    activity = await _compute_activity(db, day, cameras_uptime)

    return DailyKPIReport(
        date=day,
        date_br=day.strftime("%d/%m/%Y"),
        generated_at=datetime.now(BRT).isoformat(),
        dashboard_url=settings.REPORT_DASHBOARD_URL,
        i1=i1,
        i2=i2,
        i3=i3,
        i4=i4,
        i5=i5,
        activity=activity,
    )
