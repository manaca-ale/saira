# Campanha 19 — gate esp32_002 pedestre recall (2026-05-27)

> ❌ **FAIL** — nenhum braço atinge o alvo (pegar o 14:52 **e** baseline ≤5%). b4 (novo) regrediu: não pegou o 14:52 e estourou baseline (20%). b2 segue o melhor braço baseline-safe. (O "PASS" automático do compute_metrics é falso — ele não avalia baseline_trigger_rate nem must_catch_events.)

## Hipótese

Uma variante de gate mais permissiva (**b4**: descarte a pé de volumosos/entulho sem
veículo + carrinho parado na pilha) recupera os TPs que o b2/b3 perdem — incluindo o
**FN de 14:52** (dois homens descartando TV/espelho/metal a pé) e o **carrinho de mão
`d59d5309`** — mantendo escalações na **baseline ≤ 5%**.

## Configuração

| Item | Valor |
|------|-------|
| Gate | `gemini-2.5-flash-lite` (thinking 2048) |
| Detail | não executado (gate-only) |
| Dataset | `data/datasets/official`, filtro `cam_mangabeira` / `esp32_002` |
| TP set | **13** (7 originais + 5 CONFIRMADO da plataforma + 1 FN manual 14:52) |
| Negativos | FP catalogados + baseline dia/noite (30 janelas/período) |
| Projeto Gemini | teste `gen-lang-client-0841492152` (nunca produção) |

### Braços
- **A_v1** — gate V1 de produção (controle; deve falhar no 14:52).
- **C_v3_esp32_recall_b2** — addon atual no `develop`.
- **D_v3_esp32_recall_b3** — material-carrier recall.
- **F_v3_esp32_recall_b4** — NOVO: bulky/dismantling + carrinho parado, baseline-safe.

## Resultados

<!-- metrics-start -->

| Métrica | A_v1 | C_v3_esp32_recall_b2 | D_v3_esp32_recall_b3 | F_v3_esp32_recall_b4 |
|---------|---|---|---|---|
| TP recall (gate triggered) | 38.5% | 53.8% | 76.9% | 61.5% |
| TP recall (detail confirmado) | 0.0% | 0.0% | 0.0% | 0.0% |
| FP rate (gate triggered) | 72.1% | 32.6% | 39.5% | 60.5% |
| FP rate (detail confirmado) | 0.0% | 0.0% | 0.0% | 0.0% |
| Cost/event (USD) | $0.0010 | $0.0014 | $0.0014 | $0.0015 |
| Latency p50 | 9667 ms | 9569 ms | 9460 ms | 9114 ms |
| Output tokens (total) | 24,696 | 29,783 | 30,116 | 29,794 |
| Events processed | 116 | 116 | 116 | 116 |

### Por categoria

| Categoria | N | Confirmado (A_v1) | Confirmado (C_v3_esp32_recall_b2) | Confirmado (D_v3_esp32_recall_b3) | Confirmado (F_v3_esp32_recall_b4) |
|-----------|---|---|---|---|---|
| TP (Descarte) | 13 | 0 | 0 | 0 | 0 |
| FP (Falso Positivo) | 43 | 0 | 0 | 0 | 0 |

<!-- metrics-end -->

### Tabela decisiva (gate-only, conjunto novo de 13 TP)

| Braço | TP recall (gate) | FP gate | Baseline (60) | 14:52 | carrinho `d59d` |
|-------|-----------------:|--------:|--------------:|:-----:|:---------------:|
| A_v1 (prod V1) | 5/13 (38,5%) | 31/43 (72,1%) | 1/60 (1,7%) | ❌ conf 0 | ❌ conf 0 |
| C_b2 (develop) | 7/13 (53,8%) | 14/43 (32,6%) | 1/60 (1,7%) | ❌ conf 50 | ❌ conf 0 |
| D_b3 | 10/13 (76,9%) | 17/43 (39,5%) | **8/60 (13,3%)** | ✅ conf 90 | ❌ conf 30 |
| F_b4 (novo) | 8/13 (61,5%) | 26/43 (60,5%) | **12/60 (20,0%)** | ❌ conf 0 | ❌ conf 30 |

Critério: pegar o 14:52 **E** baseline ≤5%. **Nenhum braço atinge.**

### Por que o b4 falhou — o 14:52 é ambíguo pro gate

Mesmos 41 frames, o `scene_type` flipa com a redação do prompt:
- A_v1 → TRAFFIC (regra do veículo); C_b2 → PARKED/`from_pile` (coleta); D_b3 → DUMPING/`to_pile`; **b4 → COLLECTION** (`from_pile`, "removing a large appliance").

O modelo não consegue decidir de forma estável se os dois homens estão **depositando** ou **removendo** o objeto volumoso. `new_ground_material` e `material_flow_direction` são instáveis. Regra estrutural também não salva: `person_handling_material` dispara em 18-30% da baseline; `phm & new_ground` zera baseline mas não pega o 14:52 (no b2 ele é `from_pile`, sem material novo).

## Decisão

1. **NÃO adotar o b4** — regrediu em tudo (não pegou o 14:52, baseline 20%, FP 60%).
2. **Recomendar deploy do b2 (V3 + B2) em prod para esp32_002** — domina o V1 atual: recall +15pp (38,5%→53,8%), FP −39pp (72%→33%), baseline estável (~2%). Ganho real e seguro, independente do 14:52. (Deploy = follow-up: portar `use_camera_v3_gate` + addon do `develop` pra prod.)
3. **O caso 14:52 (depositar-vs-remover volumoso a pé) não é resolvível por prompt no gate** — bate com camps 11-16. Próximos levers (futuro, NÃO mais prompt): gate em `flash` (não flash-lite) só pra esp32_002, ou escalar ao detail (que confirma a 95%) quando há objeto volumoso + pessoa, aceitando o ruído de baseline como custo de detail.
4. **Carrinho `d59d5309`**: irrecuperável por qualquer braço (máx conf 30) — limite visual confirmado.

## Caveats

- Campanha gate-only: Agent-2 não executado. Recall = gate escalou (não confirmação final).
- 4 dos 5 CONFIRMADO importados eram backfill `manual-missed` com janelas pequenas (4-6 frames).
- Reprodução fiel de prod no braço A_v1 (V1, `prompt_version=current`).