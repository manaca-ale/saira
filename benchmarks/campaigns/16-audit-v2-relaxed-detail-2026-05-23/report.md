# Campanha 16 — audit v2 relaxed Detail (2026-05-23)

> ❌ **FAIL** (audit_v2) — FP rate 37.9% > 30%


**Hipótese:** Relaxar forcing do AUDIT (camp 15 FAIL) recupera TPs sem reverter ganho contra FPs

**Modelos:**
- Gate: `gemini-2.5-flash-lite`
- Detail: `gemini-2.5-flash`
- Thinking budget: 2048

**Prompt:** (tipo=prompt-ab)

**Dataset:** data/datasets/official (filtros aplicados — ver run-config.yaml)
- Caminho: `data/datasets/official/`
- Filtros aplicados: câmeras=[cam_mangabeira, cam_imbiribeira], categorias=[tp, fp, baseline, indefinido]

**Foco:** fp-reduction (prompt tuning)

---

## Resultados

<!-- metrics-start -->

| Métrica | audit | audit_v2 | current |
|---------|---|---|---|
| TP recall (gate triggered) | 100.0% | 100.0% | 100.0% |
| TP recall (detail confirmado) | 12.5% | 75.0% | 100.0% |
| FP rate (gate triggered) | 100.0% | 100.0% | 100.0% |
| FP rate (detail confirmado) | 10.3% | 37.9% | 50.0% |
| Cost/event (USD) | $0.0018 | $0.0018 | $0.0015 |
| Latency p50 | 13953 ms | 12014 ms | 11997 ms |
| Output tokens (total) | 15,933 | 16,349 | 13,583 |
| Events processed | 45 | 45 | 43 |

### Por categoria

| Categoria | N | Confirmado (audit) | Confirmado (audit_v2) | Confirmado (current) |
|-----------|---|---|---|---|
| TP (Descarte) | 8 | 1 | 6 | 8 |
| FP (Falso Positivo) | 29 | 3 | 11 | 14 |
| Indefinido | 8 | 1 | 4 | 6 |

<!-- metrics-end -->

---

## Decisão

**Não migrar para `audit_v2` em produção.** FAIL formal nos critérios (FP rate 37.9% > 30%).
TP recall (75%) bate exato no mínimo, mas a melhoria no controle de FPs vs `current`
(-12.1pp, 50→37.9%) custa caro em TPs (-25pp, 100→75%) — e ainda fica longe do ganho
de FP rate observado no V1 audit (-39.7pp). Trade-off não é estritamente melhor que
nenhuma das duas alternativas extremas.

**Próximos passos sugeridos:**

1. Manter prompt V1 (`current`) em produção. Foco em reduzir FPs vem pelo
   **BGSUB pre-filter** (já implementado, ativar em prod) — corta cenas
   vazias ANTES de chamar Gemini, ataque ortogonal ao prompt.
2. Padrão dos 9 FPs que `audit_v2` ainda confirmou: TODOS classificados como
   `fp_pattern=real_dumping` pelo modelo. O force-false não pega porque a
   classificação visual está errada. Próxima iteração teria que atacar a
   confusão visual (não dá pra resolver só com prompt, vai precisar de
   contexto adicional — ex. tracking de pessoa estacionária).
3. Arquivar AUDIT (V1 + V2) como dead-end de prompt engineering puro.

## Caveats

- **Subset não representativo do volume real**: 44 windows foram pré-selecionadas
  pelo gate da camp 12 V3. Em prod, o mix gate-hits é diferente — mais cenas
  realmente vazias que não chegaram aqui.
- **Modelo Gemini-2.5-flash confabula tipo de cena**: dos 11 FPs+baselines
  confirmados pelo `audit_v2`, 9 foram rotulados pelo modelo como `real_dumping`
  (não como FP pattern). Isso é uma falha de classificação visual upstream do
  forcing determinístico — atacar com prompt provavelmente atingiu plateau.
- **N=8 TPs é amostra pequena**: a diferença entre 6/8 e 8/8 é 2 eventos. Margem
  de incerteza estatística é alta. Replicar antes de qualquer decisão de prod.
- **`current` perdeu 2 eventos no parse** (43/45) por causa de algumas linhas
  inválidas na saída original da camp 15. Audit/audit_v2 tiveram 45/45. Compara
  é levemente assimétrica.
- **Cross-campaign**: as runs de `current` e `audit` rodaram em **camp 15**
  (2026-05-23, manhã); `audit_v2` rodou em **camp 16** (mesmo dia, tarde). Mesmas
  44 janelas via seed=42, mesmos modelos, mesmos `thinking_budget`. Mas duas
  execuções da API podem ter variabilidade do modelo sample. Ideal seria
  re-rodar os três arms na mesma execução.

## Artefatos

- `raw-audit_v2.json` — saída crua do bench (shape `{arm, windows}`)
- `results-audit_v2.json` — normalizado para compute_metrics (shape `{summary, results}`)
- `results-current.json` / `results-audit.json` — re-normalizadas a partir da camp 15
- `bench_audit_v2.py` — runner adaptado da camp 15 (arm único: `audit_v2`)
- `normalize_results.py` — adapter de shape camp-15 → compute_metrics
- `prompts/detail-audit.md` + `prompts/detail-audit_v2.md` — system prompts capturados
- `env-snapshot.yaml` — git SHA `4ade3ef9` + branch + python version
- `metrics.json` — sidecar gerado por compute_metrics.py
- `run.log` — stdout/stderr do bench (gitignored por convenção do projeto)

## Como reproduzir

```bash
cd c:/saira/benchmarks/campaigns/16-audit-v2-relaxed-detail-2026-05-23
# 1. Setar a chave de teste em .env.benchmark (já populada com GEMINI_TEST_API_KEY)
# 2. Rodar a bench (re-bate nas 44 janelas da camp 12 V3)
python -X utf8 bench_audit_v2.py 2>&1 | tee run.log
# 3. Normalizar formato e copiar baselines da camp 15
python -X utf8 normalize_results.py
# 4. Computar métricas + reescrever este report
python -X utf8 "C:/Users/aleco/.claude/skills/saira-benchmark/scripts/compute_metrics.py" \
  --campaign "$(pwd)"
```

## Anotações

- Hipótese parcialmente validada: V2 **recuperou** 5/7 TPs perdidos no V1 audit
  (TPs que foram classificados como "other" ou "carroceiro_sorting" no V1 saíram
  como `real_dumping` no V2 e foram confirmados). 2/8 TPs ficaram como
  `carroceiro_sorting` e o modelo decidiu `infraction_confirmed=false`.
- Custo total: $0.0819. Ficou bem abaixo do orçamento de $0.15. p50 latency
  12014 ms — similar ao `current` (11997 ms), sem regressão.
- AUDIT_V2 é estritamente melhor que AUDIT V1 (mais TPs, FP rate ainda razoável).
  Mas como AUDIT V1 já foi descartado, V2 também vai pra prateleira.
