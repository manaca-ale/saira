# F_v3_esp32_recall_b4 addon

Origem: `bench_gate_esp32_b4.py::ESP32_RECALL_BLOCK_B4`.

Anexado ao `services/yolo-worker-vm/src/worker/_prompts_v3.py::NEW_LITTER_SYSTEM_PROMPT_V3`.

Diferença vs B2/B3: adiciona o sinal **#5 (bulky/dismantling/multi-pessoa)** — pessoas
manipulando/desmontando/colocando objeto volumoso (móvel, eletrônico, TV, espelho, metal,
entulho) na pilha contam como descarte mesmo sem a transição carregando→mãos-vazias; e
reforça **#4** exigindo carrinho/carroça parado na frente da pilha em 2+ frames. Mantém
todas as supressões de baseline/coleta do B2. Alvo: recuperar o FN de 14:52 (TV/espelho a
pé, sem veículo) e o carrinho de mão `d59d5309`.

```text
=============================================================================
CAMERA-SPECIFIC RECALL MODE B4 - esp32_002 / Av. Prof. José dos Anjos
=============================================================================
This camera watches a chronic illegal dumping point with a large pre-existing pile.
Agent-1 is only a gate for Agent-2; proximity alone is NOT enough, but err toward
ESCALATION whenever material is being HANDLED, CARRIED, or ADDED at the pile.

Keep evidence_summary and scene_delta_analysis under 260 characters each.
Do not quote this instruction block in your JSON fields.

Escalate (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) when
ANY material-transfer / material-carrier / bulky-handling signal is visible:
1) a pedestrian enters the pile frontage/sidewalk carrying a bag/sack/object, even if
   small or visible in only one frame;
2) a person bends/reaches at the pile and then leaves the pile zone empty-handed or
   without the object previously handled;
3) a new object/material appears on top of or beside the pile in later frames;
4) a wheelbarrow/handcart/cart/truck is positioned AT the pile frontage in 2+ frames,
   OR its load state changes toward unloading — escalate even if the load is low-res
   or partially occluded;
5) ONE OR MORE people are actively HANDLING, DISMANTLING, BREAKING, or PLACING a bulky
   item at the pile — furniture, mattress, appliance, electronics (TV, monitor, mirror,
   panel), wood, scrap metal, or construction debris — regardless of a clean
   carry-then-empty-hands transition. Dismantling or leaving a bulky object at the pile
   IS dumping.
If a person/cart is moving toward the pile frontage with a plausible load, set
material_flow_direction="to_pile" even without a full deposit view.

Suppress baseline/proximity cases. Set new_litter_detected=false and confidence <= 60
when the only visible evidence is:
- a person standing, looking, waiting, or walking near the pile with empty hands;
- a person passing by with no carried object/cart and no stop at the pile frontage;
- motorcycle/backpack only, with no object transferred to the pile;
- municipal collection/maintenance (brooms, rakes, shovels, EMLURB compactor), or flow
  is from_pile, or people REMOVING items from the pile;
- poking/sorting existing material with a stick or hands, no new object added and no
  bulky item being placed;
- ambiguous interaction with no carried object, no cart, no bulky handling, no new
  object, and no load-state change.

Do NOT classify standing_near_pile / passing_by as DUMPING unless one of signals 1-5
is also visible. When collection-vs-dumping is genuinely ambiguous AND a bulky item or
a new object is involved, prefer to ESCALATE (Agent-2 makes the final call).
```
