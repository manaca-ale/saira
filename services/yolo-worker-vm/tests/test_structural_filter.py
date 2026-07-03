"""Tests for the structural-delta post-detail filter (Camp 41).

Covers the persistent ledger (mirrors the DINOv2 ledger contract) and the fail-open
guards of evaluate(): every skip/missing-input path must yield should_reject=False so
a broken filter never drops a real disposal.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from worker import config, detector_structural
from worker.detector_structural import StructFilterResult, record_shadow_decision

# Polígono grande o bastante p/ conter vários tiles de 32px (bbox 50..300 = ~7x7 tiles).
POLY_BIG = [[[50, 50], [300, 50], [300, 300], [50, 300]]]


def _noise_img(seed: int, h: int = 400, w: int = 400) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def _pair_with_change(tmp_path: Path, block: int = 150):
    """before/after PNG idênticos exceto por um bloco de textura nova dentro do polígono."""
    before = _noise_img(1)
    after = before.copy()
    rng = np.random.default_rng(999)
    after[90:90 + block, 90:90 + block] = rng.integers(0, 256, size=(block, block, 3), dtype=np.uint8)
    a, b = tmp_path / "before.png", tmp_path / "after.png"
    cv2.imwrite(str(a), before)
    cv2.imwrite(str(b), after)
    return a, b


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


# --- score_window: núcleo compartilhado (sem gating de modo/câmera) ------------

def test_score_window_detects_new_structure(tmp_path):
    a, b = _pair_with_change(tmp_path)
    r = detector_structural.score_window([a, b], POLY_BIG)
    assert r.reason == "scored"
    assert r.n_tiles_changed >= 2  # bloco novo grande ⇒ vários tiles mudam


def test_score_window_no_change_is_zero(tmp_path):
    before = _noise_img(1)
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    cv2.imwrite(str(a), before)
    cv2.imwrite(str(b), before.copy())  # idênticos
    r = detector_structural.score_window([a, b], POLY_BIG)
    assert r.reason == "scored" and r.n_tiles_changed == 0


def test_score_window_skip_reasons(tmp_path):
    assert detector_structural.score_window([], POLY_BIG).reason == "skipped_no_frames"
    a, b = _pair_with_change(tmp_path)
    assert detector_structural.score_window([a, b], None).reason == "skipped_no_polygon"
    # mesma path duas vezes ⇒ before/after apontam ao mesmo frame legível
    assert detector_structural.score_window([a, a], POLY_BIG).reason == "skipped_one_frame"
    # todos ilegíveis ⇒ fail-open
    assert detector_structural.score_window(
        [tmp_path / "x.png", tmp_path / "y.png"], POLY_BIG
    ).reason == "error_unreadable"


# --- evaluate() ainda deriva should_reject do score_window (regressão) ---------

def test_evaluate_thresholds_over_score(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STRUCTURAL_FILTER_MODE", "shadow")
    monkeypatch.setattr(config, "STRUCTURAL_DEVICES", {"esp32_002"})
    a, b = _pair_with_change(tmp_path)
    monkeypatch.setattr(config, "STRUCTURAL_NTILES_THR", 2)
    r = detector_structural.evaluate([a, b], "esp32_002", POLY_BIG)
    assert r.reason == "passed" and r.should_reject is False and r.threshold == 2
    n = r.n_tiles_changed
    # limiar acima do sinal ⇒ vira rejeição
    monkeypatch.setattr(config, "STRUCTURAL_NTILES_THR", n + 1)
    r2 = detector_structural.evaluate([a, b], "esp32_002", POLY_BIG)
    assert r2.reason == "rejected" and r2.should_reject is True


# --- ledger de recuperação ----------------------------------------------------

def _read_recovery_ledger(d: Path) -> list[dict]:
    p = d / detector_structural.RECOVERY_LEDGER_NAME
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_recovery_decision(tmp_path):
    detector_structural.record_recovery_decision(
        request_id="r1", device_id="esp32_002", n_tiles_changed=15, threshold=8,
        recovered=True, mode="shadow", reason="scored", models_dir=str(tmp_path),
    )
    detector_structural.record_recovery_decision(
        request_id="r2", device_id="esp32_002", n_tiles_changed=3, threshold=8,
        recovered=False, mode="shadow", reason="scored", models_dir=str(tmp_path),
    )
    rows = _read_recovery_ledger(tmp_path)
    assert len(rows) == 2
    assert rows[0]["recovered"] is True and rows[0]["n_tiles_changed"] == 15
    assert rows[1]["recovered"] is False and rows[1]["threshold"] == 8
    assert rows[0]["mode"] == "shadow" and "ts" in rows[0]


def test_record_recovery_never_raises(tmp_path):
    bad = tmp_path / "afile"
    bad.write_text("x", encoding="utf-8")
    detector_structural.record_recovery_decision(
        request_id="r", device_id="esp32_002", n_tiles_changed=1, threshold=8,
        recovered=False, mode="shadow", reason="scored", models_dir=str(bad / "sub"),
    )  # não pode levantar


# --- integração: main._structural_recovery (gating + threshold) ---------------

class _FakeCam:
    def __init__(self, poly):
        self.pile_zone_polygon = poly
        self.id = 11


def test_structural_recovery_gating_and_threshold(tmp_path, monkeypatch):
    from worker import main

    a, b = _pair_with_change(tmp_path)
    win = [a, b]
    cam = _FakeCam(POLY_BIG)
    monkeypatch.setattr(config, "STRUCTURAL_LEDGER_DIR", str(tmp_path))

    # off ⇒ None (legado preservado)
    monkeypatch.setattr(config, "STRUCTURAL_RECOVERY_MODE", "off")
    assert main._structural_recovery(
        window_paths=win, device_id="esp32_002", camera=cam, gate_request_id="g"
    ) is None

    monkeypatch.setattr(config, "STRUCTURAL_RECOVERY_MODE", "shadow")
    monkeypatch.setattr(config, "STRUCTURAL_RECOVERY_DEVICES", {"esp32_002"})

    # câmera não-alvo ⇒ None
    assert main._structural_recovery(
        window_paths=win, device_id="esp32_999", camera=cam, gate_request_id="g"
    ) is None
    # sem polígono ⇒ None
    assert main._structural_recovery(
        window_paths=win, device_id="esp32_002", camera=_FakeCam(None), gate_request_id="g"
    ) is None

    # estrutura nova forte + thr baixo ⇒ recovered True (shadow: só sinaliza)
    monkeypatch.setattr(config, "STRUCTURAL_RECOVERY_NTILES_THR", 2)
    info = main._structural_recovery(
        window_paths=win, device_id="esp32_002", camera=cam, gate_request_id="g",
    )
    assert info is not None and info["recovered"] is True and info["n_tiles_changed"] >= 2
    # persistiu no ledger durável
    assert any(r["recovered"] for r in _read_recovery_ledger(tmp_path))

    # thr acima do sinal ⇒ não recupera
    monkeypatch.setattr(config, "STRUCTURAL_RECOVERY_NTILES_THR", 9999)
    info2 = main._structural_recovery(
        window_paths=win, device_id="esp32_002", camera=cam, gate_request_id="g",
    )
    assert info2["recovered"] is False
