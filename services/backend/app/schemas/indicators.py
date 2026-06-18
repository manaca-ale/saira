"""Schemas dos Indicadores de Resultado (Anexo II — SAIRA).

Cada indicador é derivado dos dados reais da plataforma:
- I1 Confiabilidade da vigilância  → camera_heartbeats
- I2 Velocidade do alerta           → detections (+ notifications)
- I3 Qualidade da identificação      → cascade_decisions
- I4 Assertividade das detecções     → cascade_decisions (modelo) + detections (humano)
- I5 Completude do dossiê            → detections
- I6 Ações / detecções               → fora de escopo (ação externa do fiscal)
"""
from typing import List, Optional
from pydantic import BaseModel


class IndicatorPeriod(BaseModel):
    start: str
    end: str


# ---------------------------------------------------------------------------
# I1 — Confiabilidade da vigilância (%)
# ---------------------------------------------------------------------------
class CameraUptime(BaseModel):
    camera_id: int
    name: Optional[str] = None
    device_id: Optional[str] = None
    bairro: Optional[str] = None
    uptime_pct: Optional[float] = None  # None quando não há heartbeats no período
    online_checks: int
    total_checks: int


class SurveillanceReliability(BaseModel):
    period: IndicatorPeriod
    average_uptime_pct: Optional[float] = None  # média dos pontos com dados
    worst_uptime_pct: Optional[float] = None    # pior ponto da semana
    worst_camera: Optional[str] = None
    cameras: List[CameraUptime]
    has_data: bool


# ---------------------------------------------------------------------------
# I2 — Velocidade do alerta (s)
# ---------------------------------------------------------------------------
class LatencyStat(BaseModel):
    label: str          # "até registro" | "até notificação"
    p50_seconds: Optional[float] = None
    p95_seconds: Optional[float] = None
    sample_size: int


class AlertSpeed(BaseModel):
    period: IndicatorPeriod
    # Latência primária reportada (até a notificação se houver, senão até o registro).
    primary: LatencyStat
    breakdown: List[LatencyStat]


# ---------------------------------------------------------------------------
# I3 — Qualidade da identificação (%)
# ---------------------------------------------------------------------------
class IdentificationQuality(BaseModel):
    period: IndicatorPeriod
    quality_pct: Optional[float] = None  # crops extraídos / infratores presentes
    crops_extracted: int
    offenders_present: int
    has_data: bool


# ---------------------------------------------------------------------------
# I4 — Assertividade das detecções (%) — duas leituras
# ---------------------------------------------------------------------------
class AccuracyReading(BaseModel):
    accuracy_pct: Optional[float] = None
    confirmed: int
    rejected: int
    total_evaluated: int
    has_data: bool


class DetectionAccuracy(BaseModel):
    period: IndicatorPeriod
    model: AccuracyReading   # I4a — cascata Agent-1 + Agent-2
    human: AccuracyReading   # I4b — classificação do fiscal


# ---------------------------------------------------------------------------
# I5 — Completude do dossiê (%)
# ---------------------------------------------------------------------------
class DossierCompleteness(BaseModel):
    period: IndicatorPeriod
    completeness_pct: Optional[float] = None
    complete: int
    total: int
    # quantas ocorrências faltam cada campo (para diagnóstico)
    missing_photo: int
    missing_location: int
    missing_datetime: int
    missing_waste_type: int
    missing_volume: int
    has_data: bool


# ---------------------------------------------------------------------------
# Summary — snapshot para os KPI cards
# ---------------------------------------------------------------------------
class IndicatorCard(BaseModel):
    id: str                       # "I1".."I6"
    name: str
    unit: str                     # "%" | "s" | ""
    polarity: str                 # "higher_better" | "lower_better"
    periodicity: str              # "Semanal" | "Mensal"
    value: Optional[float] = None     # valor principal
    secondary: Optional[float] = None # valor secundário (ex: pior ponto, p95, humano)
    value_label: Optional[str] = None
    secondary_label: Optional[str] = None
    has_data: bool = False
    trackable: bool = True            # I6 = False


class IndicatorsSummary(BaseModel):
    period: IndicatorPeriod
    cards: List[IndicatorCard]
