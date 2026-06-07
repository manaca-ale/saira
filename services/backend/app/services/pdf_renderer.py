"""Render the daily KPI report as HTML, plain text and PDF (WeasyPrint)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.schemas.report import DailyKPIReport, IndicatorStatus

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=False,
    lstrip_blocks=False,
)

# Color mapping per status (used by HTML template)
_STATUS_COLORS = {
    IndicatorStatus.OK.value:        "#16a34a",  # green
    IndicatorStatus.ATENCAO.value:   "#d97706",  # amber
    IndicatorStatus.ABAIXO.value:    "#dc2626",  # red
    IndicatorStatus.SEM_DADOS.value: "#9ca3af",  # gray
}
_STATUS_LABELS = {
    IndicatorStatus.OK.value:        " OK ",
    IndicatorStatus.ATENCAO.value:   "ATEN",
    IndicatorStatus.ABAIXO.value:    "ABX ",
    IndicatorStatus.SEM_DADOS.value: " ND ",
}


def render_html(report: DailyKPIReport) -> str:
    template = _env.get_template("daily_report.html")
    return template.render(report=report, colors=_STATUS_COLORS, status_labels=_STATUS_LABELS)


def render_text(report: DailyKPIReport) -> str:
    template = _env.get_template("daily_report.txt")
    return template.render(report=report, status_labels=_STATUS_LABELS)


def render_pdf(report: DailyKPIReport) -> bytes:
    """Render HTML → PDF bytes. WeasyPrint is heavy; import lazily."""
    try:
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover - fail loudly if missing in container
        logger.error("WeasyPrint not installed: %s", exc)
        raise

    html = render_html(report)
    return HTML(string=html).write_pdf()
