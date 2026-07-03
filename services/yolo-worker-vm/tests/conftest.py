"""Test bootstrap: stub heavy DB/broker drivers absent outside the container.

Some worker modules (worker.db → worker.main) import psycopg2/redis at module
load. The unit tests here exercise pure logic (crops, structural delta, prompt
selection, recovery gating) and never open a real connection, so we stub the
drivers ONLY when they are not installed — keeping the suite runnable locally
while remaining a no-op in the full container image / CI (where they exist).
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock


def _ensure_stub(name: str, submodules: tuple[str, ...] = ()) -> None:
    try:
        __import__(name)
        return  # real module present (container/CI) — do not shadow it
    except ModuleNotFoundError:
        pass
    # MagicMock so module-level calls (e.g. psycopg2.extras.register_uuid()) no-op.
    sys.modules[name] = MagicMock(name=name)
    for sub in submodules:
        sys.modules[f"{name}.{sub}"] = MagicMock(name=f"{name}.{sub}")


_ensure_stub("psycopg2", ("extras", "pool"))
_ensure_stub("redis")
