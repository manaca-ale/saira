# Campanha 24 — MANGABEIRA E + pile-zone hi-res crops (Flash 2.5) 2026-05-30

> ✅ **CONCLUÍDA** — **WINNER de recall (90,5% full, 91,7% single-call)** com mesma acc do E2.
> Implementação direta da recomendação #5 (CropVLM) do Deep Research VLM pipeline.

## Hipótese

Camp 22 identificou que MANGABEIRA_E perde recall em casos onde o full-frame (1280px max)
não permite ver objetos pequenos depositados. A maioria dos TPs em cam_11 são sacolinhas
de ~0,05 m³ (~50cm³) — abaixo da resolução visível.

Adicionar **12 crops alta-res da pile_zone (440×280 px upscale 2× = 880×560)** como sequência
adicional de input ao Flash deveria:
1. Recuperar TPs que dependem de ver objeto pequeno (sacolinha aparecendo na pilha)
2. Permitir aplicação de AP4b (>30s sem objeto novo) com mais confiança

## Dataset

cam_11 only, snapshot DB prod 2026-05-30 ~10:00 BRT, n=40 events.
Cohort clean single-call: n=29.

## Estrutura de input

| Sequência | Quantidade | Resolução | Origem |
|---|---|---|---|
| 1 — globais | 48 frames | 1280px max edge (prod parity) | uniform sample da janela cascade |
| 2 — crops pile-zone | 12 frames | 880×560 (upscale 2× de 440×280) | subset uniform dos 48 globais |

`pile_zone_polygon` esp32_002 do DB: `[[480,60], [920,60], [920,340], [480,340]]` → bbox `(480, 60, 920, 340)`.

## Resultados — full cohort (n=40)

| Arm | Acc | TP | TN | FP | FN | Recall | Spec | $/event |
|---|---|---|---|---|---|---|---|---|
| Flash V1 baseline | 60% | 17 | 4 | 11 | 3 | 85,0% | 26,7% | $0,01 |
| MANGABEIRA_E (camp 22) | 61,5% | 14 | 10 | 8 | 7 | 66,7% | **55,6%** | $0,011 |
| MANGABEIRA_E2 (camp 23) | 67,5% | 18 | 9 | 10 | 3 | 85,7% | 47,4% | $0,015 |
| **🏆 E+CROPS** | **67,5%** | **19** | 8 | 11 | **2** | **90,5%** ✅ | 42,1% | $0,015 |

## Resultados — single-call cohort (n=29 prod parity)

| Arm | Acc | TP | TN | FP | FN | Recall | Spec |
|---|---|---|---|---|---|---|---|
| Flash V1 baseline | 53,8% | 11 | 3 | 11 | 1 | 91,7% | 21,4% |
| MANGABEIRA_E | 62,1% | 9 | 9 | 8 | 3 | 75,0% | **52,9%** |
| MANGABEIRA_E2 | 58,6% | 9 | 8 | 9 | 3 | 75,0% | 47,1% |
| **E+CROPS** | 58,6% | 11 | 6 | 11 | **1** | **91,7%** | 35,3% |

## Target events da camp 23 (motivaram refinamento)

| Target | E | E2 | **E+CROPS** |
|---|---|---|---|
| d59d5309 (CON, AP3 over-applied) | MISS | OK ✅ | OK ✅ |
| 3c840ac4 (CON carrinho, AP2) | MISS | MISS | MISS |
| 5520e0c7 (REJ, AP4 catador) | MISS | OK ✅ | OK ✅ |

Os crops **não resolveram o caso difícil 3c840ac4** (carrinho de mão com entulho) —
provavelmente requer detecção temporal (objeto sendo despejado em movimento) que nem
o crop nem o prompt single-shot capturam.

## Cross-bucket vs V1 (single-call)

| Bucket | E (camp 22) | E2 (camp 23) | **E+CROPS** |
|---|---|---|---|
| ✅ FP_FIXED | 5 | 4 | 3 |
| ✅ TP_NEW | 0 | 0 | **1** ✅ (be6b5e67) |
| ❌ FN_NEW | 2 | 2 | **1** (só 3c840ac4) |
| ❌ FP_NEW | 1 | 0 | 1 (2bb86418) |
| ⚪ FP_PERSIST | 6 | 7 | 8 |
| ⚪ FN_BOTH | 1 | 1 | **0** ✅ |

**Destaque E+CROPS:**
- **🎯 TP_NEW=1**: recuperou `be6b5e67` (caso noturno guarda-chuva) que era FN_BOTH em todos os outros arms — único arm que pegou esse caso difícil
- **🎯 FN_BOTH=0**: único arm onde nenhum CON é perdido por ambos (V1+arm)
- **FN_NEW=1**: só 3c840ac4 (carrinho) ainda perdido
- **FP_PERSIST=8**: casos visualmente ambíguos que prompting+crops sozinhos não filtram (limite teto, igual ao previsto)

## Análise qualitativa

### Por que crops ajudaram

1. **Recuperou be6b5e67** (TP_NEW): caso noturno em IR mode, pessoa com guarda-chuva.
   Full-frame perde detalhe; crop alta-res mostra evidência de depósito.
2. **Recuperou 5520e0c7** (REJ correto): crops confirmam "nenhum objeto novo após 2:30
   agachado" → AP4b dispara com confiança que prompt sozinho não tinha
3. **Recuperou d59d5309** (CON correto): crops confirmam que sacola foi depositada

### Por que crops introduziram 1 FP novo

- **2bb86418** (REJ real, mas E+CROPS confirmou): modelo confabulou "objeto azul depositado"
  vendo crops. Crop alta-res às vezes amplifica ambiguidade visual.

### O que crops NÃO resolveram

- **3c840ac4** (CON carrinho): caso temporal — pessoa empurra carrinho cheio, despeja
  entulho em movimento. Nem full-frame nem crop estático capturam o despejo em
  movimento. Talvez precise de tracking temporal (ByteTrack) ou modelos vídeo nativos.
- **FP_PERSIST=8**: casos onde pessoa para com sacola por 5s — visualmente parece
  depósito. Crops não ajudam aqui (a pessoa REALMENTE para na pilha com sacola).
  Limite estrutural do paradigma "1 chamada, 1 input visual".

## Trade-off operacional cam_11 (~17/dia)

| | V1 prod | MANGABEIRA_E2 | **E+CROPS** |
|---|---|---|---|
| Operador vê | 22/dia | 19/dia | 22/dia |
| Ocorrências perdidas | ~1/dia | ~1/dia | **~0,5/dia** |
| Workload op | baseline | −14% | =baseline |
| Custo | $0,17/dia | $0,26/dia | $0,26/dia |

**E+CROPS prioriza recall sobre workload**. Operador vê o mesmo número que V1 mas pega
+0,5 ocorrência/dia (~15/mês). Custo extra: ~$3/mês.

## Comparação cruzada — para escolher

| Prioridade | Recomendação |
|---|---|
| Recall máximo (missão SAIRA = pegar descarte) | **E+CROPS** |
| Workload op menor | MANGABEIRA_E2 |
| Specificity máximo (operador overworked) | MANGABEIRA_E |
| Compromisso recall/spec/custo | MANGABEIRA_E2 |

Como **recall pesa 3× spec na nossa função utilidade** (per task description): **E+CROPS é o melhor**.

## Custo e latência

| Métrica | E | E2 | **E+CROPS** |
|---|---|---|---|
| Tokens in (média) | ~13k | ~14k | ~16k (+23%) |
| Tokens out | ~3k | ~4k | ~4k |
| Custo/event | $0,011 | $0,015 | $0,015 |
| Latência média | ~20s | ~20s | ~22s |

Crops adicionam ~30% nos tokens de entrada mas a saída fica igual.

## Deployment

**Complexidade pra deploy:**
- ✅ `_make_pile_crops()` já existe no worker ([main.py:970](services/yolo-worker-vm/src/worker/main.py#L970)) — usado pelo gate
- ⚠️ Precisa de novo flow no Agent-2: extender `_process_with_gemini` pra aceitar crops paralelos
- ⚠️ Novo prompt: portar `mangabeira-e-with-pilecrops.md` pra `_prompts_v3.py`
- ⚠️ Novo flag: `GEMINI_DETAIL_PILECROP_ENABLED` + `DETAIL_PILECROP_DEVICES=esp32_002`
- ⚠️ Custo +50% vs V1 (mas ainda <$0,02/event)

**Plano shadow A/B sugerido:**
1. Implementar feature em `develop` (worker accept crops em Agent-2)
2. Subir `test-saira` (push develop → CI/CD)
3. Por 1-2 semanas, capturar ambos veredictos paralelos (V1 + E+CROPS) sem expor ao operador
4. Comparar contra labels do operador depois
5. Se mantiver recall ≥85% acc ≥65% em shadow, promover

## Caveats

1. **n=29 single-call** é pequeno; ±10pp σ. Repetir quando crescer.
2. **Coalesced events (5)** subestimam recall em prod (2+ calls independentes).
3. **3c840ac4 (carrinho)** persiste como FN — caso temporal não resolvido por crops.
4. **FP_PERSIST=8** é teto estrutural — prompting + crops sozinhos não filtram cases
   visualmente convincentes mas operacionalmente FP. Próximo nível: ensemble ou
   Agent-3 verifier (camp 20 já testou).

## Decisão

🏆 **E+CROPS é o melhor arm pra SAIRA**:
- Recall máximo (90,5% full, 91,7% single-call) = igual ao V1
- Specificity ~1,6× do V1 (42% vs 27%)
- Acc 67,5% = mais alto entre arms recall-altos
- Custo viável ($0,015/event)

✅ **Próximo passo: shadow A/B em test-saira**.

Implementação:
1. Adicionar suporte a pile-crops no Agent-2 (similar ao gate)
2. Portar prompt MANGABEIRA_E + crops para `_prompts_v3.py`
3. Flag `GEMINI_DETAIL_PILECROP_ENABLED=true` + `DETAIL_PILECROP_DEVICES=esp32_002`
4. Deploy `develop` → `test-saira`
5. Capturar veredictos paralelos por 1-2 semanas
6. Comparar e decidir prod

## Reprodução

Scripts em `scripts/`:
- `flash_mangabeira_e_with_crops.py` — bench Flash + E + crops
- `compare_all_arms.py` — comparativo cruzado dos 5 arms (V1/orig/E/E2/E+CROPS)

Prompt em `prompts/mangabeira-e-with-pilecrops.md`. Resultados em `results/`.

## Memórias relacionadas

- [[project_camp22_mangabeira_prompt_angles_2026-05-30]] — camp 22 baseline (E vencedor)
- [[project_camp23_mangabeira_e2_2026-05-30]] — refinamento de APs paralelo
- [[reference_vertex_ai_bench_setup]] — Vertex AI sem 503
- [[project_official_dataset_v1]] — pile_zone_polygon esp32_002
- Deep Research: `pesquisas/vlm_pipeline_architecture_2026-05-30.md` (rec #5 CropVLM)
