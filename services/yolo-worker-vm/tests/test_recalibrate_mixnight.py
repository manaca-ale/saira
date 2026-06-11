"""Tests for the --mix-night frame selection in worker.recalibrate_bgsub (item 6b).

Only the path-selection logic is exercised (no image decode), so cv2 is stubbed
before import — same approach as the other worker tests.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.modules.setdefault("cv2", types.ModuleType("cv2"))

from worker import config  # noqa: E402
from worker import recalibrate_bgsub as rb  # noqa: E402


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


def test_hour_of_filename():
    assert rb._hour_of(Path("03-15-00.jpg")) == 3
    assert rb._hour_of(Path("14-00-00.jpg")) == 14
    assert rb._hour_of(Path("23-59-59.jpg")) == 23


def test_mix_night_balances_pools(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    base = tmp_path / "esp32_005" / "sem_ocorrencia" / "2026" / "06" / "08"
    for i in range(10):
        _touch(base / f"02-{i:02d}-00.jpg")   # night (02h)
    for i in range(40):
        _touch(base / f"12-{i:02d}-00.jpg")   # day (12h)

    picked, meta = rb._pick_mixed_night(
        "esp32_005", 20, night_hours={0, 1, 2, 3, 4, 5},
        night_fraction=0.4, lookback_days=7,
    )

    assert meta["n_night_available"] == 10
    assert meta["n_day_available"] == 40
    assert meta["n_night_picked"] == 8     # round(0.4 * 20)
    assert meta["n_day_picked"] == 12      # remainder
    assert len(picked) == 20


def test_mix_night_falls_back_when_no_night(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    base = tmp_path / "esp32_005" / "sem_ocorrencia" / "2026" / "06" / "08"
    for i in range(30):
        _touch(base / f"12-{i:02d}-00.jpg")   # day only

    picked, meta = rb._pick_mixed_night(
        "esp32_005", 20, night_hours={0, 1, 2, 3, 4, 5},
        night_fraction=0.4, lookback_days=7,
    )

    assert meta["n_night_picked"] == 0
    assert meta["n_day_picked"] == 20
    assert len(picked) == 20


def test_mix_night_spans_multiple_days(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    root = tmp_path / "esp32_005" / "sem_ocorrencia" / "2026" / "06"
    for day in ("06", "07", "08"):
        for i in range(5):
            _touch(root / day / f"03-{i:02d}-00.jpg")   # night across 3 days
    picked, meta = rb._pick_mixed_night(
        "esp32_005", 12, night_hours={0, 1, 2, 3, 4, 5},
        night_fraction=1.0, lookback_days=7,
    )
    assert meta["n_days_scanned"] == 3
    assert meta["n_night_available"] == 15
    assert len(picked) == 12
