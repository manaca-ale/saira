"""Unit tests for V2 deterministic gate (apply_v2_gates).

Covers the behavioral discriminator logic in worker._prompts_v2 introduced
to fix the 3 dataset/prompt mismatches identified in docs/prompt_dataset_mismatch_20260522.md:

1. Pedestrian dumping (no vehicle present)
2. Uniformed workers dumping (uniform is not a discriminator)
3. Carroceiros (the cart itself is now NEUTRAL — decision falls out from flow + pile)

Each test instantiates a GeminiNewLitterReportV2 representing a plausible Agent-1
output for the scenario, runs it through apply_v2_gates, and asserts the resulting
state matches the dataset's ground-truth classification.
"""
from __future__ import annotations

from worker._prompts_v2 import GeminiNewLitterReportV2, apply_v2_gates


def _make_report(**overrides) -> GeminiNewLitterReportV2:
    """Build a V2 report with reasonable defaults; override per-test."""
    defaults = dict(
        scene_type="EMPTY",
        vehicle_stopped=False,
        person_handling_material=False,
        new_ground_material=False,
        material_flow_direction="none",
        pile_volume_change="unchanged",
        municipal_equipment_present=False,
        new_litter_detected=False,
        confidence_0_100=0,
        evidence_summary="test scenario",
    )
    defaults.update(overrides)
    return GeminiNewLitterReportV2(**defaults)


# -----------------------------------------------------------------------------
# Mismatch 1 — Pedestrian dumping (TP 12506543: "outro homem que realiza um descarte")
# -----------------------------------------------------------------------------
def test_pedestrian_dumping_no_vehicle():
    """A person depositing material on the ground without any vehicle should be
    confirmed as DUMPING. This is the most common TP shape in the official
    dataset (12 of 14 TPs)."""
    report = _make_report(
        scene_type="DUMPING",
        vehicle_stopped=False,           # no vehicle in scene
        person_handling_material=True,
        new_ground_material=True,
        material_flow_direction="to_pile",
        pile_volume_change="increased",
        municipal_equipment_present=False,
        new_litter_detected=True,
        confidence_0_100=85,
        evidence_summary="pessoa a pe descarregando saco no chao, pilha cresce",
    )
    result, is_maintenance = apply_v2_gates(report)

    assert result.new_litter_detected is True
    assert result.scene_type == "DUMPING"
    assert result.confidence_0_100 >= 85
    assert is_maintenance is False


# -----------------------------------------------------------------------------
# Mismatch 3 — Uniform must not block dumping (TP d00a79bd, CRÍTICO)
# -----------------------------------------------------------------------------
def test_uniform_does_not_block_dumping():
    """When the Agent-1 is fooled by an orange uniform and classifies as PARKED
    despite clear DUMPING signals (to_pile + increased pile), the positive
    override at _prompts_v2.py:508 must fire and force DUMPING=True."""
    report = _make_report(
        scene_type="PARKED",             # model fooled by uniform
        vehicle_stopped=False,
        person_handling_material=True,
        new_ground_material=True,
        material_flow_direction="to_pile",
        pile_volume_change="increased",
        municipal_equipment_present=False,
        new_litter_detected=False,       # model said no
        confidence_0_100=30,
        evidence_summary="homem com uniforme laranja descarregando sacos",
    )
    result, is_maintenance = apply_v2_gates(report)

    assert result.new_litter_detected is True, "positive override should fire on flow=to_pile + pile=increased"
    assert result.scene_type == "DUMPING"
    assert result.confidence_0_100 >= 85
    assert is_maintenance is False


# -----------------------------------------------------------------------------
# Mismatch 2 — Carroceiro DESCARTANDO (post-carroça-fix: cart no longer auto-suppresses)
# -----------------------------------------------------------------------------
def test_carroca_to_pile_is_dumping():
    """After the 2026-05-22 carroça patch, a wooden cart no longer counts as
    municipal_equipment_present. When the carroceiro is clearly DUMPING
    (flow=to_pile, pile=increased), the gate must NOT suppress."""
    report = _make_report(
        scene_type="DUMPING",
        vehicle_stopped=True,            # carroça (stationary cart) — still bool true is fine
        person_handling_material=True,
        new_ground_material=True,
        material_flow_direction="to_pile",
        pile_volume_change="increased",
        municipal_equipment_present=False,  # carroça is no longer "municipal equipment"
        new_litter_detected=True,
        confidence_0_100=80,
        evidence_summary="carroceiro descartando sacos da carroca, pilha cresce",
    )
    result, is_maintenance = apply_v2_gates(report)

    assert result.new_litter_detected is True
    assert result.scene_type == "DUMPING"
    assert is_maintenance is False


def test_carroca_from_pile_is_collection():
    """Carroceiro genuinely collecting recyclables — pile decreases. The
    blind pile_decreasing rule at _prompts_v2.py:497 must force new_litter=False
    even if Agent-1 was uncertain."""
    report = _make_report(
        scene_type="COLLECTION_OR_MAINTENANCE",
        vehicle_stopped=True,
        person_handling_material=True,
        new_ground_material=False,
        material_flow_direction="from_pile",
        pile_volume_change="decreased",
        municipal_equipment_present=False,   # carroça no longer qualifies
        new_litter_detected=False,
        confidence_0_100=0,
        evidence_summary="catador retirando reciclaveis para carroca, pilha diminui",
    )
    result, is_maintenance = apply_v2_gates(report)

    assert result.new_litter_detected is False
    # 2 signals (from_pile + decreased) >= 2 even without equip → is_maintenance=True
    assert is_maintenance is True


# -----------------------------------------------------------------------------
# Mismatch 1 corollary — Caminhão compactador EMLURB must be suppressed (legit collection)
# -----------------------------------------------------------------------------
def test_compactador_emlurb_is_collection():
    """Caminhão compactador EMLURB with rear-loading hopper, workers loading
    bags FROM ground INTO the truck, pile decreasing. All 3 signals fire:
    from_pile + decreased + equip → strong suppression + cooldown."""
    report = _make_report(
        scene_type="COLLECTION_OR_MAINTENANCE",
        vehicle_stopped=True,
        person_handling_material=True,
        new_ground_material=False,
        material_flow_direction="from_pile",
        pile_volume_change="decreased",
        municipal_equipment_present=True,    # caminhão compactador EMLURB
        new_litter_detected=False,
        confidence_0_100=0,
        evidence_summary="caminhao compactador EMLURB recolhendo sacos, pilha diminui",
    )
    result, is_maintenance = apply_v2_gates(report)

    assert result.new_litter_detected is False
    assert is_maintenance is True, "3 strong signals must trigger cooldown"


# -----------------------------------------------------------------------------
# Carroceiro com fluxo ambíguo — não deve auto-suprimir
# -----------------------------------------------------------------------------
def test_ambiguous_carroca_no_suppression():
    """Carroceiro 'mexendo' (handling) without clear flow direction — the gate
    must NOT auto-suppress. This is the genuinely ambiguous case (9 of 11
    carroça events in the dataset are Indefinido). Let Agent-2 decide."""
    report = _make_report(
        scene_type="PARKED",                 # benign-looking; could be either
        vehicle_stopped=True,
        person_handling_material=True,
        new_ground_material=False,
        material_flow_direction="ambiguous",
        pile_volume_change="unchanged",
        municipal_equipment_present=False,   # carroça no longer auto-flags
        new_litter_detected=False,
        confidence_0_100=20,
        evidence_summary="dois homens mexendo na carroca, fluxo de material incerto",
    )
    result, is_maintenance = apply_v2_gates(report)

    # No COLLECTION_OR_MAINTENANCE scene → no downgrade path triggers.
    # No pile=decreased → no blind suppression.
    # No flow=to_pile+pile=increased → no positive override.
    # No new_litter_detected=True → hard-gate doesn't fire either.
    # State must pass through unchanged.
    assert result.new_litter_detected is False
    assert result.scene_type == "PARKED"
    assert is_maintenance is False, "ambiguous scenes must not trigger cooldown"


# -----------------------------------------------------------------------------
# Pile decreasing blind rule — even if model insists, dumping never reduces a pile
# -----------------------------------------------------------------------------
def test_pile_decreasing_blocks_dumping():
    """Sanity check on the blind rule (_prompts_v2.py:497-503): if the model
    contradicts itself by saying flow=to_pile while pile=decreased AND
    new_litter_detected=True, the gate must force False. Physically a pile
    cannot grow and shrink simultaneously."""
    report = _make_report(
        scene_type="DUMPING",
        vehicle_stopped=True,
        person_handling_material=True,
        new_ground_material=True,
        material_flow_direction="to_pile",
        pile_volume_change="decreased",      # contradiction
        municipal_equipment_present=False,
        new_litter_detected=True,            # model insists
        confidence_0_100=90,
        evidence_summary="model contradicts itself: claims dumping but pile shrank",
    )
    result, is_maintenance = apply_v2_gates(report)

    assert result.new_litter_detected is False, "pile_decreased must veto dumping"
    assert result.confidence_0_100 == 0
