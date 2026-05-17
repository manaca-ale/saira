"""SMTP email sender used by the daily billing report.

Single function: send_email(to_addrs, subject, html_body, text_body). Returns
True on success, False on failure (logs error). Never raises.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

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
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.error(
            "SMTP not configured (SMTP_USER/SMTP_PASSWORD empty) — email not sent"
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_USER))
    msg["To"] = ", ".join(to_addrs)
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=30
        ) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USER, to_addrs, msg.as_string())
        logger.info(
            "billing email sent: recipients=%d subject=%r", len(to_addrs), subject
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
