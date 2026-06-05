"""Tests for the DINOv2 shadow-decision persistent ledger (Camp 35).

The ledger must survive container recreate (worker stdout does not), capture both
reject and pass decisions, skip non-scored rows, and never raise.
"""
from __future__ import annotations

import json
from pathlib import Path

from worker import detector_dinov2
from worker.detector_dinov2 import DinoFilterResult, record_shadow_decision


def _read_ledger(d: Path) -> list[dict]:
    p = d / detector_dinov2.SHADOW_LEDGER_NAME
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_records_reject_and_pass(tmp_path):
    record_shadow_decision(
        request_id="req-rej", device_id="esp32_001",
        result=DinoFilterResult(should_reject=True, reason="rejected", p_con=0.0015,
                                threshold=0.5, n_frames_used=3),
        gemini_disposal=True, mode="shadow", models_dir=str(tmp_path),
    )
    record_shadow_decision(
        request_id="req-pass", device_id="esp32_001",
        result=DinoFilterResult(should_reject=False, reason="passed", p_con=0.92,
                                threshold=0.5, n_frames_used=3),
        gemini_disposal=True, mode="shadow", models_dir=str(tmp_path),
    )
    rows = _read_ledger(tmp_path)
    assert len(rows) == 2
    rej, pas = rows
    assert rej["request_id"] == "req-rej" and rej["should_reject"] is True
    assert rej["p_con"] == 0.0015 and rej["reason"] == "rejected"
    assert rej["mode"] == "shadow" and rej["device_id"] == "esp32_001"
    assert rej["gemini_disposal"] is True and "ts" in rej
    assert pas["should_reject"] is False and pas["reason"] == "passed"


def test_skips_non_scored_reasons(tmp_path):
    for reason in ("skipped_disabled", "skipped_no_model", "skipped_no_crops", "error"):
        record_shadow_decision(
            request_id=f"req-{reason}", device_id="esp32_001",
            result=DinoFilterResult(should_reject=False, reason=reason),
            gemini_disposal=True, models_dir=str(tmp_path),
        )
    assert _read_ledger(tmp_path) == []


def test_appends_across_calls(tmp_path):
    for i in range(3):
        record_shadow_decision(
            request_id=f"req-{i}", device_id="esp32_001",
            result=DinoFilterResult(should_reject=True, reason="rejected", p_con=0.01,
                                    threshold=0.5, n_frames_used=3),
            gemini_disposal=True, models_dir=str(tmp_path),
        )
    rows = _read_ledger(tmp_path)
    assert len(rows) == 3
    assert [r["request_id"] for r in rows] == ["req-0", "req-1", "req-2"]


def test_never_raises_on_bad_dir(tmp_path):
    # Point at a path whose parent is a file → mkdir fails; must swallow.
    bad_file = tmp_path / "afile"
    bad_file.write_text("x", encoding="utf-8")
    record_shadow_decision(
        request_id="req", device_id="esp32_001",
        result=DinoFilterResult(should_reject=True, reason="rejected", p_con=0.01,
                                threshold=0.5, n_frames_used=3),
        gemini_disposal=True, models_dir=str(bad_file / "sub"),
    )  # should not raise
