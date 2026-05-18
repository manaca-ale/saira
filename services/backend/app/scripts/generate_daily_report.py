"""CLI: generate the SAÍRA daily KPI report on demand.

Usage (inside the backend container):
    python -m app.scripts.generate_daily_report --date 2026-05-18 --format pdf --out /app/reports/

Useful for ad-hoc generation, server-side regression of the snapshot job,
or just printing the HTML to inspect rendering offline.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.database import AsyncSessionLocal
from app.services.daily_report_service import build_daily_report
from app.services.pdf_renderer import render_html, render_pdf, render_text

BRT = ZoneInfo("America/Sao_Paulo")


def _parse_date(s: str) -> date_cls:
    s = s.lower().strip()
    if s in ("yesterday", "ontem"):
        return (datetime.now(BRT) - timedelta(days=1)).date()
    if s in ("today", "hoje"):
        return datetime.now(BRT).date()
    return date_cls.fromisoformat(s)


async def _amain(target_date: date_cls, fmt: str, out_dir: Path | None) -> None:
    async with AsyncSessionLocal() as session:
        report = await build_daily_report(session, target_date)

    if fmt == "json":
        import json as _json
        payload = report.model_dump(mode="json")
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{target_date.isoformat()}.json").write_text(
                _json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"WROTE {out_dir / (target_date.isoformat() + '.json')}")
        else:
            print(_json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if fmt == "txt":
        content = render_text(report)
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{target_date.isoformat()}.txt").write_text(content, encoding="utf-8")
            print(f"WROTE {out_dir / (target_date.isoformat() + '.txt')}")
        else:
            sys.stdout.write(content)
        return

    if fmt == "html":
        content = render_html(report)
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{target_date.isoformat()}.html").write_text(content, encoding="utf-8")
            print(f"WROTE {out_dir / (target_date.isoformat() + '.html')}")
        else:
            sys.stdout.write(content)
        return

    # PDF
    pdf_bytes = render_pdf(report)
    if not out_dir:
        out_dir = Path("/app/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{target_date.isoformat()}.pdf"
    pdf_path.write_bytes(pdf_bytes)
    print(f"WROTE {pdf_path} ({len(pdf_bytes)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SAÍRA daily KPI report.")
    parser.add_argument("--date", default="yesterday", help="YYYY-MM-DD | today | yesterday (BRT)")
    parser.add_argument("--format", choices=["pdf", "html", "txt", "json"], default="pdf")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output directory (default /app/reports for PDF, stdout otherwise)")
    args = parser.parse_args()
    asyncio.run(_amain(_parse_date(args.date), args.format, args.out))


if __name__ == "__main__":
    main()
