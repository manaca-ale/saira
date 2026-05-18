"""Pydantic schemas for the daily KPI report (5 indicadores SAÍRA)."""
from __future__ import annotations

from enum import Enum
from datetime import date as date_cls
from typing import Optional, List

from pydantic import BaseModel, Field


class IndicatorStatus(str, Enum):
    OK = "OK"
    ATENCAO = "ATENCAO"
    ABAIXO = "ABAIXO"
    SEM_DADOS = "SEM_DADOS"


class IndicatorResult(BaseModel):
    """Result of one of the 5 indicators (I1-I5) for a given day."""

    code: str                              # I1, I2, I3, I4, I5
    name: str                              # Confiabilidade da vigilância, etc.
    target_text: str                       # "≥ 90%", "p95 ≤ 60s"
    value: Optional[float] = None          # main numeric value (percent or seconds)
    value_text: str                        # "94%" or "p50=12s · p95=48s" or "n/d"
    status: IndicatorStatus
    rolling_7d: Optional[float] = None
    rolling_30d: Optional[float] = None
    rolling_7d_text: Optional[str] = None
    rolling_30d_text: Optional[str] = None
    notes: Optional[str] = None
    extra: dict = Field(default_factory=dict)


class CameraUptime(BaseModel):
    camera_id: int
    device_id: Optional[str]
    name: Optional[str]
    uptime_pct: float
    expected_buckets: int
    received_buckets: int
    capture_interval_seconds: int


class ActivityByRpa(BaseModel):
    rpa: Optional[str]
    bairros: List[str]
    count: int


class HotspotLocation(BaseModel):
    logradouro: Optional[str]
    bairro: Optional[str]
    rpa: Optional[str]
    count: int


class DailyActivity(BaseModel):
    total_detections: int
    by_rpa: List[ActivityByRpa]
    top_hotspots_30d: List[HotspotLocation]
    worst_camera: Optional[CameraUptime] = None
    cameras_uptime: List[CameraUptime] = Field(default_factory=list)


class DailyKPIReport(BaseModel):
    """Top-level daily report payload (one per date)."""

    date: date_cls
    date_br: str                # "18/05/2026"
    generated_at: str           # ISO timestamp with TZ
    dashboard_url: str
    i1: IndicatorResult
    i2: IndicatorResult
    i3: IndicatorResult
    i4: IndicatorResult
    i5: IndicatorResult
    activity: DailyActivity
