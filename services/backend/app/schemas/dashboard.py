from pydantic import BaseModel
from typing import List
from decimal import Decimal


class DashboardStats(BaseModel):
    """Estatísticas oficiais do dashboard.

    total_occurrences conta apenas detecções CONFIRMADAS (validadas pelo usuário).
    Os contadores por estado expõem o backlog de revisão.
    """

    total_occurrences: int
    daily_volume_m3: Decimal
    pending_count: int
    confirmed_count: int
    rejected_count: int
    indeterminate_count: int


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
