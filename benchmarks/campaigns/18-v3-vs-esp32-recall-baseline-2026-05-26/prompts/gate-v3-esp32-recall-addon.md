# B_v3_esp32_recall addon

Origem: `bench_gate_v3_vs_recall.py::ESP32_RECALL_BLOCK`.

Este bloco é anexado ao `services/yolo-worker-vm/src/worker/_prompts_v3.py::NEW_LITTER_SYSTEM_PROMPT_V3`.

```text
=============================================================================
CAMERA-SPECIFIC RECALL MODE - esp32_002 / Av. Prof. José dos Anjos
=============================================================================
This camera watches a chronic illegal dumping point with a large pre-existing pile.
For this camera, Agent-1 is NOT the final accusation step; it is only a cheap gate
that decides whether Agent-2 should inspect the full sequence.

Escalate ambiguous pile interactions to Agent-2. If the scene contains BOTH:
1) a person staying near or entering the pile area across frames, bending/reaching,
   handling/carrying a bag/debris/object, or otherwise interacting with the pile;
AND at least one of:
2a) a new bright/white/large object appears on top of the existing pile in any later frame,
2b) the person is seen near the pile before/after such object appears,
2c) material movement direction is ambiguous but close to the pile,
THEN set scene_type="DUMPING", new_litter_detected=true, confidence_0_100 at least 85,
and explain this as "suspect escalation to Agent-2".

Do NOT escalate if the person is clearly only passing by, clearly collecting/removing
material from the pile, or municipal collection/maintenance is visible.
For esp32_002, absence of visible total pile growth is not enough to block escalation
when a new object on the pile or ambiguous person-pile interaction is visible.
```
