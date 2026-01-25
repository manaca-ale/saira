from pydantic import BaseModel
from typing import List
from decimal import Decimal


class DashboardStats(BaseModel):
    total_occurrences: int
    daily_volume_m3: Decimal
    pending_count: int
    in_analysis_count: int
    resolved_count: int


class OccurrencesByMonth(BaseModel):
    month: str
    count: int


class RecurrentLocation(BaseModel):
    logradouro: str
    bairro: str
    rpa: str
    count: int


class VolumeByRPA(BaseModel):
    rpa: str
    avg_volume_m3: Decimal
    total_volume_m3: Decimal
    count: int
