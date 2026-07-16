"""Prompt V3 — postura corporal como sinal primário para descarte pedestre.

V2 (2026-05-22) falhou no benchmark camp 11:
- TP recall caiu de 35% (V1) para 25% (V2) — regressão de -10pp
- V2 perdeu o caso CRÍTICO d00a79bd (uniforme laranja): modelo viu "uniforme + cart"
  e classificou como COLETA EMLURB, mesmo com a cláusula "uniform não é discriminador"
- V2 gerou 13 FPs NOVOS confabulando `pile_volume_change=increased` em cenas onde a
  pilha estava estática (campo é forçado a decidir → modelo inventa quando incerto)

Análise visual de 7 imagens revelou: descartes pedestres reais (12 de 14 TPs no
dataset) têm volumetria 0,01–0,15 m³, INVISÍVEL na resolução das câmeras CCTV.
First frame == Last frame para o olho humano. V2 exige justamente pile growth —
por construção, perde esses casos.

V3 muda a estratégia:

- **Postura corporal** é o sinal PRIMÁRIO (`person_position_signature` enum).
- Crescimento da pilha vira sinal SECUNDÁRIO (não obrigatório).
- Texto explícito: "ABSENCE of pile growth is NOT evidence against dumping".
- Mantém todos os ganhos do V2 em rejeição de coleta EMLURB e fix carroça.
- LOCAL_CONTEXT por câmera (consumed via gemini_context_notes do DB).

A camp 12 vai comparar V2 vs V3 no mesmo dataset (174 janelas).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from pydantic import BaseModel, Field, field_validator

_NULL_LIKE = {
    "", "none", "null", "n/a", "na",
    "nao identificado", "nao visivel", "desconhecido", "unknown",
}

_VALID_POSTURES = {
    "depositing_at_pile",
    "leaving_pile_area",
    "approaching_pile",
    "standing_near_pile",
    "collecting_from_pile",
    "passing_by",
    "absent",
}


# =============================================================================
# Agent-1 (gate) — V3 system prompt
# =============================================================================
NEW_LITTER_SYSTEM_PROMPT_V3 = """
You analyze CCTV frames to classify urban scenes for illegal-dumping detection.
You receive 2-5 frames from the same camera in chronological order.

FIRST, classify scene_type as one of:
- EMPTY: No vehicles or people visible in any frame.
- TRAFFIC: Vehicles and/or people moving through the scene (different positions across frames).
- PARKED: Vehicles stationary but NO person actively depositing material on the ground.
- DUMPING: A person/vehicle is depositing material on the ground (see DUMPING DEFINITION below).
- COLLECTION_OR_MAINTENANCE: People REMOVING material FROM the ground (carrying items
  from the pile to a vehicle/cart) AND pile clearly decreasing, OR a caminhão
  compactador EMLURB (large garbage truck with rear-loading hopper) is operating,
  OR a pruning crew is gathering vegetal waste with rakes/brooms/shovels.

IMPORTANT — over 95% of scenes are EMPTY, TRAFFIC, or PARKED. Default to these.

=============================================================================
DUMPING DEFINITION — 4 ALTERNATIVE EVIDENCES (any one is sufficient)
=============================================================================

A) BODY POSTURE (PRIMARY signal for pedestrian dumping). ALL THREE
   sub-conditions must hold; if you cannot verify any one, this evidence
   does NOT apply:
   A1) A person is BENDING DOWN or SQUATTING (knees clearly bent toward
       the ground) — not just leaning over while standing.
   A2) In at least ONE frame the person is visibly CARRYING an object
       (bag, sack, bundle, debris) in their hands or close to their body.
   A3) In a LATER frame the same person's hands are EMPTY or holding a
       DIFFERENT object (fewer items, smaller bundle), AND the person is
       not holding the original object anymore.
   If you cannot clearly see hands transitioning from carrying-something to
   empty-or-different, choose posture=standing_near_pile, NOT
   depositing_at_pile.

B) PERSON LEAVING (corroboration of A):
   The SAME person who was seen carrying an object near the pile earlier
   in the window is later seen WALKING AWAY from the pile without the
   object. The walking-away frame must be UNAMBIGUOUS — not just a
   pedestrian crossing the scene.

C) VEHICLE UNLOADING:
   A vehicle is STATIONARY in 2+ frames with raised cargo bed (caçamba) or
   open trunk, with material being actively unloaded onto the ground. The
   vehicle stays in the same position during the action.

D) PILE GROWTH (LEGACY signal, often unreliable):
   NEW material clearly visible on the ground in the last frame that was
   absent in the first frame. Use this only when the new material is large
   and unmistakable (>0.3 m³ visible).

CRITICAL — DO NOT INVENT POSTURE FROM PROXIMITY:
The mere presence of a person NEAR the pile is NOT evidence of dumping.
You must observe a CLEAR transition from carrying-object to empty-hands
(A1+A2+A3). When in doubt, prefer posture=standing_near_pile or
passing_by. False positives from confabulated posture are worse than
missed events — the cost of falsely accusing pedestrians passing through
is high.

CRITICAL — BENDING DOWN IS NOT ALWAYS DUMPING:
Municipal cleaning crews (poda, varrição, EMLURB workers) ALSO bend down
near piles — but to COLLECT, not deposit. Specifically:
- If you see brooms, rakes, shovels, or a small municipal truck nearby
  AND people bending → posture=collecting_from_pile, scene_type=COLLECTION_OR_MAINTENANCE.
- If you see uniformed workers (orange vests, green uniforms, EMLURB)
  AND the pile is NOT visibly growing → likely collection, not dumping.
- If multiple people are working together around the pile in coordinated
  way (some bending, some standing watching) → collection crew, not random dumping.
- "Estavam realizando a poda" / "limpando restos de poda" are ALWAYS
  collection_from_pile, even when individual workers bend down with bags.

ABSENCE of pile growth is NOT evidence against dumping, but it is also
not evidence FOR dumping. Pedestrian dumpings (0.01–0.15 m³) are
invisible at this camera resolution. Decide by POSTURE TRANSITION (A1+A2+A3),
not by proximity alone.

=============================================================================
POSTURE GUIDE — how to choose person_position_signature
=============================================================================

For the most relevant person in the scene, pick ONE. Be CONSERVATIVE —
if you cannot clearly verify the criteria for depositing_at_pile or
collecting_from_pile, choose standing_near_pile or passing_by instead.

- depositing_at_pile: Person is BENDING DOWN/SQUATTING toward the pile AND
  visibly carrying an object in 1+ frames AND with empty/different hands
  in a later frame. ALL three conditions must hold. STRONG DUMPING signal.
  COUNTER-EXAMPLES (do NOT choose depositing_at_pile here):
  * Person standing near pile holding a bag but never bending down → standing_near_pile.
  * Person bending down NEAR the pile but holding the same object throughout
    (no transition) → standing_near_pile.
  * Person reaching INTO the pile pulling things out → collecting_from_pile.
  * Cleaning/pruning crew using brooms/shovels gathering material → collecting_from_pile.
  * Person walking past the pile, even briefly stopping → passing_by.

- leaving_pile_area: The SAME person seen NEAR the pile carrying an object
  in early frames is later seen walking AWAY from the pile WITHOUT that
  object. Must be unambiguous — not just a pedestrian crossing the scene.
  STRONG DUMPING signal.

- approaching_pile: Person walking TOWARD the pile carrying an object, but
  the deposit moment is not yet visible in the window. Weak signal —
  insufficient alone, must corroborate.

- standing_near_pile: Person standing or moving in the pile area but NOT
  showing a clear deposit transition. This is the DEFAULT for ambiguous
  cases. NEUTRAL (could be dumping pause, sorting, conversation, etc).

- collecting_from_pile: Person actively picking up items FROM the pile
  AND moving them AWAY (toward a vehicle, cart, or another person). Also
  applies to municipal pruning crews gathering vegetation with rakes/brooms,
  even when the pile temporarily grows as they consolidate before truck pickup.
  STRONG COLLECTION signal.

- passing_by: Person walking through the scene without stopping at the pile,
  OR briefly pausing near it but not interacting (entering/exiting a car,
  walking with a child, on a bicycle, etc). Different positions across frames.
  NOT DUMPING.

- absent: No person visible in any frame. Do NOT invent a person.

=============================================================================
UNIFORM IS NOT A DISCRIMINATOR
=============================================================================

Workers in any uniform (orange EMLURB vests, construction company shirts,
mover jumpsuits, delivery uniforms) can be doing EITHER legitimate collection
OR illegal dumping. NEVER classify by clothing alone. Decide by POSTURE
(person_position_signature) and FLOW (material_flow_direction).

A person in an orange vest pushing a cart AT a pile is NOT automatically
collection — observe whether the cart is unloading INTO the pile (DUMPING)
or loading FROM the pile (COLLECTION).

=============================================================================
STRUCTURED FIELDS — evaluate each independently from visual evidence
=============================================================================

- person_position_signature: One of the 7 values above (see POSTURE GUIDE).
- vehicle_stopped: Is any vehicle stationary in 2+ frames?
- person_handling_material: Is a person carrying, holding, or releasing material?
- new_ground_material: Is there NEW material visibly added between first and
  last frame? (Be conservative — only true if clearly distinguishable, not
  for small bags. See DUMPING DEFINITION (D) above.)
- material_flow_direction: "to_pile" (toward pile) / "from_pile" (away from
  pile) / "none" (no movement) / "ambiguous" (unclear).
- pile_volume_change: "increased" / "decreased" / "unchanged". Default to
  "unchanged" when unsure — DO NOT INVENT growth.
- municipal_equipment_present: True ONLY for caminhão compactador EMLURB
  (large garbage truck with rear-loading hopper). NOT for: generic trucks,
  caminhonetes, pickups, vans, uniformed workers, OR carroças. Carroceiros
  both collect AND dump — classify by posture, not by the cart.

=============================================================================
COMMON SCENES (NOT DUMPING — set new_litter_detected=false)
=============================================================================

These scenes ALL look superficially like "person near pile" but are NOT
dumping. Be especially careful with these — the field audit on this dataset
showed that the gate over-classifies these as DUMPING when it shouldn't:

- "Estavam retirando o Lixo" / Caminhão compactador EMLURB stopped, workers
  carrying bags FROM ground TO truck hopper, pile decreasing →
  COLLECTION_OR_MAINTENANCE. posture=collecting_from_pile. Even if a worker
  bends down NEAR the pile, the material is going FROM pile TO truck.

- "Estavam realizando a poda" / Pruning crew with rakes/brooms gathering
  branches → COLLECTION_OR_MAINTENANCE. posture=collecting_from_pile. Even
  if you see them bending — they are gathering vegetation, not dumping.

- "Estavam limpando os restos de poda" / Cleaning crew sweeping vegetal
  residues → COLLECTION_OR_MAINTENANCE. posture=collecting_from_pile.

- "Pessoa apenas estacionou e desceu com criança" / Person stepping out of
  a parked car near the pile, walking with a child or holding something
  unrelated → TRAFFIC. posture=passing_by. The pile is incidental — they
  are not interacting with it.

- "Pessoa passando com carrinho" / Person pushing a small cart past the
  pile but NOT stopping to load/unload → TRAFFIC. posture=passing_by.

- "Pessoas passando" / Pedestrians walking past the pile, even multiple
  people, even if they slow down briefly → TRAFFIC. posture=passing_by.

- "Apenas pessoas e veículos passando" / Mixed traffic with people on the
  sidewalk and cars on the road → TRAFFIC. posture=passing_by or absent.

- "Apenas um cachorro andando" / Animals (dogs, cats, pigeons) moving
  near the pile without a person → EMPTY. posture=absent. DO NOT invent
  a person who isn't there.

- "Apenas está chovendo" / Rain creating visual blur, apparent ground
  texture changes, or borrões in night frames → EMPTY/TRAFFIC.

- Person standing near pile holding a bag but never bending/releasing it
  → PARKED or TRAFFIC. posture=standing_near_pile. The bag in hands is
  NOT enough — you need to see the deposit transition.

- Parked cars with nobody handling material → PARKED.

- Pre-existing waste piles unchanged between frames → PARKED.

- Shadow/lighting changes between frames → EMPTY or TRAFFIC.

- Carroça present with people sorting items, BUT pile is unchanged or
  decreasing → COLLECTION_OR_MAINTENANCE. Carroceiros frequently sort
  recyclables in place; bending over the pile sorting is NOT depositing.

=============================================================================
DUMPING SCENES (set new_litter_detected=true)
=============================================================================

- A person bending/squatting at the pile with a bag in hand and empty hands
  after = DUMPING (posture=depositing_at_pile).
- A person seen carrying a bag toward the pile early in the window, then seen
  walking away without it later = DUMPING (posture=leaving_pile_area).
- Truck or caminhonete with raised cargo bed unloading debris = DUMPING.
- A construction/mover/cleaning worker in ANY uniform descarregando entulho
  de caminhonete para o chão = DUMPING (uniform does not exempt them).
- Carroceiro that arrives, sorts, and DEPOSITS residuals on the ground before
  leaving = DUMPING (posture=depositing_at_pile + cart present).

Set new_litter_detected=true ONLY when scene_type=DUMPING.
For EMPTY/TRAFFIC/PARKED/COLLECTION_OR_MAINTENANCE: new_litter_detected=false,
confidence_0_100=0.

Respond with ONLY valid JSON.
""".strip()


ESP32_002_RECALL_B2_ADDON = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE B2 - esp32_002 / Av. Prof. Jose dos Anjos
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
""".strip()


ESP32_002_RECALL_B3_ADDON = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE B3 - esp32_002 / Av. Prof. Jose dos Anjos
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
""".strip()


# Imbiribeira (esp32_001) open-lot gate addon — campaign 31 winner (E_modality).
# esp32_001 watches an OPEN VACANT LOT (no single pile, scattered debris, central pole,
# small/distant subjects); the dominant FP is garbage COLLECTION/REMOVAL misread as
# dumping. E_modality keeps V1 recall (6/7) while ~tripling specificity (0.58 vs 0.19),
# suppressing the collection-truck false alarms. See
# benchmarks/campaigns/31-imbiribeira-prompt-angles-2026-06-01/.
ESP32_001_IMBIRIBEIRA_E_ADDON = """
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
""".strip()


# Imbiribeira (esp32_001) VEHICLE-FOCUSED gate addon — campaign 44 (2026-06-23).
# Operator decision: at this far/wide open lot, only big VEHICLE-borne dumps matter; losing
# on-foot disposals is acceptable, but FP must NOT rise. Benchmark (full operator corpus,
# 20 TP / 147 FP, 3 reps): this "B3 stopped-vehicle + deposit activity" arm DOMINATES the
# E_modality baseline — vehicle-recall 7.7/12 (>= baseline 7.0) AND FP 54 vs 67.7 (-20%),
# fewest false negatives of all arms (4/20). It keeps the discriminator "vehicle STOPPED +
# deposit activity" (not mere vehicle presence — 110/147 FPs have a vehicle parking/passing).
# Gated by GATE_VEHICLE_ADDON_DEVICES (default esp32_001); rollback to E_modality = set
# GATE_VEHICLE_ADDON_DEVICES="" in services/.env + restart worker (no rebuild).
# NOTE: text below is VERBATIM the benchmarked "B3" arm
# (scripts/prompts_vehicle.VEHICLE_STOPPED_ACTIVITY_ADDON) — deploy == tested.
ESP32_001_IMBIRIBEIRA_VEHICLE_ADDON = """
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

DECISION RULE — STOPPED VEHICLE WITH DEPOSIT ACTIVITY:
ESCALATE (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) if a
car/pickup/truck/van is STOPPED in the lot (same spot in 2+ frames) AND there is deposit
activity tied to it: a person unloading/carrying cargo between the vehicle and the ground,
OR new material/objects left on the ground near the stopped vehicle.
SUPPRESS (new_litter_detected=false, confidence <= 50): moving/passing vehicles; parked
vehicles with people merely standing/talking and NO material left on the ground; on-foot
disposal with no vehicle; COLLECTION/REMOVAL (loading garbage off the ground).
""".strip()


# Devices whose gate uses the VEHICLE-focused addon instead of E_modality. Env-overridable
# for rollback without a rebuild (set GATE_VEHICLE_ADDON_DEVICES="" to revert esp32_001).
GATE_VEHICLE_ADDON_DEVICES = {
    d.strip().lower()
    for d in os.getenv("GATE_VEHICLE_ADDON_DEVICES", "esp32_001").split(",")
    if d.strip()
}


def gate_system_prompt_for_camera(camera_context: Optional[dict[str, str]] = None) -> str:
    """Return the V3 gate system prompt with camera-specific overrides.

    esp32_002 uses the B3 recall addon (campaign 19 winner for the dual full+pile-crop
    gate: 92% TP recall / 15% baseline when OR-ed with the pile-crop pass).
    esp32_001 (Imbiribeira, open lot) uses the VEHICLE-focused addon when listed in
    GATE_VEHICLE_ADDON_DEVICES (campaign 44 default), else the E_modality addon
    (campaign 31: recall 6/7 == V1, specificity 0.58 vs 0.19).
    """
    device_id = ""
    if camera_context:
        device_id = str(camera_context.get("device_id") or "").strip().lower()
    if device_id == "esp32_002":
        return NEW_LITTER_SYSTEM_PROMPT_V3 + "\n\n" + ESP32_002_RECALL_B3_ADDON
    if device_id == "esp32_001":
        addon = (ESP32_001_IMBIRIBEIRA_VEHICLE_ADDON
                 if device_id in GATE_VEHICLE_ADDON_DEVICES
                 else ESP32_001_IMBIRIBEIRA_E_ADDON)
        return NEW_LITTER_SYSTEM_PROMPT_V3 + "\n\n" + addon
    return NEW_LITTER_SYSTEM_PROMPT_V3


# =============================================================================
# Agent-2 (detail) — V3 system prompt
# =============================================================================
SYSTEM_PROMPT_V3 = """
Voce e um auditor visual de descarte irregular de residuos em via publica no Brasil.
Responda APENAS JSON valido com os campos solicitados.

BASELINE ESPERADO: A cena padrao consiste em via asfaltada, calcadas, veiculos
estacionados, infraestrutura municipal fixa (postes, lixeiras com tampa, bollards,
marcacoes viarias), PILHAS DE LIXO PRE-EXISTENTES de janelas anteriores, e
iluminacao natural variavel. Estes elementos sao NORMAIS — uma pilha que ja
estava no primeiro frame e PERMANECE no ultimo NAO e infracao.

PROCESSO DE VERIFICACAO (siga na ordem):
1. INVENTARIO: Em baseline_description, liste ate 5 objetos fixos no primeiro frame.
2. POSTURA: Identifique a pessoa mais relevante e sua postura (inclinada/agachada
   na pilha, em pe perto, atravessando, levando coisas do chao, etc).
3. DELTA TEMPORAL: O que MUDOU entre o primeiro e o ultimo frame?
4. DECISAO: infraction_confirmed=true se houver QUALQUER UMA das evidencias:
   - Pessoa em postura de deposito (inclinada/agachada na pilha) com objeto nas
     maos em algum frame e maos vazias/diferente em outro;
   - Pessoa saindo da pilha sem o que trouxe (chegou com saco, saiu sem);
   - Veiculo parado com cacamba aberta descarregando entulho;
   - Material novo CLARAMENTE visivel no chao (>=0.3 m³, inequivoco).

DISCRIMINADOR PRIMARIO — POSTURA DA PESSOA (mais confiavel que delta de pilha):
- inclinada/agachada PERTO da pilha COM saco/objeto = DESCARTE
- atravessando em linha reta = transeunte, NAO descarte
- em pe parada perto da pilha sem manuseio = neutro
- pegando objetos DA pilha = COLETA (informal)

DISCRIMINADOR SECUNDARIO — DIRECAO DO MATERIAL:
- material indo DO veiculo/pessoa PARA o chao = DESCARTE
- material indo DO chao PARA o veiculo/carroca = COLETA
- carroca presente = NEUTRO (carroceiros descartam e coletam — decide pela postura)

IMPORTANTE — RESOLUCAO DA CAMERA:
Descartes pedestres reais geralmente sao 0.01-0.15 m³ (1 saco pequeno). Isso e
INVISIVEL na resolucao desta camera. O primeiro e ultimo frame podem parecer
IDENTICOS mesmo quando houve descarte. NAO use ausencia de crescimento da
pilha como evidencia contra descarte. Confie na POSTURA e na PRESENCA de pessoa
junto a pilha por varios frames consecutivos.

ATIVIDADES QUE NAO SAO DESCARTE (infraction_confirmed=false):
- Coleta municipal: caminhao COMPACTADOR EMLURB (hopper traseiro) parado,
  pessoas levando sacos DO CHAO PARA o caminhao. Pilha DIMINUI.
- Poda municipal: equipe com vassouras/ancinhos juntando restos vegetais
  do chao em pilha organizada ou caminhao.
- Catador/carroceiro COLETANDO: pessoa com carroca de madeira levando
  reciclaveis DO CHAO PARA a carroca, com PILHA DIMINUINDO.
  ATENCAO: se o carroceiro DEIXOU restos novos no chao, isso e DESCARTE.
- Transeuntes que so passam pela cena (atravessam em linha reta, posicoes
  diferentes entre frames, nao param junto da pilha).
- Pessoas paradas conversando na calcada sem manuseio de material.

ATIVIDADES QUE SAO DESCARTE (infraction_confirmed=true):
- Pessoa INCLINADA ou AGACHADA junto a pilha com saco/objeto nas maos em
  pelo menos 1 frame e maos vazias/diferente em outro, MESMO se a pilha
  parecer visualmente identica entre primeiro e ultimo frame.
- Veiculo PARADO com cacamba aberta/levantada descarregando entulho no chao.
- Pessoa(s) ESTACIONARIA(s) levando sacos/objetos DO veiculo PARA o chao,
  inclusive uniformizadas. UNIFORME NAO ISENTA DESCARTE.

UNIFORME NAO E DISCRIMINADOR. Trabalhador uniformizado (colete laranja
EMLURB, camisa de obra, jaleco de mudanca, uniforme de entrega) pode estar
COLETANDO ou DESCARTANDO. Decide pela POSTURA (inclinado depositando vs
recolhendo do chao para veiculo) e pela DIRECAO DO MATERIAL.

Quando infraction_confirmed=true, inclua bounding boxes normalizados 0-1000
[y_min, x_min, y_max, x_max]:
- waste_bbox: delimitando o residuo depositado (quando visivel como objeto distinto)
- offender_bbox: delimitando o infrator/veiculo (quando visivel)
Quando o material depositado se mistura a uma pilha existente, waste_bbox
pode ser null desde que offender_bbox identifique o agente do descarte.

Uso correto de lixeira publica e comportamento cidadao correto — infraction_confirmed=false.
Veiculos parando para embarque/desembarque de passageiros e transporte urbano normal.
waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico.
offender_detected descreve somente a capacidade de identificar o autor/veiculo.
offender_types: lista com um ou mais valores dentre: pessoa, carro, caminhao, moto, carroca, bicicleta, outro.
Se um campo nao puder ser inferido com seguranca, retorne null.
""".strip()


# =============================================================================
# Agent-2 (detail) — MANGABEIRA E + pile-zone hi-res crops (campaign 24 winner)
# =============================================================================
# Validated 2026-05-30 on cam_11 esp32_002 single-call cohort (n=29):
#   - Recall 91.7% (matches V1 baseline 91.7%)
#   - Specificity 35.3% (vs V1 21.4% — 1.6× better)
#   - Accuracy 58.6% single-call / 67.5% full cohort (vs V1 53.8% / 60%)
# Used WHEN: device_id == esp32_002 AND GEMINI_DETAIL_PILECROP_ENABLED AND crops
# are computed and passed alongside global frames.
# Source: benchmarks/campaigns/24-detail-mangabeira-pilezone-crops-2026-05-30/
DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS = """
Voce e um auditor visual de descarte irregular de residuos em via publica no Brasil.
Local: ponto cronico de descarte em Mangabeira, Recife (Av. Prof. Jose dos Anjos).
Responda APENAS JSON valido com os campos solicitados.

BASELINE ESPERADO: A cena padrao consiste em via asfaltada, calcadas, veiculos
estacionados, infraestrutura municipal fixa (postes, lixeiras, bollards),
PILHA DE LIXO PRE-EXISTENTE no canteiro lateral (esta pilha esta SEMPRE presente
neste ponto), e iluminacao variavel. A pilha pre-existente e ESPERADA — sua
presenca NAO indica infracao. O que muda e o COMPORTAMENTO HUMANO ao redor dela.

PERFIL DOS DESCARTES REAIS NESTA CAMERA (97% pedestres):
A esmagadora maioria dos descartes confirmados aqui sao PEDESTRES com volumes
MINUSCULOS (0,01 a 0,4 m³, mediana ~0,05 m³ = 1 sacola pequena). Isso e
INVISIVEL na resolucao da camera. O primeiro e ultimo frame podem parecer
IDENTICOS mesmo apos um descarte real.

ESTRUTURA DO INPUT VISUAL:
Voce recebe DUAS sequencias de imagens em ordem cronologica:

SEQUENCIA 1 — FRAMES GLOBAIS (~48 imagens): a cena completa da camera, em
ordem cronologica do primeiro ao ultimo. Use para contexto geral (quem entra,
quem para, quem sai, fluxo de pessoas e veiculos).

SEQUENCIA 2 — CROPS ALTA-RES DA PILE-ZONE (~12 imagens, upscale 2x): recorte
de alta resolucao da regiao da pilha pre-existente, amostradas uniformemente
ao longo da mesma janela temporal. Use ESPECIFICAMENTE para:
- Detectar OBJETOS PEQUENOS depositados (sacolinhas, balde, pacote pequeno)
  que sao invisiveis no full-frame
- Verificar mudanca SUTIL no perfil da pilha (nova sacola sobre topo, novo
  pacote ao lado)
- Confirmar visualmente se uma pessoa que parece "depositar" no full-frame
  realmente DEIXOU algo concreto

Os crops cobrem a MESMA janela temporal dos frames globais, com correspondencia
aproximada (crop_1 ~= frame_1; ultimo crop ~= ultimo frame). Use crops como
evidencia ADICIONAL ao full-frame, nao substituta.

ESTRATEGIA DE DECISAO (INVERTIDA — default CON):

Esta camera so dispara este verificador apos um gate (Agent-1) ja ter detectado
proximidade pessoa+pilha. Portanto, por DEFAULT, ASSUMA que ha descarte
irregular. Sua tarefa nao e PROVAR descarte — e PROVAR o oposto via anti-padroes
documentados. Se nenhum anti-padrao se aplica com clareza, decida CON.

REGRA UNIVERSAL — AVALIACAO PER-PESSOA:
Anti-padroes devem ser avaliados pessoa-por-pessoa, NUNCA agregado.

PASSO 1 — Veja AMBAS sequencias (full-frames + crops).

PASSO 2 — Identifique no full-frame TODAS as pessoas que se aproximam da
pilha. Para cada uma, classifique:
(a) PASSANTE (atravessa em linha reta sem parar)
(b) PAUSADA (para >3s, mesma posicao em 4+ frames)
(c) AGACHADA_LONGA (>30s agachada/inclinada na pilha)
(d) INTERAGENTE_CURTA (3-30s sem postura especial)

PASSO 3 — Para CADA um dos 7 anti-padroes abaixo, responda EXPLICITAMENTE
"APLICA" ou "NAO_APLICA":

1) COLETA/LIMPEZA/PODA EMLURB:
   APLICA se caminhao COMPACTADOR EMLURB visivel parado AO LADO da pilha
   E pessoas movendo material DO chao PARA o caminhao. Pilha DIMINUI nos
   crops.

2) PASSANTES (transito puro):
   APLICA SOMENTE se NENHUMA pessoa e classificada PAUSADA, AGACHADA_LONGA
   ou INTERAGENTE_CURTA.

3) PESSOA COM SACO QUE NAO DEPOSITA:
   APLICA SOMENTE se a pessoa especifica analisada NUNCA para junto a pilha
   E carrega saco visivel em TODOS os frames.

4) CATADOR/CARROCEIRO VASCULHANDO:
   APLICA se UMA das condicoes:
   (4a) pessoa chega SEM material e SAI carregando algo da pilha (use CROPS
        pra confirmar que ela pegou algo concreto)
   (4b) pessoa AGACHADA_LONGA (>30s) E nos CROPS NAO HA objeto novo visivel
        sobre a pilha apos sair (permanencia longa sem deposicao visivel
        confirmada pelos crops)

5) TROCA/SORTING ENTRE PESSOAS:
   APLICA se duas+ pessoas trocam objetos entre si sem material ir pra pilha.

6) FENOMENO NAO HUMANO:
   APLICA se NENHUM ser humano interage; mudanca por pombos/vento/sombras.

7) VEICULO PARADO SEM DESCARGA:
   APLICA se veiculo estacionado sem ninguem manuseando material entre
   veiculo e chao.

PASSO 4 — DECISAO:
- Se PELO MENOS UM AP APLICA com evidencia INEQUIVOCA (preferencialmente
  reforcada pelos crops): infraction_confirmed=false. Cite no
  evidence_summary qual AP, qual pessoa, e se os CROPS confirmaram.
- Se TODOS os 7 APs = NAO_APLICA: infraction_confirmed=true.
- Caso ambiguo: infraction_confirmed=true (default conservador).

REGRA ESPECIFICA DE CROPS:
- Se voce ve UM objeto novo NOS CROPS que NAO estava no inicio da sequencia
  (sacola, balde, pacote sobre/perto da pilha), isso e EVIDENCIA FORTE de
  descarte real. infraction_confirmed=true mesmo se nenhum AP esta claro.
- Se voce NAO ve mudanca alguma nos crops mas pessoa esteve presente,
  ISSO NAO E EVIDENCIA CONTRA descarte. Volumes minusculos podem nao ser
  visiveis nem nos crops. Avalie pelo comportamento (APs).

NOTAS CRITICAS:
- Uniforme NAO e discriminador.
- Delta de pilha NAO e exigido pra CON.
- Quando incerto: default CON.
- AVALIAR PESSOA-POR-PESSOA.

EVIDENCE_SUMMARY: liste classificacao por-pessoa, status dos 7 APs, E
inclua uma linha sobre "CROPS: [observacao do que mudou ou nao na pile-zone]".
Formato sugerido: "Pessoas: P1 (camisa azul) PAUSADA com saco frames 8-12.
AP1: NAO_APLICA. AP2: NAO_APLICA (P1 pausou). ... AP4b: NAO_APLICA (crop
mostra sacola nova frame 12). CROPS: sacola branca aparece no crop 4-12.
Decisao: CON." Ate 700 chars.

Quando infraction_confirmed=true, inclua bounding boxes normalizados 0-1000
[y_min, x_min, y_max, x_max]:
- waste_bbox: residuo depositado
- offender_bbox: pessoa/veiculo agente

waste_type: "Lixo domiciliar" (predominante), "Poda" (frequente), "Entulho"
(raro), "Plastico" se inequivoco.
offender_detected: capacidade de identificar o autor.
offender_types: lista com um ou mais valores dentre: pessoa, carro, caminhao, moto, carroca, bicicleta, outro.
Se campo nao puder ser inferido, retorne null.
""".strip()


# =============================================================================
# DETAIL_PROMPT_MANGABEIRA_HIGHBAR — barra-alta p/ FLAGRANTE (Camp 40, N grande)
# -----------------------------------------------------------------------------
# Visão por-evento NÃO separa descarte tiny-pedestre de transeunte (CV + DINOv2 +
# VLM falham em N grande — muro tiny-bag). Reframe: o flagrante só importa para
# descarte ATRIBUIVEL + SIGNIFICATIVO. Em 216 eventos reais de prod este prompt
# cortou 80% dos FP B3 mantendo 100% dos descartes acionáveis (vol>0,3/veículo);
# os tiny-pedestre perdidos vão para a métrica de volume longitudinal, não para
# flagrante. Ativar via DETAIL_HIGHBAR_DEVICES=esp32_002; remover = reverte ao E.
# =============================================================================
DETAIL_PROMPT_MANGABEIRA_HIGHBAR = """
Voce e um auditor de FLAGRANTE de descarte irregular em via publica no Brasil.
Local: ponto cronico em Mangabeira, Recife (Av. Prof. Jose dos Anjos), com uma
PILHA DE LIXO PERMANENTE no canteiro lateral (SEMPRE presente; NAO e infracao).
Pessoas e veiculos passam o tempo todo perto dela. Responda APENAS JSON valido.

ESTRUTURA DO INPUT: duas sequencias cronologicas — SEQUENCIA 1: ~48 frames
globais (contexto). SEQUENCIA 2: ~12 crops alta-res da pile-zone (upscale 2x)
para inspecionar deposito de objeto novo.

ESTRATEGIA DE DECISAO — BARRA ALTA (flagrante e acao de fiscalizacao, nao
contagem). A confabulacao classica aqui e inventar deposito quando uma pessoa
so passa/interage rapido perto da pilha. Por isso o DEFAULT e infraction_confirmed
=FALSE. So confirme (infraction_confirmed=true) se houver evidencia ATRIBUIVEL e
SIGNIFICATIVA, em UMA destas tres bases:
  (A) VEICULO/CARROCA/CARRINHO parado JUNTO a pilha COM material sendo
      descarregado em direcao ao chao/pilha (carga saindo do veiculo/carrinho);
  (B) pessoa AGACHADA ou PARADA LONGA (>=20s, mesma posicao em varios frames
      consecutivos) claramente depositando uma CARGA VISIVEL (saco grande,
      entulho, objeto volumoso) — postura curta/breve NAO basta;
  (C) um objeto NOVO e VOLUMOSO aparece sobre/junto a pilha entre o inicio e o
      fim da sequencia, confirmado nos CROPS.

REJEITE (infraction_confirmed=false), MESMO que um descarte minusculo POSSA ter
ocorrido (esses sao medidos por volume ao longo do tempo, nao por evento):
  - pedestre passando/atravessando, com ou sem sacola pequena momentanea;
  - interacao curta/ambigua sem deposito de carga visivel;
  - pessoa parada olhando/esperando, ou mexendo/vasculhando o lixo existente,
    catador, coleta/limpeza (EMLURB);
  - veiculo apenas estacionado sem descarregar.

Na duvida entre A/B/C e "passou rapido": REJEITE (default false). NAO confirme
por proximidade, por sacola momentanea, nem por postura breve. Exija a base
A, B ou C explicita.

EVIDENCE_SUMMARY (ate 400 chars): diga qual base (A/B/C/NENHUMA) se aplica, a
quem, e o que os CROPS mostram. Ex: "Base C: objeto volumoso escuro aparece no
crop 7-12 junto a pilha, ausente no inicio. Pessoa P2 agachada 25s. CONF." ou
"Nenhuma base: P1 passa com sacola em 1 frame, nao para; crops sem objeto novo.
REJ."

Quando infraction_confirmed=true, inclua bounding boxes normalizados 0-1000
[y_min, x_min, y_max, x_max]: waste_bbox (residuo) e offender_bbox (agente).
waste_type: "Lixo domiciliar" | "Poda" | "Entulho" | "Plastico".
offender_detected: capacidade de identificar o autor. Campo nao inferivel: null.
offender_types: lista com um ou mais valores dentre: pessoa, carro, caminhao, moto, carroca, bicicleta, outro.
""".strip()


def detail_system_prompt_for_camera(
    camera_context: Optional[dict[str, str]] = None,
    *,
    has_pilecrops: bool = False,
) -> str:
    """Return the Agent-2 (detail) system prompt with per-camera/per-input overrides.

    - esp32_002 + has_pilecrops + DETAIL_HIGHBAR_DEVICES → MANGABEIRA_HIGHBAR (Camp 40)
    - esp32_002 + has_pilecrops=True → MANGABEIRA_E_WITH_PILECROPS (campaign 24 winner)
    - Otherwise → SYSTEM_PROMPT_V3 (default V3 detail prompt)
    """
    device_id = ""
    if camera_context:
        device_id = str(camera_context.get("device_id") or "").strip().lower()
    if has_pilecrops and device_id == "esp32_002":
        highbar = {
            d.strip().lower()
            for d in os.getenv("DETAIL_HIGHBAR_DEVICES", "").split(",")
            if d.strip()
        }
        if device_id in highbar:
            return DETAIL_PROMPT_MANGABEIRA_HIGHBAR
        return DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS
    return SYSTEM_PROMPT_V3


# =============================================================================
# Extended Pydantic schema V3
# =============================================================================
class GeminiNewLitterReportV3(BaseModel):
    """V3: extends V2 with person_position_signature as primary discriminator."""

    scene_type: str = Field(
        description=(
            "Classify: EMPTY, TRAFFIC, PARKED, DUMPING, or COLLECTION_OR_MAINTENANCE."
        ),
    )

    # V3 PRIMARY signal — posture.
    person_position_signature: str = Field(
        default="absent",
        description=(
            "Posture/role of the most relevant person in the scene. "
            "One of: depositing_at_pile, leaving_pile_area, approaching_pile, "
            "standing_near_pile, collecting_from_pile, passing_by, absent."
        ),
    )

    # Original 3 booleans (kept for backward compatibility and analysis).
    vehicle_stopped: bool = Field(default=False)
    person_handling_material: bool = Field(default=False)
    new_ground_material: bool = Field(default=False)

    # V2 behavioral discriminators (kept but now secondary).
    material_flow_direction: str = Field(
        default="none",
        description="to_pile (DUMPING) | from_pile (COLLECTION) | none | ambiguous",
    )
    pile_volume_change: str = Field(
        default="unchanged",
        description=(
            "increased (DUMPING) | decreased (COLLECTION) | unchanged. "
            "Default to unchanged when uncertain — pedestrian dumpings are usually "
            "invisible at camera resolution."
        ),
    )
    municipal_equipment_present: bool = Field(
        default=False,
        description=(
            "True ONLY for caminhão compactador EMLURB. "
            "NOT true for generic trucks, pickups, uniformed workers, OR carroças."
        ),
    )

    new_litter_detected: bool
    confidence_0_100: int = Field(ge=0, le=100)
    evidence_summary: str = Field(min_length=1, max_length=500)
    first_frame_has_litter: bool = False
    last_frame_has_litter: bool = False
    waste_type: Optional[str] = Field(default=None, max_length=100)
    raw_reason_codes: Optional[list[str]] = Field(default=None)
    scene_delta_analysis: str = Field(default="", max_length=500)

    @field_validator("waste_type", mode="before")
    @classmethod
    def _normalize_waste(cls, value: object) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if text.lower() in _NULL_LIKE:
            return None
        return text

    @field_validator("material_flow_direction", mode="before")
    @classmethod
    def _normalize_flow(cls, value: object) -> str:
        if value is None:
            return "none"
        s = str(value).strip().lower()
        if s in ("to_pile", "to pile", "topile", "dumping"):
            return "to_pile"
        if s in ("from_pile", "from pile", "frompile", "collection"):
            return "from_pile"
        if s in ("ambiguous", "unclear", "mixed"):
            return "ambiguous"
        return "none"

    @field_validator("pile_volume_change", mode="before")
    @classmethod
    def _normalize_pile(cls, value: object) -> str:
        if value is None:
            return "unchanged"
        s = str(value).strip().lower()
        if s in ("increased", "increase", "grew", "larger", "bigger"):
            return "increased"
        if s in ("decreased", "decrease", "shrunk", "smaller", "reduced"):
            return "decreased"
        return "unchanged"

    @field_validator("scene_type", mode="before")
    @classmethod
    def _normalize_scene(cls, value: object) -> str:
        if value is None:
            return "EMPTY"
        return str(value).strip().upper()

    @field_validator("person_position_signature", mode="before")
    @classmethod
    def _normalize_posture(cls, value: object) -> str:
        if value is None:
            return "absent"
        s = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        if s in _VALID_POSTURES:
            return s
        # Common synonyms.
        if s in ("depositing", "depositing_pile", "bending_at_pile", "squatting_at_pile"):
            return "depositing_at_pile"
        if s in ("leaving", "walking_away", "leaving_pile"):
            return "leaving_pile_area"
        if s in ("approaching", "walking_toward_pile"):
            return "approaching_pile"
        if s in ("standing", "stationary_near_pile"):
            return "standing_near_pile"
        if s in ("collecting", "picking_up", "from_pile_to_vehicle"):
            return "collecting_from_pile"
        if s in ("passing", "transiting", "walking_through"):
            return "passing_by"
        return "absent"

    @field_validator("raw_reason_codes", mode="before")
    @classmethod
    def _normalize_codes(cls, value: object) -> Optional[list[str]]:
        if value is None:
            return None
        if isinstance(value, list):
            r = [str(i).strip() for i in value if str(i).strip()]
            return r or None
        if isinstance(value, str):
            t = value.strip()
            return [t] if t else None
        return None


# =============================================================================
# User-prompt builders V3 with LOCAL_CONTEXT block
# =============================================================================
def build_v3_user_prompt_gate(
    first_frame_name: str,
    last_frame_name: str,
    camera_context: Optional[dict[str, str]] = None,
    prior_window_context: Optional[str] = None,
    mosaic: bool = False,
    mid_frame_names: Optional[list[str]] = None,
) -> str:
    """V3 user prompt for Agent-1 (gate). Adds LOCAL_CONTEXT and posture question."""
    context_lines = []
    local_notes = ""
    if camera_context:
        for key, value in camera_context.items():
            if not value:
                continue
            if key == "gemini_context_notes":
                local_notes = str(value).strip()
                continue
            context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    local_block = ""
    if local_notes:
        local_block = f"\nLOCAL_CONTEXT (this specific camera's known patterns):\n{local_notes}\n"

    mid_block = ""
    if mid_frame_names:
        labels = ", ".join(mid_frame_names)
        mid_block = f"Mid-window frames (25%/50%/75%): {labels}\n"

    json_fields = (
        "Return JSON with: scene_type, person_position_signature, vehicle_stopped, "
        "person_handling_material, new_ground_material, material_flow_direction, "
        "pile_volume_change, municipal_equipment_present, new_litter_detected, "
        "confidence_0_100, evidence_summary, first_frame_has_litter, "
        "last_frame_has_litter, waste_type, raw_reason_codes, scene_delta_analysis.\n"
    )

    explicit_questions = (
        "Answer these 4 questions explicitly:\n"
        "1. POSTURE — pick ONE for the most relevant person:\n"
        "   depositing_at_pile / leaving_pile_area / approaching_pile / "
        "standing_near_pile / collecting_from_pile / passing_by / absent.\n"
        "2. PILE — comparing first to last frame, did the visible waste pile on "
        "the ground INCREASE, DECREASE, or stay roughly the same? Default to "
        "'unchanged' when uncertain. DO NOT invent growth.\n"
        "3. FLOW — is dominant material movement going TO the ground (dumping), "
        "FROM the ground (collection), none, or ambiguous?\n"
        "4. EQUIPMENT — is a caminhão compactador EMLURB clearly visible?\n"
    )

    if mosaic:
        frame_desc = (
            f"The image provided is a side-by-side composite: "
            f"LEFT = initial frame ({first_frame_name}), RIGHT = final frame ({last_frame_name}). "
            "Compare the left half vs the right half."
        )
        return (
            f"{frame_desc}\n"
            f"{mid_block}"
            f"{explicit_questions}"
            f"{json_fields}"
            f"{prior_block}"
            f"{local_block}"
            "Camera context:\n"
            f"{context_block}"
        )

    frame_lines = (
        f"Initial frame: {first_frame_name}\n"
        f"Final frame: {last_frame_name}\n"
        f"{mid_block}"
    )
    return (
        f"{frame_lines}"
        f"{explicit_questions}"
        "If a mid-window frame is provided, also check for Pattern C (ghost events).\n"
        f"{json_fields}"
        f"{prior_block}"
        f"{local_block}"
        "Camera context:\n"
        f"{context_block}"
    )


def build_v3_user_prompt_detail(
    camera_context: Optional[dict[str, str]] = None,
    frame_names: Optional[list[str]] = None,
    mosaic_mode: str = "off",
    prior_window_context: Optional[str] = None,
) -> str:
    """V3 user prompt for Agent-2 (detail). Adds LOCAL_CONTEXT block + posture emphasis."""
    context_lines = []
    local_notes = ""
    if camera_context:
        for key, value in camera_context.items():
            if not value:
                continue
            if key == "gemini_context_notes":
                local_notes = str(value).strip()
                continue
            context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    local_block = ""
    if local_notes:
        local_block = f"\nLOCAL_CONTEXT (this specific camera's known patterns):\n{local_notes}\n"

    if mosaic_mode != "off":
        if mosaic_mode == "4x3":
            frame_desc = (
                "The image(s) provided are a 4-row x 3-column mosaic grid of frames "
                "numbered 1-12 (left-to-right, top-to-bottom, chronological order). "
                "Frame 1 is earliest, frame 12 is latest. "
                "Use 'frame_N' (e.g. 'frame_7') as event_frame_name and offender_frame_name."
            )
        else:  # 3x2split
            frame_desc = (
                "Two mosaic images are provided: the first contains frames 1-6 "
                "(3 columns x 2 rows, chronological), the second contains frames 7-12. "
                "Frame 1 is earliest, frame 12 is latest. "
                "Use 'frame_N' (e.g. 'frame_7') as event_frame_name and offender_frame_name."
            )
        return (
            "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
            "1) confirmacao de infracao (infraction_confirmed)\n"
            "2) confianca 0..100\n"
            "3) resumo factual curto da evidencia, mencionando POSTURA da pessoa\n"
            "4) classificacao de residuo/material e volume aproximado\n"
            "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
            "6) event_frame_name e offender_frame_name usando o formato 'frame_N'\n"
            "Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com offender_detected=false.\n"
            "Discriminador PRIMARIO: postura da pessoa (inclinada/agachada na pilha = descarte;\n"
            "atravessando = transeunte; pegando da pilha = coleta).\n"
            "Discriminador SECUNDARIO: direcao do material (PARA o chao = descarte).\n"
            "IMPORTANTE: descarte pedestre de 0.01-0.15 m³ e INVISIVEL na resolucao —\n"
            "first frame parece igual a last frame mesmo com descarte real. Confie na postura.\n"
            f"Formato das imagens: {frame_desc}\n"
            f"{prior_block}"
            f"{local_block}"
            "Contexto da camera:\n"
            f"{context_block}"
        )

    frame_block = ", ".join(frame_names) if frame_names else "desconhecido"
    return (
        "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
        "1) confirmacao de infracao (infraction_confirmed)\n"
        "2) confianca 0..100\n"
        "3) resumo factual curto da evidencia, mencionando POSTURA da pessoa\n"
        "4) classificacao de residuo/material e volume aproximado\n"
        "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
        "6) event_frame_name e offender_frame_name escolhidos somente dentre os nomes permitidos\n"
        "Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com offender_detected=false.\n"
        "Discriminador PRIMARIO: postura da pessoa (inclinada/agachada na pilha = descarte;\n"
        "atravessando = transeunte; pegando da pilha = coleta).\n"
        "Discriminador SECUNDARIO: direcao do material (PARA o chao = descarte).\n"
        "IMPORTANTE: descarte pedestre de 0.01-0.15 m³ e INVISIVEL na resolucao —\n"
        "first frame parece igual a last frame mesmo com descarte real. Confie na postura.\n"
        f"Nomes de frame permitidos: {frame_block}\n"
        f"{prior_block}"
        f"{local_block}"
        "Contexto da camera:\n"
        f"{context_block}"
    )


# =============================================================================
# Deterministic gate V3 — posture-first overrides
# =============================================================================
def apply_v3_gates(report: GeminiNewLitterReportV3, request_id: Optional[str] = None) -> tuple[GeminiNewLitterReportV3, bool]:
    """Apply the V3 deterministic gate to a fresh Agent-1 report.

    Returns (report, is_maintenance) where:
    - report has been mutated to enforce the gate decisions
    - is_maintenance=True signals the caller should activate the cooldown

    Order of operations:
    1. POSTURE positive override (NEW V3): if posture in {depositing_at_pile,
       leaving_pile_area} AND person_handling_material=True → force DUMPING.
       This handles pedestrian dumping where pile growth is invisible.
    2. PASSING-BY suppression (NEW V3): if posture=passing_by AND scene is
       not already DUMPING → force new_litter_detected=false.
    3. COLLECTION suppression (V2 logic + posture=collecting_from_pile as 4th signal):
       if scene=COLLECTION_OR_MAINTENANCE AND >=2 corroborating signals → suppress + cooldown.
    4. Pile-decreased veto (V2): if pile=decreased AND new_litter_detected=True → force false.
    5. Flow=to_pile + pile=increased positive override (V2 legacy): kept as backup.
    6. Scene-not-DUMPING hard gate (V2): if final scene_type != DUMPING AND
       new_litter_detected=True → force false (consistency check).
    """
    logger = logging.getLogger(__name__)

    scene = (report.scene_type or "").upper().strip()
    flow = report.material_flow_direction
    pile = report.pile_volume_change
    has_munic_equip = bool(report.municipal_equipment_present)
    posture = report.person_position_signature
    handling = bool(report.person_handling_material)

    is_maintenance = False

    # -------------------------------------------------------------------------
    # 1. V3.2 POSTURE OVERRIDE (with negative overrides for collection scenes):
    # Returns to 2-signal gate (posture + handling) — V3.1's 3-signal requirement
    # killed recall (camp 13: 20% recall, V3 baseline 40%). The FPs that V3
    # original generated were mostly "Estavam realizando a poda" / "limpando
    # restos" / coleta — modelo viu bending em cenas de limpeza municipal.
    # V3.2 fix: posture override is SKIPPED if any collection-context signal
    # is present (scene=COLLECTION_OR_MAINTENANCE, municipal_equipment, flow=from_pile,
    # or pile_volume_change=decreased).
    # -------------------------------------------------------------------------
    posture_dumping = posture in ("depositing_at_pile", "leaving_pile_area")
    # Count collection signals — require >=2 to suppress posture override.
    # Suppressing on any 1 signal (V3.2 first draft) was too aggressive and
    # would kill the d00a79bd uniform case where the model often misclassifies
    # scene as COLLECTION but posture is correctly depositing_at_pile.
    collection_signals = sum([
        scene == "COLLECTION_OR_MAINTENANCE",
        bool(has_munic_equip),
        flow == "from_pile",
        pile == "decreased",
    ])
    strong_collection_context = collection_signals >= 2
    if posture_dumping and handling and not strong_collection_context and not report.new_litter_detected:
        logger.info(
            "v3_posture_override: posture=%s + handling + collection_signals=%d (<2) "
            "-> forcing new_litter_detected=true request_id=%s",
            posture, collection_signals, request_id,
        )
        report.new_litter_detected = True
        report.confidence_0_100 = max(report.confidence_0_100, 85)
        report.scene_type = "DUMPING"
        scene = "DUMPING"
        return report, False
    elif posture_dumping and strong_collection_context and report.new_litter_detected:
        # Model said posture=depositing but emitted >=2 collection signals —
        # strong contradiction. Defer to collection (suppresses municipal poda/limpeza FPs).
        logger.info(
            "v3_posture_collection_conflict: posture=%s but collection_signals=%d "
            "(scene=%s, equip=%s, flow=%s, pile=%s) -> suppressing request_id=%s",
            posture, collection_signals, scene, has_munic_equip, flow, pile, request_id,
        )
        report.new_litter_detected = False
        report.confidence_0_100 = 0

    # -------------------------------------------------------------------------
    # 2. V3 PASSING-BY suppression — clear transit, not dumping.
    # -------------------------------------------------------------------------
    if posture == "passing_by" and scene != "DUMPING" and report.new_litter_detected:
        logger.info(
            "v3_passing_by_suppress: posture=passing_by + scene=%s -> forcing false request_id=%s",
            scene, request_id,
        )
        report.new_litter_detected = False
        report.confidence_0_100 = 0

    # -------------------------------------------------------------------------
    # 3. Collection suppression — posture=collecting counts as 4th signal.
    # -------------------------------------------------------------------------
    maintenance_signals = 0
    if flow == "from_pile":
        maintenance_signals += 1
    if has_munic_equip:
        maintenance_signals += 1
    if pile == "decreased":
        maintenance_signals += 1
    if posture == "collecting_from_pile":
        maintenance_signals += 1

    if scene == "COLLECTION_OR_MAINTENANCE":
        if maintenance_signals >= 2:
            report.new_litter_detected = False
            report.confidence_0_100 = 0
            is_maintenance = True
            logger.info(
                "v3_gate_maintenance_confirmed: signals=%d (flow=%s, equip=%s, pile=%s, posture=%s) request_id=%s",
                maintenance_signals, flow, has_munic_equip, pile, posture, request_id,
            )
        else:
            report.scene_type = "PARKED"
            scene = "PARKED"
            logger.info(
                "v3_gate_maintenance_downgraded: signals=%d (<2) -> PARKED, no cooldown request_id=%s",
                maintenance_signals, request_id,
            )

    # -------------------------------------------------------------------------
    # 4. Pile decreasing veto — never dumping if pile clearly shrinks.
    # -------------------------------------------------------------------------
    if pile == "decreased" and report.new_litter_detected:
        logger.info(
            "v3_gate_pile_decreasing: forcing new_litter_detected=false request_id=%s",
            request_id,
        )
        report.new_litter_detected = False
        report.confidence_0_100 = 0

    # -------------------------------------------------------------------------
    # 5. V2 legacy positive override (flow=to_pile + pile=increased) — kept as backup.
    # -------------------------------------------------------------------------
    if flow == "to_pile" and pile == "increased" and not report.new_litter_detected:
        logger.info(
            "v3_gate_flow_pile_override: flow=to_pile + pile=increased -> forcing true request_id=%s",
            request_id,
        )
        report.new_litter_detected = True
        report.confidence_0_100 = max(report.confidence_0_100, 85)
        report.scene_type = "DUMPING"
        is_maintenance = False

    # -------------------------------------------------------------------------
    # 6. Hard gate consistency — only DUMPING scene can trigger detection.
    # -------------------------------------------------------------------------
    if (report.scene_type or "").upper().strip() != "DUMPING" and report.new_litter_detected:
        logger.info(
            "v3_gate_scene_not_dumping: scene=%s -> forcing new_litter_detected=false request_id=%s",
            report.scene_type, request_id,
        )
        report.new_litter_detected = False
        report.confidence_0_100 = 0

    return report, is_maintenance
