"""Bounding-box grounding of the detail (Agent-2) report.

Campaign 53: gemini-3.8-flash draws tight boxes, and on the HD Pi camera a person covers
less than 1% of the frame. With the historical 1% floor every box was dropped and, with
GEMINI_REQUIRE_BBOX=true, the worker turned real confirmations into "no" (2 of the 19 real
detections of the official set). Both rules are now configurable; the defaults keep the
historical behaviour.
"""
import pytest

from worker import config
from worker import detector_gemini as dg
from worker.schemas_gemini import GeminiInfractionReport


def _box(side: int) -> list[int]:
    """Square box of `side` per mille: area = (side / 1000) ** 2 of the image."""
    return [100, 100, 100 + side, 100 + side]


def _report(**kw) -> GeminiInfractionReport:
    base = dict(infraction_confirmed=True, confidence_0_100=90, evidence_summary="x",
                offender_detected=True)
    base.update(kw)
    return GeminiInfractionReport(**base)


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_REQUIRE_BBOX", True, raising=False)
    monkeypatch.setattr(config, "GEMINI_BBOX_MIN_AREA_RATIO", 0.01, raising=False)


def test_default_floor_is_one_percent():
    assert dg._validate_bbox(_box(90), "waste") is None          # 0.81%
    assert dg._validate_bbox(_box(105), "waste") == _box(105)    # 1.10%


def test_floor_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_BBOX_MIN_AREA_RATIO", 0.0025, raising=False)
    assert dg._validate_bbox(_box(70), "waste") == _box(70)      # 0.49%
    assert dg._validate_bbox(_box(40), "waste") is None          # 0.16%


def test_ceiling_and_malformed_boxes_are_still_rejected(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_BBOX_MIN_AREA_RATIO", 0.0, raising=False)
    assert dg._validate_bbox([0, 0, 900, 900], "waste") is None  # 81% of the image
    assert dg._validate_bbox([10, 10, 5, 50], "waste") is None   # inverted
    assert dg._validate_bbox([0, 0, 10], "waste") is None        # wrong length
    assert dg._validate_bbox(None, "waste") is None


def test_require_bbox_vetoes_a_confirmation_with_only_small_boxes():
    r = dg._sanitize_report(_report(waste_bbox=_box(60), offender_bbox=_box(80)))
    assert r.infraction_confirmed is False
    assert r.confidence_0_100 == 0


def test_without_require_bbox_the_model_answer_stands(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_REQUIRE_BBOX", False, raising=False)
    r = dg._sanitize_report(_report(waste_bbox=_box(60), offender_bbox=_box(80)))
    assert r.infraction_confirmed is True
    assert r.confidence_0_100 == 90
    assert r.waste_bbox is None and r.offender_bbox is None      # dropped by the 1% floor


def test_lower_floor_keeps_small_boxes_for_the_report(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_REQUIRE_BBOX", False, raising=False)
    monkeypatch.setattr(config, "GEMINI_BBOX_MIN_AREA_RATIO", 0.0025, raising=False)
    r = dg._sanitize_report(_report(waste_bbox=_box(60), offender_bbox=_box(80)))
    assert r.infraction_confirmed is True
    assert r.waste_bbox == _box(60) and r.offender_bbox == _box(80)


def test_a_negative_answer_is_never_turned_into_a_confirmation(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_REQUIRE_BBOX", False, raising=False)
    r = dg._sanitize_report(_report(infraction_confirmed=False, confidence_0_100=95,
                                    waste_bbox=_box(200)))
    assert r.infraction_confirmed is False
    assert r.confidence_0_100 == 95
