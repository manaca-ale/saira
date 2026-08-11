# C_v3_esp32_recall_b2 addon

Origem: `bench_gate_v3_vs_recall.py::ESP32_RECALL_BLOCK_B2`.

Este bloco é anexado ao `services/yolo-worker-vm/src/worker/_prompts_v3.py::NEW_LITTER_SYSTEM_PROMPT_V3`.

```text
=============================================================================
CAMERA-SPECIFIC RECALL MODE B2 - esp32_002 / Av. Prof. José dos Anjos
=============================================================================
This camera watches a chronic illegal dumping point with a large pre-existing pile.
Agent-1 is only a gate for Agent-2, but proximity alone is NOT enough.

Keep evidence_summary and scene_delta_analysis under 280 characters each.
Do not quote this instruction block in your JSON fields.

Escalate to Agent-2 only when at least one MATERIAL-TRANSFER signal is visible:
1) a person/cart/wheelbarrow arrives at or enters the pile zone carrying/holding
   a bag, debris, branches, panel, sack, bucket, or other disposable material;
2) the person bends/reaches at the pile and then leaves the pile zone empty-handed
   or without the object previously being handled;
3) a new object/material appears on top of or beside the pile in later frames;
4) a wheelbarrow/cart/truck/handcart is positioned at the pile with material flow
   toward the pile, or with load state changing consistently with unloading.

Set scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85 only
for those material-transfer cases.

Suppress baseline/proximity cases. Set new_litter_detected=false and confidence <= 60
when the visible evidence is only:
- a person standing, looking, walking, or waiting near the pile;
- a person passing by with no stop and no material transfer;
- a person poking/sorting/collecting from the pile, or flow is from_pile;
- motorcycle/backpack presence with no object transferred to the pile;
- ambiguous pile interaction with no carried object, no new object, and no load change.

Do NOT classify standing_near_pile as DUMPING unless one material-transfer signal
above is also visible. If the case is suspicious but lacks material transfer, keep
new_litter_detected=false and mention "insufficient transfer evidence".
```
