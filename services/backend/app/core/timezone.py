from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


BRAZIL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def now_brazil() -> datetime:
    """Timezone-aware current datetime in Brazil timezone."""
    return datetime.now(BRAZIL_TIMEZONE)


def now_brazil_naive() -> datetime:
    """Naive datetime (without tzinfo) representing Brazil local time."""
    return now_brazil().replace(tzinfo=None)
