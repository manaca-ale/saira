# Campaign 44 — Imbiribeira (esp32_001): reduzir FP

**Data:** 2026-06-23 · **Câmera:** esp32_001 / cam_10 / Imbiribeira (terreno baldio aberto, vista distante)
**Objetivo:** reduzir falsos positivos. Duas alavancas: (C) polígonos recall-safe, (D) gate veículo-focado.

---

## TL;DR

1. **Pull full-DB**: dataset oficial do Imbiribeira **55 → 211 eventos** (20 TP / 147 FP / 44 indef),
   puxados de prod por `detections.status` (CONFIRMADO/REJEITADO/INDETERMINADO).
2. **Gate veículo-focado = REPROVADO.** Exigir veículo corta MUITO FP mas **destrói recall**:
   - A_baseline (prod): recall **60%** (12/20), FP 66/147 (spec 0.55)
   - C_vehicle_soft: recall **40%** (8/20), FP 26/147 (spec 0.82) — corta 40 FP, perde 4 TP
   - B_vehicle_hard: recall **15%** (3/20), FP 11/147 (spec 0.93) — corta 55 FP, perde 9 TP
   - Piso de recall (SAIRA ×3) = **85%** → **nenhum arm de veículo passa** (nem o baseline).
   - **Motivo-raiz**: veículo **não discrimina** — o modelo vê veículo em **110/147 FPs (75%)**
     (estacionamento/via de passagem) e **muitos TPs reais são a pé** (carrinho/sacola).
3. **Polígonos**: confirmados **4 polígonos vivos**. Preview preliminar (via `waste_bbox`,
   aproximado): os 4 atuais cobrem só **~22%** dos pontos de TP → fortes indícios de que
   atrapalham. **Resposta definitiva aguarda sua marcação manual dos 20 TPs** (Fase B).

**Veredito:** a alavanca de veículo não serve para este ângulo de câmera. O caminho de
corte de FP **sem custo de recall** é **redesenhar os polígonos** (Fase C) — recall-safe.

---

## Fase A — Pull full-DB + dataset oficial (FEITO)

Pull read-only de `saira-prod` (container `saira-db-prod`, `psql COPY`) de TODAS as
detecções rotuladas do esp32_001 + detection_frames do worker + frames do S3
(12 even-spaced/evento, 2160/2184 baixados, 1.1% miss). Mesclado no dataset oficial com
dedup por `event_id` (24 já existiam, preservados). Manifest mestre reconstruído.

| | antes | depois |
|---|---|---|
| TP (CONFIRMADO) | 7 | **20** |
| FP (REJEITADO) | 31 | **147** |
| Indef (INDETERMINADO) | 17 | **44** |
| **total** | **55** | **211** |

Achado colateral: **DINOv2 do esp32_001 já está em `shadow`** (não `enforce`) — a maior
armadilha do plano (recorte DINOv2 acoplado ao polígono) está neutralizada.

## Fase D.2 — Benchmark do gate veículo-focado (FEITO)

Gate-only, `gemini-2.5-flash-lite`, thinking 2048, Vertex/ADC, frames first+3mid+last,
trigger conf≥85. 167 eventos (20 TP + 147 FP) × 3 arms = 501 chamadas, **0 erros, ~$0.74**.
Mesma base V3 + preâmbulo de cena; só muda o gating de modalidade.

| arm | recall | spec | TP | FP disp. | FP cortados | score (r×3) |
|---|---|---|---|---|---|---|
| **A_baseline** (prod hoje) | 0.60 | 0.55 | 12/20 | 66/147 | — | 0.588 |
| **C_vehicle_soft** | 0.40 | 0.82 | 8/20 | 26/147 | 40 | 0.506 |
| **B_vehicle_hard** | 0.15 | 0.93 | 3/20 | 11/147 | 55 | 0.344 |

### Split de veículo (Fase D.1)
- **FPs**: modelo vê veículo em **110/147 (75%)** → "veículo presente" não separa TP de FP
  (terreno é estacionamento + via). Só **37 FP** seriam "sem veículo" (teto do corte limpo).
- **TPs**: dos 12 que o baseline pega, **≥5 não têm veículo** (modelo) — descartes a pé
  ("dois homens descartando…"). O gate hard descarta esses descartes legítimos.

### Cross-tab (TP perdidos pelo arm hard = 9 de 12)
Vários com justificativa explícita de descarte **a pé/carrinho**: "dois homens descartando
o conteúdo de um saco", "pessoas realizando o descarte", "dois homens mexendo no lixo".

> ⚠️ Caveat de fidelidade: o recall do baseline (60%) é menor que o 6/7 (86%) do dataset
> curado pequeno (camp-31) — efeito do corpus maior/representativo + amostragem de 5 frames
> da janela de 12. A **comparação relativa A/B/C** (mesmos frames) é válida e robusta.

### Verificação adversarial por visão (workflow, ultracode — 24 agentes, 140 reads de frame)
Agentes de visão independentes leram os frames reais dos **9 TPs perdidos** pelo arm hard
e de **14 FPs** que o modelo marcou com veículo.

- **TPs perdidos: 8/9 são perda LEGÍTIMA** — descartes a pé/carrinho/grupo, veículo
  presente só estacionado/passando (modalidade: 3 on_foot, 3 group, 2 handcart, 1 vehicle;
  `recoverable_by_vehicle_prompt`=false em 8/9). Só **1** (e2bdf0d5) é bug de prompt real
  (sedã que para e descarrega, mas aparece em ~1 frame).
- **FPs com veículo: 14/14 têm veículo real, mas 0/14 descarregando** (13 "no", 1 "unclear";
  um é caminhão de REMOÇÃO de lixo). Detecção de veículo é precisa, mas **não discrimina**.
- **Teto estrutural de recall de QUALQUER gate-veículo = (20−8)/20 = 60%** — 25pp abaixo do
  piso de 85% (precisa ≥17/20). Não é tuning: é a câmera. **`vehicle_lever_viable=false`.**

> Resultado completo em `results/vehicle_audit.json`. Reproduz a lição recorrente do
> projeto (camps 25/32/42): veto de sinal único falha o recall neste tipo de cena.

## Fase C — Polígonos (FINAL, com marcação manual dos 20 TPs)

Você marcou os **20 TPs** (0 pulados). Split de veículo (GT humano): **12 com / 8 sem** →
confirma o teto de recall do gate-hard = **60%** (idêntico à auditoria por visão;
concordância modelo×humano 17/20).

| conjunto | TP_cov (manual) | FP_cov~ (bbox) | área | n |
|---|---|---|---|---|
| **current_live** | **55%** (11/20) | ~56% | 22.3% | 4 |
| camp-41 | 0% | ~22% | 3.3% | 3 |
| **proposed (recall-safe)** | **100%** (20/20) | ~27% | 15.1% | 4 |

**Os 4 polígonos atuais ATRAPALHAM, sim:** cobrem só 55% dos descartes reais — **9 de 20
caem FORA**, na maioria nas **lacunas entre os quads** (os polígonos atuais são 4 quads
pequenos desconexos) e nas bordas de cima. IDs fora: `06414b5a, 12506543, 48350bb4,
67d156a3, a447ff19, b0a0e12e, c8cb22fb, c9c2c83e, cb49921a`.

**Proposta recall-safe (4 polígonos):** cobre **100% dos 20 TPs**, com área MENOR (15,1% vs
22,3%) e menos sobreposição com zona de FP (~56%→~27%, aproximado). A jogada: manter as
faixas de meia-altura onde caem os descartes + **encolher a caixa inferior-esquerda gigante**
atual (que pega pedestre no primeiro plano) para só o canto com TP real. SQL em
`results/proposed_polygons.json` (`update_sql`) — **entregável, não aplicado**.

**Caveats honestos:**
- `BGSUB_PREFILTER_ENABLED=true`, sem shadow → BGSUB **enforça** no esp32_001. Mas conta
  movimento em QUALQUER ponto da união das zonas (a pessoa cruza um polígono ao andar até o
  ponto), então **"45% fora" ≠ "45% de recall perdido hoje"** — os 9 são CONFIRMADOS reais.
  O ganho do redesenho é **cortar FP** (trim do foreground-pedestre) + cobertura correta das
  zonas, não recuperar recall já perdido.
- FP_cov é via `waste_bbox` (espaço 0-1000 do Gemini), **aproximado** — direcional, não exato.
- 20 TPs é amostra limitada; "100%" = dos 20 conhecidos. Novos locais podem cair fora.
- Polígono = zona do BGSUB + bbox do recorte DINOv2. Trocar exige **recalibrar baseline
  BGSUB** (`calibrate_bgsub.py`) e medir em shadow antes de confiar no corte de FP.

## Próximos passos (recomendado)
1. Aplicar a proposta em **shadow/validação**: rodar BGSUB com a nova zona em paralelo,
   medir supressão de FP vs recall ao longo de alguns dias (DINOv2 já está em shadow).
2. Recalibrar baseline BGSUB após trocar a zona.
3. Se segurar recall e cortar FP → enforce. **Polígono é a alavanca de FP sem custo de
   recall** (≠ gate-veículo, reprovado).
