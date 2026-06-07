# Campanha 22 — MANGABEIRA prompt angles (Flash) 2026-05-30

> Continuação direta da camp 21 — só cam_11. Mantém Flash 2.5 como modelo
> (usuário descartou Pro/Sonnet por custo) e testa ângulos de prompt
> mecanicamente distintos.

## Hipótese

Camp 21 mostrou que `DETAIL_PROMPT_V3_MANGABEIRA` com Flash:
- Recall 75% (3 FN entre 12 CONs)
- Specificity 33% (10 FP entre 15 REJs)

Análise dos 4 FN_NEW + 7 FP_PERSIST + 3 FP_NEW (vs Flash V1 baseline) revela:

1. **Confabulação** — modelo descreve depósito quando há só postura ambígua (FP_PERSIST + FP_NEW)
2. **Anti-padrões aplicados inconsistentemente** — quando aplicam, funcionam (FP_FIXED); quando não aplicam, modelo cai no default REJ (FN_NEW) ou inventa CON (FP_PERSIST)
3. **Anti-padrão #4 (CATADOR) sobre-aplicado** — modelo até inverteu direção do material num caso (d27e2560: "retirou da pilha" quando era depósito)

## Ângulos testados

| Ângulo | Mecanismo | Hipótese |
|---|---|---|
| **C** — Two-step checklist | 5 critérios S/N obrigatórios por pessoa relevante; CON só com 5/5 | Força evidência explícita; reduz confabulação |
| **E** — Negative-first | Inverte default: assume CON, prova REJ via anti-padrões; em dúvida CON | Recupera recall mantendo specificity quando AP claros |

Cada ângulo roda Flash 2.5 (mesmo modelo) só nos 35 events cam_11.

## Production parity

| Parâmetro | Prod | Bench | Status |
|---|---|---|---|
| `GEMINI_CASCADE_MAX_FRAMES` | 48 | 48 | ✅ |
| `GEMINI_MOSAIC_AGENT2` | off | off | ✅ |
| `GEMINI_DETAIL_MODEL` | gemini-2.5-flash | gemini-2.5-flash | ✅ |

Cache de frames reusado de `/tmp/flash_per_camera/frames/esp32_002/` (camp 21).

## Como rodar

```bash
# Ship script + prompts pro worker
scp scripts/flash_mangabeira_angles.py saira-prod:/tmp/
scp prompts/mangabeira-c-checklist.md saira-prod:/tmp/
scp prompts/mangabeira-e-negative-first.md saira-prod:/tmp/
ssh saira-prod 'docker cp /tmp/flash_mangabeira_angles.py saira-yolo-worker-prod:/tmp/ && \
                docker cp /tmp/mangabeira-c-checklist.md saira-yolo-worker-prod:/tmp/ && \
                docker cp /tmp/mangabeira-e-negative-first.md saira-yolo-worker-prod:/tmp/'

# Run angle C (Vertex, ~10min)
ssh saira-prod 'docker exec \
  -e ANGLE=C \
  -e GOOGLE_GENAI_USE_VERTEXAI=true \
  -e GOOGLE_APPLICATION_CREDENTIALS=/tmp/saira-bench-vertex.json \
  -e GOOGLE_CLOUD_PROJECT=gen-lang-client-0841492152 \
  -e GOOGLE_CLOUD_LOCATION=global \
  saira-yolo-worker-prod stdbuf -oL -eL python -u /tmp/flash_mangabeira_angles.py'

# Run angle E (same flags, ANGLE=E)
```

Reusa `_bench_common.py` da camp 21 que já está em `/tmp/_bench_common.py` no worker.

## Comparação

Após rodar, comparar contra os 2 caches da camp 21:
- `/tmp/flash_baseline_v1_cache.json` (V1 prod baseline)
- `/tmp/flash_per_camera_cache.json` (MANGABEIRA original — ângulo "atual")
- `/tmp/flash_mangabeira_C_cache.json` (NOVO)
- `/tmp/flash_mangabeira_E_cache.json` (NOVO)

Métrica chave: cam_11 single-call cohort (n≈27) — acc, recall, specificity.

## Custo estimado

35 events × ~17k in_tok × $0.30/M + ~3k out_tok × $2.50/M ≈ **$0.45/arm**.

Total camp 22: ~$0.90.

## Memórias relacionadas

- [[project_camp21_per_camera_detail_2026-05-30]] — origem
- [[feedback_bench_match_prod_exactly]] — N=48, coalesced caveat
- [[reference_vertex_ai_bench_setup]] — Vertex flags
