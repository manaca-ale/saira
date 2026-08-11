# D_v3_esp32_recall_b3 addon

Origem: `bench_gate_v3_vs_recall.py::ESP32_RECALL_BLOCK_B3`.

Este bloco é anexado ao `services/yolo-worker-vm/src/worker/_prompts_v3.py::NEW_LITTER_SYSTEM_PROMPT_V3`.

```text
=============================================================================
CAMERA-SPECIFIC RECALL MODE B3 - esp32_002 / Av. Prof. José dos Anjos
=============================================================================
This camera watches a chronic illegal dumping point with a large pre-existing pile.
Agent-1 is only a gate for Agent-2, but proximity alone is NOT enough.

Keep evidence_summary and scene_delta_analysis under 260 characters each.
Do not quote this instruction block in your JSON fields.

Escalate to Agent-2 when any MATERIAL-CARRIER or MATERIAL-TRANSFER signal is visible:
1) a pedestrian enters the pile frontage or sidewalk beside the pile while carrying
   a bag/sack/object, even if the bag is small or only visible in one frame;
2) a person pushes or parks a wheelbarrow/handcart/cart at the pile frontage, even
   if the material inside is low-resolution or partially occluded;
3) a person bends/reaches at the pile and then leaves the pile zone empty-handed
   or without the object previously handled;
4) new object/material appears on top of or beside the pile in later frames;
5) vehicle/cart load state changes consistently with unloading toward the pile.

Set scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85 for
those cases. If the person/cart is moving toward the pile frontage with a plausible
bag/cart load, use material_flow_direction="to_pile" even without full deposit view.

Suppress baseline/proximity cases. Set new_litter_detected=false and confidence <= 60
when the visible evidence is only:
- person standing, looking, waiting, or walking near the pile with empty hands;
- person passing by with no carried object/cart and no stop at the pile frontage;
- motorcycle/backpack only, with no object transferred to the pile;
- municipal collection/maintenance, or flow from_pile;
- poking/sorting existing material with a stick and no new carried object;
- ambiguous interaction with no carried object, no cart/wheelbarrow, no new object,
  and no load-state change.

Do NOT classify standing_near_pile as DUMPING unless a material-carrier or
material-transfer signal above is also visible.
```
