# Camp 42 — Agent-3 FP-screener Mangabeira: Gemini 2.5 Flash vs Claude Haiku 4.5

**Data:** 2026-06-19 · **Câmera:** Mangabeira (esp32_002 / cam_11) · **Tipo:** model-selection

## Hipótese

Um **terceiro agente (Agent-3)**, rodando *depois* do Agent-2 confirmar um descarte,
consegue **vetar falsos positivos de "revira/mexe no lixo"** (catador + passante) fazendo
a comparação **antes/depois** da pilha — **sem matar descartes reais (recall guard)**.
Comparamos dois modelos como screener: **Gemini 2.5 Flash** (modelo do Agent-2 hoje) vs
**Claude Haiku 4.5 via Amazon Bedrock** (prompt afinado pelo Deep Research DR#1), contra
um **baseline sem screener** (= produção hoje, tudo passa).

## Dataset (`eval_manifest.csv`, 243 eventos)

Eventos esp32_002 **confirmados-pelo-Agent-2** (chegaram à plataforma) + rótulo:

| gold | subtype | N | fonte |
|------|---------|---|-------|
| keep | real_deposit (CONFIRMADO) | 72 | comentário humano |
| kill | revira_explicit | 36 | comentário humano (catador/mexe/revira) |
| kill | revira_mexe | 25 | visão 2-votos |
| kill | passante_parado | 110 | 50 comentário + 60 visão |
| — | excluídos (13 uncertain + 4 contested_deposit) | 17 | — |

Alvo primário do veto = **revira (61)**; secundário = **passante (110)**. Guarda de recall = **TP (72)**.
Fonte: corpus do Camp 40 (`largeN/`) + passada de visão (workflow 2-votos, 89/102 concordância).
Dataset persistido em `data/datasets/official/cam_mangabeira/` (campo `fp_subtype`, sidecar `manifest_revira.csv`).

## Contrato do screener

Input por evento: BEFORE (1º frame) + 2 mids + AFTER (último) + **pile-crop hi-res** (bbox
`[480,60,920,340]`, 2×) do before e do after. Output JSON: `is_real_new_disposal` (bool),
`pile_delta`, `actor_behavior`, `confidence_0_100`, `reason`. **Decisão: `is_real_new_disposal=false` → KILL (veta FP).**

- **Gemini arm:** `gemini-2.5-flash`, `response_mime_type=json`, thinking=0, frames intercalados com rótulo (DR#1 técnica 1).
- **Haiku arm (DR#1-tuned):** `us.anthropic.claude-haiku-4-5`, system persona-forense + `<rules>` (recall guard >15%), frames XML `<frame>`, `output_config` json_schema (fallback prompted), `thinking budget=1024`, `max_tokens=2048`, sem temperature/prefill.

## Como rodar

```bash
export GEMINI_TEST_API_KEY=$(grep '^GEMINI_TEST_API_KEY=' services/.env.benchmark | cut -d= -f2-)
aws sso login --profile codex-ops   # para o arm Haiku (Bedrock us-east-1)
C=benchmarks/campaigns/42-mangabeira-agent3-fp-screen-2026-06-19
python $C/scripts/run_screener.py --provider baseline --manifest $C/eval_manifest.csv --arm baseline --out $C/results/baseline.json
python $C/scripts/run_screener.py --provider gemini   --manifest $C/eval_manifest.csv --arm gemini_flash --out $C/results/gemini.json --workers 8
python $C/scripts/run_screener.py --provider bedrock  --manifest $C/eval_manifest.csv --arm haiku --out $C/results/haiku.json --workers 4
python $C/scripts/compute_screener_metrics.py --results $C/results/baseline.json $C/results/gemini.json $C/results/haiku.json
```

## Métrica de decisão (peso recall ×3 da SAIRA)

Maximizar **FP-suppression** sujeito a **TP-preservation ≥ 95%** (perder ≤ ~1 TP). Custo
secundário (Agent-3 só roda em eventos já confirmados). Ver `report.md` para resultados.
