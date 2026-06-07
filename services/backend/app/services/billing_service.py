"""Aggregations and HTML rendering for the daily Gemini billing report."""
from __future__ import annotations

import logging
from datetime import date as date_cls, datetime, timedelta
from decimal import Decimal
from html import escape
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.billing import (
    BillingRow, BillingTotals, DailyBillingResponse, DailyTotal,
)

logger = logging.getLogger(__name__)

BRT = ZoneInfo("America/Sao_Paulo")


def yesterday_brt() -> date_cls:
    return (datetime.now(BRT) - timedelta(days=1)).date()


def today_brt() -> date_cls:
    return datetime.now(BRT).date()


async def fetch_daily_rows(
    db: AsyncSession,
    target_date: date_cls,
    *,
    camera_id: Optional[int] = None,
    agent: Optional[str] = None,
) -> list[BillingRow]:
    """Aggregate gemini_call_log by (camera, agent, model) for a given BRT date."""
    where_extra = ""
    params: dict = {"target_date": target_date}
    if camera_id is not None:
        where_extra += " AND g.camera_id = :camera_id"
        params["camera_id"] = camera_id
    if agent is not None:
        where_extra += " AND g.agent = :agent"
        params["agent"] = agent

    sql = text(
        f"""
        SELECT g.camera_id, c.name AS camera_name, c.rpa,
               g.agent, g.model,
               COUNT(*) AS calls,
               COALESCE(SUM(g.input_tokens), 0) AS input_tokens,
               COALESCE(SUM(g.output_tokens), 0) AS output_tokens,
               COALESCE(SUM(g.total_tokens), 0) AS total_tokens,
               COALESCE(SUM(g.estimated_cost_usd), 0) AS cost_usd
        FROM gemini_call_log g
        LEFT JOIN cameras c ON c.id = g.camera_id
        WHERE g.call_date_brt = :target_date
          AND g.success = TRUE
          {where_extra}
        GROUP BY g.camera_id, c.name, c.rpa, g.agent, g.model
        ORDER BY cost_usd DESC, g.camera_id ASC, g.agent ASC
        """
    )
    result = await db.execute(sql, params)
    rows: list[BillingRow] = []
    for r in result.mappings():
        rows.append(
            BillingRow(
                camera_id=r["camera_id"],
                camera_name=r["camera_name"],
                rpa=r["rpa"],
                agent=r["agent"],
                model=r["model"],
                calls=int(r["calls"] or 0),
                input_tokens=int(r["input_tokens"] or 0),
                output_tokens=int(r["output_tokens"] or 0),
                total_tokens=int(r["total_tokens"] or 0),
                cost_usd=Decimal(r["cost_usd"] or 0),
            )
        )
    return rows


async def fetch_daily_total(db: AsyncSession, target_date: date_cls) -> BillingTotals:
    sql = text(
        """
        SELECT COUNT(*) AS calls,
               COALESCE(SUM(input_tokens), 0) AS input_tokens,
               COALESCE(SUM(output_tokens), 0) AS output_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               COALESCE(SUM(estimated_cost_usd), 0) AS cost_usd
        FROM gemini_call_log
        WHERE call_date_brt = :target_date AND success = TRUE
        """
    )
    result = await db.execute(sql, {"target_date": target_date})
    r = result.mappings().one()
    return BillingTotals(
        calls=int(r["calls"] or 0),
        input_tokens=int(r["input_tokens"] or 0),
        output_tokens=int(r["output_tokens"] or 0),
        total_tokens=int(r["total_tokens"] or 0),
        cost_usd=Decimal(r["cost_usd"] or 0),
    )


async def fetch_range(
    db: AsyncSession, start: date_cls, end: date_cls
) -> list[DailyTotal]:
    sql = text(
        """
        SELECT call_date_brt AS day,
               COUNT(*) AS calls,
               COALESCE(SUM(estimated_cost_usd), 0) AS cost_usd
        FROM gemini_call_log
        WHERE call_date_brt BETWEEN :start AND :end AND success = TRUE
        GROUP BY call_date_brt
        ORDER BY call_date_brt ASC
        """
    )
    result = await db.execute(sql, {"start": start, "end": end})
    return [
        DailyTotal(
            date=r["day"],
            calls=int(r["calls"] or 0),
            cost_usd=Decimal(r["cost_usd"] or 0),
        )
        for r in result.mappings()
    ]


async def build_daily_report(
    db: AsyncSession, target_date: date_cls
) -> DailyBillingResponse:
    rows = await fetch_daily_rows(db, target_date)
    totals = await fetch_daily_total(db, target_date)
    prev_total = await fetch_daily_total(db, target_date - timedelta(days=1))
    prev_cost = prev_total.cost_usd
    delta_pct: Optional[float] = None
    if prev_cost and prev_cost != 0:
        delta_pct = float(
            (totals.cost_usd - prev_cost) / prev_cost * Decimal(100)
        )
    return DailyBillingResponse(
        date=target_date,
        totals=totals,
        previous_day_cost_usd=prev_cost,
        delta_pct=delta_pct,
        rows=rows,
    )


def _fmt_usd(value: Decimal) -> str:
    return f"US$ {value:.4f}"


def _fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def render_email_subject(report: DailyBillingResponse) -> str:
    return f"[SAIRA] Custo Gemini — {report.date.isoformat()} — {_fmt_usd(report.totals.cost_usd)}"


def render_email_html(report: DailyBillingResponse) -> str:
    """Render the daily report as a self-contained HTML email body."""
    if report.delta_pct is None:
        delta_html = ""
    else:
        color = "#1a7f37" if report.delta_pct >= 0 else "#d1242f"
        sign = "+" if report.delta_pct >= 0 else ""
        prev_str = (
            _fmt_usd(report.previous_day_cost_usd) if report.previous_day_cost_usd else "US$ 0"
        )
        delta_html = (
            f' (<span style="color:{color}">{sign}{report.delta_pct:.1f}%</span>'
            f' vs dia anterior {escape(prev_str)})'
        )

    rows_html = "".join(
        f"""
        <tr>
            <td>{escape(r.camera_name or "—")}</td>
            <td>{escape(r.rpa or "—")}</td>
            <td>{escape(r.agent)}</td>
            <td>{escape(r.model)}</td>
            <td style="text-align:right">{_fmt_int(r.calls)}</td>
            <td style="text-align:right">{_fmt_int(r.input_tokens)}</td>
            <td style="text-align:right">{_fmt_int(r.output_tokens)}</td>
            <td style="text-align:right"><b>{_fmt_usd(r.cost_usd)}</b></td>
        </tr>
        """
        for r in report.rows
    )

    if not rows_html:
        rows_html = (
            '<tr><td colspan="8" style="text-align:center;color:#666">'
            "Nenhuma chamada Gemini bem-sucedida no dia.</td></tr>"
        )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>SAIRA — Custo Gemini diário</title></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1f2328;max-width:920px;margin:24px auto;padding:0 16px">
<h2 style="margin:0 0 8px 0">Custo Gemini diário</h2>
<p style="margin:0 0 16px 0;color:#57606a">
   Data: <b>{report.date.isoformat()}</b> (BRT)<br>
   Total: <b>{_fmt_usd(report.totals.cost_usd)}</b>{delta_html}<br>
   Chamadas: <b>{_fmt_int(report.totals.calls)}</b> · Tokens in: <b>{_fmt_int(report.totals.input_tokens)}</b> · Tokens out: <b>{_fmt_int(report.totals.output_tokens)}</b>
</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:13px">
<thead style="background:#f6f8fa">
<tr>
<th>Câmera</th><th>RPA</th><th>Agente</th><th>Modelo</th>
<th>Calls</th><th>Tokens in</th><th>Tokens out</th><th>USD</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
<tfoot style="background:#f6f8fa">
<tr>
<th colspan="4" style="text-align:right">TOTAL</th>
<th style="text-align:right">{_fmt_int(report.totals.calls)}</th>
<th style="text-align:right">{_fmt_int(report.totals.input_tokens)}</th>
<th style="text-align:right">{_fmt_int(report.totals.output_tokens)}</th>
<th style="text-align:right">{_fmt_usd(report.totals.cost_usd)}</th>
</tr>
</tfoot>
</table>
<p style="color:#57606a;font-size:11px;margin-top:16px">
   Câmeras sem chamadas bem-sucedidas no dia são omitidas.<br>
   Preços: input US$ {settings.GEMINI_INPUT_TOKEN_PRICE_PER_1M:.3f}/1M · output US$ {settings.GEMINI_OUTPUT_TOKEN_PRICE_PER_1M:.3f}/1M (env, fonte: worker)<br>
   Estimativa baseada em <code>usage_metadata</code> retornado pela Gemini API por chamada.
</p>
</body></html>"""


def render_email_text(report: DailyBillingResponse) -> str:
    """Plain-text fallback for the multipart email."""
    lines = [
        f"SAIRA — Custo Gemini diário",
        f"Data: {report.date.isoformat()} (BRT)",
        f"Total: {_fmt_usd(report.totals.cost_usd)}",
    ]
    if report.delta_pct is not None:
        prev_str = _fmt_usd(report.previous_day_cost_usd or Decimal(0))
        lines.append(f"  vs dia anterior {prev_str} ({report.delta_pct:+.1f}%)")
    lines.append(f"Chamadas: {report.totals.calls} · Tokens in: {report.totals.input_tokens} · out: {report.totals.output_tokens}")
    lines.append("")
    lines.append(f"{'Câmera':<24} {'RPA':<4} {'Agente':<7} {'Modelo':<28} {'Calls':>6} {'USD':>10}")
    for r in report.rows:
        lines.append(
            f"{(r.camera_name or '—')[:24]:<24} "
            f"{(r.rpa or '—')[:4]:<4} "
            f"{r.agent[:7]:<7} "
            f"{r.model[:28]:<28} "
            f"{r.calls:>6} "
            f"{_fmt_usd(r.cost_usd):>10}"
        )
    return "\n".join(lines)
