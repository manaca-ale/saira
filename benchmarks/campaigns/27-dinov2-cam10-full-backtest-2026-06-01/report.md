# Camp 27 — Backtest offline do filtro DINOv2 em cam_10 (Imbiribeira)

**Data:** 2026-06-01 · **Modelo:** DINOv2 ViT-S/14 (384-d, crop pile-zone bbox `[6,297,995,719]`) + LogReg
**Dataset:** conjunto COMPLETO de eventos rotulados de cam_10 — **32 eventos (10 CON / 22 REJ)** com timestamps
**Custo:** $0 (CPU/GPU local) · **Objetivo:** validação out-of-sample antes de produtizar (Fase 1 do plano)

## Por que esta campanha existe

A Camp 26 (31/05) mediu o filtro DINOv2 em cam_10 com **5-fold CV random**: acc 95,2%, spec 100%,
AUC 0,947 — o melhor resultado de FP-reduction do projeto. Mas o usuário pediu, com razão, um
**teste offline com TODOS os FP e TP** antes de tocar no worker. Esta campanha:
1. amplia o dataset de 27→**32** eventos (5 REJ novos desde 31/05),
2. salva timestamps,
3. adiciona um **holdout temporal** (treina passado → testa futuro) que a Camp 26 não tinha.

## Achado nº 1 — confound classe×tempo

Os rótulos estão **quase separados no tempo**:

| Classe | Janela | n |
|---|---|---|
| CON (TP) | 19/05 .. 28/05 | 10 |
| REJ (FP) | 27/05 .. 01/06 | 22 |

O último CON é de 28/05; tudo depois é REJ. Consequência: **um holdout temporal não consegue medir
recall** (não há CONs futuros) — só especificidade (eliminação de FP em dados futuros).

## Resultado 1 — RepeatedSKF 5×20 (CV random) ✅ reproduz a Camp 26

| acc (média±dp) | AUC (OOF) |
|---|---|
| **95,6% ± 2,1%** | **0,945** |

Curva do filtro (P(CON) < t → REJ):

| t | FP elim | TP perdido | recall | spec | acc |
|---|---|---|---|---|---|
| 0.2 | 21/22 | 1/10 | 90% | 95% | 94% |
| **0.4–0.8** | **22/22** | **1/10** | **90%** | **100%** | **97%** |
| 0.9 | 22/22 | 2/10 | 80% | 100% | 94% |

Único TP perdido: `8bfe0a1f` (OOF p=0,009) — **o mesmo caso difícil da Camp 26** (descarte real que
não muda a aparência da pile-zone). Recall-teto ~90%. **Platô agora em t=0,4–0,5** (domina o t=0,2 da
Camp 26: mesmo 1 TP de custo, +5pp spec).

## Resultado 2 — Holdout TEMPORAL ⚠️ expõe drift

Treina ≤28/05 (10 CON, 5 REJ), testa >28/05 (0 CON, 17 REJ futuros):

| t | FP_elim (futuro) | spec out-of-sample |
|---|---|---|
| 0.2 | 3/17 | **18%** |
| 0.3 | 6/17 | 35% |
| 0.5 | 9/17 | 53% |

Corte na mediana temporal (treino 10C/6R, teste 16 REJ): t=0,2 → 31%, t=0,5 → 62%.

➡️ Out-of-sample em FPs **genuinamente futuros**, o filtro no t=0,2 da Camp 26 pega só **18–31%** dos
FPs — muito longe dos 95–100% que o CV random sugere. **O CV random é otimista** (vê eventos
temporalmente vizinhos no treino).

## Resultado 2b — Diagnóstico: drift real vs falta de REJ no treino

Split **random** com a MESMA composição do treino temporal (10 CON + 5 REJ), 100 sorteios:

| t | FP_elim random-starved | FP_elim temporal |
|---|---|---|
| 0.2 | **67% ± 12%** | 18–31% |
| 0.5 | 82% ± 12% | 53–62% |

➡️ O modelo random com a mesma escassez de REJ elimina **67%** dos FPs; o temporal só **18%**.
A queda **não é só falta de exemplos REJ — há drift temporal REAL** (~49pp de gap em t=0,2). Os FPs de
29/05–01/06 são visualmente diferentes, no espaço de embedding da pile-zone, dos FPs de 27–28/05.

## Veredito (Fase 1)

- **In-distribution: forte e robusto.** RepeatedSKF 95,6%±2,1%, AUC 0,945, platô estável, 1 TP-teto.
  Confirma e amplia a Camp 26 com n=32. A pile-zone de Imbiribeira É linearmente separável por DINOv2.
- **Forward (out-of-sample temporal): NÃO atinge o gate.** O critério do plano era spec ≈100% e ≤1 TP
  perdido *fora-de-amostra*. Um modelo **estático** treinado hoje pega só ~18–31% dos FPs da semana
  seguinte em t=0,2. **Há drift temporal confirmado** (diagnóstico 2b), não curável só com volume.
- **Implicação:** **não deployar enforce com modelo estático.** O caminho viável é
  **shadow + retreino periódico**: shadow coleta rótulos forward não-confundidos, retreina semanal,
  mede spec/recall forward reais. Subir o threshold operacional para **t≈0,4–0,5** (domina o 0,2).
- O teste offline com tudo **fez seu papel**: revelou um drift que o 5-fold CV da Camp 26 mascarava.

## Próximos passos sugeridos

1. **Shadow mode** no worker (Fase 2, sem enforce): logar `p_con` por evento cam_10 confirmado,
   acumular vs rótulo do operador → medir forward real e a cadência de drift.
2. **Retreino periódico** (semanal) com janela recente de rótulos; reavaliar enforce quando o forward
   spec estabilizar ≥ alvo com ≤1 TP perdido.
3. Reconsiderar peso relativo vs **track de prompt** (Fase 3) dado o drift — prompt não sofre drift de
   modelo, mas tem o risco de recall da Camp 21.

## Arquivos

- `scripts/extract_embeddings_cam10.py` — extração (rodou em `saira-yolo-worker-prod`, read-only)
- `scripts/eval_backtest.py` — RepeatedSKF + holdout temporal + diagnóstico 2b
- `results/embeddings_cam10.npz` — X(32,384), y, ids, ts, bbox
- `results/eval_output.txt` — saída completa
