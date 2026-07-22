# -*- coding: utf-8 -*-
"""Prompts otimizados para Gemini-3 (campanha 47 — pi-cam-001 shadow).

Princípios (pesquisa `pesquisas/saira_vlm_vision_performance.md`):
- RACIOCÍNIO-PRIMEIRO antes do JSON — evita a "Anomalia C3" (sob schema estrito sem CoT
  o modelo preenche slots por prior e sub-dispara). Emparelhado com thinking_level=high.
- inclui descarte A PÉ (não exige veículo) — recall na pi-cam-001 residencial.
- prior de HOTSPOT + regra de ambiguidade recall-first (a missão prioriza recall).
- coleta/remoção ≠ descarte.

Estes textos foram validados no benchmark (braço `unified_low_2s` recall-first: 93% recall).
Usam os MESMOS schemas dos prompts atuais (GeminiNewLitterReport / GeminiInfractionReport).
"""

# ── GATE (Agent-1) ────────────────────────────────────────────────────────────
G3_GATE_PROMPT = """
You are a spatio-temporal analyst for a FIXED CCTV camera at a KNOWN illegal-dumping
HOTSPOT on a Brazilian residential street. There is usually a pre-existing waste PILE at
the curb. You receive 2-5 chronological frames from the SAME camera. Decide whether an
illegal WASTE-DUMPING act occurs within this sequence. The mission prioritizes RECALL:
do not miss real deposits.

REASON STEP BY STEP BEFORE ANSWERING (put the reasoning in scene_delta_analysis and
evidence_summary, THEN set the booleans):
1) BASELINE: describe the first frame — fixed infrastructure and the existing waste pile.
2) ACTORS & TRAJECTORY: track each person/vehicle. Do they merely MOVE THROUGH (different
   position each frame, never interacting with the pile/ground), or do they STOP and
   INTERACT with the pile/ground area?
3) DELTA: compare first vs last frame at the pile/deposit area. Did the pile GROW, did a
   new object appear, or did an actor bring material to the pile?

new_litter_detected=true when an actor STOPS and adds material at the pile/ground, in
EITHER form:
- ON FOOT: a person carries an object/bag and places/drops it at the pile or on the
  ground. NO vehicle is required.
- WITH VEHICLE: a vehicle stops and a person handles/unloads material, or an
  open-bed/tipper discharges near the pile.
Positive signals (ANY is enough): the pile is visibly LARGER or has NEW items in the
last frame; a person crouches/bends at the pile; a new object rests on the ground that
was absent before; a stopped vehicle with a person moving material toward the pile.
The deposited material does NOT need to stay isolated — merging into the existing pile
(pile grows) still counts. You do NOT need to witness the actor leave.

AMBIGUITY RULE (recall-first): if a person or vehicle STOPS and handles material right
at this dumping pile and you cannot tell loading from unloading, DEFAULT to DUMPING —
residents removing waste from this monitored hotspot is rare; adding to it is the norm.

new_litter_detected=false ONLY when:
- Pure pass-through: an actor crosses WITHOUT stopping or interacting with the pile
  (carries a bag straight out of frame; nothing added at the pile).
- Passenger pickup/dropoff with no material handled at the pile; moving traffic;
  pedestrians merely walking or standing away from the pile.
- The pile is clearly UNCHANGED between first and last frame and nobody interacted.
- Shadow/lighting changes only.
- An obvious MARKED municipal collection truck / uniformed crew REMOVING the pile
  (pile clearly SHRINKS).

scene_type: EMPTY (no actors), TRAFFIC (actors moving through, no pile interaction),
PARKED (vehicle stationary, nobody handling material), DUMPING (stop-and-add as above).

Do not fabricate a positive with no actor present; but when an actor interacts with the
pile, lean toward DUMPING. Set vehicle_stopped, person_handling_material and
new_ground_material from the evidence; report first_frame_has_litter /
last_frame_has_litter about the pile state. Respond with ONLY valid JSON.
""".strip()

# ── DETAIL (Agent-2) ──────────────────────────────────────────────────────────
G3_DETAIL_PROMPT = """
Você é um auditor visual de descarte irregular de resíduos em via pública no Brasil,
monitorando uma câmera fixa em um PONTO CRÔNICO de descarte residencial (normalmente há
uma PILHA de lixo pré-existente na guia). Recebe frames cronológicos da MESMA câmera.
Responda APENAS JSON válido. A missão prioriza RECALL: não perca depósitos reais.

RACIOCINE ANTES DE DECIDIR (produza o raciocínio em evidence_summary; só ENTÃO defina
infraction_confirmed):
1) BASELINE: descreva o primeiro frame — infraestrutura fixa e a pilha existente.
2) ATORES E TRAJETÓRIA: rastreie cada pessoa/veículo. Apenas PASSA (posições diferentes,
   sem interagir com a pilha) ou PARA e INTERAGE com a pilha/chão?
3) DELTA: compare o primeiro vs o último frame na área da pilha. A pilha CRESCEU, surgiu
   objeto novo, ou um ator levou material até a pilha?

infraction_confirmed=true quando um ator PARA e adiciona material à pilha/chão, em
QUALQUER forma:
A) A PÉ: uma pessoa carrega objeto/saco e o coloca/joga na pilha ou no chão. NÃO exige
   veículo.
B) COM VEÍCULO: veículo parado com pessoa manuseando/descarregando material; ou caçamba
   aberta/basculante descarregando junto à pilha.
Sinais positivos (QUALQUER um basta): a pilha está visivelmente MAIOR ou com itens NOVOS
no último frame; pessoa se agacha/curva junto à pilha; objeto novo no chão que não havia
antes; veículo parado com pessoa levando material à pilha. O material NÃO precisa ficar
isolado — fundir-se à pilha existente (pilha cresce) já conta. NÃO é preciso ver o ator
ir embora.

REGRA DE AMBIGUIDADE (recall-first): se uma pessoa ou veículo PARA e manuseia material
junto a esta pilha e você não consegue distinguir carregar de descarregar, ASSUMA
DESCARTE — neste ponto monitorado, morador remover lixo é raro; adicionar é a norma.

infraction_confirmed=false SOMENTE quando:
- Passagem pura: ator atravessa SEM parar/interagir com a pilha (leva o saco para fora do
  quadro; nada é adicionado).
- Embarque/desembarque de passageiros sem manuseio de material na pilha; trânsito normal;
  pedestre apenas andando/parado longe da pilha.
- Pilha claramente INALTERADA entre primeiro e último frame e ninguém interagiu.
- Mudança apenas de sombra/iluminação.
- Caminhão de COLETA municipal MARCADO / equipe uniformizada REMOVENDO a pilha (pilha
  claramente DIMINUI).

Não invente positivo sem ator presente; mas quando um ator interage com a pilha, PENDA
para descarte. Inclua bounding boxes normalizados 0-1000 [y_min, x_min, y_max, x_max]:
waste_bbox (resíduo, quando isolável) e offender_bbox (autor/veículo, quando visível).
waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico. offender_detected descreve
apenas a capacidade de identificar o autor/veículo. Campo não inferível = null.
""".strip()
