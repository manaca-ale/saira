# Campanha 20 — detail+verifier model comparison (2026-05-30)

> ✅ **CONCLUÍDA** — 10 braços executados em dataset operacional (n=52).

## Hipótese

Quatro hipóteses testadas no mesmo dataset operacional:

- **H1** — Trocar Gemini Flash por Sonnet 4.6 ou Pro 2.5 no Agent-2 (detail) reduz false positives sem perder recall.
- **H2** — Adicionar uma 3ª etapa "Agent-3 verifier" com few-shot REJ examples filtra confabulações do detail.
- **H3** — Filtros locais zero-cost (DINOv2 embeddings, pile-zone delta OpenCV, ByteTrack+YOLO) podem substituir ou complementar o Agent-3 pago em câmeras com sinal visual estável.
- **H4** — Per-camera prompt match (V1 cam_10 vehicle-centric, V3 cam_11 postura-based) muda significativamente o resultado de cada modelo.

## Dataset

- **Fonte**: snapshot do DB de produção `saira-db-prod` em 2026-05-29 23h59 BRT
- **NÃO usa** o `data/datasets/official/manifest.csv` canônico — usa labels do operador humano
- **n=52** (22 REJEITADO + 30 CONFIRMADO)
- Per câmera:

| Câmera | n | CON | REJ | Gate prompt prod |
|---|---|---|---|---|
| cam_10 (Imbiribeira, esp32_001) | 23 | 10 | 13 | V1 (vehicle-centric) |
| cam_11 (Mangabeira, esp32_002) | 29 | 20 | 9 | V3+B3 (postura, deployed 2026-05-28) |

## Resultados — Detail (Agent-2) sobre 52 events

Per-camera prompt match (V1 cam_10, V3 cam_11) para fairness com gate config de prod. 12 keyframes/event amostrados evenly.

| Arm | Modelo | Prompt | Acc | TP | TN | FP | FN | $/event | Latência |
|---|---|---|---|---|---|---|---|---|---|
| `detail_flash_v1` | Gemini Flash | V1 (prod baseline) | **57,7%** | 30 | 0 | 22 | 0 | $0,005 | ~3s |
| `detail_sonnet_V1_V3` | Sonnet 4.6 | V1+V3 | 55,77% | 22 | 7 | 15 | 8 | $0,0515 | ~15s |
| `detail_pro_V1_V3` | Gemini Pro 2.5 | V1+V3 | **51,92%** | 19 | 8 | 14 | **11** | $0,0217 | ~14s |

**Per-camera detail (Pro vs Sonnet):**

| Câmera | Prompt | Pro acc | Pro TN/REJ | Pro FN/CON | Sonnet acc | Sonnet TN/REJ | Sonnet FN/CON |
|---|---|---|---|---|---|---|---|
| cam_10 | V1 | **34,78%** | 1/13 (7,7%) | 3/10 | 47,8% | 4/13 (30,8%) | 3/10 |
| cam_11 | V3 | 65,52% | **7/9 (78%)** | 8/20 | 62,1% | 3/9 (33%) | 5/20 |

**Achados detail:**

1. **Trocar Flash por Sonnet ou Pro PIORA o detail.** Os dois modelos mais caros adicionam false-rejects (matam ocorrências reais) sem ganhar specificity suficiente.
2. **Pro com V1 em cam_10 é catastrófico** — confabula 12 FPs em 13 REJ. Pior que sortear cara/coroa.
3. **Pro com V3 em cam_11** tem a melhor specificity testada (78%) mas perde 8/20 ocorrências reais — trade-off inaceitável.
4. **A confabulação não vem do modelo, vem do role + prompt.** Detail prompts pedem "encontre infração" → modelos maiores encontram com mais confiança.

## Resultados — Verifier (Agent-3) sobre 8 events

Sub-amostra: 4 REJ + 4 CON (mix cam_10/cam_11). 3 few-shot REJ disjoint (do dia 29/05, fora do test set). 3 keyframes/event (first / `selected_frame` do detail / last).

| Arm | Modelo | Acc | False-confirm | False-reject | $/event | Latência |
|---|---|---|---|---|---|---|
| `agent3_pro` | Gemini Pro 2.5 | **87,5% (7/8)** | **0** | 1 (E5) | $0,015 | ~10s |
| `agent3_sonnet` | Sonnet 4.6 | 75% (6/8) | 0 | 2 (E5, E8) | $0,050 | ~14s |
| `agent3_flashlite` | Gemini Flash Lite | 50% (4/8) | **4** | 0 | $0,0004 | ~1,4s |

**Achados verifier:**

1. **Pro 2.5 com few-shot REJ é o vencedor claro.** 87,5%, mais barato que Sonnet, único com false-confirm zero E low false-reject.
2. **O mesmo Pro 2.5 entrega 51,92% como detail e 87,5% como verifier.** Conclusão: **arquitetura/prompt importa muito mais que modelo.**
3. **Flash Lite confabula tudo** (4 false-confirms). Modelo de gate não serve como verifier.
4. **E5 (18:45 cam_10)** é o caso genuinamente ambíguo: Pro, Sonnet e DINOv2 erram juntos. Sacola pequena depositada em pilha grande no entardecer.

## Resultados — Filtros locais (free, sem API call)

| Arm | Acc geral | Acc cam_10 | Acc cam_11 | AUC | Latência/event | Custo |
|---|---|---|---|---|---|---|
| `filter_dinov2_global` | 69,27% | 91,3%* | 51,72%* | 0,822 | 1,11s CPU | $0 |
| `filter_dinov2_per_cam` | — | **96,00%** | 47,33% | cam_10 0,933 / cam_11 0,525 | 1,11s | $0 |
| `filter_dinov2_handcrafted` | 71,09% | — | — | 0,822 | 1,2s | $0 |
| `filter_pile_delta_logreg` | 67,5% (cap) | — | — | 0,708 | <50ms | $0 |
| `filter_bytetrack_yolov8s_11` | — | — | 60% (=baseline) | 0,550 | 25,3s | $0 |

\* Per-camera measured global model on per-camera subsets.

**Achados free filters:**

1. **DINOv2 per-camera é o vencedor pra cam_10.** 96% acc / AUC 0,933 — iguala Agent-3 Pro a custo zero. O único miss (E5 18:45) é o mesmo do Pro.
2. **cam_11 é não-separável por imagem estática** com DINOv2 (47%, AUC 0,52 = chute). O dual-gate V3+B3 deixa passar casos visualmente idênticos a REJ — precisa de sinal temporal ou semântico que o frame estático não tem.
3. **Pile-zone edge delta cap em 67,5%** com LogReg sobre 14 features. Anti-correlação inesperada: alta atividade na pilha = REJ frequente (passantes), CON tem menos motion.
4. **ByteTrack + YOLOv8s em cam_11 = 60%** (abaixo do baseline trivial "sempre CON" 69%). YOLO COCO não detecta os depositadores reais (pequenos, ângulo alto). Precisaria de YOLO custom treinado em "pessoa no ponto de descarte".

## Decisão de roadmap

| Posição | Modelo escolhido | Por quê |
|---|---|---|
| Agent-1 (gate) cam_10 | Manter Flash Lite V1 | Sem mudança |
| Agent-1 (gate) cam_11 | Manter Flash Lite V3+B3 | Deploy 2026-05-28 funcionando |
| **Agent-2 (detail) ambos** | **Manter Gemini Flash V1/V3** | Sonnet e Pro PIORAM detail |
| **Filter pós-detail cam_10** | **DINOv2 + LogReg** (shadow A/B) | 96% acc, $0, 1,1s CPU |
| **Agent-3 verifier cam_11** | **Pro 2.5 + few-shot REJ** | 87,5%, $0,015/event |
| ❌ Sonnet 4.6 (qualquer papel) | Descartado | Pior+caro que Pro em ambos |
| ❌ Pro como detail | Descartado | 51,92%, perde 11 ocorrências reais |
| ❌ Flash Lite como verifier | Descartado | Confabula igual ao Flash |
| ❌ Pile-zone delta hard filter | Descartado | Cap em 67,5% |
| ❌ ByteTrack COCO pra cam_11 | Descartado | Não detecta depositadores reais |

## Custos extrapolados (3 cams, ~28 detections/dia atual)

| Configuração | Custo/dia | Custo/mês |
|---|---|---|
| Atual (Flash apenas) | $0,14 | $4,20 |
| Atual + DINOv2 cam_10 | $0,14 | $4,20 (DINOv2 free) |
| Atual + Pro Agent-3 cam_11 | $0,44 | $13,20 |
| **Atual + DINOv2 cam_10 + Pro Agent-3 cam_11** | **$0,44** | **$13,20** |
| Substituir Flash por Sonnet detail | $2,74 | $82,30 (descartado) |
| Substituir Flash por Pro detail | $1,28 | $38,40 (descartado) |

## Caveats

1. **n=52 é pequeno.** Significância estatística limitada — folds de 5-fold CV têm σ alto.
2. **Não-reproduzível sem snapshot do DB.** Dataset depende do estado atual de operator labels.
3. **Sample 8-event do Agent-3** é minúsculo — resultado de Pro 87,5% pode ser ruído.
4. **Per-camera DINOv2 cam_11 47%** poderia melhorar com mais dados. Hoje 29 events cam_11; com 100+, vale re-testar.
5. **Pro 2.5 detail com V1 cam_10 = 34,78%** pode parcialmente ser efeito de V1 ser explicitamente vehicle-centric (cam_10 V1 era ajustado pra cenário onde Pro 2.5 não foi tunado). Não testamos V3 em cam_10.
6. **E5 18:45 é miss compartilhado** de Pro Agent-3, Sonnet Agent-3 e DINOv2 cam_10 — provavelmente um caso ambíguo de operator label, não falha do método.

## Reprodução

Scripts em `scripts/`, resultados em `results/`. Para re-executar sem snapshot do DB, ver `scripts/dinov2_eval.py` (DINOv2 embeddings podem ser regenerados em ~1 min se houver acesso ao DB + S3) ou pular pra fase de classificação consumindo `results/dinov2_results.json`.

Para os bench de modelos pagos, é necessário:
- `GEMINI_TEST_API_KEY` em `services/.env.benchmark` (Gemini Pro / Flash Lite)
- AWS SSO `codex-ops` profile, region `us-east-1`, com acesso ao Bedrock inference profile `us.anthropic.claude-sonnet-4-6` (Sonnet)

## Memórias relacionadas

- `project_dinov2_filter_2026-05-29.md` — detalhes DINOv2
- `project_sonnet_bench_2026-05-29.md` — Sonnet + Pro + Flash Lite
- `project_pilezone_delta_proto_2026-05-29.md` — pile-delta
- `project_agent3_prototype_2026-05-29.md` — Pro Agent-3 original
- `reference_deep_research_fp_filter_2026-05-29.md` — relatório Deep Research que inspirou DINOv2/ByteTrack
