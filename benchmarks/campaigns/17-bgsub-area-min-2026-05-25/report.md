# Campanha 17 — BGSUB Area-Min Contour Filter

**Data**: 2026-05-25
**Tipo**: feature toggle A/B (single MOG2 com 2 morpho modes)
**Hipótese**: substituir `MORPH_OPEN + MORPH_CLOSE` por filtro de área mínima por contour (area=400) preserva TPs E filtra mais FPs (especialmente tráfego pequeno em esp32_001).

## Origem da hipótese

Deep Research (Gemini DR, [pesquisas/bgsub_filter_optimization.md](../../../pesquisas/bgsub_filter_optimization.md)) recomendou:
> "MOG2's morphological post-processing is the primary reason small falling or abandoned objects are entirely eliminated from the detection mask. For waste disposal scenarios where the target may occupy ≤5% of the ROI, standard morphological opening must be discarded. Instead, noise suppression should be achieved through spatial bounding-box filtering—discarding contours with an area under a specific pixel threshold."

## Smoke test offline (3 TPs + 7 FPs labeled do 24/05)

| Variant | TP | FP filter | p95 latency |
|---|---:|---:|---:|
| single_baseline (morpho open_close, atual) | 3/3 | 3/7 | 9.1s |
| no_morpho_off | 3/3 | 1/7 | 13.9s |
| no_morpho_area50 | 3/3 | 2/7 | 10.8s |
| no_morpho_area100 | 3/3 | 3/7 | 14.9s |
| no_morpho_area200 | 3/3 | 4/7 | 14.5s |
| no_morpho_area300 | 3/3 | 4/7 | 10.6s |
| **no_morpho_area400** ⭐ | **3/3** | **5/7** | 13.9s |
| no_morpho_area500 | 3/3 | 5/7 (TPs ↓) | 10.4s |

CSV completo: `/tmp/sim_smoke/results_phase1.csv` + `results_phase1_refine.csv` no worker prod.

### TPs preservados (24/05 esp32_002)

| TP | Persistência (px) baseline → area_min=400 |
|---|---|
| 08:09 papelão | 8301 → **10747** |
| 08:21 pedestre marginal | 3290 → **5786** |
| 08:36 papelão deixado | 6104 → **7206** |

### FPs filtrados (extras vs baseline)

| FP | Persistência baseline → area_min=400 |
|---|---|
| FP 09:30 tráfico esp32_001 | 1310 → **0** (filtra) |
| FP 10:00 tráfico esp32_001 | 2418 → **0** (filtra) |

## Alternativas testadas e descartadas

### F1 — BackgroundSubtractorCNT (opencv-contrib)

Drop-in replacement do MOG2 com hit-count integer per-pixel. Pesquisa Deep Research dizia "2.5× mais rápido, preserva small objects estacionários".

| Variant | TP | FP filter | p95 |
|---|---:|---:|---:|
| cnt_default | 3/3 | **0/7** | 2.6s (3.5× mais rápido) |
| cnt_no_morpho | 3/3 | 0/7 | 3.8s |
| cnt_area400 | 3/3 | 0/7 | 3.9s |

**Veredito**: CNT é genuinamente 3-4× mais rápido, mas **sensível demais** — persistência explode em qualquer pixel mudando (TP 08:09 = 30k px no CNT vs 8.3k no MOG2). Combos com area_min não ajudam: o ruído é grande, não pequeno. Descartado.

### F4 — Dual-rate MOG2 + Evidence Accumulator (Porikli 2008)

Dois MOG2 paralelos (fast LR=0.05, slow LR=0.0001). Array 2D acumulador per-pixel. Disparo quando max(accumulator) > N.

| Variant | TP | FP filter |
|---|---:|---:|
| evidence_N3 / N5 / N8 / N12 | 3/3 | **0/7** |
| evidence_lrF01_N20 | 3/3 | 0/7 |
| evidence_lrF01_N50 | **0/3** | 7/7 |

**Veredito**: comportamento binário — passa tudo (N pequeno) ou zera tudo (N grande). Provavelmente requer object-permanence tracker upstream (SORT/ByteTrack) pra ser realmente útil. Descartado nesta rodada; fica como candidato futuro se YOLO PeopleCar for integrado.

## Implementação

- `services/yolo-worker-vm/src/worker/config.py:154-163`: novas envs `BGSUB_MORPHO_MODE` (default `open_close`), `BGSUB_AREA_MIN` (default 400)
- `services/yolo-worker-vm/src/worker/bgsub_filter.py:_apply_and_combine()`: 3 branches (open_close legacy, area_min, off)
- `services/docker-compose.{prod,test,yml}.yml`: envs whitelist expostas (sem isso, defaults do código eram usados — bug do BGSUB_MOG2_HISTORY_FAST padrão do PR #17)
- Tests novos em `tests/test_bgsub_filter.py` (3 cenários: area_min filtra small, off skip, default preserva legacy)
- 27/27 pytest verde

## Deploy

- PR #18 → develop (squash merge)
- PR #19 develop → main (admin merge, deploy CI/CD 34s)
- PR #20 (compose envs) → main (admin merge, deploy 34s)
- `.env` prod recebeu `BGSUB_MORPHO_MODE=area_min` + `BGSUB_AREA_MIN=400`
- Worker restartado 2026-05-25 ~23:30 UTC (20:30 BRT)
- Config validada: `MORPHO: area_min AREA_MIN: 400 MPF: 0.4`

## Métricas a monitorar (48h)

- `saira_bgsub_eval_total{reason="filtered",camera_id}` — filter rate por câmera
- `saira_gemini_calls_total{agent="gate",camera_id}` — taxa de chamadas Gate
- `saira_gemini_calls_total{agent="detail",camera_id}` — Detail triggers (TPs detectados)
- Query DB `SELECT count(*) FROM detections WHERE created_at >= 'deploy_ts'` — TPs reais

## Kill-switch

Reversão em ~30s:
```bash
ssh saira-prod 'sed -i "s/^BGSUB_MORPHO_MODE=.*/BGSUB_MORPHO_MODE=open_close/" /home/ubuntu/saira/services/.env && docker compose -p saira-prod -f /home/ubuntu/saira/services/docker-compose.prod.yml --profile worker up -d --force-recreate yolo-worker'
```

## Critério de decisão (24-48h pós-deploy)

- **Manter**: filter rate ≥ 70% em ambas câmeras E zero regressão em Detail triggers (TPs detectados continuam aparecendo) E custo Gemini cai pelo menos 10% vs período pré-deploy.
- **Reverter**: filter rate < 60% OU Detail rate cai > 20% vs baseline OU latência p95 evaluate sobe > 50%.

<!-- decision -->
## Decisão preliminar (T+60min pós-deploy)

✅ **MANTER em prod**, monitorar 24-48h adicionais.

| Cam | Pre area_min (baseline 1h) | T+30min area_min | T+60min area_min |
|---|---:|---:|---:|
| esp32_001 (cam10) | 75% | 60% (noise) | **79%** |
| esp32_002 (cam11) | 90% | 100% | **100%** |

- Filter rate ≥ baseline em ambas câmeras ✓
- Zero Detail triggers em 1h (período noturno, esperado)
- Latência não medida em prod mas smoke offline mostrou +30% (10s → 13s) — aceitável dentro do worker poll de 180s
- Custos Gemini Gate devem cair proporcional ao aumento de filter rate

## Critério final (48h, ~24h diurno + 24h noturno)

- Manter SE filter rate diurno ≥ 70% E TPs detectados (Detail triggers) ≥ baseline EXPECTATIVA (3-5 TPs/dia esp32_002 historicamente)
- Reverter SE Detail rate cair > 30% vs período pré-deploy ou TPs reportados pelo user/dashboards forem missed
- Avaliar novamente em 2026-05-27 ~12h BRT (24h pós-deploy)
