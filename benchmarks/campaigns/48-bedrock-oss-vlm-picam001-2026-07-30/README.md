# Camp 48 — VLMs open-weight no Bedrock vs Gemini-2.5 (cam_picam001)

O `gemini-2.5-flash-lite` (gate) e o `gemini-2.5-flash` (detail) de produção **são
desligados em 16/out/2026**. O [Camp 47](../47-picam001-model-migration-2026-07-22/report.md)
mostrou que o caminho oficial (Gemini-3) só **empata** com prod e mantém o lock-in.

Esta campanha testa a terceira via: **VLM de peso aberto no Amazon Bedrock**.
Aprovado = recall/detecção ≥85%, custo ≤ o do caminho Gemini-3, pesos publicados.

## Pré-requisitos

```bash
# 1. AWS — perfil SSO codex-ops (conta 818680680175)
aws sts get-caller-identity --profile codex-ops     # deve responder sem erro
# se expirou:  aws sso login --profile codex-ops

# 2. Gemini — só para o braço de CONTROLE (chave AI Studio da conta Saira - Testes)
export GEMINI_TEST_API_KEY=...        # NUNCA a chave de produção

# 3. Dataset — já local, nada a baixar (122 eventos / 4.218 JPGs / 928 MiB em D:)
```

## Fase 0 — validação visual (obrigatória, sem custo de API)

Exporta, por evento, os frames que vão ao **gate** e ao **detail**, usando o mesmo
código de janela do runner (`subsample_frames(48)` → `fit_frames_to_payload(8 MB)`).

```bash
python scripts/export_review.py --limit 2      # smoke
python scripts/export_review.py --limit 2 --verify
python scripts/export_review.py               # todos os 122
```

Saída em `data/datasets/official/cam_picam001/_review_camp48/`:

| Caminho | Para quê |
|---|---|
| `INDEX.csv` | **preencher `VALID` (`y`/`n`) e `NOTE`** — colunas 1 e 2 |
| `por_evento/<cat>/<id>/contact_detail.jpg` | grade da janela; frames do gate em **vermelho** |
| `por_evento/<cat>/<id>/contact_gate.jpg` | os 5 frames do gate em linha, rotulados |
| `por_evento/<cat>/<id>/gate/`, `detail/` | frames em resolução cheia (hardlink, ~0 B) |
| `por_evento/<cat>/<id>/info.json` | `n_raw` → `n_after_subsample` → `n_window`, bytes, label |
| `por_estagio/{gate,detail}/` | visão plana para varrer as 122 janelas rápido |

Comece pelas `contact_detail.jpg` — 122 eventos × até 48 frames são 4.218 imagens.

**Olhe `n_dropped_payload`**: o teto de 8 MB corta bem mais que a contagem de 48.
Em `tp/evt-20260715_165230`, 85 frames brutos → 48 (contagem) → **26** (payload):
prod vê 30% do evento. Se a janela não contém o depósito, o evento não serve para
medir modelo nenhum — marque `VALID=n`.

Reexecutar preserva os veredictos já preenchidos no `INDEX.csv`.

## Fases pagas

```bash
python scripts/screen_bedrock.py                       # Fase A — ~US$ 4-6
python scripts/bench_bedrock.py --arms current --limit 3 --dry-run
python scripts/bench_bedrock.py --arms current          # controle + auditoria de paridade
python scripts/fidelity_check.py                       # BLOQUEIA a Fase B se falhar
python scripts/bench_bedrock.py --arms <finalistas> --workers 3   # Fase B — ~US$ 25-50
python scripts/agg_all.py
```

A **auditoria de paridade** compara a confiança do gate no braço de controle com
`label.json.agent1_confidence` (valor real de prod). O Camp 47 bateu 15/16 TPs em 95.
Se este fork não reproduzir, o harness quebrou o input — parar antes de gastar.

## Achado do probe (2026-07-30, 40 chamadas reais)

Cinco candidatos aceitam a **janela de 48 frames inteira** e acertaram em qual quadro
o objeto aparece: `gemma-3-27b`, `gemma-3-12b`, `qwen3-vl-235b`,
`nemotron-nano-12b-v2`, `kimi-k2.5`, `magistral-small`. Ou seja, **paridade com prod é
possível** — não é preciso sub-amostrar.

**Llama 4 (Scout e Maverick) está eliminado: teto de 3 imagens**, não roda nem o gate
de 5 frames. `palmyra-vision-7b` para em 5 (só gate ou mosaico). `pixtral-large` não
tem teto de validação mas sofre throttle agressivo e custa ~10× os pares.

Ver `run-config.yaml § image_caps` para a tabela completa.
