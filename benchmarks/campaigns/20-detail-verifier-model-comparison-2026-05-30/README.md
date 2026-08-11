# Campanha 20 — detail+verifier model comparison (2026-05-30)

**Hipótese**: Trocar modelo no Agent-2 (detail) ou Agent-3 (verifier) muda o trade-off acuracia/custo; testar Flash, Sonnet, Pro, Pro+few-shot, DINOv2 e tracking heuristics

**Tipo**: `model-selection` | **Foco**: model-selection

Esta campanha foi inicializada pela skill `saira-benchmark` em 2026-05-30.
Para detalhes completos (modelos, métricas, decisão), ver [report.md](report.md).

## Como reproduzir

```powershell
cd c:\saira
python benchmarks\scripts\rebench_run.py `
  --campaign "benchmarks\campaigns\20-detail-verifier-model-comparison-2026-05-30\" `
  # … argumentos específicos do runner (ver SKILL.md Fase 2)
```

## Artefatos esperados nesta pasta

- `report.md` — relatório final (preenchido por `compute_metrics.py`)
- `run-config.yaml` — configuração desta campanha (filtros, critérios)
- `results-<variant>.json` — saída crua do runner (1+ arquivo)
- `run.log` — stdout+stderr da execução
- `.env.benchmark` — env vars usadas (GEMINI_TEST_API_KEY, overrides do tipo)
