"""APScheduler cron job that emails the daily Gemini billing report.

Runs once per day at BILLING_REPORT_HOUR_BRT:BILLING_REPORT_MINUTE_BRT
(America/Sao_Paulo). Aggregates yesterday's gemini_call_log, renders HTML,
sends via SMTP. Errors are logged but never propagate.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.redis import get_redis
from app.services.billing_service import (
    build_daily_report, render_email_html, render_email_subject, render_email_text,
)
from app.services.email_service import parse_recipients, send_email

logger = logging.getLogger(__name__)
BRT = ZoneInfo("America/Sao_Paulo")

_scheduler: AsyncIOScheduler | None = None


async def _acquire_single_send_lock(target_date) -> bool:
    """Redis SET NX EX lock so only one uvicorn worker sends the email.

    Returns True if THIS process acquired the lock (i.e. should send).
    The key is date-scoped and expires after 12h so a retry next day works.
    """
    try:
        redis = get_redis()
        key = f"saira:billing:daily_report_sent:{target_date.isoformat()}"
        acquired = await redis.set(key, "1", ex=12 * 3600, nx=True)
        return bool(acquired)
    except Exception:
        logger.exception("billing_scheduler: redis lock failed — falling back to send (risk of duplicate)")
        return True


async def run_daily_billing_job() -> None:
    """Compute report for yesterday and email it. Never raises."""
    target_date = (datetime.now(BRT) - timedelta(days=1)).date()
    recipients = parse_recipients(settings.BILLING_REPORT_RECIPIENTS)
    if not recipients:
        logger.warning(
            "billing_scheduler: no recipients configured (BILLING_REPORT_RECIPIENTS) — skipping"
        )
        return
    if not await _acquire_single_send_lock(target_date):
        logger.info(
            "billing_scheduler: another worker already sent report for %s — skipping",
            target_date,
        )
        return
    try:
        async with AsyncSessionLocal() as db:
            report = await build_daily_report(db, target_date)
        subject = render_email_subject(report)
        html = render_email_html(report)
        text = render_email_text(report)
        ok = send_email(
            to_addrs=recipients, subject=subject, html_body=html, text_body=text
        )
        if ok:
            logger.info(
                "billing_scheduler: report sent date=%s rows=%d total_usd=%s recipients=%d",
                target_date, len(report.rows), report.totals.cost_usd, len(recipients),
            )
        else:
            logger.error(
                "billing_scheduler: SMTP send failed date=%s rows=%d",
                target_date, len(report.rows),
            )
    except Exception:
        logger.exception(
            "billing_scheduler: unexpected error building/sending report date=%s",
            target_date,
        )


def start_billing_scheduler() -> None:
    global _scheduler
    if not settings.BILLING_REPORT_ENABLED:
        logger.info("billing_scheduler: disabled (BILLING_REPORT_ENABLED=false)")
        return
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone=BRT)
    _scheduler.add_job(
        run_daily_billing_job,
        trigger=CronTrigger(
            hour=settings.BILLING_REPORT_HOUR_BRT,
            minute=settings.BILLING_REPORT_MINUTE_BRT,
            timezone=BRT,
        ),
        id="daily_gemini_billing_report",
        name="Daily Gemini billing report (email)",
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "billing_scheduler: started cron=%02d:%02d BRT recipients=%s",
        settings.BILLING_REPORT_HOUR_BRT,
        settings.BILLING_REPORT_MINUTE_BRT,
        settings.BILLING_REPORT_RECIPIENTS,
    )


def stop_billing_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("billing_scheduler: error during shutdown")
    _scheduler = None
