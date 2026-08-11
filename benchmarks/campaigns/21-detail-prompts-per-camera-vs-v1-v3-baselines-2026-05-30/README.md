# Campanha 21 — detail prompts per-camera vs V1/V3 baselines (2026-05-30)

**Hipótese**: Per-camera detail prompts (Imbiribeira/Mangabeira) com vocabulario de operador derivado do spreadsheet bate >=70% acc no Flash V1 (vs 57.7% baseline) sem perder >5pp de recall

**Tipo**: `model-selection` | **Foco**: model-selection

Esta campanha foi inicializada pela skill `saira-benchmark` em 2026-05-30.
Para detalhes completos (modelos, métricas, decisão), ver [report.md](report.md).

## Como reproduzir

```powershell
cd c:\saira
python benchmarks\scripts\rebench_run.py `
  --campaign "benchmarks\campaigns\21-detail-prompts-per-camera-vs-v1-v3-baselines-2026-05-30\" `
  # … argumentos específicos do runner (ver SKILL.md Fase 2)
```

## Artefatos esperados nesta pasta

- `report.md` — relatório final (preenchido por `compute_metrics.py`)
- `run-config.yaml` — configuração desta campanha (filtros, critérios)
- `results-<variant>.json` — saída crua do runner (1+ arquivo)
- `run.log` — stdout+stderr da execução
- `.env.benchmark` — env vars usadas (GEMINI_TEST_API_KEY, overrides do tipo)
