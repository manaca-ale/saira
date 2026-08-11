# Campaign 37c/37d/37e — Arruda gate: V1 vs SCRATCH nas janelas exatas + FNs recuperados (2026-06-11)

## TL;DR consolidado (37c + 37e)

**Recall em 26 eventos reais de janela exata** (20 positivos históricos do S3 + 5 FNs do
Drive + 1 KEPT; evento coalesced conta como pego se qualquer janela dispara):

| | V1 (prod) | SCRATCH |
|---|---|---|
| **Recall (eventos)** | 20/26 = **77%** | 21/26 = **81%** |
| **FP windows (37c, n=30)** | 15/30 = 50% | 17/30 = 57% |
| **FP operador-facing (REVIEWREJ)** | 9/11 | 9/11 (empate) |

**Perfil dos misses é o que decide** (não a taxa):
- V1 perde: **a classe a pé/carrinho inteira** (id31, id32, 08_KEPT) + 2 CONFIRMADOS
  (ce13f76c com evidência literal *"no clear evidence of a vehicle stopped"*; 9085ad0e
  com `new_litter=false` a 85) + 6328e4e6.
- SCRATCH perde: 3 INDETERMINADOS ambíguos (9e112c6d "walking away", b797daa9 "pessoa
  agachada" — planilha marca Indefinido; bd466bda = caminhão de lixo na pilha lido como
  **coleta**, que é o design do prompt e arguably correto) + id32 + 6328e4e6.
- COLETA real (8657dafd, planilha): **os dois disparam** — nenhum suprime essa.

## TL;DR (descobertas da 37c)
1. **Os 5 eventos perdidos do Arruda foram RECUPERADOS limpos do Drive** (id25/26/27 de
   02/06, id31/32 de 09/06; 109 frames, std 60-66). A tese "exports do Drive corrompidos /
   id25-27 irrecuperáveis" (Camp 34) estava **errada** — a corrupção entrou na curadoria
   local, não na fonte. O recall do Arruda agora É testável offline.
2. **A causa dos FNs se divide em 3 classes** (não uma):
   - **FN de PROMPT** (id31 carrinho, 08_KEPT, id32): V1 ancora DUMPING em veículo.
     Evidência literal do V1 no 08_KEPT: *"appearing to deposit additional material.
     However, **no vehicle is stopped** at the dumping location"* → conf 70, não dispara.
   - **FN de AMOSTRAGEM** (id25, id26): ação de 25-60s numa janela de ~4min; picks fixos
     25/50/75% (~60s de intervalo) mostram a ação em ≤1 de 5 frames. Com frames densos na
     ação, o V1 acerta os mesmos eventos com 95×3.
   - **FN de BGSUB** (id27, id24): janela nem chegou ao gate (corrigido pelo
     frozen-baseline de 06/04).
3. **SCRATCH > V1 no set completo** (38 janelas: 5 FN + 3 KEPT/PENDENTE + 19 FP exatas +
   11 NEG; 228 calls): recall confirmado **5/6 vs 3/6**, FP 17/30 vs 15/30 (e 2-3 dos
   "FPs" em NEG são suspeitos de descarte real — ver §Achado lateral). Sob peso recall×3,
   SCRATCH vence com folga. **0 flips em 228 calls** (flash-lite@thinking2048 é
   determinístico por input; repeats são desnecessários, varie frames).
4. **SCRATCH2 (37d, cláusula on-foot-carrier p/ id32) REJEITADO**: ganhou o alvo (id32
   30→90) mas **perdeu id25/26 (90→30)**, passou a disparar em 4 janelas-FP novas
   (16/17/28/29) e **suprimiu a carroça-suspeita do 31_NEG**. Uma cláusula reembaralha o
   comportamento global (mesma lição das camps 11-16/22). Score 3-way ponderado
   (3·TP − FPrev − 0,3·FPa2 − FPneg): **V1 −3,2 | SCRATCH +1,5 | SCRATCH2 −2,9**.
5. **Nenhum prompt resolve o flood de FP** (~15-17 das 30 janelas FP disparam nos dois):
   o FP dominante (pessoa parada/mexendo na pilha crônica = catador/revirador) é
   exatamente o que um gate recall-first deve escalar. O corte tem que vir de
   filtro pós-gate (DINOv2 per-camera / Agent-2 / review).

## Dados
- **Janelas exatas de prod** via audit JSONL (`/app/state/gemini_cascade_audit/`, 15 dias
  disponíveis, 28/05→11/06) + frames do volume (purge <24h — frames de 06/10 já não
  existiam às 19h30 de 06/11). 33 janelas exatas de 06/11 em `tmp/ar_exact/`.
- **FNs recuperados**: `tmp/arruda_fn_drive/{id25,id26,id27,id31,id32}` baixados da pasta
  Drive da planilha "Mapeamento de Ocorrências" (aba Não Capturadas) via API
  (token Envs). ⚠️ A data do id32 na planilha está errada: diz 05/06, frames são de
  **09/06 14:42-14:49** (bate com o audit: janelas 14:38-14:50 todas conf=0).
- **Ground truth**: DB prod (`detections camera_id=14`). 15 dias: 22 reais
  (CONF+INDET), 37 REJEITADO, 4 PENDENTE → precisão pós-review ~37%, com V1 disparando
  ~8/dia (120 triggers/15d, 52 A2REJ).

## Resultado por janela (conf, determinístico ×3)
| Cohort (n) | V1 dispara | SCRATCH dispara | Leitura |
|---|---|---|---|
| FN reais (5) | 3 (id25/26/27 @95) | **4 (+id31 @90)** | id32 escapa dos dois (30) |
| KEPT confirmado (1) | **0** (c=70!) | **1** (@85) | V1 offline nem reproduz o trigger de prod |
| REVIEWREJ (11) | 9 | 9 | FP operador-facing: empate |
| A2REJ (8) | 4 | 5 | FP custo-only: empate prático |
| NEG (11) | 2 | 3 | ver Achado lateral (24/27/31) |
| PENDENTE (2) | 2 | 1 (suprime 34_DET) | resolver quando revisarem |

## Achado lateral (ação humana sugerida)
- **31_NEG 16:48-16:51 de 06/11**: carroça carregada PARA na faixa crônica, pessoa
  abaixada ao lado, carroça some no frame seguinte. Prod deu a1c=80 (<85) → nunca virou
  detecção e NÃO está na planilha. Ambos os gates offline dão 90-95. **Forte candidato a
  descarte real perdido por 5 pontos de threshold** — vale revisão humana
  (`tmp/ar_exact/31_NEG_16-51-34/`).
- 24_NEG 05:25 e 27_NEG 10:01: pessoa/caminhão na faixa, ambíguos (catador?).

## Reprodutibilidade offline (calibração de expectativa)
Replay offline com janelas exatas é **direcional, não bit-exato**: das 19 janelas que o
prod disparou, o V1 offline dispara 13 (~68%); 08_KEPT prod=90 vs offline=70; 2 NEG
prod<85 vs offline=95. Causa provável: o pick dos 3 mid-frames difere do prod (lista
em memória vs reconstrução do disco) + sensibilidade de threshold em casos borderline.
Fix definitivo: logar os 5 frames usados no `_audit_record` (main.py:1438) — mudança de
~3 linhas, recomendada antes de qualquer shadow A/B.

## Recomendações (em ordem de alavanca)
1. **Logar frames escolhidos no `_audit_record`** (3 linhas; destrava replay bit-exato e
   acúmulo diário de dataset rotulado por janela exata).
2. **Shadow A/B do SCRATCH no esp32_005** (log-only, padrão do ledger DINOv2/Camp 35):
   prompt em `arruda_gate_from_scratch.md`, ganho esperado = classe carrinho/pedestre
   (id31, 08_KEPT) sem piora mensurável de FP. Offline já reproduziu 2× (n=1 da sessão
   anterior + 3 reps determinísticos desta).
3. **Motion-aware mid-frame picking** (ataca os FNs de amostragem id25/26, $0/call):
   protótipo em `tools/motion_pick_proto.py`; pendência = polígono só da faixa (hoje pega
   via e tráfego vira ruído). Alternativa de força bruta: mais mid-frames por janela.
4. **FP flood**: não é prompt. Retreinar/portar o filtro DINOv2 per-camera (Camp 26/27)
   pro cam_14 — agora há ~8 triggers/dia pra rotular, mas frames purgam em <24h → a
   extração diária de janelas exatas (item 1) é pré-requisito do dataset.

## 37f — DINOv2 FP-filter pro cam_14: separabilidade AINDA NÃO (2026-06-11, noite)

Eval offline com receita idêntica ao `retrain_dinov2.py` (últimos 3 frames/detecção,
crop bbox do polígono, vits14, Scaler+LogReg balanced): 47 eventos treináveis
(10 CONFIRMADO vs 37 REJEITADO; 11 INDET + 1 COLETA como sonda; 12 eventos de 06/11
recuperados do volume — ainda não tinham migrado pro S3).

| bbox | cohort | AUC (CV estratificado ×10) |
|---|---|---|
| polígono do DB | todos | 0,684 ± 0,191 |
| polígono do DB | só ângulo novo (≥02/06 15h) | 0,603 ± 0,310 |
| **faixa completa (wide)** | todos | **0,781 ± 0,159** |
| **faixa completa (wide)** | só ângulo novo | **0,768 ± 0,218** |

- **cam_14 hoje ≈ cam_11 da Camp 26 (0,714 = fraco), longe do cam_10 (0,947).** Não
  passa o gate de retreino de prod (AUC ≥ 0,85) — o próprio `retrain_dinov2` recusaria
  promover o artefato. **NÃO ligar shadow no esp32_005 ainda.**
- **O polígono é parte do problema**: alargar o bbox pra faixa crônica completa
  (x 585→1230, y 320→560) ganha **+0,10-0,17 AUC** — o `pile_zone_polygon` atual cobre
  só a metade de cima da faixa (a carroça de 16:49 e o ponto do id32 caem FORA).
  Redesenhar o polígono é ganho barato e certo.
- **Holdout temporal inviável ainda**: os 30% mais recentes não têm nenhum CONFIRMADO
  (último = 08/06) — gargalo é n_con=10 (6 no ângulo novo). O dataset cresce ~8
  detecções/dia sozinho (detection_frames persiste tudo); em 2-3 semanas re-avaliar.
- Sonda INDET (wide, t=0,5): barraria 9/12 — threshold operacional teria que ser baixo
  e mesmo assim a margem não existe com AUC 0,78.

Artefatos: `dinov2_arruda_eval.py`, `dinov2_arruda_emb.npz` (59×384×2 bboxes,
reutilizável), `run_37f.log`.

## Custo
228 calls (37c) + 38 calls (37d) + 50 calls (37e) flash-lite ≈ **$0.40**; 37f = $0 (CPU local). Total Arruda camps 34+37*: ~$1.

## Arquivos
- `bench_v1_vs_scratch_full.py` / `results_37c.json` / `run_37c.log`
- `bench_scratch2.py` / `results_37d.json` / `run_37d.log` (FAIL, registrado)
- `tmp/arruda_fn_drive/` (109 frames limpos), `tmp/ar_exact/` (33 janelas exatas 06/11),
  `tmp/audit_all/` (15 dias de audit esp32_005)
