# Camp 36 — Window-strategy latency simulator (2026-06-05)

## Hipótese
Reduzir a latência "descarte real → notificação na plataforma" (hoje ~1–7 min,
dominada por `POLL_INTERVAL=180s` + `GEMINI_CASCADE_WINDOW_SECONDS=240s`) sem
regredir recall/FP, via três levers:

- **#4 — encolher a janela**: `GEMINI_CASCADE_WINDOW_SECONDS` 240→120→90→60 (com
  `MIN/MAX_FRAMES` proporcionais).
- **#3 — janela deslizante (sliding)**: reavaliar a cada `stride` segundos sobre os
  últimos `window` segundos, em vez de janelas fixas não-sobrepostas.
- **POLL_INTERVAL (grátis)**: 180→60→30. Não custa nenhuma chamada Gemini extra.

## Método — simulador de replay (mede 2 eixos no mesmo corpus)
Diferente dos benchmarks anteriores (que medem só qualidade em janelas estáticas de
12 frames), este replaya **timelines completas** (~40–127 frames, cadência ~5s,
cobrindo antes→durante→depois do descarte) e mede:

1. **Qualidade**: recall (a janela confirma o descarte?) + FP (dispara em baseline?).
2. **Latência**: sim-time da PRIMEIRA janela confirmada − `disposal_start` (ground truth).

O simulador reproduz `_collect_time_windows` + o cascade gate→detail (`persist=False`),
com **memoização** das chamadas Gemini (cache por frame-set) pra limitar custo.

### Portão de fidelidade (crítico)
Antes de comparar estratégias, rodar o simulador com os params reais de prod
(window=240, min=12, max=48, poll=180) nos 2 âncoras e reproduzir a latência medida:
- `a5a72209` (Arruda): **3 min 13 s** (disposal 2026-06-04 20:44:49 BRT)
- `c9c2c83e` (Imbiribeira): **59 s** (disposal 2026-06-03 19:32:44 BRT)

## Params reais de prod (verificados 2026-06-05 via saira-prod .env)
| Param | default código | **prod** |
|---|---|---|
| GEMINI_CASCADE_WINDOW_SECONDS | 120 | **240** |
| GEMINI_CASCADE_MIN_FRAMES | 6 | **12** |
| GEMINI_CASCADE_MAX_FRAMES | 12 | **48** |
| POLL_INTERVAL | 10 | **180** |
| GEMINI_AGENT1_THINKING_BUDGET | 2048 | **1024** |
| GEMINI_MODEL | gemini-2.5-flash | gemini-2.5-flash |

## Corpus (Fase 0)
- **Positivos**: 21 detections (status operador CONFIRMADO, exceto âncora `a5a72209`
  PENDENTE) com timeline completa viva no S3. Imbiribeira 5 / Mangabeira 9 / Arruda 7.
- **Negativos**: baselines do dataset oficial (day+night por câmera) + horas extras
  de `sem_ocorrencia` do prod, alvo ~10h.
- **disposal_start**: auto-proposto (CV onset) + confirmado pelo operador via contact sheet.

## Decisões (aprovadas pelo usuário 2026-06-05)
- Rótulo GT: auto-propõe + usuário confirma lote de ~20.
- Corpus: ~20 positivos + ~10h baseline.
- Levers: #3 + #4 + POLL.

## disposal_start (decisão do operador 2026-06-05)
Aceitar proposta CV (estado-final) para os 19 + rótulos manuais dos 2 âncoras.
Justificativa: a incerteza do disposal_start (±5–18 frames em descartes sutis) é um
**offset constante por evento → cancela na comparação A/B entre estratégias** (o
objetivo). Só a latência absoluta sofre ±15s, tolerável para o número-manchete.
Calibração: a5a72209 cvΔ=−25s, c9c2c83e cvΔ=−90s.

## Modelo de latência (decomposição — Fase 1)
`latência = T_dados + T_poll + T_gemini`, medidos separadamente:
- **T_dados** = `ts(F*) − disposal_start`, onde F* = último frame da PRIMEIRA janela que
  confirma (gate→detail positivo). Determinístico por estratégia; é o termo que #3/#4 atacam.
- **T_poll** = atraso até o próximo poll. Fase do poll é arbitrária em prod →
  esperado = `POLL_INTERVAL/2`, pior = `POLL_INTERVAL`. É o termo que o lever POLL ataca.
- **T_gemini** = gate + (detail) ≈ constante (medir p50 das chamadas).

Vantagem: early-stop em F* (não avalia janelas após a 1ª confirmação) + memoização por
frame-set ⇒ poucas chamadas Gemini. T_poll é analítico (não precisa simular o relógio do poll).

## Status — CONCLUÍDA (ver report.md)
- [x] Fase 0: corpus (21 timelines, 1391 frames) + disposal_start (CV+2 âncoras) + baselines
- [x] Fase 1: simulador + **portão de fidelidade PASS** (reproduz F* 20:47:29/195s e 19:33:09/55s exatos)
- [x] Fase 2: matriz 11 estratégias (#4/#3/POLL) + negativos (FP/h limpo em 4h baseline)
- [x] Fase 3: report.md (Pareto latência×FP) + SUMMARY.md (camp 36)

## Resultado (resumo)
- **Latência** dominada pela fase do poll (60–305s/evento). `slide_120_str60` = melhor Pareto
  (p50 70s vs 120s, FP 1.5→2.25/h, reduz FP Mangabeira). `POLL=60` = ponte zero-código (FP dobra).
- **Recall do corpus positivo descartado** (clipes coalescidos + rótulo CV impreciso).
- Custo: ~$12 USD bench (Vertex). Caches em `cache/` (re-run = hit).
