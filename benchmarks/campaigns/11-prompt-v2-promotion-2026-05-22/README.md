# Campanha 11 — Promoção do prompt V2

A/B controlado comparando o prompt V1 atual em produção contra o prompt V2 (com
fix carroça aplicado em 2026-05-22) no dataset oficial v1.

**Driver:** [docs/prompt_dataset_mismatch_20260522.md](../../../docs/prompt_dataset_mismatch_20260522.md)
identificou 3 mismatches estruturais do V1 com os descartes reais (pedestres, carroceiros,
uniforme). V2 já cobre todos eles, mas estava dormido por padrão e tinha bug em carroça
— corrigido nesta campanha.

**PASS criteria** (definidos em [run-config.yaml](run-config.yaml)):

| Critério | Limite | Razão |
|---|---|---|
| TP recall absoluto (B) | ≥ 25.0% | V1 baseline na camp 08 foi 15% |
| FP rate (B) | ≤ 43.8% | V1 baseline na camp 09 foi 38.8% (+5pp tolerância) |
| Δ recall (B-A) | ≥ 10pp | Garantir que a melhora é estatisticamente relevante |
| Golden cases | 3/3 acertados | Casos específicos do dataset que motivaram o V2 |

Todos os 4 devem passar → PR para `develop`. Qualquer falha → follow-up doc.

## Como rodar

Smoke test (~30 s, 1 TP + 1 FP + 1 baseline por arm):

```powershell
python bench_prompt_v2_promotion.py --smoke-test
```

Run completo (~1-2h, 174 janelas × 2 arms):

```powershell
python bench_prompt_v2_promotion.py --arms A_current,B_v2_patched
python compute_metrics.py
```

Aplicar só 1 arm para reusar resultados antigos:

```powershell
python bench_prompt_v2_promotion.py --arms B_v2_patched
```

## Resultado

Veja [report.md](report.md) após `compute_metrics.py` rodar.
