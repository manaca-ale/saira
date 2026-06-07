"""Daily KPI report endpoint — JSON, HTML and PDF formats.

Reports the 5 indicators (I1-I5) of the SAÍRA MVP for a given date.
Designed for manual delivery: a human opens the HTML preview, copies it
into Gmail, and (optionally) attaches the PDF version. No SMTP sending here.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from app.api.deps import get_db
from app.services.daily_report_service import build_daily_report
from app.services.pdf_renderer import render_html, render_pdf

router = APIRouter()
logger = logging.getLogger(__name__)

BRT = ZoneInfo("America/Sao_Paulo")


def _resolve_date(date_param: Optional[str]) -> date_cls:
    """Accept YYYY-MM-DD or 'yesterday' / 'today'. Default = yesterday (BRT)."""
    if not date_param or date_param.lower() in ("yesterday", "ontem"):
        return (datetime.now(BRT) - timedelta(days=1)).date()
    if date_param.lower() in ("today", "hoje"):
        return datetime.now(BRT).date()
    try:
        return date_cls.fromisoformat(date_param)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date: {date_param!r}. Use YYYY-MM-DD, 'today' or 'yesterday'.",
        ) from exc


@router.get("/daily", summary="Relatório diário SAÍRA (JSON | HTML | PDF)")
async def get_daily_report(
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD; default = ontem (BRT)"),
    format: str = Query(default="json", pattern="^(json|html|pdf)$"),
    db: AsyncSession = Depends(get_db),
):
    """Generate the daily KPI report. Public endpoint by design — content is
    safe to share with the Prefeitura and the human operator needs frictionless
    access. Add auth here if/when the report becomes sensitive."""
    target_date = _resolve_date(date)
    report = await build_daily_report(db, target_date)

    if format == "json":
        return JSONResponse(content=report.model_dump(mode="json"))

    if format == "html":
        html = render_html(report)
        return HTMLResponse(content=html)

    # PDF
    try:
        pdf_bytes = render_pdf(report)
    except Exception as exc:
        logger.exception("PDF rendering failed for date=%s", target_date)
        raise HTTPException(status_code=500, detail=f"PDF render failed: {exc}") from exc

    filename = f"saira-relatorio-{target_date.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
