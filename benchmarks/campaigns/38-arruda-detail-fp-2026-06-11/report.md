# Campaign 38 — Arruda detail prompt A/B para reduzir FP (2026-06-11)

## Hipótese
Um detail prompt específico do cam_14 (V1 + anti-padrões negative-first tirados da
taxonomia de FP da planilha: catador, animal, aproximação-sem-largada, tráfego +
exigência de prova positiva P1/P2) corta os false-confirms (REVIEWREJ) sem perder
CONFIRMADOS.

## Dados
59 detecções reais do cam_14 com **janela exata completa** (37 REJEITADO, 10
CONFIRMADO, 11 INDETERMINADO, 1 COLETA; corpus `tmp/arruda_detail_corpus/`, frames do
S3 + 12 eventos de 06/11 do volume). Paridade prod: `analyze_with_gemini` V1 code path,
flash 2.5, mosaic off, janela cheia. 1 rep + rep extra nos 7 casos decisivos.

## Resultado

| arm | REJ confirma (querer ↓) | CONF confirma (querer ↑) | INDET | COLETA |
|---|---|---|---|---|
| V1 (prod) | 29/37 = 78% | 9/10 | 8/11 | 1/1 |
| **ARRUDA** | **14/37 = 38%** | 8/10* | 4/10 | 1/1 |

*contando ERR como perda (ver abaixo).

- **Corte de FP: −52%** (15 REVIEWREJ a menos chegariam à revisão no período) — muito
  acima da banda de ruído (±3 flips entre reps).
- **Custo de recall (estável em 2 reps): 2 CONFIRMADOS perdidos** —
  `9085ad0e` (30/05, ângulo antigo; rejeita 2×) e `bcb8038c` (04/06, ângulo novo;
  ERR de JSON truncado 3×/3 + rej no rep 2). V1 perde `6328e4e6` em 1 dos 2 reps
  (borderline). Misses majoritariamente disjuntos.
- **Bug de truncação reproduzível no arm ARRUDA**: 2 eventos (`bcb8038c` 80f,
  `6e2e95ce`) estouram o output e falham validação Pydantic 3×/3 — prompt mais longo →
  resposta mais verbosa → EOF. Em prod isso viraria FN silencioso.
- **Variância**: flash-detail NÃO é determinístico como o flash-lite-gate (4/7 casos
  decisivos flipparam entre reps em pelo menos um arm). Conclusões de evento individual
  exigem ≥2 reps; o agregado (Δ15 no cohort REJ) é robusto.
- COLETA real (8657dafd): ambos confirmam — segue sem solução via prompt.

## Decisão
**NÃO adotar como está.** O sinal de FP-cut é forte, mas: (1) perder 2/10 CONFIRMADOS
contraria a missão recall-first; (2) a truncação de JSON é um blocker técnico.

## Próxima iteração (ARRUDA_V2)
1. **Encurtar** o prompt (comprimir APs, remover exigência de citar prova no evidence)
   pra eliminar a truncação.
2. Re-testar com 2 reps fixos; alvo: REJ ≤ 50% E CONF ≥ 9/10.
3. Qualquer adoção via shadow A/B (log-only) — nunca direto.
4. Lembrar: o DINOv2 (quando o cam_14 acumular CONFIRMADOS no polígono novo) ataca o
   mesmo FP sem mexer no detail — os dois levers se somam, não competem.

## 38b — ARRUDA_V2 (encurtado): FAIL
A iteração "encurtar + concisão + prova positiva mais branda" (2 reps, 118 calls):

| | V1 prod | ARRUDA v1 | **ARRUDA_V2** |
|---|---|---|---|
| REJ confirma | 78% | 38% | **64% / 62%** (2 reps) |
| CONF ok | 9/10 | 8/10 | **6/10** (3 ERRs estáveis 2×) |
| ERRs | ~1 | 2 | **11** |

- A cláusula branda ("agente estacionário manuseando material próprio") reabriu o
  buraco do catador → FP-cut evaporou.
- "Seja CONCISO" NÃO resolveu a truncação — ERRs subiram e ficaram determinísticos
  por evento (50c32313, 6328e4e6, bcb8038c EE nos 2 reps) + timeouts.
- Mesma lição das camps 11-16/22 e do SCRATCH2: edição pontual de prompt reembaralha
  o comportamento global. **Parar de iterar detail-prompt por ora.**

## Estado final da frente detail
- ARRUDA v1 = candidato em espera (FP-cut real de 52%, custo de 2/10 CONF + bug de
  truncação que precisa de fix de infra: max_output_tokens / schema mais enxuto).
- Levers de FP do cam_14 em ordem: (1) DINOv2 quando acumular CONF no polígono novo
  (~2-3 semanas), (2) Agent-3 verifier (proto 87,5%), (3) detail ARRUDA v1 após fix
  da truncação — sempre via shadow A/B.

## Custo
~130 calls (38) + 118 calls (38b) flash com janela cheia ≈ **$2.8**.

## Artefatos
`bench_detail.py`, `results_38.json`, `results_38_rep2.json`, `run_38.log`.
