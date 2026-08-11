# Campanha 25 — `pile_volume_change` isolado + voto combinado (crops hi-res)

**Data:** 2026-05-30 · **Modelo:** gemini-2.5-flash (Vertex) · **Dataset:** cam_11, n=40 (21 CON / 19 REJ) · **Custo:** $0,088

## Hipótese (do usuário)

As camps 11-14 testaram `pile_volume_change` **sem** crops hi-res e falharam (o modelo
confabulava `increased`). Com o **close da pile-zone** (crop upscale 2×), talvez o sinal de
delta-volume separe CON/REJ de forma confiável — sozinho ou como veto.

## Método

Variante "pile-only puro": envia **só** os 12 crops hi-res da pile-zone (sem frames globais,
sem raciocínio de pessoa), prompt minimalista pedindo **só** `pile_volume_change` ∈
{increased, decreased, unchanged}. Decisão derivada: `increased` → CON. Depois, fusão offline
com a decisão E+CROPS (camp 24) nos mesmos 40 eventos.

## Resultados

| Abordagem | Acc | Recall | Spec | Prec | TP/TN/FP/FN |
|---|---|---|---|---|---|
| E+CROPS modelo sozinho (camp 24) | 67,5% | **90,5%** | 42,1% | 63,3% | 19/8/11/2 |
| `pile_volume` sozinho (`increased`→CON) | 65,0% | 57,1% | 73,7% | 70,6% | 12/14/5/9 |
| R1) modelo AND ≠decreased | 67,5% | 90,5% | 42,1% | 63,3% | 19/8/11/2 |
| **R2) modelo AND increased** | **72,5%** | 57,1% | **89,5%** | **85,7%** | 12/17/**2**/9 |
| R4) modelo OR increased (união) | 60,0% | 90,5% | 26,3% | 57,6% | 19/5/14/2 |

### Distribuição do sinal puro

| | increased | unchanged |
|---|---|---|
| CON (real) | 12 | 9 |
| REJ (FP) | 5 | 14 |

### Diagnóstico dos 11 FPs do modelo
- **9 têm `pile_volume=unchanged`** → o sinal **discorda** da decisão errada e os vetaria.
- **2 confabulam `increased` junto** (`5896feaa` conf75, `686b5746` conf85) → sem ajuda.

### Diagnóstico dos 2 FN do modelo
- Ambos (`3c840ac4`, `ae3d87cb`) têm `pile_volume=unchanged` → o sinal **também erra**, não resgata recall.

## Conclusões

1. **A hipótese estava parcialmente certa.** Com crop hi-res, `pile_volume_change` é o **sinal mais
   específico já medido** (spec 74% sozinho; 89,5% como gate). Melhorou vs camps 11-14.

2. **Descoberta melhor que o esperado:** ao contrário do palpite inicial, **9 de 11 FPs** do modelo
   recebem `unchanged` do sinal de volume — ou seja, o delta-volume **discorda** dos FPs e poderia
   vetá-los. Só 2 confabulam junto.

3. **Mas o custo em recall inviabiliza como decisor.** Exigir `increased` (R2) leva spec a 89,5% e
   precision a 85,7%, **porém derruba recall de 90,5% → 57,1%**: mata 7 dos 19 descartes reais —
   sacolas pequenas (mediana 0,05 m³) que **não mudam o volume visível** e recebem `unchanged`
   corretamente, mas eram CON.

4. **Sob o peso da SAIRA (recall ×3), R2 não compensa**: trocar ~9 FP por ~7 TP perdidos é ruim
   nesse critério. **Nenhuma regra combinada supera o E+CROPS** no balanço recall-ponderado.

5. **R1 é inócuo aqui**: nenhum FP teve `decreased`, então o veto de coleta nunca dispara neste set
   (continua útil conceitualmente p/ casos de coleta EMLURB, que não apareceram nesta amostra).

## Recomendação

- `pile_volume_change` via VLM **não substitui nem melhora** o pipeline sob o peso recall-3× da SAIRA.
  Seria útil só se a meta virasse minimizar FP aceitando perda de recall.
- O caminho de um sinal de volume **forte e independente** continua sendo **CV geométrico** (Δ-volume
  medido, não estimado por VLM) — consistente com o teto ~67% do `pilezone_delta_proto` (2026-05-29).
- ⚠️ Regras avaliadas nos mesmos 40 eventos (sem holdout) → ganhos otimistas.
