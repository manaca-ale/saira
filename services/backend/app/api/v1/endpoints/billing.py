"""Billing endpoints — daily Gemini cost report.

Endpoints:
- GET  /api/v1/billing/daily?date=YYYY-MM-DD&camera_id=&agent=
- GET  /api/v1/billing/range?start=YYYY-MM-DD&end=YYYY-MM-DD
- POST /api/v1/billing/test-email           — fires the email job on demand
"""
from __future__ import annotations

import logging
from datetime import date as date_cls, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.user import User
from app.schemas.billing import (
    BillingRangeResponse, DailyBillingResponse,
    TestEmailRequest, TestEmailResponse,
)
from app.services.billing_service import (
    build_daily_report, fetch_range, render_email_html,
    render_email_subject, render_email_text, today_brt, yesterday_brt,
)
from app.services.email_service import parse_recipients, send_email

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/daily", response_model=DailyBillingResponse)
async def get_daily_billing(
    date: Optional[date_cls] = Query(
        None, description="BRT date. Defaults to today (BRT)."
    ),
    camera_id: Optional[int] = Query(None, description="Filter by camera id."),
    agent: Optional[str] = Query(
        None, description="Filter by agent ('gate' or 'detail')."
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyBillingResponse:
    """Per-camera, per-agent Gemini cost breakdown for a given day (BRT)."""
    target = date or today_brt()
    report = await build_daily_report(db, target)
    if camera_id is not None or agent is not None:
        report.rows = [
            r for r in report.rows
            if (camera_id is None or r.camera_id == camera_id)
            and (agent is None or r.agent == agent)
        ]
    return report


@router.get("/range", response_model=BillingRangeResponse)
async def get_billing_range(
    start: date_cls = Query(..., description="Start date (BRT, inclusive)."),
    end: date_cls = Query(..., description="End date (BRT, inclusive)."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillingRangeResponse:
    """Daily totals across a date range — for time-series charts."""
    if end < start:
        raise HTTPException(
            status_code=400, detail="end must be >= start"
        )
    if (end - start).days > 366:
        raise HTTPException(
            status_code=400, detail="range cannot exceed 366 days"
        )
    days = await fetch_range(db, start, end)
    return BillingRangeResponse(start=start, end=end, days=days)


@router.post("/test-email", response_model=TestEmailResponse)
async def post_test_email(
    payload: TestEmailRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestEmailResponse:
    """Fire the daily report email immediately (uses payload.date or yesterday)."""
    target = payload.date or yesterday_brt()
    recipients = payload.to or parse_recipients(settings.BILLING_REPORT_RECIPIENTS)
    if not recipients:
        raise HTTPException(
            status_code=400,
            detail="No recipients configured (BILLING_REPORT_RECIPIENTS env or payload.to).",
        )
    report = await build_daily_report(db, target)
    subject = render_email_subject(report)
    try:
        ok = send_email(
            to_addrs=recipients,
            subject=subject,
            html_body=render_email_html(report),
            text_body=render_email_text(report),
        )
        return TestEmailResponse(
            sent=ok,
            recipients=recipients,
            date=target,
            subject=subject,
            error=None if ok else "SMTP send returned False — see backend logs.",
        )
    except Exception as exc:  # defensive — send_email already swallows internally
        logger.exception("test-email failed unexpectedly")
        return TestEmailResponse(
            sent=False,
            recipients=recipients,
            date=target,
            subject=subject,
            error=str(exc),
        )
