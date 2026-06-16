# Camp 41 — Structural-delta para o Mangabeira (esp32_002 / cam_11)

**Data:** 2026-06-16 · **Custo:** $0 (cv2+numpy, CPU, frames já em disco) · **Câmera:** esp32_002 Mangabeira

## Hipótese

Detecção de mudança **estrutural** (Census Transform/Hamming + micro-tiles, before/after)
separa descarte real (TP) de transeunte (B3) onde tudo falhou na Camp 40 — porque ataca as
2 razões dos fracassos: (a) descritores estruturais **ignoram intensidade absoluta** →
imunes a sombra/sol/IR (o que matava o MOG2); (b) **micro-tiles** → saco pequeno = ~100% de
mudança em 2-3 tiles, independente da pilha permanente (o "permanence" global da Camp 40 diluía).

Baseado em `pesquisas/aod-persistent-pile-outdoor.md` (algoritmo agnóstico de hardware; a parte
de FSM-on-Pi foi ignorada — tudo roda no worker da EC2, contra os frames que já chegam).

## Dados (reuso Camp 40 largeN, N grande de prod)

71 TP + 142 B3 com frames de evidência no S3 (`ocorrencias/`, não purgam), janelas completas
38-165 frames, subamostradas a 24 frames/evento (`frames24/`). Polígono REAL da pilha (banco,
esp32_002): `[[461,154],[704,66],[939,299],[617,416]]` (ref 1280×720).

## Método

1. **before/after** por evento. Duas estratégias:
   - *motion-picked* (`extract_before_after.py`): menor movimento na pile-zone no 1º/último 30%.
   - *first-vs-last* (`make_firstlast.py`): 1º vs último frame da janela (heurística camp 20).
2. **Descritores estruturais** (`phase_struct_signals.py`), dentro do polígono, tiles 16×16/32×32:
   - **Census-Hamming** (numpy puro — invariante a iluminação), **Canny new-edge**, **NCC**.
   - Agregados por evento: `max_tile`, `mean_tile`, `n_tiles_changed` (por descritor) + globais camp-20.
3. **Separabilidade** (`phase_struct_roc.py`): AUC TP-vs-B3, bootstrap 95% CI, **holdout
   temporal** (treina antigos / testa novos), sweep de veto no piso de recall, **permutation check**.

## Resultado — GATE PASSOU (variante first-vs-last)

A `motion-picked` é um **lower bound fraco**: a sanidade visual (`viz/pair_*.jpg`) mostrou que o
"after" de baixa-movimento **ainda contém pessoas paradas** na pilha (pessoa parada = baixa
motion = a armadilha) → o sinal media em parte PESSOAS. AUC topo 0,76, holdout estável mas
supressão fraca. A `first-vs-last` é o proxy correto (o depósito persiste até o fim da janela; o
transeunte passa e a estrutura reverte) **e é o que o worker tem** (`sequence_paths[0]`/`[-1]`).

**Sinal vencedor: `census_ntiles_t32`** (nº de tiles 32×32 com ≥50% de pixels census-mudados):

| critério do gate | exigido | medido | veredito |
|---|---|---|---|
| AUC (keep TP) | ≥ 0,75 | **0,827** | ✅ |
| CI inferior (bootstrap 95%) | > 0,5 | **0,767** [0,767–0,880] | ✅ |
| B3 suprimido @ ≤15% TP perdido | ≥ 30% | **63%** (90/142) @ 86% recall (thr=2) | ✅ |
| holdout temporal não-colapsa | gap pequeno | **train 0,832 → test 0,826** (gap 0,006) | ✅✅ |
| permutation (labels shuffle) | AUC≈0,5 | obs 0,827 vs perm_mean 0,533, **p=0,0000** | ✅ |

`census_ntiles_t16` confirma (AUC 0,815, test 0,834, 61% B3 supp). Census domina edge/NCC.

### O contraste com o DINOv2 (Camp 40)
O DINOv2 deu AUC 0,89 in-sample mas **colapsou no holdout temporal (0,51 = acaso)** = overfitting
de N pequeno. O structural-delta é uma **MEDIDA determinística** (cv2+numpy, sem treino) → **não há
nada pra overfittar**; o holdout segura (0,83≈0,83). Mesma lição da Camp 40 ("regra > classificador
treinado") — agora a favor da visão. **A tese "visão não separa tiny-bag de transeunte, ponto" da
Camp 40 vale para embedding por-frame (DINOv2) e pixel cru (BGSUB), NÃO para o before/after
estrutural** — o ingrediente que faltava era o eixo temporal (transeunte reverte; depósito persiste).

### Confounds descartados
- **Nº de frames:** constante (24 todos) → correlação ~0.
- **Duração da janela:** TP med 234s ≈ B3 220s; correlação census×span existe (+0,5 TP) MAS o
  **AUC dentro de banda de duração casada [60,300]s = 0,818** (≈ os 0,827 do full) → o confound
  **não dirige** a separação.
- **Reprodução camp 20** (4 eventos cam_11 do proto original, no manifest): `edge_delta_pct`
  separa limpo (REJ −0,34/−0,98; CON +0,75/+0,46) → o sinal do proto se confirma; os 4 cam_10
  precisam de S3 (não-locais).

## Papel de deploy (decidido pós-Fase 1)

| papel | AUC | resultado | veredito |
|---|---|---|---|
| **Veto de FP standalone** | **0,83** | 63% B3 cortado @ 86% recall, holdout-estável | **forte** |
| Recuperação de recall (preferência do plano) | 0,72 | recupera só 4-7 TP **tiny (≤0,1 m³, não-autuáveis)**, re-admite 5-12 B3 | **fraco — descartado** |
| Veto 2º-estágio (sobre os confirms do barra-alta) | 0,74 | mata ~32% dos 28 B3 residuais @ 96% recall, mantém 4/4 acionáveis | aditivo modesto |

A **recuperação não se sustenta**: os TP que o barra-alta larga são genuinamente tiny e
recuperá-los re-injeta FP no alerta. O valor real é **veto de FP**. Como o barra-alta já corta
80% dos B3, o detector entra em **SHADOW** (loga, não altera) pra medir no vivo antes de qualquer
enforce — e poderá rodar como 2º-estágio ou substituir/complementar o barra-alta conforme os dados.

## Fase 2 — integração no worker EC2 (implementada, shadow)

- `services/yolo-worker-vm/src/worker/detector_structural.py` — espelha `detector_dinov2.py`:
  census+tiles embutidos (cv2+numpy), **fail-open**, ledger durável (`structural_decisions.jsonl`),
  flag por-device. `should_reject = n_tiles_changed < STRUCTURAL_NTILES_THR (=2)`.
- Seam: post-detail veto em `main.py` (logo após o bloco DINOv2, só quando `disposal=True`).
- Configs `STRUCTURAL_*` em `config.py` + 3 composes (off por padrão).
- **Paridade local PASS**: o módulo do worker reproduz exatamente o `census_ntiles_t32` da campanha
  (21, 3, 7, 0, 14, 6). **137 testes do worker passam** (7 novos em `test_structural_filter.py`).
- Rollout: shadow (`STRUCTURAL_FILTER_MODE=shadow`, `STRUCTURAL_DEVICES=esp32_002`) → enforce após
  ≥3 dias de ledger limpo, comparando o que rejeitaria contra os rótulos do operador (padrão DINOv2/BGSUB).

## Artefatos
`scripts/{census,extract_before_after,make_firstlast,phase_struct_signals,phase_struct_roc,verify_checks}.py`
· `results/{before_after,before_after_firstlast,struct_signals,struct_signals_firstlast}.csv`
· `results/{struct_roc,struct_roc_firstlast}.json` · `viz/pair_*.jpg`.
