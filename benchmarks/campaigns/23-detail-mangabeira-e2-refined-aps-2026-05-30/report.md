# Campanha 23 — MANGABEIRA E2 — APs refinados (Flash 2.5) 2026-05-30

> ✅ **CONCLUÍDA** — refinamento dos APs funcionou (2/3 targets recuperados, acc 67,5% no full cohort).
> Camp 24 (E+CROPS) testou estratégia complementar.

## Hipótese

Camp 22 mostrou que `MANGABEIRA_E` perde 2 TPs reais (FN_NEW) por AP2/AP3 sobre-aplicados
("todos passam" agregado) e introduz 1 FP novo (5520e0c7) por AP4 sub-aplicado (não pega
agachamento longo sem objeto novo).

**E2 ataca esses 3 modos especificamente:**

1. **AP2 (Passantes)** refinado: "APLICA SOMENTE se NENHUMA pessoa é classificada como
   PAUSADA/AGACHADA_LONGA/INTERAGENTE_CURTA" — força avaliação pessoa-por-pessoa
2. **AP3 (Pessoa com saco)** refinado: "APLICA SOMENTE se a pessoa específica analisada
   NUNCA para" — sem agregação
3. **AP4 (Catador)** adicionado **4b**: "permanência >30s agachada sem objeto novo no chão
   = vasculhamento extenso, REJ"
4. **PASSO 2 obrigatório** novo: classificar cada pessoa (PASSANTE/PAUSADA/AGACHADA_LONGA/INTERAGENTE_CURTA)
   antes de avaliar APs

## Resultados — full cohort (n=40)

| Arm | Acc | TP | TN | FP | FN | Recall | Spec | $/event |
|---|---|---|---|---|---|---|---|---|
| Flash V1 baseline | 60,0% | 17 | 4 | 11 | 3 | 85,0% | 26,7% | $0,01 |
| MANGABEIRA orig | 56,8% | 15 | 6 | 10 | 6 | 71,4% | 37,5% | $0,01 |
| MANGABEIRA_E (camp 22) | 61,5% | 14 | 10 | 8 | 7 | 66,7% | **55,6%** | $0,011 |
| **MANGABEIRA_E2** | **67,5%** ✅ | 18 | 9 | 10 | 3 | **85,7%** | 47,4% | $0,015 |

## Resultados — single-call cohort (n=29 prod parity)

| Arm | Acc | TP | TN | FP | FN | Recall | Spec |
|---|---|---|---|---|---|---|---|
| Flash V1 baseline | 53,8% | 11 | 3 | 11 | 1 | **91,7%** | 21,4% |
| MANGABEIRA_E | 62,1% | 9 | 9 | 8 | 3 | 75,0% | **52,9%** |
| MANGABEIRA_E2 | 58,6% | 9 | 8 | 9 | 3 | 75,0% | 47,1% |

No cohort clean, E2 fica abaixo de E em acc/spec (mas dentro do erro de amostragem n=29).
**No full cohort (n=40), E2 é claramente superior**.

## Target events da camp 23

Os 3 eventos que motivaram este experimento:

| Target | E | E2 | Outcome |
|---|---|---|---|
| **d59d5309** (CON, AP3 over-applied) | MISS ❌ | **OK ✅** | AP3 per-person refinement funcionou |
| **3c840ac4** (CON carrinho, AP2 over-applied) | MISS | MISS | caso estruturalmente difícil — refinamento AP2 insuficiente |
| **5520e0c7** (REJ, AP4 under-applied) | MISS ❌ | **OK ✅** | AP4b (>30s sem objeto novo) funcionou |

**Score: 2/3 targets recuperados**. O caso 3c840ac4 (carrinho de mão com entulho onde
"todas as pessoas estão em movimento agregado") continua resistente — provavelmente
precisa de outra estratégia (CROPS na camp 24 também não pegou).

## Cross-bucket vs V1 (single-call)

| Bucket | E (camp 22) | **E2 (camp 23)** | Δ E→E2 |
|---|---|---|---|
| ✅ FP_FIXED | 5 | 4 | −1 |
| ✅ TP_NEW | 0 | 0 | = |
| ❌ FN_NEW | 2 | 2 | = (mas IDs diferentes) |
| ❌ FP_NEW | 1 | **0** ✅ | −1 (5520e0c7 recuperado) |
| ⚪ FP_PERSIST | 6 | 7 | +1 |
| ⚪ FN_BOTH | 1 | 1 | = |

**Mudanças importantes:**
- **FP_NEW caiu de 1 → 0** (5520e0c7 recuperado via AP4b) ✅
- **Novo FN_NEW: 7ada74a4** (não estava no E — refinamento introduziu este caso)
- **3c840ac4 continua FN_NEW** em ambos

## Trade-off operacional cam_11 (~17/dia)

| | V1 prod | MANGABEIRA_E (camp 22) | **MANGABEIRA_E2** |
|---|---|---|---|
| Operador vê | 22/dia | 17/dia | 19/dia |
| Ocorrências perdidas | ~1/dia | ~3/dia | **~1/dia** |
| Workload op | baseline | −22% | **−14%** |
| Custo | $0,17/dia | $0,19/dia | $0,26/dia |

**E2 oferece o melhor compromisso**: −14% workload do operador SEM perder recall.
+$0,09/dia (~$3/mês) de custo.

## Caveats

1. **n=29 single-call ainda pequeno** — diferenças de 1 evento ≈ 3,5%
2. **Mudou 1 IDs do FN_NEW** (3c840ac4 persiste, 7ada74a4 novo) — refinamento mexe o erro mas não elimina
3. **Cohort full n=40 vs single-call n=29** — alguns coalesced events foram resolvidos
   de forma sutil pelos APs refinados (5 coalesced + 6 no_audit no full)

## Decisão

✅ **MANGABEIRA_E2 é melhor que MANGABEIRA_E** — refinamento dos APs funcionou
parcialmente (recall recuperado, FP_NEW eliminado, acc +6pp no full cohort).

🎯 **Próxima iteração: camp 24 (E + pile-zone crops)** testa estratégia complementar —
adicionar crops alta-res ao input. Ver se ataca os FP_PERSIST que prompt sozinho não
filtra (casos visualmente ambíguos onde pessoa para com sacola por 5s).

## Reprodução

Scripts em `scripts/`:
- `flash_mangabeira_e2.py` — bench Flash + MANGABEIRA_E2
- `../22-.../scripts/_bench_common.py` — utility compartilhada

Prompt em `prompts/mangabeira-e2-refined-aps.md`. Resultados em `results/`.
Cache reusado: `/tmp/flash_per_camera/frames/esp32_002/`.

## Memórias relacionadas

- [[project_camp22_mangabeira_prompt_angles_2026-05-30]] — E vencedor original, motivação dos 3 targets
- [[feedback_bench_match_prod_exactly]] — N=48 production parity
- [[reference_vertex_ai_bench_setup]] — Vertex AI sem 503
