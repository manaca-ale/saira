from datetime import date as date_cls
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field


class BillingRow(BaseModel):
    camera_id: Optional[int] = None
    camera_name: Optional[str] = None
    rpa: Optional[str] = None
    agent: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal


class BillingTotals(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal


class DailyBillingResponse(BaseModel):
    date: date_cls
    totals: BillingTotals
    previous_day_cost_usd: Optional[Decimal] = None
    delta_pct: Optional[float] = Field(
        None, description="% change vs previous day. None when previous day had no calls."
    )
    rows: List[BillingRow]


class DailyTotal(BaseModel):
    date: date_cls
    calls: int
    cost_usd: Decimal


class BillingRangeResponse(BaseModel):
    start: date_cls
    end: date_cls
    days: List[DailyTotal]


class TestEmailRequest(BaseModel):
    to: Optional[List[str]] = Field(
        None,
        description="Override recipients. Defaults to BILLING_REPORT_RECIPIENTS env.",
    )
    date: Optional[date_cls] = Field(
        None, description="Report date. Defaults to yesterday (BRT)."
    )


class TestEmailResponse(BaseModel):
    sent: bool
    recipients: List[str]
    date: date_cls
    subject: str
    error: Optional[str] = None
