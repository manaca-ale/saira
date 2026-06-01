# Camp 28 — Detail prompt cam_10 Imbiribeira: V1 vs V1_IMBIRIBEIRA (reduzir FP)

> ❌ **FAIL** — o candidato AUMENTOU FP (15 vs 13 no cohort comum) em vez de reduzir.
> A cláusula de proteção de recall ("na dúvida, confirme") dominou o discriminador de direção.

**Data:** 2026-06-01 · **Modelo:** gemini-2.5-flash, temp 0, N_FRAMES=48 (paridade prod)
**Cohort:** 32 eventos DB-rotulados de cam_10 (esp32_001), mesmo do backtest DINOv2 Camp 27
**Custo:** ~$0,67 (chave de teste `gen-lang-client-0841492152`) · roda no worker prod

## Hipótese

`DETAIL_PROMPT_V1_IMBIRIBEIRA` (V1 atual + discriminador de direção EMLURB/coleta +
proteção de recall veicular) reduz FP em cam_10 sem perder recall vs V1 baseline.
Braço A = V1 de prod; braço B = A + bloco inserido (diff controlado, schema idêntico).

## Resultados (29 eventos comuns aos dois braços)

| Braço | TP | FN | FP | TN | recall | fp_rate | acc |
|---|---|---|---|---|---|---|---|
| **V1 (baseline)** | 7 | 3 | 13 | 6 | 70% | 68% | 45% |
| **V1_IMBIRIBEIRA** | 8 | 2 | **15** | 4 | 80% | **79%** | 41% |

(2 eventos só no braço A, 1 só no B — skips de resolução de frame; comparação feita na interseção.)

## O que mudou (11 flips A→B)

| Efeito | Eventos | Saldo |
|---|---|---|
| FP consertado (CON→REJ, gt=REJ) | 01948367, 6a0b10ec, 9e90cc61 | **+3 bom** |
| FP NOVO (REJ→CON, gt=REJ) | 0a24b0c6, 2cf37e71, 6e7d7409, 85634170, cdf19b66 | **−5 ruim** |
| TP recuperado (REJ→CON, gt=CON) | 8bfe0a1f, a447ff19 | +2 bom |
| TP perdido (CON→REJ, gt=CON) | b0a0e12e | −1 ruim |

**Saldo líquido: +1 TP, +2 FP.** O bloco fez o modelo confirmar MAIS no geral (mais TP e mais FP).

## Por que falhou

O bloco candidato misturava dois efeitos opostos:
1. **Discriminador de direção EMLURB/coleta** (deveria reduzir FP) — consertou só 3 FPs.
2. **Proteção de recall** ("se ambíguo + pessoa estacionária → confirme; na dúvida, confirme") —
   empurrou o modelo a confirmar 5 REJs ambíguos como descarte.

O efeito (2) dominou. O modelo **confabula a direção do material** em cenas com pessoa próxima
da pilha (coleta vira "descarte ambíguo" → confirma). Mais texto de prompt não desfaz a
confabulação — **reproduz exatamente o achado dos camps 11-16 e 21**.

## Decisão

**Não deployar.** Prompt não é a alavanca de FP em Imbiribeira — o modelo confabula direção/
postura independentemente das instruções. Manter V1 (`current`) em prod. **O sinal visual
(DINOv2, Track A, já em shadow desde 2026-06-01) é o caminho real de redução de FP** — ele
opera no espaço de embedding da pile-zone, não na interpretação semântica do VLM.

Variação futura possível (baixa prioridade): bloco SÓ com as exclusões de coleta, SEM a cláusula
de proteção de recall — mas arrisca a regressão de recall da Camp 21. Não vale o risco enquanto
o DINOv2 shadow estiver maturando.

## Caveats

- Cohort pequeno (29 comuns, 10 TP) — recall com denominador fino; deltas de 1-2 eventos são ruído.
- Cohort DB-rotulado (não o oficial de 55) — escolhido p/ consistência com o backtest DINOv2.
- V1 baseline aqui (70% recall) diverge do "83%" da Camp 21 (cohort/seed diferentes); o que vale
  é o delta A↔B nos MESMOS eventos.

## Arquivos

- `scripts/run_ab_cam10.py` — runner 2 braços (rodou no worker)
- `scripts/_bench_common.py`, `scripts/_baseline_prompts.py` — reusados da Camp 21
- `prompts/detail-V1.md`, `prompts/detail-V1_IMBIRIBEIRA.md`, `prompts/_inserted_block.md`
- `results/results-V1.json`, `results/results-V1_IMBIRIBEIRA.json`
- `run-config.yaml`
