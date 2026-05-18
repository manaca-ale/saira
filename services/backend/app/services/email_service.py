"""Resend email sender used by the daily billing report.

Single function: send_email(to_addrs, subject, html_body, text_body). Returns
True on success, False on failure (logs error). Never raises.

Uses Resend HTTP API via the official Python SDK — same provider as
Manacafinance for consistency. RESEND_API_KEY + EMAIL_FROM come from env.
"""
from __future__ import annotations

import logging
from typing import Optional

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_email(
    *,
    to_addrs: list[str],
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
) -> bool:
    if not to_addrs:
        logger.warning("send_email called with empty to_addrs — skipping")
        return False
    if not settings.RESEND_API_KEY:
        logger.error(
            "Resend not configured (RESEND_API_KEY empty) — email not sent"
        )
        return False
    if not settings.EMAIL_FROM:
        logger.error(
            "Resend not configured (EMAIL_FROM empty) — email not sent"
        )
        return False

    resend.api_key = settings.RESEND_API_KEY
    from_address = (
        f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        if settings.EMAIL_FROM_NAME
        else settings.EMAIL_FROM
    )
    params: dict = {
        "from": from_address,
        "to": to_addrs,
        "subject": subject,
        "html": html_body,
    }
    if text_body:
        params["text"] = text_body

    try:
        result = resend.Emails.send(params)
        email_id = result.get("id") if isinstance(result, dict) else None
        logger.info(
            "billing email sent: recipients=%d subject=%r resend_id=%s",
            len(to_addrs), subject, email_id,
        )
        return True
    except Exception:
        logger.exception("send_email failed (non-fatal)")
        return False


def parse_recipients(raw: str) -> list[str]:
    """Split a comma-separated recipient list, trimming and skipping empties."""
    if not raw:
        return []
    return [addr.strip() for addr in raw.split(",") if addr.strip()]
