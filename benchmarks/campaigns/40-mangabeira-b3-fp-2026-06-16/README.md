# Campanha 40 — Redução de FP B3 no Mangabeira (esp32_002 / cam_11)

**Pergunta:** algum sinal barato separa os FP B3 (transeunte/trânsito) dos descartes reais
em Mangabeira, dado que o prompt deployado confirma por comportamento (descartes minúsculos,
muitas vezes invisíveis)? 3 alavancas testadas, piso de recall ≥ 11/13.

**Resposta (ver `report.md`):** o muro tiny-bag vale só para foreground **bruto** (CV não
separa). Sinais **semânticos** cortam metade-a-80% dos B3 mantendo recall:
- **V1 (prompt)** — anti-padrão duro de passante crop-grounded: **50% B3 a −1 TP**, sem
  modelo, sem drift. 1ª variante de prompt que funciona.
- **DINOv2 veto** — eval AUC 0,89, **55% B3 recall-safe**, mas drift temporal (holdout 0,64)
  → shadow + retreino.
- **V1 + DINOv2 = 80%** (complementares).

## Achado de método (ler antes)

A camp 24 não tem previsões E+CROPS para nenhum FP oficial (só 11/13 TP) → o baseline B3 foi
re-rodado localmente. Frames oficiais (mediana 12–24) < 48 de prod → números não transferem
1:1; comparações são internas. Validar em **shadow A/B de prod** antes de enforce.

## Como reproduzir

```
python scripts/build_eval_set.py        # split 20 B3 / 28 B1B2 (assert)
python scripts/phase_a_cv_signals.py    # CV: persistence/permanence/peak (offline)
python scripts/phase_b_dinov2.py        # DINOv2 retreino offline + holdout temporal
python scripts/phase_c_variant_local.py # baseline E+CROPS + V1 + V2 (bench Gemini ~$1)
python scripts/phase_d_postfilter.py    # Pareto + bootstrap
```

Reusa `tools/spike_bgsub_filter.py`, harness da camp 24, `retrain_dinov2.py`/
`detector_dinov2.py`, `_prompts_v3.py`. Bench key only (`gen-lang-client-0841492152`).
