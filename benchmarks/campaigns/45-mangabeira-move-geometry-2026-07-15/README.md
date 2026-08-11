# Campanha 45 — Mangabeira pós-mudança de posição: geometria + BGSUB + structural (2026-07-15)

## Hipótese

Com o polígono redesenhado para a visão nova (câmera movida em 09/07, agora distante do ponto de descarte), o BGSUB enforce + structural-delta recuperam a taxa de confirmação do operador (9,6% → ≥20%) suprimindo FPs de transeunte/alucinação sem perder nenhum dos 12 confirmados pós-mudança.

## Configuração

| Item | Valor |
|------|-------|
| Gate | `gemini-2.5-flash-lite` V3+B3 (hardcoded esp32_002) — inalterado |
| Detail | `gemini-2.5-flash` V3 (HIGHBAR reativa na Fase 3 com pilecrops) |
| Thinking budget | 1024 (prod, inalterado) |
| Prompt | sem mudança de prompt nesta campanha |
| Dataset | janelas reais de prod pós-mudança (126 rotuladas: 12 CONF + 114 REJ; + TRIG/NEG do audit) |
| Caminho | `tmp/mangabeira_move/` (frames S3 `descartadas`+`ocorrencias` 07-09..07-14 + volume 07-15) |
| Filtro | esp32_002 / camera_id=11, created_at ≥ 2026-07-09 |
| Foco | fp-reduction (geometria: polígono novo + BGSUB recal + structural à distância) |

## Fases

- **Fase 0** — classificação visual cega das 126 detecções (taxonomia FP) + validação do polígono com usuário.
- **Fase 1** — polígono novo no DB + recal BGSUB (`worker.recalibrate_bgsub --device esp32_002 --mix-night`) + `STRUCTURAL_FILTER_MODE=shadow` (recreate worker).
- **Fase 2** — backtest offline: `scripts/build_manifest.py` → `scripts/replay_bgsub.py` (sweep braços × mf × thr + replay sequencial STATIC/ADAPT 6 dias + passe enforce-sim) → `scripts/score_structural.py` (t32/t16 + ROC/veto).
- **Fase 3** — rollout env-only: BGSUB enforce (thr/mf por câmera via DB), `GEMINI_DETAIL_PILECROP_ENABLED=true` (HIGHBAR), structural enforce após ledger shadow limpo ≥3 dias.

Critério duro: **0/12 CONF suprimidas** no operating point escolhido (guarda TRIG como recall proxy).

## Resultados

Pendente.

## Decisão

Pendente.

## Caveats

- 07-09 é dia misto (mudança ocorreu durante o dia) — janelas pré-mudança excluídas das métricas headline; braço `fresh` avalia só ≥ 07-10 03h (baseline 07-10 00-03h, sem vazamento).
- 12 CONF é amostra fina — guarda TRIG + shadow ao vivo com polígono novo entre Fase 1 e 3 complementam.
- FPs catador/limpeza sobrevivem a BGSUB+structural por construção (persistem E mudam a pilha) — alavanca deles é o detail HIGHBAR (Fase 3), medir residual no monitoramento.
