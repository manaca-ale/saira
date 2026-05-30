# Campanha 24 — MANGABEIRA prompt E + pile-zone hi-res crops (Flash 2.5) 2026-05-30

> Implementação da **recomendação #5 (CropVLM)** do Deep Research VLM pipeline
> (2026-05-30). Adiciona crops alta-res da `pile_zone_polygon` esp32_002
> como sequência adicional de input, mantendo MANGABEIRA_E como prompt base.

## Hipótese

A maioria dos descartes em cam_11 (Mangabeira) é de sacolinhas pequenas
(0,05 m³, mediana) **invisíveis** na resolução full-frame da câmera. Crops
alta-res da pile zone (440×280px upscale 2x) deveriam recuperar recall pra
esses casos sem trocar de modelo.

Bench compara:
- Flash + MANGABEIRA_E (single-input baseline da camp 22)
- Flash + MANGABEIRA_E + 12 crops alta-res (este experimento)

Isolando o efeito do **crop** vs o efeito do prompt refinement (E2).

## Dataset

cam_11 only, snapshot DB prod 2026-05-30 ~10:00 BRT, n=40 events.
Cohort clean single-call: n=29.

## Estrutura de input

| Sequência | Quantidade | Resolução | Origem |
|---|---|---|---|
| 1 — globais | 48 frames | 1280px max edge (prod parity) | uniform sample da janela cascade |
| 2 — crops pile-zone | 12 frames | 880×560 (upscale 2× de 440×280) | subset uniform dos 48 globais |

Pile zone esp32_002: bbox `(480, 60, 920, 340)` (canto superior central — onde a pilha existente fica visível na câmera).

## Production parity

| Parâmetro | Prod | Bench | Status |
|---|---|---|---|
| `GEMINI_CASCADE_MAX_FRAMES` | 48 | 48 globais + 12 crops | ⚠️ globais OK; crops são extra |
| `GEMINI_MOSAIC_AGENT2` | off | off | ✅ |
| Modelo | gemini-2.5-flash | gemini-2.5-flash | ✅ |
| `GATE_PILECROP_UPSCALE` (gate) | 2 | 2 (mesmo) | ✅ consistente |

**Caveat**: prod hoje só faz pile-crops no **gate** (esp32_002, behind flag
`GEMINI_GATE_PILECROP_ENABLED=false`). Este bench testa pile-crops no **detail**
(Agent-2) — novo experimento, não tem flag de prod ainda.

## Como rodar

```bash
# Ship
scp scripts/flash_mangabeira_e_with_crops.py saira-prod:/tmp/
scp prompts/mangabeira-e-with-pilecrops.md saira-prod:/tmp/
ssh saira-prod 'docker cp /tmp/flash_mangabeira_e_with_crops.py saira-yolo-worker-prod:/tmp/ && \
                docker cp /tmp/mangabeira-e-with-pilecrops.md saira-yolo-worker-prod:/tmp/'

# Run (Vertex, ~12min)
ssh saira-prod 'docker exec \
  -e GOOGLE_GENAI_USE_VERTEXAI=true \
  -e GOOGLE_APPLICATION_CREDENTIALS=/tmp/saira-bench-vertex.json \
  -e GOOGLE_CLOUD_PROJECT=gen-lang-client-0841492152 \
  -e GOOGLE_CLOUD_LOCATION=global \
  saira-yolo-worker-prod stdbuf -oL -eL python -u /tmp/flash_mangabeira_e_with_crops.py'
```

Cache: `/tmp/flash_mangabeira_E_CROPS_cache.json`.
Frames cache reusado: `/tmp/flash_per_camera/frames/esp32_002/` (camp 21).

## Custo estimado

~$0.013/event × 40 = **~$0.55 total** (vs $0.41 do E sem crops).
Custo extra: +30% (12 crops adicionam ~3-4k tokens entrada).

## Smoke test (1 evento)

Evento `e268d665` (gt=REJ, 12:59 BRT) — case ambíguo onde MANGABEIRA_E e E2
provavelmente confirmariam (pessoa agachada perto da pilha).

**Resultado**: `pred=REJ` ✅ (correto). Modelo:

- Classificou pessoas como AGACHADA_LONGA (P5 chapéu vermelho + P6 camisa clara, 09:57:16-09:59:35)
- Aplicou AP4 (catador) com nova condição **4b: ">30s sem objeto novo nos crops"**
- Citou crops como evidência: *"CROPS: Nenhuma adição de objeto novo visível na pilha após a saída de P5 e P6"*

Os crops estão sendo **referenciados explicitamente** pelo modelo — confirma
que o anchor visual está funcionando.

## Memórias relacionadas

- [[project_camp22_mangabeira_prompt_angles_2026-05-30]] — E é o melhor prompt single-input
- [[reference_vertex_ai_bench_setup]] — Vertex flags
- [[project_official_dataset_v1]] — pile_zone_polygon esp32_002 = [[480,60],[920,60],[920,340],[480,340]]
- Deep Research: `pesquisas/vlm_pipeline_architecture_2026-05-30.md` (recomendação #5 CropVLM)
