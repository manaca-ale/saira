# -*- coding: utf-8 -*-
"""Campaign 44 — vehicle-focused gate addons for esp32_001 (Imbiribeira).

Same OPEN-LOT scene preamble as the live E_modality addon (campaign 31 winner); the
ONLY difference between arms is how dump modalities gate the decision. This keeps it a
clean A/B/C test (arm A = live E_modality, untouched).

  A_baseline      -> live ESP32_001_IMBIRIBEIRA_E_ADDON (any of a/b/c/d escalates)
  B_vehicle_hard  -> ONLY modality (a) VEHICLE escalates; on-foot/handcart/group suppressed
  C_vehicle_soft  -> vehicle escalates freely; on-foot modalities require a HIGHER bar
"""

# Shared scene preamble (verbatim from the live E_modality addon).
_PREAMBLE = """
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
""".rstrip()


# B — VEHICLE REQUIRED (hard). A dump counts ONLY when a vehicle deposits a load.
VEHICLE_HARD_ADDON = (_PREAMBLE + """

DECISION RULE — VEHICLE-DEPOSIT ONLY (this camera is far; pedestrians are mostly noise):
ESCALATE (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) ONLY if:
(a) VEHICLE: a car/pickup/truck/van STOPS in the lot and a load is unloaded, OR a bulky
    item is left on the ground from it (tailgate/trunk/bed activity ending with material
    on the ground). The vehicle being stationary + material appearing on the ground is the
    required signal.
Any dumping WITHOUT a depositing vehicle — on-foot bag, handcart/wheelbarrow, or a group
on foot — is NOT escalated by this gate -> new_litter_detected=false.
HARD SUPPRESS (confidence <= 50): COLLECTION/REMOVAL (truck/team LOADING garbage off the
ground, sweeping, hauling away), parked-only vehicles with no unloading, and any
pass-through with empty hands.
""").strip()


# C — VEHICLE PREFERRED (soft). Vehicle escalates freely; on-foot needs a higher bar.
VEHICLE_SOFT_ADDON = (_PREAMBLE + """

DECISION RULE — VEHICLE-FIRST, with a HIGH BAR for on-foot:
ESCALATE (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) if:
(a) VEHICLE: a car/pickup/truck/van STOPS and unloads a load / leaves a bulky item on the
    ground (tailgate/trunk/bed activity ending with material on the ground). Escalate.
On-foot modalities escalate ONLY with STRONG evidence (otherwise new_litter_detected=false):
(b) ON-FOOT BAG: a person shows a clear posture transition — carrying a bag/sack toward the
    lot and then EMPTY-HANDED — AND a new object is visibly left on the ground. A person
    merely walking, standing, or near debris with no carry->empty transition is NOT a dump.
(c) HANDCART: a handcart/wheelbarrow is pushed in and its load is visibly tipped/dumped.
(d) GROUP: TWO OR MORE people together handle and deposit objects on the ground.
If none of (a)-(d) meets its bar -> new_litter_detected=false.
HARD SUPPRESS (confidence <= 50): COLLECTION/REMOVAL (truck/team loading garbage off the
ground, sweeping, hauling away), parked-only vehicles, and pass-through with empty hands.
""").strip()


# B2 — STOPPED VEHICLE + BULKY LOAD. Targets the user's intent ("big disposals are made by
# vehicles") without requiring the exact unload-to-ground frame. The bulky-load requirement
# is what filters the parked/passing vehicles that make 110/147 FPs have a vehicle.
VEHICLE_BULKY_ADDON = (_PREAMBLE + """

DECISION RULE — STOPPED VEHICLE LEAVING A BULKY LOAD (only big vehicle dumps matter here):
ESCALATE (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) if BOTH:
(1) a car/pickup/truck/van is STOPPED in the lot — same spot across 2+ frames, NOT merely
    driving/passing through; AND
(2) a BULKY or LARGE load is left on the ground associated with it — entulho, móveis,
    construction/wood debris, several/large bags, big objects — that appears near the stopped
    vehicle and stays on the ground after the people/vehicle activity.
The vehicle does NOT need to be filmed mid-unload: a STOPPED vehicle + a NEW BULKY load on the
ground is enough (people may carry it the last few metres from the vehicle).
SUPPRESS (new_litter_detected=false, confidence <= 50): moving/passing vehicles; parked
vehicles with NO load left; a single small bag or light hand-carried item; pedestrians or
handcarts with no vehicle; COLLECTION/REMOVAL (truck/team LOADING garbage off the ground).
""").strip()


# B3 — STOPPED VEHICLE + ANY DEPOSIT ACTIVITY (looser; higher recall, higher FP risk).
VEHICLE_STOPPED_ACTIVITY_ADDON = (_PREAMBLE + """

DECISION RULE — STOPPED VEHICLE WITH DEPOSIT ACTIVITY:
ESCALATE (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) if a
car/pickup/truck/van is STOPPED in the lot (same spot in 2+ frames) AND there is deposit
activity tied to it: a person unloading/carrying cargo between the vehicle and the ground,
OR new material/objects left on the ground near the stopped vehicle.
SUPPRESS (new_litter_detected=false, confidence <= 50): moving/passing vehicles; parked
vehicles with people merely standing/talking and NO material left on the ground; on-foot
disposal with no vehicle; COLLECTION/REMOVAL (loading garbage off the ground).
""").strip()


ARM_ADDONS = {
    "B_vehicle_hard": VEHICLE_HARD_ADDON,
    "C_vehicle_soft": VEHICLE_SOFT_ADDON,
    "B2_vehicle_bulky": VEHICLE_BULKY_ADDON,
    "B3_vehicle_stopped": VEHICLE_STOPPED_ACTIVITY_ADDON,
    # A_baseline intentionally absent -> runner keeps the live E_modality addon.
}
