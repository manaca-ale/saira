"""Unit tests for the AUDIT detail prompt (Agent-2 as adversarial reviewer).

Covers:
- Schema extension with fp_pattern_match enum + alias normalization
- apply_audit_consistency() forces infraction_confirmed=false when pattern is FP
- Builder includes the required field instruction
"""
from __future__ import annotations

import pytest

from worker._prompts_audit import (
    GeminiInfractionReportAudit,
    V2_FORCE_FALSE_PATTERNS,
    VALID_FP_PATTERNS,
    apply_audit_consistency,
    apply_audit_v2_consistency,
    build_audit_user_prompt,
    build_audit_v2_user_prompt,
)


def _make_audit_report(**overrides) -> GeminiInfractionReportAudit:
    defaults = dict(
        baseline_description="test scene",
        infraction_confirmed=False,
        confidence_0_100=0,
        evidence_summary="test",
        offender_detected=False,
        fp_pattern_match="other",
    )
    defaults.update(overrides)
    return GeminiInfractionReportAudit(**defaults)


# -----------------------------------------------------------------------------
# Schema normalization
# -----------------------------------------------------------------------------
def test_fp_pattern_valid_passes_through():
    """Each canonical pattern is accepted as-is."""
    for p in VALID_FP_PATTERNS:
        r = _make_audit_report(fp_pattern_match=p)
        assert r.fp_pattern_match == p


def test_fp_pattern_alias_normalization():
    """Common variants from the model should normalize to canonical values."""
    cases = {
        "DUMPING": "real_dumping",
        "Coleta": "municipal_collection",
        "passing": "traffic_passing",
        "carroceiro": "carroceiro_sorting",
        "chuva": "rain_blur",
        "poda": "pruning_crew",
        "estacionamento": "parking_dropoff",
    }
    for raw, expected in cases.items():
        r = _make_audit_report(fp_pattern_match=raw)
        assert r.fp_pattern_match == expected, f"{raw!r} -> {r.fp_pattern_match}, expected {expected}"


def test_fp_pattern_unknown_falls_back_to_other():
    """Garbage in → 'other' (safe default). String must NOT contain any alias keyword."""
    r = _make_audit_report(fp_pattern_match="xyzzy_unknown_label")
    assert r.fp_pattern_match == "other"


def test_fp_pattern_none_becomes_other():
    r = _make_audit_report(fp_pattern_match=None)
    assert r.fp_pattern_match == "other"


# -----------------------------------------------------------------------------
# apply_audit_consistency — the key contract
# -----------------------------------------------------------------------------
def test_consistency_real_dumping_keeps_confirmation():
    """real_dumping + confirmed=True → stays confirmed."""
    r = _make_audit_report(
        infraction_confirmed=True, confidence_0_100=88,
        fp_pattern_match="real_dumping",
    )
    out = apply_audit_consistency(r)
    assert out.infraction_confirmed is True
    assert out.confidence_0_100 == 88


def test_consistency_traffic_passing_forces_false():
    """fp_pattern=traffic_passing but model said confirmed=True → forced False."""
    r = _make_audit_report(
        infraction_confirmed=True, confidence_0_100=80,
        fp_pattern_match="traffic_passing",
    )
    out = apply_audit_consistency(r)
    assert out.infraction_confirmed is False
    assert out.confidence_0_100 == 0


def test_consistency_municipal_collection_forces_false():
    r = _make_audit_report(
        infraction_confirmed=True, confidence_0_100=92,
        fp_pattern_match="municipal_collection",
    )
    out = apply_audit_consistency(r)
    assert out.infraction_confirmed is False
    assert out.confidence_0_100 == 0


def test_consistency_other_pattern_forces_false():
    """other (ambiguous) → never confirm."""
    r = _make_audit_report(
        infraction_confirmed=True, confidence_0_100=70,
        fp_pattern_match="other",
    )
    out = apply_audit_consistency(r)
    assert out.infraction_confirmed is False


def test_consistency_no_change_when_not_confirmed():
    """If model already said not infraction, leave alone."""
    r = _make_audit_report(
        infraction_confirmed=False, confidence_0_100=10,
        fp_pattern_match="other",
    )
    out = apply_audit_consistency(r)
    assert out.infraction_confirmed is False
    assert out.confidence_0_100 == 10


# -----------------------------------------------------------------------------
# Builder shape
# -----------------------------------------------------------------------------
def test_user_prompt_includes_fp_pattern_instruction():
    text = build_audit_user_prompt(frame_names=["a.jpg", "b.jpg"])
    assert "fp_pattern_match" in text
    assert "real_dumping" in text
    # All 8 patterns should be enumerated for the model
    for p in VALID_FP_PATTERNS:
        assert p in text, f"missing pattern {p} in builder output"


def test_user_prompt_mosaic_mode():
    text = build_audit_user_prompt(mosaic_mode="4x3")
    assert "mosaic" in text.lower() or "frame_" in text
    assert "fp_pattern_match" in text


# -----------------------------------------------------------------------------
# AUDIT_V2 — relaxed force-false list
# -----------------------------------------------------------------------------
def test_v2_force_false_set_excludes_carroceiro_other_real():
    """V2 force-set must NOT include carroceiro_sorting / other / real_dumping."""
    assert "carroceiro_sorting" not in V2_FORCE_FALSE_PATTERNS
    assert "other" not in V2_FORCE_FALSE_PATTERNS
    assert "real_dumping" not in V2_FORCE_FALSE_PATTERNS
    # And must include the 5 unambiguous FP patterns
    for p in ("traffic_passing", "municipal_collection", "pruning_crew",
              "rain_blur", "parking_dropoff"):
        assert p in V2_FORCE_FALSE_PATTERNS


def test_v2_consistency_traffic_passing_forces_false():
    r = _make_audit_report(
        infraction_confirmed=True, confidence_0_100=80,
        fp_pattern_match="traffic_passing",
    )
    out = apply_audit_v2_consistency(r)
    assert out.infraction_confirmed is False
    assert out.confidence_0_100 == 0


def test_v2_consistency_municipal_collection_forces_false():
    r = _make_audit_report(
        infraction_confirmed=True, confidence_0_100=92,
        fp_pattern_match="municipal_collection",
    )
    out = apply_audit_v2_consistency(r)
    assert out.infraction_confirmed is False


def test_v2_consistency_carroceiro_keeps_model_decision():
    """V2 does NOT force false for carroceiro_sorting — model decides.
    This is the key regression fix from camp 15 V1 audit.
    """
    r = _make_audit_report(
        infraction_confirmed=True, confidence_0_100=75,
        fp_pattern_match="carroceiro_sorting",
    )
    out = apply_audit_v2_consistency(r)
    assert out.infraction_confirmed is True
    assert out.confidence_0_100 == 75


def test_v2_consistency_other_keeps_model_decision():
    """V2 does NOT force false for 'other' — model decides.
    V1 default-to-other killed 3/7 lost TPs in camp 15.
    """
    r = _make_audit_report(
        infraction_confirmed=True, confidence_0_100=60,
        fp_pattern_match="other",
    )
    out = apply_audit_v2_consistency(r)
    assert out.infraction_confirmed is True
    assert out.confidence_0_100 == 60


def test_v2_consistency_real_dumping_keeps_confirmation():
    r = _make_audit_report(
        infraction_confirmed=True, confidence_0_100=90,
        fp_pattern_match="real_dumping",
    )
    out = apply_audit_v2_consistency(r)
    assert out.infraction_confirmed is True
    assert out.confidence_0_100 == 90


def test_v2_consistency_no_change_when_not_confirmed():
    r = _make_audit_report(
        infraction_confirmed=False, confidence_0_100=5,
        fp_pattern_match="traffic_passing",
    )
    out = apply_audit_v2_consistency(r)
    assert out.infraction_confirmed is False


def test_v2_user_prompt_mentions_v2_rule():
    text = build_audit_v2_user_prompt(frame_names=["a.jpg", "b.jpg"])
    assert "fp_pattern_match" in text
    # The V2 rule explicitly enumerates the 5 force-false patterns
    for p in ("traffic_passing", "municipal_collection", "pruning_crew",
              "rain_blur", "parking_dropoff"):
        assert p in text, f"V2 builder must enumerate {p} as force-false pattern"
    # Real_dumping is still mentioned (so the model knows it's a valid choice)
    assert "real_dumping" in text


def test_v2_user_prompt_mosaic_mode():
    text = build_audit_v2_user_prompt(mosaic_mode="3x2split")
    assert "fp_pattern_match" in text
    assert "mosaic" in text.lower() or "frame_" in text
