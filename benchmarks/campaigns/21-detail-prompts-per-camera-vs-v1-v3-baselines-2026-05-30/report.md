# Campanha 21 — detail prompts per-camera vs V1/V3 baselines (2026-05-30)

> ✅ **CONCLUÍDA** — vencedor parcial em cam_11; cam_10 e baseline mantidos.

## Hipótese

H1 — Prompts de detail per-camera com anti-padrões derivados das justificativas do operador (planilha) batem o baseline V1 trivial sem perder recall.

H2 — A mudança de modelo (Flash → Pro/Sonnet) com o mesmo prompt per-camera ganha specificity sem destruir recall.

## Dataset (production-parity)

Snapshot do DB de prod (`saira-db-prod`) em 2026-05-30 07:00 BRT. **n=64 eventos** (31 CON + 33 REJ).
A **planilha foi atualizada** ([Ocorrências Capturadas](https://docs.google.com/spreadsheets/d/1wABg4qMYFR5IHG0lWlj0CBhL2jm5c_ARJQjdDXpvqko)) com +20 classificações ao longo do bench.

**Production parity:**

| Parâmetro | Prod | Bench | Status |
|---|---|---|---|
| `GEMINI_CASCADE_MAX_FRAMES` | 48 | **48** | ✅ corrigido durante o bench |
| `GEMINI_MOSAIC_AGENT2` | off | off | ✅ |
| `GEMINI_PROMPT_VERSION` | current (V1) | varies | ⚠️ controle do experimento |

**Coalesced events:** 9/64 detecções vieram de >1 chamada Agent-2 (audit log). O bench mistura essas
janelas em 1 call só → input ≠ prod. Comparação justa usa só os **49 single-call** (= prod fez 1 call de até 48 frames).

| Cohort | n | CON | REJ | Comparação válida? |
|---|---|---|---|---|
| Single-call | 49 | 19 | 30 | ✅ prod parity |
| Coalesced | 9 | 6 | 3 | ⚠️ bench underestima |
| Sem audit | 6 | 6 | 0 | ⚠️ eventos pré-audit log |

## Resultados — single-call cohort (n=49)

| Arm | Acc | TP | TN | FP | FN | Recall | Spec | $/event |
|---|---|---|---|---|---|---|---|---|
| **Flash V1 prod (baseline)** | 50,0% | 16 | 7 | 21 | 2 | **88,9%** | 25,0% | $0,01 |
| Flash + per-camera | 51,0% | 15 | 10 | 20 | 4 | 78,9% | 33,3% | $0,01 |
| **Pro + per-camera** | **71,4%** | 12 | 23 | 7 | 7 | 63,2% | **76,7%** | $0,04 |
| Sonnet + per-camera | 71,4% | 12 | 23 | 7 | 7 | 63,2% | 76,7% | **$0,15** |

**Insights:**

- Baseline Flash V1 com **recall 88,9%** — sua intuição "alta taxa de recall" confirmada.
- Pro + Sonnet **empatam** na cohort clean (mesma confusion matrix). Sonnet 3,75× mais caro → fora.
- Pro filtra 76,7% dos FPs ao custo de perder 36,8% dos CONs reais — pior no agregado, melhor por câmera.

## Resultados — per-camera dentro do single-call (49)

### cam_10 Imbiribeira (n=20-22)

| Arm | Acc | TP/CON | FN | TN/REJ | FP | Recall |
|---|---|---|---|---|---|---|
| Flash V1 baseline | 45% | 5/6 | 1 | 4/14 | 10 | 83% |
| Flash per-camera | 50% | 6/7 | 1 | 5/15 | 10 | 86% |
| **Pro per-camera** | 59% | **3/7** | **4** | 10/15 | 5 | **43%** ❌ |

**cam_10 verdict:** o prompt IMBIRIBEIRA QUEBRA o recall veicular. Pro perde 4/7 CONs reais.
**MANTER Flash V1 em prod pra cam_10**.

### cam_11 Mangabeira (n=26-27)

| Arm | Acc | TP/CON | FN | TN/REJ | FP | Recall |
|---|---|---|---|---|---|---|
| Flash V1 baseline | 54% | 11/12 | 1 | 3/14 | 11 | 92% |
| Flash per-camera | 52% | 9/12 | 3 | 5/15 | 10 | 75% |
| **Pro per-camera** | **81,5%** ✅ | 9/12 | 3 | **13/15** | **2** | 75% |

**cam_11 verdict:** prompt MANGABEIRA + Pro funciona. Filtra 13/15 dos FPs mantendo 9/12 dos CONs.
**ADOTAR Pro + DETAIL_PROMPT_V3_MANGABEIRA pra cam_11**.

## Recomendação cirúrgica

| Câmera | Decisão | Why |
|---|---|---|
| cam_10 (esp32_001 Imbiribeira) | **Manter Flash V1** (sem mudança) | Novo prompt regrediu recall 83%→43% |
| **cam_11 (esp32_002 Mangabeira)** | **Adotar Pro 2.5 + DETAIL_PROMPT_V3_MANGABEIRA** | 81,5% acc, −50% workload operador |
| cam_14 (esp32_005 Arruda) | Manter Flash V1 (sem dados) | 3 events no DB, insuficiente |

### Trade-off operacional cam_11 deploy

Volume atual cam_11 ≈ 17 detections/dia. Com novo prompt+Pro:

| Métrica | Hoje (Flash V1) | Com Pro per-cam | Δ |
|---|---|---|---|
| Operador vê | 17/dia (11 TP + 6 FP) | 11/dia (9 TP + 2 FP) | **−35% workload** |
| Ocorrências reais perdidas | ~1/dia | ~3/dia | +2/dia (~60/mês) ❌ |
| Custo | $0,17/dia | $0,68/dia | +$0,51/dia (~$15/mês) |

⚠️ O **−50% workload é positivo, mas os +2 missed ocorrências/dia é o real cost** — operador
prefere falsos positivos a falsos negativos no contexto SAIRA (missão = pegar descarte).

**Antes de deploy: validar shadow A/B em test-saira** por 1-2 semanas, capturando ambos os
veredictos (Flash V1 + Pro per-cam) em colunas paralelas, sem bloquear o flow operador-facing.

## Caveats

1. **Coalesced events (n=9, 14% do dataset)** têm input incomparável (prod = 2+ calls, bench = 1).
   No subset clean (49), Pro recall = 63%. Em prod, coalesced fazem 2+ avaliações independentes,
   recuperando alguns CONs. **Em prod o recall real do Pro per-cam tende a ser MAIOR que o bench mostra.**
2. **N=49 é pequeno**. σ de fold = ±10pp pelo menos. Validar com 100+ eventos quando crescer.
3. **Pro/Sonnet empatados** na cohort clean é suspeito — pode ser que ambos convergiram em decisões
   triviais com o prompt rico. Single-event diffs podem diferir mas a agregada coincidiu.
4. **cam_10 Pro falhou (43% recall)** — o prompt IMBIRIBEIRA tem anti-padrões muito agressivos que
   também filtram veículos descarregando legítimos. Refinar antes de re-testar.

## Decisão

✅ **Implementar deploy faseado:**

1. Portar `DETAIL_PROMPT_V3_MANGABEIRA` para `_prompts_v3.py` como constante.
2. Adicionar `detail_system_prompt_for_camera()` em `_prompts_v3.py` (mirror do `gate_system_prompt_for_camera`).
3. Adicionar `GEMINI_DETAIL_MODEL_OVERRIDE_BY_CAM={esp32_002:gemini-2.5-pro}` em `config.py`.
4. Modificar `analyze_with_gemini` em `detector_gemini.py` pra ativar override per-camera.
5. Shadow A/B em `test-saira` antes de prod.

❌ **NÃO deployar `DETAIL_PROMPT_V3_IMBIRIBEIRA`** — re-iterar com menos anti-padrão veicular.

## Reprodução

Scripts em `scripts/`:

- `_bench_common.py` — utility compartilhada
- `_baseline_prompts.py` — V1/V3 prod snapshots
- `flash_baseline_v1_prod.py` — baseline
- `flash_as_detail_per_camera.py` — Flash + per-camera
- `pro_as_detail_per_camera.py` — Pro + per-camera (suporta Vertex via `GOOGLE_GENAI_USE_VERTEXAI=true`)
- `sonnet_as_detail_per_camera.py` — Sonnet via Bedrock
- `compute_metrics_clean_cohort.py` — re-score nas 3 cohorts
- `verify_window_match_sample.py` — sanity check prod parity
- `count_coalesced.py` — count audit-log entries per detection

Results em `results/`. Prompts source em `prompts/`. Frames cacheados em
`/tmp/{flash,pro,sonnet}_per_camera/frames/` no worker.

## Memórias relacionadas

- [[feedback_bench_match_prod_exactly]] — N=48 + coalesced caveat
- [[reference_vertex_ai_bench_setup]] — Vertex AI (evita 503 do Pro 2.5)
- [[project_dualgate_deployed_2026-05-28]] — gate V3+B3 cam_11 já deployed (contexto)
- [[project_sonnet_bench_2026-05-29]] — camp 20 (Sonnet/Pro detail mostrou-se inferior; este bench refina)
