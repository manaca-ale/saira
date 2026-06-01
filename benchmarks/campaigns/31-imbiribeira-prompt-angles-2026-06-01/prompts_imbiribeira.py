"""Imbiribeira (esp32_001) gate prompt angles — campaign 31.

Design grounded in the data (camp 30 + frame review):
- Scene: OPEN VACANT LOT (terreno baldio), no single pile, scattered debris everywhere,
  vertical pole crossing the frame center, subjects often SMALL/DISTANT, lighting varies
  (day/dusk/dawn/night-IR). Lot is also used for parking and as a thru-path.
- Missed TPs (V3+B3): small/distant on-foot people with bag/handcart -> called TRAFFIC.
- Dominant FPs: trucks/teams REMOVING garbage (collection/cleanup) + parked cars.

All angles are appended to NEW_LITTER_SYSTEM_PROMPT_V3 (V3 schema: scene_type,
person_position_signature, material_flow_direction, pile_volume_change, ...).
"""

# Shared open-lot reframing preamble (prepended to each angle below).
IMBIRIBEIRA_PREAMBLE = """
=============================================================================
CAMERA-SPECIFIC MODE - esp32_001 / Imbiribeira (OPEN VACANT LOT)
=============================================================================
This camera overlooks an OPEN VACANT LOT (terreno baldio) that is a chronic illegal
dumping ground. Scene facts you MUST assume:
- A vertical utility/light POLE crosses the center of the frame. IGNORE the pole.
- There is NO single pile. Scattered debris already covers much of the lot; the ENTIRE
  lot surface (ground, edges, near the shacks on the right) is a valid dumping target.
  "pile_volume_change" is unreliable here (debris is everywhere) — do NOT rely on it.
- Subjects often appear SMALL and DISTANT in the wide lot. A small figure is STILL a
  person; do NOT dismiss small/distant figures as "just traffic".
- The lot is ALSO used for parking and as a through-path, and municipal/informal teams
  sometimes REMOVE garbage with a truck. These are NOT dumping.
Agent-1 is only a cheap gate for Agent-2. Keep evidence_summary and scene_delta_analysis
under 260 chars each. Do not quote this block in your JSON fields.
"""

# Angle C — direction-aware (deposit vs remove). Targets the dominant collection FP.
ANGLE_C_DIRECTION = IMBIRIBEIRA_PREAMBLE + """
DECISION RULE — MATERIAL FLOW DIRECTION IS PRIMARY:
Set material_flow_direction and decide by it.
ESCALATE (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) when
material moves TO the lot/ground:
- a person/cart/vehicle ARRIVES with a load and is later seen lighter / empty-handed;
- an object/bag/sack/bulky item is placed or dropped on the ground anywhere in the lot;
- a pickup/car stops and material is moved from the vehicle toward the ground.
SUPPRESS (new_litter_detected=false, confidence <= 50) when material moves FROM the lot,
i.e. COLLECTION/REMOVAL — even if the scene is busy with trucks and people:
- a truck/team loading garbage FROM the ground onto a vehicle (retirada de lixo);
- sweeping, raking, gathering, or hauling debris AWAY;
- people/vehicles merely parked or passing through with no object placed on the ground.
If direction is genuinely ambiguous but an object clearly ends up on the ground, escalate.
"""

# Angle D — small/distant-subject recall. Targets the missed on-foot TPs + FN.
ANGLE_D_SMALLSUBJECT = IMBIRIBEIRA_PREAMBLE + """
DECISION RULE — DO NOT MISS SMALL/DISTANT ON-FOOT DUMPERS:
Inspect small/distant figures carefully (they are the usual dumpers here).
ESCALATE (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) when a
person — EVEN small, distant, or partly behind the pole — does ANY of:
- stops in the lot and bends/squats/reaches toward the ground;
- carries a bag/sack/box/bulky object toward the lot and is later without it;
- pushes/parks a handcart/wheelbarrow/cart in the lot and handles its load;
- two or more people handle/deposit objects together on the lot.
The action may be in only one or two frames. Position ANYWHERE on the lot counts (no
"pile frontage" needed).
SUPPRESS (new_litter_detected=false, confidence <= 50) only for: a person clearly walking
THROUGH without stopping and with empty hands; municipal collection/removal; parked
vehicles with nobody transferring material.
"""

# Angle E — modality checklist. Enumerates the dump types seen at this camera.
ANGLE_E_MODALITY = IMBIRIBEIRA_PREAMBLE + """
DECISION RULE — CLASSIFY THE DUMP MODALITY:
Check, in order, whether ANY of these dumping modalities is visible. If yes -> ESCALATE
(scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85):
(a) VEHICLE: a car/pickup/truck STOPS in the lot and a load is unloaded / a bulky item is
    left on the ground (tailgate/trunk/bed activity ending with material on the ground);
(b) ON-FOOT BAG: a person (even small/distant) brings a bag/sack and leaves it on the lot;
(c) HANDCART: a handcart/wheelbarrow is pushed into the lot and its load is dumped;
(d) GROUP: two or more people handle and deposit objects on the lot together.
If NONE of (a)-(d) is visible -> new_litter_detected=false.
HARD SUPPRESS (confidence <= 50): COLLECTION/REMOVAL (truck/team loading garbage off the
ground, sweeping, hauling away), parked-only vehicles, and pass-through with empty hands.
"""

# Angle F — combined direction + small-subject (C+D).
ANGLE_F_COMBINED = IMBIRIBEIRA_PREAMBLE + """
DECISION RULE — combine flow-direction with careful small-subject inspection:
First set material_flow_direction. Inspect small/distant figures (the usual dumpers).
ESCALATE (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) when
EITHER:
- material clearly moves TO the lot/ground (object/bag/bulky item placed or dropped on the
  ground; loaded arrival then lighter departure; vehicle unloads toward the ground); OR
- a person — even small, distant, or partly behind the pole — stops and bends/reaches at
  the ground, carries a bag/object toward the lot and is later without it, or pushes a
  handcart whose load is handled. Action in one or two frames, anywhere on the lot, counts.
HARD SUPPRESS (new_litter_detected=false, confidence <= 50) when material moves FROM the
lot — COLLECTION/REMOVAL (truck/team loading garbage off the ground, sweeping, hauling
away) — or only parked vehicles / empty-handed pass-through are visible.
If an object clearly ends up on the ground, escalate even if direction was ambiguous.
"""

# Angle E2 — E_modality refined: tighten the VEHICLE modality so a car merely STOPPING
# (with a person getting out / walking) is NOT enough; require material to reach the
# ground. Targets E's residual "stopped vehicle + person" false alarms while keeping the
# real vehicle dumps (which leave a visible load/bulky item on the ground).
ANGLE_E2_MODALITY_TIGHT = IMBIRIBEIRA_PREAMBLE + """
DECISION RULE — CLASSIFY THE DUMP MODALITY (material must reach the ground):
Check, in order, whether ANY of these dumping modalities is visible. If yes -> ESCALATE
(scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85):
(a) VEHICLE: a car/pickup/truck stops AND material/a bulky item is actually moved from the
    vehicle ONTO the ground (a load leaves the vehicle, a bag/object/bulky item ends up on
    the lot, or the bed/trunk empties). A vehicle merely STOPPING, or a person simply
    getting out / standing / walking away with NO object placed on the ground, is NOT
    enough -> new_litter_detected=false.
(b) ON-FOOT BAG: a person (even small/distant) brings a bag/sack and LEAVES it on the lot;
(c) HANDCART: a handcart/wheelbarrow is pushed into the lot and its load is DUMPED on the
    ground;
(d) GROUP: two or more people handle and DEPOSIT objects on the lot together.
For (b)-(d), the carried object must end up on the ground (person later without it, or a
new object visible on the lot). Mere carrying-while-passing with the object retained is NOT
dumping.
If NONE of (a)-(d) is visible -> new_litter_detected=false.
HARD SUPPRESS (confidence <= 50): COLLECTION/REMOVAL (truck/team loading garbage off the
ground, sweeping, hauling away), parked-only or stopped vehicles with no material placed on
the ground, dogs/rain/lighting changes, and pass-through with empty hands or retained load.
"""

ANGLES = {
    "C_direction": ANGLE_C_DIRECTION,
    "D_smallsubject": ANGLE_D_SMALLSUBJECT,
    "E_modality": ANGLE_E_MODALITY,
    "F_combined": ANGLE_F_COMBINED,
    "E2_tight": ANGLE_E2_MODALITY_TIGHT,
}
