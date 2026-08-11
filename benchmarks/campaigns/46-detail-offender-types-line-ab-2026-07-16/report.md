# Camp 46 — Detail `offender_types` line A/B (safety gate)

- Data: 2026-07-16 11:23
- Model: gemini-2.5-flash · Vertex `saira-tests-260520` (conta Saira-Testes)
- Braço B = linha PRESENTE (código atual) · Braço A = linha REMOVIDA (runtime)
- Mangabeira (esp32_002): `mangabeira_with_pilecrops` + pile_crops (polígono `current`).
- Imbiribeira (esp32_001): `current`/V1 `SYSTEM_PROMPT`.
- `prior_window_context=None` nos dois braços (idêntico; não afeta o delta A vs B).

## 1. infraction_confirmed agreement (SAFETY GATE)

- Eventos com A e B OK: **51** (erros: 3)
- A == B: **42/51 = 82.4%**
- Disagreements: **9**

| event_id | camera | gt | A | B |
|---|---|---|---|---|
| 01d10d17 | cam_mangabeira | fp | False | True |
| 02c019f4 | cam_mangabeira | fp | True | False |
| 0444830d | cam_imbiribeira | fp | False | True |
| 08533ffb | cam_mangabeira | fp | False | True |
| 0a24b0c6 | cam_imbiribeira | fp | False | True |
| 0bb40faf | cam_imbiribeira | tp | True | False |
| 0f90ca65 | cam_mangabeira | fp | True | False |
| 315734c1 | cam_mangabeira | tp | False | True |
| 3c840ac4 | cam_mangabeira | tp | False | True |

## 2. TP recall / FP rate por variante (deve ser ~idêntico)

| variante | TP recall | FP rate (confirm em FP) |
|---|---|---|
| A (no-line) | 20/26 = 76.9% | 16/25 = 64.0% |
| B (with-line) | 21/26 = 80.8% | 18/25 = 72.0% |

## 3. offender_types distribution (DEVE mudar — mostra que a linha funciona)

- Eventos com offender_types diferente (set-wise) A vs B: **18/51**

| tipo | A (no-line) | B (with-line) |
|---|---|---|
| Caminhao | 0 | 3 |
| Carro | 0 | 5 |
| Carroca | 0 | 1 |
| Moto | 0 | 1 |
| Pessoa | 38 | 43 |
| **total menções** | 38 | 53 |

## 4. Custo e volume

- Chamadas OK: 105 (51 eventos × 2 braços)
- Custo total: **$1.0961** (conta Saira-Testes)

## VEREDITO: NOT SAFE (9 disagreements)