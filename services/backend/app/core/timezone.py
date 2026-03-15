from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


BRAZIL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def now_brazil() -> datetime:
    """Timezone-aware current datetime in Brazil timezone."""
    return datetime.now(BRAZIL_TIMEZONE)
