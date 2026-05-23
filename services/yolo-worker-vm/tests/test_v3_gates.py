"""Unit tests for V3 deterministic gate (apply_v3_gates).

V3 introduces person_position_signature as the PRIMARY discriminator for
pedestrian dumping. Tests verify the new override logic and ensure V2 logic
that V3 inherits (pile_decreased veto, flow+pile positive override) still works.

Driving cases from the official dataset (camp 11 results):
- 48350bb4 (pano branco): V2 lost — posture should recover.
- d00a79bd (uniforme): V2 lost — posture should recover.
- 12506543 (pedestre): V2 lost — posture should recover.
- e435c966 ("passando"): V2 ok — passing_by suppression confirms.
- 8c092e51 (carroça FP): V2 ok — carroça stays neutral.
"""
from __future__ import annotations

from worker._prompts_v3 import GeminiNewLitterReportV3, apply_v3_gates, build_v3_user_prompt_gate


def _make_report(**overrides) -> GeminiNewLitterReportV3:
    """Build a V3 report with reasonable defaults; override per-test."""
    defaults = dict(
        scene_type="EMPTY",
        person_position_signature="absent",
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
    return GeminiNewLitterReportV3(**defaults)


# -----------------------------------------------------------------------------
# Primary fix — posture override recovers TPs V2 lost.
# -----------------------------------------------------------------------------
def test_pedestrian_dumping_no_pile_growth():
    """TP 48350bb4 (pano branco) shape: person depositing.
    V3.2: posture + handling alone is enough IF no collection context."""
    report = _make_report(
        scene_type="PARKED",
        person_position_signature="depositing_at_pile",
        person_handling_material=True,
        material_flow_direction="none",
        pile_volume_change="unchanged",
        new_ground_material=False,
        municipal_equipment_present=False,
        new_litter_detected=False,
        confidence_0_100=20,
        evidence_summary="homem inclinado sobre pilha com saco branco",
    )
    result, is_maintenance = apply_v3_gates(report)
    assert result.new_litter_detected is True, "posture+handling (no collection context) should force DUMPING"
    assert result.scene_type == "DUMPING"
    assert result.confidence_0_100 >= 85
    assert is_maintenance is False


def test_posture_overridden_by_strong_collection_signals():
    """V3.2 fix: if model says posture=depositing_at_pile BUT >=2 collection
    signals present (scene=COLLECTION + flow=from_pile, for example), suppress.
    Handles 'Estavam realizando a poda' / 'limpando restos' false positives."""
    report = _make_report(
        scene_type="COLLECTION_OR_MAINTENANCE",  # signal 1
        person_position_signature="depositing_at_pile",
        person_handling_material=True,
        material_flow_direction="from_pile",     # signal 2
        new_litter_detected=True,
        confidence_0_100=80,
        evidence_summary="poda municipal — modelo confabulou postura",
    )
    result, _ = apply_v3_gates(report)
    assert result.new_litter_detected is False, "2+ collection signals must override posture"
    assert result.confidence_0_100 == 0


def test_single_collection_signal_does_not_suppress():
    """V3.2: a SINGLE collection signal (e.g. scene=COLLECTION_OR_MAINTENANCE
    alone) is not enough to override posture — protects d00a79bd uniform case
    where model sometimes mis-classifies scene as collection but posture is
    correctly depositing_at_pile."""
    report = _make_report(
        scene_type="COLLECTION_OR_MAINTENANCE",  # only signal 1
        person_position_signature="depositing_at_pile",
        person_handling_material=True,
        material_flow_direction="to_pile",       # NOT a collection signal
        pile_volume_change="unchanged",          # NOT a collection signal
        municipal_equipment_present=False,       # NOT a collection signal
        new_litter_detected=False,
        confidence_0_100=20,
        evidence_summary="uniforme laranja inclinado sobre pilha — d00a79bd",
    )
    result, _ = apply_v3_gates(report)
    assert result.new_litter_detected is True, "single collection signal must not block posture override"
    assert result.scene_type == "DUMPING"


def test_posture_overridden_by_pile_decreasing():
    """Even if posture=depositing, if pile is decreasing the deposit can't be real."""
    report = _make_report(
        scene_type="PARKED",
        person_position_signature="depositing_at_pile",
        person_handling_material=True,
        pile_volume_change="decreased",          # contradicts deposit
        new_litter_detected=True,
        confidence_0_100=80,
    )
    result, _ = apply_v3_gates(report)
    assert result.new_litter_detected is False


def test_uniform_pedestrian_dumping():
    """TP d00a79bd (uniforme laranja) shape: worker in uniform IS depositing.
    V2 lost it by classifying as COLLECTION. V3 must detect via posture."""
    report = _make_report(
        scene_type="COLLECTION_OR_MAINTENANCE",    # model fooled by uniform
        person_position_signature="depositing_at_pile",
        person_handling_material=True,
        material_flow_direction="to_pile",
        pile_volume_change="unchanged",            # also invisible
        municipal_equipment_present=False,
        new_litter_detected=False,
        confidence_0_100=10,
        evidence_summary="homem uniforme laranja inclinado sobre pilha",
    )
    result, is_maintenance = apply_v3_gates(report)
    assert result.new_litter_detected is True
    assert result.scene_type == "DUMPING"
    assert is_maintenance is False


def test_leaving_pile_area_is_dumping():
    """TP 12506543-like: person seen earlier near pile carrying something, then
    walking away without it in later frames. V3.1 requires corroboration —
    posture=leaving_pile_area + handling + new_ground (the bag they left)."""
    report = _make_report(
        scene_type="TRAFFIC",
        person_position_signature="leaving_pile_area",
        person_handling_material=True,
        material_flow_direction="to_pile",         # corroboration
        pile_volume_change="unchanged",
        new_ground_material=True,                  # bag left visible
        new_litter_detected=False,
        confidence_0_100=30,
        evidence_summary="pessoa caminhando para longe da pilha sem o objeto que carregava",
    )
    result, is_maintenance = apply_v3_gates(report)
    assert result.new_litter_detected is True
    assert result.scene_type == "DUMPING"


# -----------------------------------------------------------------------------
# Suppression — V3 must not over-detect.
# -----------------------------------------------------------------------------
def test_passing_by_suppression():
    """FP e435c966-like: pessoas passando. V3 must suppress via posture=passing_by."""
    report = _make_report(
        scene_type="TRAFFIC",
        person_position_signature="passing_by",
        person_handling_material=False,
        material_flow_direction="none",
        pile_volume_change="unchanged",
        new_litter_detected=True,                  # model wrongly said yes
        confidence_0_100=70,
        evidence_summary="pessoas atravessando a calcada perto da pilha",
    )
    result, is_maintenance = apply_v3_gates(report)
    assert result.new_litter_detected is False, "passing_by must suppress"
    assert result.confidence_0_100 == 0


def test_standing_near_pile_no_action():
    """Person near pile but not depositing — neutral, no override."""
    report = _make_report(
        scene_type="PARKED",
        person_position_signature="standing_near_pile",
        person_handling_material=False,
        material_flow_direction="none",
        pile_volume_change="unchanged",
        new_litter_detected=False,
        confidence_0_100=10,
        evidence_summary="pessoa parada perto da pilha sem manuseio",
    )
    result, is_maintenance = apply_v3_gates(report)
    assert result.new_litter_detected is False, "standing alone is not dumping"
    assert result.scene_type == "PARKED"
    assert is_maintenance is False


# -----------------------------------------------------------------------------
# Collection — V3 inherits V2 logic + posture=collecting_from_pile as 4th signal.
# -----------------------------------------------------------------------------
def test_collecting_from_pile_is_collection():
    """Catador honesto collecting from pile to cart. Pile decreases.
    4 signals: from_pile + decreased + posture=collecting → maintenance + cooldown."""
    report = _make_report(
        scene_type="COLLECTION_OR_MAINTENANCE",
        person_position_signature="collecting_from_pile",
        person_handling_material=True,
        material_flow_direction="from_pile",
        pile_volume_change="decreased",
        municipal_equipment_present=False,         # carroça doesn't qualify
        new_litter_detected=False,
        confidence_0_100=0,
        evidence_summary="catador levando reciclaveis da pilha para carroca",
    )
    result, is_maintenance = apply_v3_gates(report)
    assert result.new_litter_detected is False
    assert is_maintenance is True, "3+ signals must trigger cooldown"


def test_compactador_emlurb_still_collection():
    """Sanity: V2 case (caminhão compactador EMLURB) still works in V3."""
    report = _make_report(
        scene_type="COLLECTION_OR_MAINTENANCE",
        person_position_signature="collecting_from_pile",
        person_handling_material=True,
        material_flow_direction="from_pile",
        pile_volume_change="decreased",
        municipal_equipment_present=True,
        new_litter_detected=False,
    )
    result, is_maintenance = apply_v3_gates(report)
    assert result.new_litter_detected is False
    assert is_maintenance is True


# -----------------------------------------------------------------------------
# Legacy V2 logic still works.
# -----------------------------------------------------------------------------
def test_pile_growth_alone_is_dumping():
    """Sinal D (legacy V2 path): pile clearly grew, even without posture signal.
    Vehicle unloading would also fall here."""
    report = _make_report(
        scene_type="DUMPING",
        person_position_signature="absent",        # camera missed the person
        vehicle_stopped=True,
        person_handling_material=False,
        material_flow_direction="to_pile",
        pile_volume_change="increased",
        new_litter_detected=False,                 # model unsure
        confidence_0_100=40,
        evidence_summary="material novo apareceu no chao",
    )
    result, is_maintenance = apply_v3_gates(report)
    assert result.new_litter_detected is True, "legacy flow+pile override still works"
    assert result.scene_type == "DUMPING"
    assert result.confidence_0_100 >= 85


def test_pile_decreasing_blocks_dumping():
    """Sanity: pile decreasing veto from V2 still applies in V3."""
    report = _make_report(
        scene_type="DUMPING",
        person_position_signature="absent",
        person_handling_material=True,
        material_flow_direction="to_pile",
        pile_volume_change="decreased",            # contradiction
        new_litter_detected=True,
        confidence_0_100=80,
    )
    result, is_maintenance = apply_v3_gates(report)
    assert result.new_litter_detected is False, "pile_decreased must veto"
    assert result.confidence_0_100 == 0


# -----------------------------------------------------------------------------
# LOCAL_CONTEXT injection sanity check.
# -----------------------------------------------------------------------------
def test_local_context_injected_in_user_prompt():
    """The user prompt builder must include the LOCAL_CONTEXT block when
    gemini_context_notes is present in camera_context."""
    notes = "Camera em poste sobre terreno baldio. Descartes geralmente a noite por pedestres."
    text = build_v3_user_prompt_gate(
        first_frame_name="2026-05-19_18-39-24.jpg",
        last_frame_name="2026-05-19_18-40-19.jpg",
        camera_context={
            "camera_name": "ESP32-001 Imbiribeira",
            "logradouro": "Rua Professor Pedro Augusto",
            "gemini_context_notes": notes,
        },
    )
    assert "LOCAL_CONTEXT" in text
    assert notes in text
    # gemini_context_notes should NOT appear as a generic context line.
    assert "- gemini_context_notes:" not in text
    # And the other camera fields should still show up.
    assert "camera_name" in text


def test_no_local_context_when_notes_missing():
    """If gemini_context_notes is missing/empty, no LOCAL_CONTEXT block appears."""
    text = build_v3_user_prompt_gate(
        first_frame_name="a.jpg",
        last_frame_name="b.jpg",
        camera_context={"camera_name": "ESP32-001"},
    )
    assert "LOCAL_CONTEXT" not in text
