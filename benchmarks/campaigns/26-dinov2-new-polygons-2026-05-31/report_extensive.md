# Camp 26 — Avaliação EXTENSIVA do DINOv2 como filtro de FP (todas as câmeras)

**Data:** 2026-05-31 · **Modelo:** DINOv2 ViT-S/14 (384-d, crop pile-zone polígono novo) + LogReg
**Validação:** RepeatedStratifiedKFold **5×20 = 100 splits** (média±desvio) · OOF probabilities · **$0 (CPU)**

## Enquadramento "filtro" (o correto para produção)

Todo evento em `detections` foi um **CON do pipeline** (Agent-2 disposal=true → virou ocorrência).
O operador depois rotulou CONFIRMADO (TP real) ou REJEITADO (FP real). Logo:

- **SEM DINO** (produção hoje): tudo passa como CON → **recall 100%, specificity 0%**, todos os FPs vazam.
- **COM DINO** (filtro): re-julga cada evento; pode reverter CON→REJ.
  - **FP eliminado** = REJ que o DINO marca REJ (ganho)
  - **TP perdido** = CON que o DINO marca REJ (custo)

`t` = limiar de P(CON): abaixo de `t` o evento vira REJ (filtrado).

## Dataset (todas as câmeras rotuladas no DB)

| Câmera | n | TP (CON) | FP (REJ) |
|---|---|---|---|
| cam_10 Imbiribeira | 27 | 10 | 17 |
| cam_11 Mangabeira | 40 | 21 | 19 |
| cam_14 Arruda | 7 | 4 | 3 |
| **POOLED** | 74 | 35 | 39 |

## Robustez (RepeatedSKF 5×20)

| Câmera | acc (média±dp) | AUC (OOF) |
|---|---|---|
| **cam_10** | **95,2% ± 2,6%** | **0,947** |
| cam_11 | 62,5% ± 5,3% | 0,714 |
| cam_14 | — (n=7, LeaveOneOut) | — |
| POOLED | 71,1% ± 3,6% | 0,782 |

## Curva do filtro — cam_10 Imbiribeira (FP=17, TP=10)

| t | FP elim | TP perdido | recall | spec | acc |
|---|---|---|---|---|---|
| 0.0 (sem DINO) | 0/17 | 0/10 | 100% | 0% | 37% |
| 0.1 | 16/17 | 1/10 | 90% | 94% | 93% |
| **0.2** | **17/17** | **1/10** | **90%** | **100%** | **96%** |
| 0.5 | 17/17 | 1/10 | 90% | 100% | 96% |
| 0.9 | 17/17 | 3/10 | 70% | 100% | 89% |

➡️ **cam_10 é um filtro de FP fortíssimo**: em t=0.2 elimina **TODOS os 17 FPs** ao custo de **1 TP**
(recall 90%, spec 100%, acc 96%). E é estável de t=0.2 a 0.8 (platô) — não depende de um threshold mágico.

## Curva do filtro — cam_11 Mangabeira (FP=19, TP=21)

| t | FP elim | TP perdido | recall | spec | acc |
|---|---|---|---|---|---|
| 0.0 (sem DINO) | 0/19 | 0/21 | 100% | 0% | 52% |
| 0.1 | 6/19 | 2/21 | 90% | 32% | 62% |
| 0.3 | 9/19 | 5/21 | 76% | 47% | 62% |
| 0.5 | 12/19 | 7/21 | 67% | 63% | 65% |
| 0.9 | 18/19 | 15/21 | 29% | 95% | 60% |

➡️ **cam_11 é filtro fraco**: AUC 0,714. A zona de recall alto só remove poucos FPs; filtrar mais
custa TP rápido. Sob o peso recall×3 da SAIRA, só uso bem conservador (t≈0.1: tira 6/19 FPs perdendo 2 TPs).

## Curva do filtro — cam_14 Arruda (FP=3, TP=4, LeaveOneOut)

| t | FP elim | TP perdido | recall | spec |
|---|---|---|---|---|
| 0.3 | 0/3 | 1/4 | 75% | 0% |
| 0.5 | 1/3 | 2/4 | 50% | 33% |

➡️ **n=7 é pequeno demais** (CV impossível, só LeaveOneOut). Sinal ruim, mas **sem poder estatístico** —
inconclusivo. Precisa acumular rótulos (embeddings já extraídos, bbox novo 585,320,874,470).

## Curva do filtro — POOLED (todas, 1 modelo · FP=39, TP=35)

| t | FP elim | TP perdido | recall | spec | acc |
|---|---|---|---|---|---|
| 0.0 (sem DINO) | 0/39 | 0/35 | 100% | 0% | 47% |
| 0.2 | 25/39 | 6/35 | 83% | 64% | 73% |
| 0.4 | 30/39 | 8/35 | 77% | 77% | 77% |
| 0.5 | 30/39 | 10/35 | 71% | 77% | 74% |

## Conclusões

1. **cam_10 (Imbiribeira): vitória clara.** DINOv2 como filtro elimina **100% dos FPs com 1 TP de custo**
   (acc 95% robusto, AUC 0,95, platô estável de threshold). É o melhor resultado de filtro de FP grátis
   que o projeto já produziu. Candidato forte a shadow A/B.
2. **cam_11 (Mangabeira): filtro fraco** (AUC 0,71). Confirma que cam_11 é estruturalmente difícil
   mesmo por embedding — o descarte de sacolinha não muda a aparência da pile-zone o suficiente.
3. **cam_14 (Arruda): inconclusivo** — n=7 sem poder estatístico.
4. **Per-camera >> pooled.** O modelo único (71%) é puxado pra baixo pelo cam_11; treinar por câmera
   é claramente melhor. Não usar um modelo global.

## Caveats (não deployar ainda)

- cam_10 n=27 (só 10 TP): robusto no RepeatedSKF, mas amostra pequena em absoluto. **Validação temporal
  out-of-sample obrigatória** antes de qualquer deploy (treinar no passado, testar no futuro).
- A curva inteira de threshold está publicada → a escolha do ponto de operação é explícita, sem cherry-pick.
- 3 variáveis mudaram vs baseline 29/05 (polígono+crop+modelo) — ganho de cam_11 não atribuído a uma só.
- sklearn não está no worker; deploy exigiria empacotar (numpy puro/onnx) ou treinar offline + servir pesos.
