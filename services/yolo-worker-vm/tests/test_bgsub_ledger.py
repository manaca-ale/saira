"""Tests for the BGSUB persistent decision ledger (Camp 39).

Mirrors the DINOv2 shadow ledger: must capture filtered AND passed decisions
(with persistence — previously invisible for passes), skip non-scored rows,
and never raise.
"""
from __future__ import annotations

import json
from pathlib import Path

from worker import bgsub_filter
from worker.bgsub_filter import FilterResult, record_decision


def _read_ledger(d: Path) -> list[dict]:
    p = d / bgsub_filter.SHADOW_LEDGER_NAME
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_records_filtered_and_passed(tmp_path):
    record_decision(
        gate_request_id="req-sup", device_id="esp32_005",
        result=FilterResult(should_suppress=True, reason="filtered", persistence=120.0,
                            n_frames_ok=2, n_frames_total=40, mode="single"),
        shadow=True, threshold=1000, models_dir=str(tmp_path),
    )
    record_decision(
        gate_request_id="req-pass", device_id="esp32_005",
        result=FilterResult(should_suppress=False, reason="passed", persistence=5480.0,
                            n_frames_ok=39, n_frames_total=40, mode="single"),
        shadow=True, threshold=1000, models_dir=str(tmp_path),
    )
    rows = _read_ledger(tmp_path)
    assert len(rows) == 2
    sup, pas = rows
    assert sup["gate_request_id"] == "req-sup" and sup["should_suppress"] is True
    assert sup["shadow"] is True and sup["persistence"] == 120.0
    assert sup["threshold"] == 1000.0 and sup["device_id"] == "esp32_005"
    assert "ts" in sup and sup["mode"] == "single"
    assert pas["should_suppress"] is False and pas["reason"] == "passed"
    assert pas["persistence"] == 5480.0  # pass persistence agora visível


def test_skips_non_scored_reasons(tmp_path):
    for reason in ("skipped_disabled", "skipped_no_polygon", "skipped_no_model", "error"):
        record_decision(
            gate_request_id=f"req-{reason}", device_id="esp32_005",
            result=FilterResult(should_suppress=False, reason=reason),
            shadow=False, threshold=1000, models_dir=str(tmp_path),
        )
    assert _read_ledger(tmp_path) == []


def test_never_raises_on_bad_dir():
    # caminho inválido no Windows/Linux — deve logar warning e seguir
    record_decision(
        gate_request_id="req-x", device_id="esp32_005",
        result=FilterResult(should_suppress=True, reason="filtered"),
        shadow=True, threshold=1000, models_dir="\0invalid\0path",
    )
