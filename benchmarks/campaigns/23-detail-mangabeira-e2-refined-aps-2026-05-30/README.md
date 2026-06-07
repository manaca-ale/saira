# Campanha 23 — MANGABEIRA E2 — APs refinados (Flash 2.5) 2026-05-30

> Iteração direta da [camp 22](../22-detail-mangabeira-prompt-angles-2026-05-30/).
> Atacou 3 erros específicos do prompt MANGABEIRA_E (camp 22 winner) sem trocar
> modelo (Flash 2.5 mantido).

## Hipótese

Camp 22 mostrou MANGABEIRA_E perder 2 TPs reais (FN_NEW) e introduzir 1 FP novo
(FP_NEW) por:

- **AP2/AP3 sobre-aplicados**: avaliação agregada "todos passam" ignorava pessoas
  individuais que paravam junto à pilha
- **AP4 sub-aplicado**: não pegava agachamento prolongado sem objeto visível
  saindo da pilha

E2 corrige:

1. **AP2/AP3 per-person**: novo PASSO 2 obrigatório classifica cada pessoa
   (PASSANTE/PAUSADA/AGACHADA_LONGA/INTERAGENTE_CURTA) antes de aplicar APs
2. **AP4b temporal**: ">30s agachada sem objeto novo no chão = vasculhamento, REJ"

## Production parity

| Parâmetro | Prod | Bench | Status |
|---|---|---|---|
| `GEMINI_CASCADE_MAX_FRAMES` | 48 | 48 | ✅ |
| `GEMINI_MOSAIC_AGENT2` | off | off | ✅ |
| Modelo | gemini-2.5-flash | gemini-2.5-flash | ✅ |

Cache de frames reusado de `/tmp/flash_per_camera/frames/esp32_002/` (camp 21).
Provider: **Vertex AI** (location=global, SA `saira-bench-vertex@gen-lang-client-0841492152`).

## Como rodar

```bash
# Ship
scp scripts/flash_mangabeira_e2.py saira-prod:/tmp/
scp prompts/mangabeira-e2-refined-aps.md saira-prod:/tmp/
ssh saira-prod 'docker cp /tmp/flash_mangabeira_e2.py saira-yolo-worker-prod:/tmp/ && \
                docker cp /tmp/mangabeira-e2-refined-aps.md saira-yolo-worker-prod:/tmp/'

# Run (Vertex, ~10min)
ssh saira-prod 'docker exec \
  -e GOOGLE_GENAI_USE_VERTEXAI=true \
  -e GOOGLE_APPLICATION_CREDENTIALS=/tmp/saira-bench-vertex.json \
  -e GOOGLE_CLOUD_PROJECT=gen-lang-client-0841492152 \
  -e GOOGLE_CLOUD_LOCATION=global \
  saira-yolo-worker-prod stdbuf -oL -eL python -u /tmp/flash_mangabeira_e2.py'
```

Cache: `/tmp/flash_mangabeira_E2_cache.json`.

## Custo

~$0,015/event × 40 events = **~$0,60 total**.

## Memórias relacionadas

- [[project_camp22_mangabeira_prompt_angles_2026-05-30]] — E vencedor original, motivação dos 3 targets
- [[project_camp24_pilezone_crops_2026-05-30]] — estratégia complementar (mesma sessão)
- [[feedback_bench_match_prod_exactly]] — N=48 production parity
- [[reference_vertex_ai_bench_setup]] — Vertex AI sem 503
