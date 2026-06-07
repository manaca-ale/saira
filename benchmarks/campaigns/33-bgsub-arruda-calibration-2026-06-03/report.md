# Camp 33 — BGSUB calibration sweep para esp32_005 (Arruda)

**Data:** 2026-06-03
**Hipótese:** recalibrar o BGSUB do esp32_005 (em vez de desligar) — achar operating
point que passa os 4 descartes reais suprimidos de 02/06 (IDs 24-27) mantendo
supressão de cena-vazia.

## Setup
- Módulo REAL `worker.bgsub_filter` (build de modelo + `_apply_and_combine` single/dual + math de persistence idênticos a prod). Sweep de threshold feito analiticamente sobre as fg-masks por frame.
- Polígono real do esp32_005: `[[[585,350],[658,320],[874,413],[768,467],[755,470]]]` (área = **19103 px**).
- TP set: 4 eventos de 02/06 (frames do Drive): id24 lixo 12:42 (5f), id25 poda 15:28 (10f), id26 poda 15:59 (10f), id27 entulho/carroça 18:26 noite (10f).
- Baseline + negativos: esp32_005 `sem_ocorrencia/2026/06/03` (167 frames baseline dia+noite; 20 janelas negativas de 10 frames).
- Grid: mode {single, dual} × min_persistence_frames {0.10..0.40} × threshold {200..1000}. Baseline FRESCO (rebuild por janela = adaptive OFF).

## Resultado — ⚠️ TP side INVÁLIDO (confound de dia)
- Single, baseline fresco: os 4 TPs deram `persistence = 19103` (a **zona inteira**), idêntico nos 4 e em todos os min_frames. Inspeção frame-a-frame: **o foreground já está saturado no PRIMEIRO frame de cada evento, ANTES da deposição** (ex.: id24 12-42-37 = 18984 px). 
- Negativo de 06/03 (mesmo dia do baseline): **~17–40 px** (vazio correto).
- **Diagnóstico do método:** o baseline é de 06/03 e os TPs são de 02/06. A diferença de dia (iluminação/exposição/estado da pilha) acende a zona inteira para QUALQUER janela de 02/06 — descarte ou não. Logo o "4/4 passou" é **espúrio**; o sweep **não valida recall** com dados cross-day. (Aplica [[feedback_bench_match_prod_exactly]].)

## Conclusões VÁLIDAS (apesar do confound)
1. **Dual-rate está DESCARTADO.** Mesmo com o confound a favor, o dual deu `persistence=0` em mf=0.40 para 3 dos 4 (id24/25/26) — o modelo *fast* absorve o objeto depositado (drop-and-stay). Dual NÃO serve para este ponto.
2. **Especificidade do baseline fresco OK:** 20/20 janelas vazias de 06/03 suprimidas (~0 px) contra baseline 06/03 — baseline fresco não estoura FP em cena vazia do mesmo dia.
3. **Threshold NÃO é a alavanca.** A causa-raiz é a **frescura do baseline** (drift do adaptive), provada pelos **logs de prod** (independem do sweep): 382/409 janelas com `persistence=0.0`; os descartes capturados (08:47, 09:30) passaram cedo com baseline fresco e tudo colapsou para 0.0 após ~10:14 com o drift acumulado.

## Limitação de dados
Validação offline de recall exigiria baseline + negativos + TPs do **mesmo dia**. O histórico do esp32_005 é efêmero (só 06/03 sobrevive; 02/06 rotacionado), e não há evento de descarte rotulado em 06/03. Portanto o recall do fix só pode ser validado **ao vivo** (Fase 4: test-saira com baseline fresco + adaptive OFF, observando descarte real).

## Implicação pro plano
- Fase 3 simplifica: **não mexer em threshold/min_frames** (defaults de prod ok). O fix é: **desligar adaptive no esp32_005 + congelar baseline fresco + recalibração semanal** (cron). Dual-rate fora.
- Validação migra pro ao vivo (Fase 4).
