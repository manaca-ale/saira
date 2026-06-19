"""Tests for the structural-delta post-detail filter (Camp 41).

Covers the persistent ledger (mirrors the DINOv2 ledger contract) and the fail-open
guards of evaluate(): every skip/missing-input path must yield should_reject=False so
a broken filter never drops a real disposal.
"""
from __future__ import annotations

import json
from pathlib import Path

from worker import config, detector_structural
from worker.detector_structural import StructFilterResult, record_shadow_decision


def _read_ledger(d: Path) -> list[dict]:
    p = d / detector_structural.SHADOW_LEDGER_NAME
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_records_reject_and_pass(tmp_path):
    record_shadow_decision(
        request_id="req-rej", device_id="esp32_002",
        result=StructFilterResult(should_reject=True, reason="rejected",
                                  n_tiles_changed=0, threshold=2, n_frames_used=2),
        gemini_disposal=True, mode="shadow", models_dir=str(tmp_path),
    )
    record_shadow_decision(
        request_id="req-pass", device_id="esp32_002",
        result=StructFilterResult(should_reject=False, reason="passed",
                                  n_tiles_changed=9, threshold=2, n_frames_used=2),
        gemini_disposal=True, mode="shadow", models_dir=str(tmp_path),
    )
    rows = _read_ledger(tmp_path)
    assert len(rows) == 2
    rej, pas = rows
    assert rej["request_id"] == "req-rej" and rej["should_reject"] is True
    assert rej["n_tiles_changed"] == 0 and rej["reason"] == "rejected"
    assert rej["mode"] == "shadow" and rej["device_id"] == "esp32_002"
    assert rej["gemini_disposal"] is True and "ts" in rej
    assert pas["should_reject"] is False and pas["n_tiles_changed"] == 9


def test_records_all_reasons_including_skips(tmp_path):
    # Skips/errors MUST be recorded too — sem isso os fail-opens ficam invisíveis e
    # o shadow parece coletar dados quando não roda (bug 2026-06-18: 3 de 26 logavam).
    reasons = ("skipped_no_polygon", "skipped_no_frames", "error_unreadable",
               "error_shape", "skipped_one_frame")
    for reason in reasons:
        record_shadow_decision(
            request_id=f"req-{reason}", device_id="esp32_002",
            result=StructFilterResult(should_reject=False, reason=reason),
            gemini_disposal=True, models_dir=str(tmp_path),
        )
    rows = _read_ledger(tmp_path)
    assert len(rows) == len(reasons)
    assert {r["reason"] for r in rows} == set(reasons)
    assert all(r["should_reject"] is False for r in rows)


def test_never_raises_on_bad_dir(tmp_path):
    bad_file = tmp_path / "afile"
    bad_file.write_text("x", encoding="utf-8")
    record_shadow_decision(
        request_id="req", device_id="esp32_002",
        result=StructFilterResult(should_reject=True, reason="rejected",
                                  n_tiles_changed=0, threshold=2, n_frames_used=2),
        gemini_disposal=True, models_dir=str(bad_file / "sub"),
    )  # must not raise


def test_evaluate_failopen_off(monkeypatch):
    monkeypatch.setattr(config, "STRUCTURAL_FILTER_MODE", "off")
    r = detector_structural.evaluate([Path("a.jpg"), Path("b.jpg")], "esp32_002", [[[0, 0], [1, 0], [1, 1]]])
    assert r.should_reject is False and r.reason == "skipped_disabled"


def test_evaluate_failopen_not_targeted(monkeypatch):
    monkeypatch.setattr(config, "STRUCTURAL_FILTER_MODE", "shadow")
    monkeypatch.setattr(config, "STRUCTURAL_DEVICES", {"esp32_002"})
    r = detector_structural.evaluate([Path("a.jpg"), Path("b.jpg")], "esp32_999", [[[0, 0], [1, 0], [1, 1]]])
    assert r.should_reject is False and r.reason == "skipped_not_targeted"


def test_evaluate_failopen_too_few_frames(monkeypatch):
    monkeypatch.setattr(config, "STRUCTURAL_FILTER_MODE", "shadow")
    monkeypatch.setattr(config, "STRUCTURAL_DEVICES", {"esp32_002"})
    r = detector_structural.evaluate([Path("only_one.jpg")], "esp32_002", [[[0, 0], [1, 0], [1, 1]]])
    assert r.should_reject is False and r.reason == "skipped_no_frames"


def test_evaluate_failopen_no_polygon(monkeypatch):
    monkeypatch.setattr(config, "STRUCTURAL_FILTER_MODE", "shadow")
    monkeypatch.setattr(config, "STRUCTURAL_DEVICES", {"esp32_002"})
    r = detector_structural.evaluate([Path("a.jpg"), Path("b.jpg")], "esp32_002", None)
    assert r.should_reject is False and r.reason == "skipped_no_polygon"
