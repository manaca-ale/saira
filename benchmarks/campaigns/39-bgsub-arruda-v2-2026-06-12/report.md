# Campaign 39 — BGSUB Arruda: diagnóstico do always-pass + calibração (2026-06-12)

## TL;DR
1. **Causa-raiz do BGSUB inerte no Arruda: baseline alarm.** O lixo depositado depois
   do baseline (10/06) vira foreground permanente — floor de persistência 1,2k-5,6k px
   (zona antiga) / 4,4k-12,9k (zona nova) em janelas VAZIAS, sempre ≥ threshold (1000).
   Heatmaps confirmam: a região divergente é a própria faixa crônica. **Nenhum
   threshold separa com baseline velho** (positivos reais: 1,6k-3,2k px — abaixo do
   floor noturno).
2. **Com baseline FRESCO (≤7h), os parâmetros atuais de prod já separam**: sweep de 8
   braços × 30 configs → `fresh/new/single, mf=0.4, thr=1000` suprime **9/15 (60%)**
   das janelas vazias do dia + a janela do FP do gate de 03:12 (persistence **0 px** —
   o Agent-2 tinha rejeitado essa mesmo), enquanto a detecção real de 05:40 passa com
   **17-20k px** (margem 17×). Modo dual e zona não mudam o jogo; staleness muda tudo.
3. **Fix estrutural = recalibração DIÁRIA** (era semanal). Aplicado: crontab
   `30 4 * * 0` → `30 4 * * *` + recal manual imediata (08:19 BRT, mix noturno,
   120 frames) + restart pelo próprio script. **Primeira janela pós-recal ao vivo:
   `bgsub_suppressed esp32_005 persistence=0.0 shadow=true`** — comportamento ao vivo
   bate com o offline.
4. **PR #39** (develop): ledger durável `shadow_decisions.jsonl` pro BGSUB (padrão do
   ledger DINOv2) registrando supressões E passes com persistência — antes os passes
   eram invisíveis e as decisões shadow morriam com o container. 3 testes novos;
   30 passed. Pré-requisito cumprido: back-merge `main→develop` (PRs #35/36) feito e
   pushed (`804caba49`).

## Dados e método
- 23 janelas NEG completas + 7 janelas TRIG de 06/12 (extraídas do volume antes do
  purge), 26 positivos S3 + 5 FN Drive (camps 37c/e), baseline de prod (npz 10/06,
  157 MB) e baseline fresco (130 frames 00-03h de 06/12).
- `worker.bgsub_filter` REAL (md5 idêntico prod↔local), votes computados 1× por
  janela/braço, sweep analítico (padrão Camp 33).
- Braço fresh sem vazamento: baseline 00-03h, avaliação só ≥03h.

## Matriz (resumo; completa em results/sweep_39.json)
| braço | thr=1000, mf=0.4 | leitura |
|---|---|---|
| prod(10/06)/old/single | NEG 0/23 sup | floor acima do thr (estado atual) |
| prod/old/dual | NEG 6/23, mas POS 5/26 sup | dual fura recall com baseline velho |
| **fresh/new/single** | **NEG 9/15 sup, TRIG real passa (17k px), FP do gate suprimido (0 px)** | **vencedor** |
| fresh/{old,new}/{single,dual} | 8-10/15 | staleness domina; zona/modo secundários |

## Estado pós-campanha
- esp32_005 segue em **SHADOW** (`BGSUB_SHADOW_DEVICES`) — zero risco; agora com
  baseline fresco diário, o shadow registra supressões reais (via docker logs até o
  PR #39 chegar em prod; depois, ledger durável).
- **Critério de promoção a enforce** (Fase 4 do plano): ≥3 dias de shadow com
  0 would-suppress em janelas que viraram detecção CONF/INDET + taxa de supressão
  ≥30%. Promover = remover esp32_005 de `BGSUB_SHADOW_DEVICES` + recreate.
- Rollback de cada peça: cron de volta pra `* * 0`; baseline `.bak` ao lado do npz;
  PR revert; shadow já é o estado seguro.

## Acompanhamento ao vivo (12/06, 08:20→16h)
- 129 janelas: **16 would-suppress (12%)**, persistências suprimidas p50=0/máx=662;
  **0/16 triggers** (9 viraram detecção) interferidos — recall limpo.
- **Taxa zera a partir das 11h** (08h: 9/12 → 11h+: 0/119). Probe da tarde com heatmap:
  floor voltou a 9,7k-16k px porque **lixo novo REAL foi depositado durante o dia**
  (9 janelas-detecção 10:57→15:32; material espalhado até na via). Não é luz — é o
  drop-and-stay re-formando em horas. **A supressão só vive nos intervalos entre
  descartes** → recal precisa ser intra-dia.
- Mitigação aplicada: cron **2×/dia** (04:30 e 12:30) + commit no PR #39 com
  **hot-reload do npz por mtime** (recal sem restart do worker) → habilita cadência
  4h depois do deploy sem 6 restarts/dia.

## 39b — Replay full-day: ADAPTIVO vs ESTÁTICO (mesma origem, mesmo dia)
A pedido do usuário ("por que não usar o adaptável igual Mangabeira/Imbiribeira?"),
replay prod-fiel do dia 12/06 (248 janelas ≥03h, absorção governada pelo veredito
real do gate no audit, lr=0,05, MIN_CONF=0 — esquema idêntico ao dos outros pontos):

| política | supressão total | detecções reais engolidas |
|---|---|---|
| STATIC (recal fresco) | 40/248 (16%) | **0/10** ✅ (única TRIG suprimida = o FP de 03:12 que o Agent-2 rejeitou) |
| ADAPT (adaptivo pleno) | 224/248 (90%) | **9/10** ❌ (persistence 0 nas janelas de detecção!) |

**O adaptivo pleno teria suprimido 16/19 janelas de trigger e 9 das 10 detecções
reais do dia** — reprodução quantitativa do incidente de 02/06: como o gate é cego
à atividade sutil do Arruda e a faixa tem movimento constante, a absorção contínua
"aprende" a cena ativa em minutos e o descarte real passa a ler persistence ≈ 0
ANTES do gate. A taxa de 90% de supressão é uma armadilha: ele suprime tudo,
inclusive o que importa. **Adaptivo pleno REPROVADO para o Arruda — sem A/B vivo
necessário; o replay com n=10 detecções reais é conclusivo.** A combinação correta
segue sendo: shadow estático + recal intra-dia (+ clean-zone adaptive que absorve
só zona limpa, já ativo).

## Riscos remanescentes
- Staleness intra-dia: baseline das 04:30 tem até 24h de idade à meia-noite seguinte
  (teste usou ≤7h). O ledger vai mostrar se o floor sobe à noite → se sim, recal 2×/dia.
- Guarda de recall same-day tem n=1 detecção real; os 26 positivos históricos só
  validam o braço prod. Mitigação = exatamente o shadow de 3+ dias antes do enforce.

## Artefatos
`probe.py` (+ heatmaps em `probe_out/`), `sweep.py`, `results/sweep_39.json`,
`run_sweep.log`. Custo: $0 (CPU local). PR: #39.
