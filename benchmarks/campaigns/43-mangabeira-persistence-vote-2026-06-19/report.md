# Camp 43 — Persistence-by-vote vs first-vs-last + diagnóstico estratificado por subtype

**Data:** 2026-06-19 · **Câmera:** Mangabeira (esp32_002 / cam_11) · **Tipo:** CV offline ($0)
**Dataset:** 243 eventos (72 TP/real_deposit + 171 FP: 110 passante_parado, 36 revira_explicit, 25 revira_mexe), `struct_scores.csv` Camp 42 + frames Camp 42.

> ❌ **FAIL (Proposta #1 refutada)** — persistência-por-voto é PIOR que o first-vs-last deployado em todo eixo.
> ✅ **Diagnóstico (Proposta #2) entregou o achado de maior valor:** o structural resolve **passante** mas é **CEGO pro revira**.

## Hipótese

P#1: votar a persistência tile-a-tile sobre a 2ª metade dos frames (em vez de só first-vs-last) cortaria o FP residual de "pessoa parada no último frame" sem perder recall.
P#2: split temporal estratificado por subtype revelaria qual sub-causa o structural deployado corta.

## Método

- Sinal deployado: `census_ntiles_t32` first-vs-last (frame[0] vs frame[-1]), polígono esp32_002 `[[461,154],[704,66],[939,299],[617,416]]`, HAM_THR=3, tile=32, frac>0.50 (idêntico Camp 41/42, reusa `census.py`).
- Sinal novo `persist_pXX`: baseline=frame[0]; tile "persistente" se census-changed vs baseline em ≥XX% da 2ª metade dos frames; score = nº tiles persistentes (P∈{50,70,90}).
- Lógica de detecção (= produção): suprime quando score < T. recall = P(score≥T | TP); fp_supp = P(score<T | FP).
- Split TEMPORAL por datetime (train ≤ mediana 2026-06-07 → test mais novo), operating point recall_train ≥ 95%.

## Resultados

**FP-supp @ recall≥95% (split temporal):**

| sinal | T | rec_test | fpsupp_test | gap tr→te | passante | revira_expl | revira_mexe |
|---|---|---|---|---|---|---|---|
| **census_ntiles_t32** (deployed) | 1 | 0,962 | **0,347** | 0,166 | **0,528** | 0,138 | 0,077 |
| persist_p50 | 0 | 1,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 |
| persist_p70 | 0 | 1,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 |
| persist_p90 | 0 | 1,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 |

**AUC por subtype (sinal como classificador TP-vs-FP; 0,5 = acaso):**

| sinal | passante_parado | revira_explicit | revira_mexe |
|---|---|---|---|
| census_ntiles_t32 | **0,885** | 0,525 | 0,634 |
| census_ntiles_t16 | 0,875 | 0,544 | 0,645 |
| g_ncc | 0,821 | 0,527 | 0,606 |
| persist_p70 | 0,835 | 0,492 | 0,597 |

- Persistência: AUC global 0,728 < 0,773 do first-vs-last. **17% dos TP têm persist_p70=0** (sacola minúscula não produz tile persistente no census) → força T=0 → suprime nada. Refutada.
- **Estrutura (qualquer variante) é CEGA pro revira_explicit (~0,52 = acaso)** e fraca no revira_mexe (~0,60-0,65). Forte só no passante (~0,82-0,89).

## Decisão

1. **NÃO seguir com persistência-por-voto nem refinar o structural pra revira.** Estrutura não separa catador de depositante — ambos reestruturam a pilha. Teto provado em N=243 com holdout temporal.
2. **Deployar o enforce do structural deployado** segue valendo: é o **matador de passante** (AUC 0,885; corta ~53% recall-safe), o maior balde de FP (110/171). Esta campanha re-valida.
3. **Revira (61 ev) é o muro residual** e exige sinal NÃO-estrutural de ADICIONAR vs REMOVER/MEXER: object/hand-flow (entra carregando vs sai carregando) OU rotear revira pra banda de abstenção/DEFER humano. Pose-gate-de-passante (Proposta #3) ficou REDUNDANTE — o structural já resolve passante.

## Caveats

- struct_scores rotulado parte por `comment` (humano) parte por `vision_2vote` (Sonnet) — revira_explicit/mexe vêm muito de visão; AUC ~0,5 é robusto mas a fronteira revira/TP pode ter ruído de rótulo.
- recall medido como veto sobre eventos já-CON (recall condicional), não recall ponta-a-ponta.
- 72 TP → ~36/split; operating point recall≥95% tolera ~1-2 TP. AUC é a métrica mais estável aqui.
