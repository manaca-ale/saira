# Campanha 16 — audit v2 relaxed Detail (2026-05-23)

**Hipótese**: Relaxar forcing do AUDIT (camp 15 FAIL) recupera TPs sem reverter ganho contra FPs

**Tipo**: `prompt-ab` | **Foco**: fp-reduction (prompt tuning)

Esta campanha foi inicializada pela skill `saira-benchmark` em 2026-05-23.
Para detalhes completos (modelos, métricas, decisão), ver [report.md](report.md).

## Como reproduzir

```powershell
cd c:\saira
python benchmarks\scripts\benchmark_prompt_v2_ab.py `
  --campaign "benchmarks\campaigns\16-audit-v2-relaxed-detail-2026-05-23\" `
  # … argumentos específicos do runner (ver SKILL.md Fase 2)
```

## Artefatos esperados nesta pasta

- `report.md` — relatório final (preenchido por `compute_metrics.py`)
- `run-config.yaml` — configuração desta campanha (filtros, critérios)
- `results-<variant>.json` — saída crua do runner (1+ arquivo)
- `run.log` — stdout+stderr da execução
- `.env.benchmark` — env vars usadas (GEMINI_TEST_API_KEY, overrides do tipo)
