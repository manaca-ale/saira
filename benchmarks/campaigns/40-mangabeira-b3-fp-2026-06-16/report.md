# Campanha 40 — Redução de FP B3 no Mangabeira (esp32_002 / cam_11)

**Data:** 2026-06-16 · **Modelo detail:** gemini-2.5-flash · **Custo novo:** ~$1,10
(bench `gen-lang-client-0841492152`) · **Eval:** dataset oficial `cam_mangabeira`
(13 TP + 20 B3 FP; 28 B1/B2 e 3 indef reportados à parte).

## Hipótese / pergunta

Mangabeira é a câmera que mais gera FP. O prompt deployado (E+CROPS) confirma por
**comportamento** e **não exige delta de pilha** (descartes reais são sacolas minúsculas,
muitas vezes invisíveis). Pergunta: **algum sinal barato separa os FP B3 (transeunte/
trânsito) dos descartes reais (TP)?** Testamos 3 alavancas — CV (foreground), DINOv2
(embedding do crop) e variante de prompt — com piso de recall ≥ 11/13 (aceito perder 1 TP).

## Achado de método (verificado)

A camp 24 (`results/flash_mangabeira_E_CROPS_results.json`) cobre **11/13 TP e 0/48 FP**
oficiais. Logo o baseline E+CROPS dos 20 B3 foi **rodado de novo** localmente. Os frames
do dataset oficial (mediana 12–24) são **menos** que os 48 de prod → números absolutos não
transferem; comparações são internas (mesmos frames p/ baseline/V1/V2).

## Resultados por fase

### Fase A — sinais CV (foreground bruto na zona da pilha): **NÃO separa** ($0)

| Sinal | AUC (TP vs B3) | 95% CI | melhor veto |
|---|---|---|---|
| persistence | **0,408** | — | 2/20 B3 |
| permanence (ficou algo novo?) | **0,558** | [0,35–0,75] cruza 0,5 | 4/20 (20%) @13/13 |
| peak_fg | 0,377 | — | 1/20 |

→ **Muro tiny-bag confirmado para a alavanca CV.** Foreground bruto não distingue depósito
minúsculo de movimento de transeunte (B3 chegam a ter MAIS persistência que TP).

### Fase B — DINOv2 retreino offline cam_11: **separa, mas com drift** ($0)

Treino: 13 TP (CON) + 48 FP (REJ) do dataset oficial (frames de prod purgaram). Out-of-fold.

- **CV AUC 0,933** (muito > 0,71 da camp 26) · **eval TP-vs-B3 AUC 0,892** (p_con TP med
  0,915 vs B3 0,060).
- ⚠️ **Holdout temporal AUC 0,644** (gap +0,29) → reproduz o **drift da camp 27**: a
  separação é real **in-distribution** mas degrada pra frente no tempo. Não existe artefato
  cam_11 em prod (só cam_10).

### Fase C — variantes de prompt: **V1 funciona, V2 fura recall** (~$1)

| Prompt | recall | B3-FP | comentário |
|---|---|---|---|
| baseline E+CROPS | 12/13 | 18/20 | confirma quase todo B3 (default-CON) |
| **V1** (anti-padrão DURO de passante crop-grounded) | **11/13** | **10/20** | corta 8 FP, −1 TP |
| V2 (evidência só p/ INTERAGENTE_CURTA) | 10/13 | 11/20 | **perde 2 TP → reprovado** |

V1 é a **1ª variante de prompt que funciona** (camps 11-14/22/23/32 falharam) — porque
ADICIONA um anti-padrão duro ("passante linear sem objeto novo no crop → REJ mesmo com
sacola momentânea") em vez de relaxar o default-CON. `crop_new_object=False` em 10/10 dos
B3 rejeitados (coerente).

### Fase D — post-filtro + Pareto (recall ≥ 11/13, bootstrap 10k)

| Regra | recall | B3 suprimido (95% CI) | obs |
|---|---|---|---|
| baseline E+CROPS | 12/13 | 2/20 = 10% [0,25] | — |
| **D6 — V1 + DINOv2 veto** | **11/13** | **16/20 = 80% [60,95]** | levers complementares |
| D2' — DINOv2 veto @floor | 11/13 | 12/20 = 60% [40,80] | thr 0,043 |
| D2 — DINOv2 veto recall-safe | 12/13 | 11/20 = 55% [35,75] | thr 0,008, **0 TP extra** |
| V1 prompt standalone | 11/13 | 10/20 = 50% [30,70] | sem modelo, sem drift |
| D1 — CV permanence veto | 11/13 | 6/20 = 30% [10,50] | fraco |
| V2 prompt | 10/13 | 45% | ❌ fura piso |

TP perdido pelo baseline (em frames oficiais): `8fdb7d45` (caso difícil; até o deployado erra).

## ⚠️ Validação com N grande (2026-06-16, tarde) — DINOv2 REFUTADO

As Fases A-D acima usaram o dataset oficial (**13 TP / 20 B3** — N pequeno). Reexecutamos o
DINOv2 com **N realista**: todas as detecções persistidas de cam_11 em prod (frames de
evidência no S3, janelas completas 38-143), bucketizadas pelo comentário do operador →
**71 TP + 142 B3 + 38 B1/B2 (n=251)**, últimos 3 frames, out-of-fold + holdout temporal.

| | N pequeno (13/48) | **N grande (71/180)** |
|---|---|---|
| CV AUC (CON-vs-REJ) | 0,933 | **0,551** |
| eval TP-vs-B3 AUC | 0,892 | **0,546** |
| **holdout temporal AUC** | 0,644 | **0,507 (acaso)** |
| veto recall-safe | 55% B3 | **1% B3** |

**O resultado de N pequeno era OVERFITTING.** Com 13 TP e 5-fold CV (~2-3 TP/fold), a AUC
0,93 foi ruído de amostra pequena + dataset oficial curado. Em N realista, **o DINOv2 NÃO
separa B3 de TP** (AUC ≈ 0,55, holdout ≈ acaso). **→ O muro tiny-bag vale também para o
embedding semântico do DINOv2, não só para o foreground bruto.** Vision não distingue
descarte minúsculo de transeunte. Artefatos: `largeN/{manifest,dinov2_scores}.csv`,
`scripts/largeN_{fetch,dinov2}.py`.

## Decisão (corrigida pós-N-grande)

**Ambas as alavancas de visão (CV bruto E DINOv2) batem no muro tiny-bag em N realista.**
O único sinal que sobra é **comportamental (prompt V1)** — que, por ser uma regra e não um
classificador treinado, não tem o modo de falha de overfitting. Mas **V1 ainda NÃO foi
validado em N grande** (precisa de chamadas Gemini novas). Conclusão de visão:

1. **DINOv2 cam_11 — DESCARTADO.** O ganho de N pequeno era overfitting; em N realista não
   separa (AUC 0,55, holdout acaso). Não treinar/deployar para cam_11.
2. **CV (foreground) — DESCARTADO** já na Fase A (não separa em nenhum N).
3. **Prompt V1 — único candidato vivo.** É a única alavanca que sobra. PORÉM seu 50% também
   veio de N pequeno (20 B3); **precisa validar em N grande** (72 TP + 144 B3 reais de prod,
   ~$3 Gemini) antes de recomendar deploy. Sem isso, não dá garantia.

**Lição de método:** N pequeno (dataset oficial curado) infla classificador treinado.
Sempre validar alavancas em N realista (detecções persistidas de prod via S3) antes de
concluir. O instinto de "testar com N maior" salvou a campanha de uma recomendação errada.

## Caminho NÃO-VISUAL — gate barra-alta (o que funciona)

Esgotada a visão por-evento, mudamos a PERGUNTA. Check estruturado ($0, n=71/142): hora do
dia (TP manhã 31% vs B3 26%), volume (0,07 vs 0,05) e tipo de infrator NÃO separam. **Nenhum
sinal — visual ou estruturado — classifica o evento tiny-pedestre.** Reframe: as 2 missões da
SAIRA pedem coisas diferentes. Para **flagrante** (alerta/autuação), só importa descarte
**atribuível+significativo** (veículo/carroça/agachada-longa/volumoso) — e esses SÃO
distinguíveis. Testamos um **GATE BARRA-ALTA** (só CON nesses casos; rejeita pedestre-breve/
ambíguo mesmo com sacola momentânea) nos **216 eventos reais de prod** (gemini-2.5-flash via
Vertex, $1,19):

| | Baseline deployado | **Gate barra-alta** |
|---|---|---|
| B3 FP (alerta/métrica/custo) | 142/142 (100%) | **28/142 → corta 80%** |
| TP mantidos (recall) | 71/71 (100%) | 53/71 (75%) |
| **TP acionáveis** (vol>0,3 ou veículo) | 4/4 | **4/4 = 100%** |
| TP perdidos | 0 | 18 — **17/18 são tiny (≤0,1 m³)** |

**O gate barra-alta corta 80% dos B3 FP mantendo 100% dos descartes ACIONÁVEIS.** Os 18 TP
perdidos são tiny-pedestre não-autuáveis — exatamente a classe que deve ir pra **métrica de
volume longitudinal** (crescimento da pilha no tempo via BGSUB), não pra flagrante. Ataca as
3 dores de uma vez: **alerta** (−80% FP), **métrica** (−80% contagem inflada), **custo Gemini**
(deployar no GATE = ~80% menos chamadas Agent-2 nessas janelas). Resíduo: 28 B3 (16 por
confabular agachada-longa) → apertar critério B (exigir carga visível) deve reduzir mais.

## Recomendação final

1. **Flagrante: deploy do gate barra-alta no esp32_002** (addon que exige sinal
   atribuível+significativo; substitui o `ESP32_002_RECALL_B3_ADDON` permissivo). Via shadow
   A/B. Validado em N grande: −80% FP, 100% dos acionáveis. Artefatos: `largeN/highbar_*`,
   `scripts/largeN_highbar.py`.
2. **Métrica: prototipar volume longitudinal** (BGSUB baseline drift / volume-da-pilha no
   tempo) — captura o dumping tiny-pedestre sem classificar evento; FP não move volume. $0.
3. **NÃO investir** mais em classificador visual por-evento (CV/DINOv2) nem em afrouxar prompt
   pra recuperar tiny-pedestre — é o muro tiny-bag, comprovado em N grande.

**Ressalvas:** N pequeno (13 TP / 20 B3), frames oficiais < 48 de prod → validar em **shadow
A/B de prod** antes de enforce. Nada otimiza B1/B2 (catador/limpeza) — fora de escopo.

## Próximo passo sugerido

Deploy **V1 em shadow A/B** no esp32_002 (paralelo ao E+CROPS deployado) por ~1 semana,
medindo recall (não perder TP além do baseline) e corte de FP em prod real. Em paralelo,
treinar o artefato DINOv2 cam_11 e rodá-lo em shadow (ledger), como no Imbiribeira.

## Artefatos

`scripts/{build_eval_set,phase_a_cv_signals,phase_b_dinov2,phase_c_variant_local,
phase_d_postfilter}.py` · `results/{b3_split,phase_a_signals,phase_b_dinov2,phase_d_pareto}.csv`,
`phase_c_variant_results.json` · `prompts/{baseline,V1,V2}`. Reusa `tools/spike_bgsub_filter.py`,
camp 24 harness, `retrain_dinov2.py`/`detector_dinov2.py`, `_prompts_v3.py`.
