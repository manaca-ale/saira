# Campanha 18 — v3 vs esp32 recall baseline (2026-05-26)

**Hipótese**: O prompt v3 com recall mode para esp32_002 aumenta o recall em TP sem elevar demais FP e disparos em baseline dia/noite.

**Tipo**: `prompt-ab` | **Foco**: fp-reduction (prompt tuning)

Esta campanha foi inicializada pela skill `saira-benchmark` em 2026-05-26.
Para detalhes completos (modelos, métricas, decisão), ver [report.md](report.md).

## Como reproduzir

```powershell
cd c:\saira
python benchmarks\scripts\benchmark_prompt_v2_ab.py `
  --campaign "benchmarks\campaigns\18-v3-vs-esp32-recall-baseline-2026-05-26\" `
  # … argumentos específicos do runner (ver SKILL.md Fase 2)
```

## Artefatos esperados nesta pasta

- `report.md` — relatório final (preenchido por `compute_metrics.py`)
- `run-config.yaml` — configuração desta campanha (filtros, critérios)
- `results-<variant>.json` — saída crua do runner (1+ arquivo)
- `run.log` — stdout+stderr da execução
- `.env.benchmark` — env vars usadas (GEMINI_TEST_API_KEY, overrides do tipo)
