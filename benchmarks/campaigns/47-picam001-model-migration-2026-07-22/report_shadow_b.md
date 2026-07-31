# Shadow B — poder discriminante do structural-delta na pi-cam-001

**Data:** 2026-07-22 · **Tipo:** calibração offline ($0, CPU) · **Câmera:** pi-cam-001 (event-driven)
**Escopo executado:** Fase 1 (offline). Fase 2 (deploy shadow em prod) **NÃO executada** — decisão
"calibrar, depois eu reviso". Veredito abaixo recomenda **não** ligar como veto de FP.

## Hipótese

A recomendação final da camp 47 (migrar para `gemini-3.1-flash-lite` low-res 2-estágios,
recall-first) atinge 93% de recall ≈ 2.5 mas com **baseline-fire ~15%**, e propõe apoiar a
especificidade com um **pré-filtro structural-delta** ($0, CPU). O Shadow B mede, no dataset
`cam_picam001`, quanto o `census_ntiles_t32` (camp 41) SOZINHO separa TP de FP/baseline.

## Método (fiel à prod)

Reusei o **próprio código de produção** — `worker.detector_structural.score_window` — sobre os
122 eventos do dataset oficial. Isso garante que o threshold transfere 1:1 para o hook de prod
(mesmo census, `TILE=32 / FRAC=0.50 / HAM_THR=3 / MIN_COVER=24`, regra
`should_reject = n_tiles_changed < thr`). Janela = `sorted(evt/frames/*.jpg)` (= caminho
event-driven da prod). Scripts: `scripts/phase_struct_picam.py`, `scripts/struct_picam_viz.py`.

- **Resolução:** todos os 122 eventos são **1280×720** (inclusive pós-upgrade de 16/07) — o
  substream de evento continua 720p, então o polígono de referência 720p está alinhado. ✅
- **Polígono:** buscado do **DB de prod** (fonte de verdade), que **difere** do handoff:
  `[[[18,550],[12,709],[1264,709],[1262,540]],[[325,3],[288,73],[1191,162],[1167,8]]]`.
- **Alvo primário = TP vs FP** (o set `disposal=True` que o shadow de prod veria). `baseline`
  (negativos verdadeiros) e `indefinido` reportados à parte.

## Resultados

| métrica | valor |
|---|---|
| **AUC TP vs FP** (alvo primário) | **0,696** · IC95 [0,556, 0,827] · permutação p=0,005 |
| AUC TP vs baseline (bônus) | 0,811 |
| sinal `n_tiles` — mediana TP / FP / baseline | 19,5 / 7,0 / 0,0 |
| veto recall-safe (≥85% TP), thr=1 | mantém **90% TP** (perde 3), suprime só **16% FP** (6/37) |
| holdout temporal (cut 18/07) | train AUC 0,73 → test 0,69 (não colapsa, mas fraco) |

### Gate de discriminância (critério camp 41: AUC≥0,75 ∧ IC_low>0,5 ∧ veto recall-safe útil)

**VEREDITO: FAIL.** AUC 0,696 < 0,75. O sinal é estatisticamente real (p=0,005) e direcional,
mas **fraco demais** para veto de FP: no ponto recall-safe corta só 16% dos FP ao custo de 3 TPs.

Posição vs outras câmeras: **melhor** que Imbiribeira (0,50) e Arruda (0,63), **pior** que
Mangabeira (0,83, único que passou). Confirma o padrão: structural-delta é geometria-específico.

### A geometria do polígono NÃO é a alavanca (A/B testado)

| polígono | TP vs FP | TP vs baseline |
|---|---|---|
| DB prod (largo, 2 zonas) | 0,696 | 0,811 |
| handoff (concentrado, 2 zonas) | 0,714 | 0,809 |
| só primeiro-plano (larga a faixa de vegetação) | 0,685 | 0,769 |

Todas as variantes ficam em **0,68–0,71** em TP-vs-FP. Re-marcar o polígono **não** resgata o gate.

### Achado colateral acionável: a faixa superior do polígono cobre VEGETAÇÃO

Os overlays (`viz/pair_*.jpg`) mostram que a **2ª zona do polígono do DB** (topo) cobre a
vegetação/árvores ao fundo, que balançam ao vento e acendem census-change em **qualquer** evento
(TP, FP e baseline — ver `pair_fp_evt-20260715_120735.jpg`, faixa superior saturada de vermelho num
FP). Isso injeta ruído. Curiosamente, largá-la (FG-only) **piora** o ponto recall-safe: ~5 TPs não
acendem a pilha de primeiro plano (descarte na borda / pessoa-só), e a vegetação estava
artificialmente "salvando" esses TPs no veto. Ou seja: o sinal não é confiável em nenhuma
configuração — **independente de polígono, o structural não distingue TP de FP nesta câmera**,
porque muitos FPs têm mudança estrutural real (caminhões, pessoas remexendo a pilha existente).

## Recomendação

1. **NÃO ligar o structural-delta como veto de FP (`STRUCTURAL_FILTER_MODE=enforce`) na
   pi-cam-001.** Cortaria ~10% de recall por só ~16% de FP — troca ruim. Gate reprovado.
2. **Deploy shadow (log-only) é opcional e de valor limitado** com o pipeline 2.5 atual: o hook só
   dispara em `disposal=True` (TP+FP), onde o poder é 0,70. O sinal mais forte (TP-vs-baseline 0,81)
   fica **invisível** ao shadow, porque a prod 2.5 rejeita os baseline antes (disposal=False). Só
   valeria a pena logar em prod **depois** da migração para Gemini-3, quando os baseline-fires viram
   `disposal=True` e o structural poderia atacá-los — aí sim o TP-vs-baseline 0,81 seria exercido.
3. **Item de higiene (à parte do Shadow B):** a 2ª zona do `pile_zone_polygon` de prod cobre
   vegetação. Vale re-marcar (via `tools/polygon_marker.html`) para o motion-trigger e o BGSUB não
   dispararem em vento — mas isso é qualidade de polígono, não resgata o structural.
4. **Especificidade da migração Gemini-3 fica no LLM** (prompt/confiança recall-first já em teste),
   não no structural-delta. Consistente com o histórico ("veto de sinal único fura recall").

## Artefatos

- `scripts/phase_struct_picam.py` — calibração (reusa `detector_structural.score_window`).
- `scripts/struct_picam_viz.py` — overlays + A/B de polígono.
- `results/struct_picam_signals.csv` — n_tiles_changed por evento (122).
- `results/struct_picam_roc.json` — AUC/IC/sweep/holdout/permutação (gate=FAIL).
- `viz/pair_*.jpg` — 4 TP + 4 FP com polígono + census-change.

## Definition of Done
✅ Threshold/AUC/holdido reportados no dataset cam_picam001. ✅ Overlays validando polígono.
✅ Veredito do gate (FAIL) + recomendação. ⏸️ Fase 2 (prod) parada para revisão do usuário.

---

# Shadow A — 2.5 vs 3.1 fechado (2026-07-30)

O follow-up pendente (`compare_shadow.py`) foi entregue. 4.132 eventos de shadow entre
22/07 e 30/07, cruzados com o status do operador nas 61 detecções da pi-cam-001 no
período. Números em `results/shadow_3v1_report.md`; discordâncias em
`results/shadow_3v1_quadrants.csv`.

**As duas fases não se agregam** — `g3` troca modelo *e* prompt, `current` isola o modelo:

| fase | n | prod SIM / shadow SIM | recall (do que o operador CONFIRMOU) | alarme falso (do que ele REJEITOU) | US$/ev |
|---|---|---|---|---|---|
| `g3` (22–28/07) | 2.559 | 59 / 213 | 22/32 · 68,8% | 15/19 · 78,9% | 0,00140 |
| `current` (28–30/07) | 1.573 | 18 / 10 | 1/2 · 50,0% | 4/11 · 36,4% | 0,00107 |

**Leitura.** As duas fases falham por motivos opostos e nenhuma domina a prod:

- O **prompt `g3` dispara demais**: 213 confirmações contra 59 da prod, e ainda assim
  perde 10 dos 32 eventos que o operador confirmou. Mais alarme falso *e* menos recall.
- Com o **mesmo prompt de prod**, o 3.1 fica muito mais conservador: dos 18 eventos em
  que a prod criou detecção, ele confirmaria só 5. Isso reproduz em tráfego real o
  resultado do Camp 47 (3.1 regride recall) — agora sem o prompt como variável.

O braço `current` ainda é **estatisticamente fraco** (n=13 detecções julgadas em 2,5
dias, das quais só 2 CONFIRMADO). Por isso o shadow 3.1 **segue ligado até ~04/08**, em
paralelo ao shadow kimi, em vez de ser desligado agora.

**Custo real** (`gemini_call_log`, mesmo período): prod 2.5 US$ 6,32 · shadow 3.1
US$ 5,26. O 3.1 também foi mais rápido (gate 4,7 s vs 7,8 s; detail 7,9 s vs 15,9 s) e
teve **0 erros contra 115 da prod** — disponibilidade e latência são a favor do 3.1; o
que não fecha é recall.
