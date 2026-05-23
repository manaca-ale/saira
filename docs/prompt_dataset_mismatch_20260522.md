# Mismatch entre prompt Gemini (V1 em produção) e o dataset oficial v1

**Data:** 2026-05-22
**Autor:** Alexandre Manaca (com auditoria assistida)
**Prompt analisado:** V1 atual em produção — `SYSTEM_PROMPT` e `NEW_LITTER_SYSTEM_PROMPT` em [services/yolo-worker-vm/src/worker/detector_gemini.py:84-149](../services/yolo-worker-vm/src/worker/detector_gemini.py#L84-L149)
**Dataset analisado:** [data/datasets/official/](../data/datasets/official/) (119 eventos catalogados + 2.875 frames de baseline, ver [README do dataset](../data/datasets/official/README.md))

---

## TL;DR

- O prompt V1 em produção foi desenhado em torno do padrão "veículo parado + pessoa estacionária descarregando", mas **12 dos 14 TPs (86 %) do dataset oficial são descartes pedestres puros, sem veículo nenhum**.
- O gate V1 ([detector_gemini.py:128](../services/yolo-worker-vm/src/worker/detector_gemini.py#L128)) define literalmente: *"DUMPING: A vehicle is STOPPED and a person is ACTIVELY depositing material on the ground"* — esta cláusula exclui por construção quase todos os TPs reais.
- **Carroceiros são a maior fonte de incerteza no dataset**: 11 eventos com carroça, 9 classificados como "Indefinido" pela equipe humana — V1 não menciona carroça; V2 (não promovido) trataria carroça como `municipal_equipment_present=true`, o que viraria FN se o carroceiro estiver descartando.
- O caso CRÍTICO de uniforme (TP [d00a79bd-4052-4406-986f-01707b7fc713](../data/datasets/official/cam_mangabeira/tp/d00a79bd-4052-4406-986f-01707b7fc713/label.json), *"Grande quantidade de lixo descartada por um homem utilizando uniforme laranja"*) só foi acertado pelo Gemini 2.5 Flash porque V1 não tem cláusula explícita — em modelos mais "pensadores" o uniforme bloqueia a detecção. V2 já trata isso, V1 não.
- Métrica de produção: na campanha 08 ([benchmarks/campaigns/08-cascade-two-pass-2026-05-22/report.md](../benchmarks/campaigns/08-cascade-two-pass-2026-05-22/report.md)) o arm A (budget=2048, prod) tem **TP recall de 15 % (3/20)** contra os positivos do dataset oficial.

---

## Metodologia

1. Leitura literal do prompt V1 em [detector_gemini.py:84-149](../services/yolo-worker-vm/src/worker/detector_gemini.py#L84-L149).
2. Enumeração de todos os 14 TPs em [events.json](../data/datasets/official/events.json) e leitura da `justificativa` de cada um.
3. Cruzamento de cada cláusula do prompt com os padrões encontrados nos TPs.
4. Para carroças e uniforme, busca textual em `justificativa` por "carroç" e cruzamento com a categoria de classificação humana.
5. Evidências quantitativas da campanha 08 (mesmo dataset, prompt V1).

---

## Mismatch 1 — Gate exige veículo, mas 86 % dos TPs reais são pedestres

### Trecho literal do prompt V1 que causa o problema

[detector_gemini.py:121-149](../services/yolo-worker-vm/src/worker/detector_gemini.py#L121-L149) — `NEW_LITTER_SYSTEM_PROMPT` define os 4 valores de `scene_type`:

```text
- EMPTY: No vehicles or people visible in any frame.
- TRAFFIC: Vehicles and/or people moving through the scene (different positions across frames).
- PARKED: Vehicles stationary but NO person handling material nearby.
- DUMPING: A vehicle is STOPPED and a person is ACTIVELY depositing material on the ground.
```

E [detector_gemini.py:98-103](../services/yolo-worker-vm/src/worker/detector_gemini.py#L98-L103) — `SYSTEM_PROMPT` lista 3 evidências:

```text
A) Material novo claramente visivel no chao que surgiu durante a sequencia.
B) Veiculo PARADO (mesma posicao em 2+ frames) proximo a area de residuos com pessoa
   ESTACIONARIA entre o veiculo e o chao, carregando ou manuseando material.
C) Veiculo com cacamba aberta/levantada proximo a pilha de residuos, descarregando.
```

Das 3 evidências, **B e C exigem veículo**. Só (A) cobre descarte pedestre — e é frágil porque exige material "claramente visível", o que entra em conflito com a volumetria baixa típica destes TPs (0,01 a 0,15 m³).

### Casos do dataset que contradizem

Os 14 TPs do dataset oficial, com a justificativa humana literal:

| event_id (8 dígitos) | Câmera | Volumetria | Tem veículo? | Justificativa |
|---|---|---|---|---|
| `48350bb4` | Imbiribeira | 0.15 m³ | ❌ | Dois homens descartando o conteúdo dentro de um grande saco/pano branco |
| `57f7f1ed` | Mangabeira | 0.05 m³ | ❌ | Uma pessoa realizando descarte de múltiplas coisas |
| `be6b5e67` | Mangabeira | 0.01 m³ | ❌ | Um homem realizando o descarte de múltiplas coisas |
| `ad65ae06` | Mangabeira | 0.05 m³ | ❌ | Um homem realizando o descarte de um saco de lixo |
| `bc0528c2` | Mangabeira | 0.05 m³ | ❌ | Um homem realizando o descarte do conteúdo de uma sacola branca |
| `454c8308` | Imbiribeira | 0.05 m³ | ❌ (carrinho de mão) | Um homem realizando o descarte de lixo com um carrinho de mão |
| `a73a3f44` | Imbiribeira | 0.5 m³ | ✅ caminhonete | Caminhonete azul escura realiza o descarte de um grande volume de lixo |
| `06414b5a` | Imbiribeira | 0 m³ | ✅ carro | Carro escuro (preto) realizando descarte de lixo |
| `cb49921a` | Imbiribeira | 1.5 m³ | ❌ | Pessoas realizando o descarte do conteúdo de um saco marom aparentemente |
| `218673e1` | Imbiribeira | 0.1 m³ | ❌ | Dois homens realizando o descarte de objetos grandes |
| `d00a79bd` | Mangabeira | 0.1 m³ | ❌ | Grande quantidade de lixo descartada por um homem utilizando uniforme laranja |
| `d59d5309` | Mangabeira | 0.01 m³ | ❌ (carrinho) | Um homem realizando o descarte utilizando um carrinho de mão |
| `2bb892bc` | Mangabeira | 0.4 m³ | ❌ | Pessoas descartando restos de poda |
| `12506543` | Imbiribeira | 0.1 m³ | ❌ | Os dois homens ainda estavam mexendo no lixo, mas no final aparece um outro homem que realiza um descarte |

**Distribuição:** apenas **2 dos 14 TPs (14 %)** têm um veículo motorizado envolvido (`a73a3f44` caminhonete, `06414b5a` carro). Os outros **12 (86 %)** são descartes pedestres — homem com saco, homem com carrinho de mão, pessoa com sacola, restos de poda largados.

### Impacto observado

[benchmarks/campaigns/08-cascade-two-pass-2026-05-22/report.md](../benchmarks/campaigns/08-cascade-two-pass-2026-05-22/report.md), tabela "Por categoria":

```text
| TP (Descarte) + Missed | 20 | 3 (15.0%) | 5 (25.0%) | 8 (40.0%) |
```

O arm A (`budget=2048`, equivalente a produção) detecta apenas **3 de 20 positivos**. O report explicita no caveat: *"Bench usou só first+last frame — produção real usa 3-5 frames por janela. Recall absoluto em produção provavelmente é maior."* Mesmo assim, o ranking relativo A < B < C com 15 % vs 40 % é robusto e aponta para o mesmo viés veicular.

---

## Mismatch 2 — Carroceiros: 9 dos 11 eventos são "Indefinido"

### Trecho literal do prompt V1

V1 **não menciona carroça** em nenhum lugar do `SYSTEM_PROMPT` ou `NEW_LITTER_SYSTEM_PROMPT` ([detector_gemini.py:84-149](../services/yolo-worker-vm/src/worker/detector_gemini.py#L84-L149)). A palavra simplesmente não aparece. O modelo precisa decidir caso a caso usando o framework genérico "veículo parado + pessoa descarregando", que não foi feito para tração animal/humana.

### Casos no dataset (11 eventos, todos em Imbiribeira)

| event_id (8 dígitos) | Categoria | Volumetria | Justificativa |
|---|---|---|---|
| `85a764a7` | indefinido | 0.15 m³ | Possível descarte ou coleta sendo realizada com uma carroça |
| `92968ee2` | indefinido | 0.8 m³ | Possível descarte ou coleta sendo realizada com uma carroça |
| `e2d7dc4b` | indefinido | 0.05 m³ | Possível descarte ou coleta sendo realizada com uma carroça |
| `8c092e51` | fp | 0.15 m³ | Apenas pessoas passando e mexendo em uma carroça |
| `731a6a77` | indefinido | 0.1 m³ | Dois homens deixando uma televisão perto da carroça |
| `3f115960` | indefinido | 0.1 m³ | Pessoas perto da carroça |
| `62894ccc` | indefinido | 0.15 m³ | Pessoas mexendo, tirando e colocando objetos na carroça |
| `dc64aac1` | indefinido | 0.8 m³ | Pessoas mexendo, tirando e colocando objetos na carroça. Mas deixaram o que aparentam ser sacos de lixo na carroça |
| `3497125c` | indefinido | 0.1 m³ | Dois homens com uma carroça estão mexendo no lixo |
| `3c60eccd` | indefinido | 0.5 m³ | Três homens mexendo em uma carroça, no lixo e queimando com fogo um objeto |
| `d52cc8db` | fp | 0.03 m³ | Apenas uma pessoa mexendo na carroça |

**Distribuição:** 9 Indefinidos + 2 FPs + **0 TPs**. Não é que carroceiro nunca descarta — é que a equipe humana não conseguiu separar descarte de catação só pela imagem na maioria dos casos.

### Por que é difícil

Carroceiro **descarta E coleta** com o mesmo equipamento. As justificativas mais reveladoras:

- `62894ccc`: *"Pessoas mexendo, tirando E colocando objetos na carroça"* — fluxo bidirecional simultâneo.
- `dc64aac1`: *"tirando e colocando objetos na carroça. Mas deixaram o que aparentam ser sacos de lixo na carroça"* — começou parecendo descarte, terminou parecendo coleta.

A única discriminação possível é **fluxo de material** (`to_pile` vs `from_pile`) e **delta de volume da pilha** entre primeiro e último frame. V1 não tem esses campos no schema; V2 tem.

### Onde V2 ajudaria — e onde tropeçaria

V2 ([_prompts_v2.py:76-81](../services/yolo-worker-vm/src/worker/_prompts_v2.py#L76-L81)) introduz `municipal_equipment_present`, com a definição literal:

```text
True ONLY if a specific municipal collection vehicle or tool is clearly visible:
caminhão compactador (large garbage truck with rear-loading hopper, often with
EMLURB logo) OR carroça de madeira (wooden horse-drawn or hand-pulled cart used
by catadores/recyclable collectors).
```

E o gate V2 ([_prompts_v2.py:466-485](../services/yolo-worker-vm/src/worker/_prompts_v2.py#L466-L485)) usa esse campo para classificar como `COLLECTION_OR_MAINTENANCE` quando há ≥2 sinais. **Risco**: dos 9 Indefinidos com carroça, alguns são descartes reais — o V2 forçaria todos como manutenção se a carroça estiver presente, virando FN. O `apply_v2_gates` tem uma cláusula de override positivo ([_prompts_v2.py:506-516](../services/yolo-worker-vm/src/worker/_prompts_v2.py#L506-L516)) para `flow=to_pile + pile=increased`, mas ela exige que o modelo identifique corretamente o fluxo — em cenas com fluxo bidirecional simultâneo (`62894ccc`, `dc64aac1`) isso não é confiável.

---

## Mismatch 3 — Uniforme municipal usado por descartador real

### Trecho literal do prompt V1

V1 **não tem nenhuma cláusula sobre uniforme** em [detector_gemini.py:84-149](../services/yolo-worker-vm/src/worker/detector_gemini.py#L84-L149). A palavra "uniforme"/"uniform" não aparece. A regra de uso correto ([detector_gemini.py:114](../services/yolo-worker-vm/src/worker/detector_gemini.py#L114)) diz apenas: *"Uso correto de lixeira publica e comportamento cidadao correto — infraction_confirmed=false"* — não diferencia trabalhador uniformizado descartando vs cidadão usando lixeira.

### Caso no dataset

TP [d00a79bd-4052-4406-986f-01707b7fc713](../data/datasets/official/cam_mangabeira/tp/d00a79bd-4052-4406-986f-01707b7fc713/label.json) (Mangabeira, 2026-05-21T11:15:34):

```json
"tipo_residuo": "Lixo Domiciliar",
"volumetria": "0.1 m³",
"classificacao": "Descarte",
"category": "tp",
"justificativa": "Grande quantidade de lixo descartada por um homem utilizando uniforme laranja"
```

Frames: 44, intervalo das 11:11:59 às 11:15:34 (3 min 35 s).

### Por que isso é frágil

Gemini 2.5 Flash hoje em produção (V1) acerta esse caso. Mas o acerto depende do modelo **não** interpretar o uniforme laranja como sinal de "agente da EMLURB → coleta legítima". Em modelos com mais "thinking" (testes com Haiku-thinking documentados na campanha 07) o raciocínio adicional **leva a rejeitar o descarte**: o modelo lê "uniforme laranja" → "EMLURB" → "coleta" → `new_litter_detected=false`.

V2 trata isso de forma explícita ([_prompts_v2.py:51-55](../services/yolo-worker-vm/src/worker/_prompts_v2.py#L51-L55)):

```text
UNIFORM IS NOT A DISCRIMINATOR. Workers in any uniform (orange EMLURB vests,
construction-company shirts, mover jumpsuits, delivery uniforms) can be doing
EITHER legitimate collection OR illegal dumping. Decide by the BEHAVIOR (where the
material is going) and EQUIPMENT (specific municipal equipment vs generic vehicles),
NEVER by clothing alone.
```

E reforça em [_prompts_v2.py:97-100](../services/yolo-worker-vm/src/worker/_prompts_v2.py#L97-L100):

```text
- A construction/mover/cleaning worker in ANY uniform descarregando entulho de
  caminhonete para o chão (uniform does not exempt them — material direction
  determines the classification).
```

V1 não tem nada equivalente. Hoje funciona por "sorte" — qualquer alteração de modelo ou de thinking budget pode quebrar `d00a79bd` (e outros casos similares que ainda não foram catalogados).

---

## Apêndice A — Outros mismatches conhecidos (não aprofundados)

### A1. Coleta municipal vira FP em massa

Justificativa "Estavam retirando o Lixo" aparece em **22 dos 79 FPs** do dataset (caminhão compactador EMLURB) e o V1 não consegue distinguir visualmente coleta de descarte de caçamba. Solução visual pura é limitada — exige sinal extrínseco (horário/rota da EMLURB) ou os discriminadores comportamentais do V2.

Referência: [benchmarks/campaigns/01-prompt-v2-ab-2026-05-22/results-current.json](../benchmarks/campaigns/01-prompt-v2-ab-2026-05-22/results-current.json).

### A2. Baseline esperado não inclui pilhas pré-existentes

[detector_gemini.py:88-90](../services/yolo-worker-vm/src/worker/detector_gemini.py#L88-L90) lista o baseline como *"via asfaltada, calcadas, veiculos estacionados, infraestrutura municipal fixa (postes, lixeiras com tampa, bollards, marcacoes viarias)"*. Não menciona **pilhas de lixo pré-existentes**, que são comuns nas duas câmeras. Isso atrapalha o "DELTA TEMPORAL" do prompt: quando uma pilha já está lá no frame 1, o modelo tende a tratar qualquer mexida como mudança suspeita. V2 corrige em [_prompts_v2.py:91](../services/yolo-worker-vm/src/worker/_prompts_v2.py#L91) (*"Pre-existing waste piles unchanged between frames = PARKED"*) e em [_prompts_v2.py:61-62](../services/yolo-worker-vm/src/worker/_prompts_v2.py#L61-L62) (*"specifically NEW material — not pre-existing piles"*).

---

## Apêndice B — Casos críticos para revisão manual

Eventos prioritários para olhar com olho humano + log do Gemini lado a lado:

| event_id | Tipo | Câmera | Quando | Por que olhar |
|---|---|---|---|---|
| [12506543-...](../data/datasets/official/cam_imbiribeira/tp/12506543-1c64-4604-8c76-a85300a43669/label.json) | TP pedestre | Imbiribeira | 22/05 02:52 | Descarte pedestre com pessoas pré-existentes na cena (ambiguidade temporal) |
| [d00a79bd-...](../data/datasets/official/cam_mangabeira/tp/d00a79bd-4052-4406-986f-01707b7fc713/label.json) | TP uniforme | Mangabeira | 21/05 11:15 | Único TP com uniforme laranja — caso de bordo para modelo com thinking |
| [d59d5309-...](../data/datasets/official/cam_mangabeira/tp/d59d5309-60c5-4ce9-8a64-2c68342c07c5/label.json) | TP carrinho-de-mão | Mangabeira | 21/05 11:33 | Equipamento manual pequeno — categoria não coberta nem por V1 nem por V2 |
| [3497125c-...](../data/datasets/official/cam_imbiribeira/indefinido/3497125c-7695-4123-b17d-4e86ae390cb2/label.json) | Indef carroça | Imbiribeira | 22/05 00:32 | Exemplo canônico de carroceiro ambíguo |
| [dc64aac1-...](../data/datasets/official/cam_imbiribeira/indefinido/dc64aac1-d9cb-46f9-a115-5762fbf330c5/label.json) | Indef carroça | Imbiribeira | 21/05 03:38 | Carroceiro que **deixou** sacos na carroça — fluxo bidirecional |

---

## Apêndice C — Prompt V1 atual na íntegra (snapshot 2026-05-22)

### SYSTEM_PROMPT (Agent-2 / detail)

Trecho literal de [detector_gemini.py:84-119](../services/yolo-worker-vm/src/worker/detector_gemini.py#L84-L119):

```text
Voce e um auditor visual de descarte irregular de residuos em via publica no Brasil.
Responda APENAS JSON valido com os campos solicitados.

BASELINE ESPERADO: A cena padrao consiste em via asfaltada, calcadas, veiculos estacionados,
infraestrutura municipal fixa (postes, lixeiras com tampa, bollards, marcacoes viarias) e
iluminacao natural variavel. Estes elementos sao NORMAIS e ESPERADOS.

PROCESSO DE VERIFICACAO (siga na ordem):
1. INVENTARIO: Em baseline_description, liste ate 5 objetos fixos/permanentes visiveis no primeiro frame.
2. DELTA TEMPORAL: Identifique o que MUDOU entre o primeiro e o ultimo frame.
3. CLASSIFICACAO: Cada mudanca e SOMBRA_ILUMINACAO, OBJETO_EM_MOVIMENTO, ou COMPORTAMENTO_DESCARTE.
4. DECISAO: infraction_confirmed=true quando houver COMPORTAMENTO_DESCARTE confirmado.

COMPORTAMENTO_DESCARTE e confirmado quando QUALQUER das seguintes evidencias e visivel:
A) Material novo claramente visivel no chao que surgiu durante a sequencia.
B) Veiculo PARADO (mesma posicao em 2+ frames) proximo a area de residuos com pessoa
   ESTACIONARIA entre o veiculo e o chao, carregando ou manuseando material.
C) Veiculo com cacamba aberta/levantada proximo a pilha de residuos, descarregando.

SINAL-CHAVE: Veiculos e pessoas realizando descarte ficam ESTACIONARIOS entre os frames
(mesma posicao relativa). Trafego normal mostra veiculos/pessoas em POSICOES DIFERENTES
entre frames. Use esta diferenca para distinguir descarte de trafego.

Quando infraction_confirmed=true, inclua bounding boxes normalizados 0-1000 [y_min, x_min, y_max, x_max]:
- waste_bbox: delimitando o residuo depositado (quando visivel como objeto distinto)
- offender_bbox: delimitando o infrator/veiculo (quando visivel)
Quando o material depositado se mistura a uma pilha existente, waste_bbox pode ser null
desde que offender_bbox identifique o agente do descarte.

Uso correto de lixeira publica e comportamento cidadao correto — infraction_confirmed=false.
Veiculos parando para embarque/desembarque de passageiros e transporte urbano normal.
waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico.
offender_detected descreve somente a capacidade de identificar o autor/veiculo.
Se um campo nao puder ser inferido com seguranca, retorne null.
```

### NEW_LITTER_SYSTEM_PROMPT (Agent-1 / gate)

Trecho literal de [detector_gemini.py:121-149](../services/yolo-worker-vm/src/worker/detector_gemini.py#L121-L149):

```text
You analyze CCTV frames to classify urban scenes. You receive 2-5 frames from the same camera.

FIRST, classify scene_type as one of:
- EMPTY: No vehicles or people visible in any frame.
- TRAFFIC: Vehicles and/or people moving through the scene (different positions across frames).
- PARKED: Vehicles stationary but NO person handling material nearby.
- DUMPING: A vehicle is STOPPED and a person is ACTIVELY depositing material on the ground.

IMPORTANT: Over 95% of scenes are EMPTY, TRAFFIC, or PARKED. Default to these.

EVALUATE each boolean field INDEPENDENTLY based on visual evidence:
- vehicle_stopped: Is a vehicle stationary (same position in 2+ frames)?
- person_handling_material: Is a person carrying, unloading, or depositing material near a vehicle?
- new_ground_material: Is there new material on the ground in the last frame that was absent in the first?

COMMON SCENES (these are normal, not DUMPING):
- Vehicles driving through = TRAFFIC
- Vehicle stopped briefly for passenger pickup/dropoff (person enters/exits vehicle) = TRAFFIC
- Pedestrians walking or standing = TRAFFIC
- Parked cars with nobody unloading = PARKED
- Shadow or lighting changes between frames = EMPTY or TRAFFIC
- Pre-existing waste piles unchanged between frames = PARKED

Set new_litter_detected=true ONLY when scene_type=DUMPING.
For EMPTY/TRAFFIC/PARKED: new_litter_detected=false, confidence_0_100=0.

Respond with ONLY valid JSON.
```

Observe as cláusulas problemáticas grifadas pela análise acima:

- *"DUMPING: A vehicle is STOPPED…"* — exclui pedestres por construção.
- *"person_handling_material: Is a person carrying, unloading, or depositing material **near a vehicle**?"* — boolean também exige proximidade de veículo.
- *"Pedestrians walking or standing = TRAFFIC"* — classifica explicitamente "pedestre parado" como `TRAFFIC` em vez de candidato a `DUMPING`. Conflita com TPs como `48350bb4`, `218673e1`, `12506543`.

---

## Próximos passos (sem execução agora)

As opções ficaram em aberto. Em ordem do mais cirúrgico ao mais ambicioso:

1. **Patch cirúrgico em V1** — adicionar 4ª evidência (D) cobrindo descarte pedestre, reescrever `DUMPING` no gate, adicionar cláusula uniforme, mencionar pilha pré-existente. Validar via `saira-benchmark` antes de subir.
2. **Promover V2 em produção** — V2 já cobre uniforme e fluxo de material, mas precisa antes:
   - Resolver a regra "carroça = `municipal_equipment_present=true`" (talvez deixar carroça como neutra e decidir só por fluxo).
   - Adicionar flag `PROMPT_VERSION` em [config.py](../services/yolo-worker-vm/src/worker/config.py) para alternância controlada.
3. **Expandir dataset com TPs pedestres explícitos** — hoje só temos 14 TPs e 12 deles são pedestres, mas só com 2 câmeras. Ampliar para 4-5 câmeras antes de tunar prompt evita overfit ao perfil Mangabeira/Imbiribeira.
4. **Per-camera notes** — V2 já suporta `gemini_context_notes` ([_prompts_v2.py:299-302](../services/yolo-worker-vm/src/worker/_prompts_v2.py#L299-L302)) injetando bloco `LOCAL_CONTEXT`. Vale popular esse campo para cada câmera ativa (padrões locais conhecidos: carroceiros em Imbiribeira de madrugada, etc.).

Nenhum destes passos foi executado nesta análise — este documento é só o diagnóstico de base.
