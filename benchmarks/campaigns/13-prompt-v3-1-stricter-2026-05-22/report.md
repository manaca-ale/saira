# Campanha 13 — V3.1 stricter (3-signal gate + negative examples) — 2026-05-22

> ❌ **FAIL** — V3 não atingiu os critérios: TP recall 20.0% < 35.0%, Δ recall -20.0pp regrediu, golden cases 0/3. Não promover. Escrever follow-up doc com próximos passos.

**Hipótese:** V3.1 reduz drasticamente o FP rate de V3 (39.55% → ~20%) mantendo o
ganho de TP recall (40%) através de:
1. Prompt mais rigoroso para `depositing_at_pile` (3 sub-condições obrigatórias).
2. Exemplos negativos do dataset (poda, "pessoa estacionou com criança", etc).
3. Gate exige 3 sinais (posture + handling + flow/new_ground), não 2.

**Bench reduzido:** 50 eventos + 8 baseline/série = ~80 janelas × 2 arms (V2 + V3.1)
para iterar rápido. Se PASS, V3.2 ou V3.3 rodam full bench (174 windows).

## Resultados

<!-- metrics-start -->

### Comparação A_v2_baseline vs B_v3_1_stricter

| Métrica | A_v2_baseline | B_v3_1_stricter | Δ (B-A) | Regra | Veredito |
|---------|----------------|----------------|----------|-------|----------|
| **TP recall total (%)** | 40.00 | 20.00 | -20.0pp | B >= 35.0% | ❌ |
|   delta vs A | — | -20.0pp | — | B-A >= 0.0pp | ❌ |
|   TP só catalogados | 40.00 | 20.00 | — | (informativo) | — |
|   Missed recall | 0.00 | 0.00 | — | — | — |
| **FP rate total (%)** | 12.33 | 12.33 | +0.0pp | B <= 21.42% | ✅ |
|   FP só catalogados | 14.63 | 21.95 | — | — | — |
|   FP em baseline | 9.38 | 0.00 | — | — | — |
| Indef trigger rate | 75.00 | 75.00 | — | informativo | — |
| Gate cost total (USD) | 0.06 | 0.06 | — | — | — |
| **Blended cost (USD)** | 0.13 | 0.13 | — | (informativo) | — |
| Latency p50 (ms) | 5503 | 4758 | — | — | — |
| Latency p95 (ms) | 18009 | 22892 | — | — | — |

### Golden cases (PASS criterion)

| Golden case | Esperado | B_v3 retornou | Veredito | Posture | Razão |
|-------------|----------|----------------|----------|---------|-------|
| 48350bb4 | ✅ detected | ❌ rejected (conf=None) | ❌ | — | TP pano branco (descarte pedestre noturno) |
| 12506543 | ✅ detected | (não encontrado) | ❌ | — | TP pedestre puro (3 homens) |
| d00a79bd | ✅ detected | (não encontrado) | ❌ | — | TP uniforme laranja |

### Por câmera

| Câmera | A TP recall | B TP recall | Δ | A FP rate | B FP rate | Δ |
|--------|--------------|--------------|----|------------|------------|----|
| cam_mangabeira | 50.0% (2/4) | 25.0% (1/4) | -25.0pp | 13.3% (4/30) | 20.0% (6/30) | +6.7pp |
| cam_imbiribeira | 0.0% (0/1) | 0.0% (0/1) | +0.0pp | 18.2% (2/11) | 27.3% (3/11) | +9.1pp |

### Distribuição de posture (V3)

| Posture (V3) | N windows |
|--------------|-----------|
| passing_by | 30 |
| depositing_at_pile | 12 |
| collecting_from_pile | 11 |
| standing_near_pile | 10 |
| absent | 9 |

### Categorias do dataset

| Categoria | N |
|-----------|---|
| TP catalogados | 5 |
| Missed | 0 |
| FP catalogados | 41 |
| Baseline | 32 |
| Indefinido | 4 |

### Diffs por evento (V2 → V3)

#### 🔴 TPs/Missed que V3 perdeu (V2 pegava, V3 não) — REGRESSÃO (1 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| be6b5e67 | cam_mangabeira | tp | Um homem realizando o descarte de múltiplas coisas | standing_near_pile | A person is visible near the waste pile in the last frame, holding a white bag. A white vehicle is also visible in the background. No clear  |

#### 🟡 FPs/baseline novos do V3 (V2 rejeitava, V3 confirma) — REGRESSÃO (7 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 17ff7912 | cam_mangabeira | fp | Estavam realizando a poda | depositing_at_pile | A person is observed bending down near the pile while carrying an object (frame 2), and then standing up with empty hands (frame 3), indicat |
| 1a2c6dc6 | cam_imbiribeira | fp | Pessoas passando | depositing_at_pile | A person is observed bending down near the waste pile in multiple frames (19:23:24, 19:23:35, 19:23:50). In a later frame (19:24:05), the sa |
| 66280d13 | cam_mangabeira | fp | Estavam limpando os restos de poda | depositing_at_pile | A person is observed carrying an object (bag) towards the pile, then bending down at the pile, and subsequently moving away with empty hands |
| 767e7d17 | cam_imbiribeira | fp | Nada ocorrendo | depositing_at_pile | A person is observed near the pile, appearing to bend down and handle material. The presence of a person interacting with the pile at night, |
| a018dd4d | cam_mangabeira | fp | Estavam limpando os restos de poda | depositing_at_pile | The person in blue/brown is observed bending down at the pile (frame 3) while carrying an object (frame 2) and later seen with empty hands m |
| d588e2b2 | cam_mangabeira | fp | Estavam realizando a poda | depositing_at_pile | A person is observed bending down and interacting with the trash pile, appearing to deposit material. A small truck is parked nearby. The pi |
| e435c966 | cam_mangabeira | fp | Pessoas passando | depositing_at_pile | A person in a yellow shirt is observed bending down and handling material near the informal trash pile in frames 3 and 4. This posture, comb |

#### ✅ FPs/baseline que V3 rejeitou (V2 confirmava, V3 rejeita) — DESEJADO (7 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 07925285 | cam_imbiribeira | fp | Pessoa passando com um carrinho | — |  |
| 5e3e79cd | cam_mangabeira | fp | Estavam retirando o Lixo | collecting_from_pile | The scene shows a truck with its bed raised, and several individuals in blue uniforms are actively loading debris from a ground pile into th |
| 61c6be4e | cam_mangabeira | fp | Estavam limpando os restos de poda | — |  |
| 983dc78f | cam_mangabeira | fp | Pessoas passando | standing_near_pile | A person is present near an informal waste pile with a bicycle. No material is being deposited or collected. The pile size appears unchanged |
| baseline | cam_imbiribeira | baseline |  | absent | No significant activity observed. A person is visible in the distance on the road in early frames, and another person is seen standing near  |
| baseline | cam_mangabeira | baseline |  | passing_by | A white truck is parked on the road in the last frames. A person is seen walking along the sidewalk, passing by the informal waste pile. No  |
| baseline | cam_mangabeira | baseline |  | absent | A white car is parked on the side of the road near an informal trash pile. No people are visible interacting with the pile or the vehicle. T |

#### 🟡 Indef que V3 marcou (V2 não marcava) (1 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| ffdafc45 | cam_imbiribeira | indefinido | Possivel descarte sendo realizado por um homem | depositing_at_pile | A person is observed near the debris pile, appearing to bend down and handle material. While the exact transition of carrying an object to e |

#### ✅ Indef que V3 parou de marcar (V2 marcava) (1 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 570a5967 | cam_mangabeira | indefinido | Possivelmente apenas uma pessoa passando com um carrinho de mão indo para uma re | standing_near_pile | A person in a red shirt is observed standing near an informal waste pile across multiple frames. No active dumping, collection, or significa |

<!-- metrics-end -->

## Como reproduzir

```powershell
cd c:\saira
python benchmarks\campaigns\13-prompt-v3-1-stricter-2026-05-22\bench_v3_1.py `
  --limit-events 50 --baseline-per-series 8
python benchmarks\campaigns\13-prompt-v3-1-stricter-2026-05-22\compute_metrics.py
```