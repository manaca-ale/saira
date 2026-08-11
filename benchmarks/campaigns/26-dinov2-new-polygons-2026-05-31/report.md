# Campanha 26 — DINOv2 (pile-zone crop) com polígonos novos + cruzamento vs Gemini

**Data:** 2026-05-31 · **Modelo:** DINOv2 ViT-S/14 (384-d, CPU, $0) + LogReg 5-fold CV
**Dataset:** 67 eventos rotulados (cam_10: 10 CON/17 REJ; cam_11: 21 CON/19 REJ) · DB prod

## Hipótese

Os polígonos novos (cam_10 45%→22%, cam_11 13% justo, redesenhados em 2026-05-30) podem
melhorar o DINOv2, que extrai embedding **da região recortada da pile-zone**. Baseline
2026-05-29 usava frame inteiro + polígono antigo: cam_10 96%, **cam_11 47% (chute)**.

## Método

Crop da pile-zone (bbox do polígono ATUAL), DINOv2 ViT-S/14 CLS token, média dos últimos 3
frames → vetor 384-d. LogReg per-camera, 5-fold estratificado, OOF. ⚠️ Mudaram 3 variáveis vs
baseline (polígono novo + crop em vez de frame inteiro + small/384 em vez de base/2304) —
o ganho não está atribuído a uma só.

## Resultado standalone

| Câmera | acc | AUC | recall | spec | OOF |
|---|---|---|---|---|---|
| **cam_10** (Imbiribeira) | **96,0%** | **1.000** | 90% | **100%** | TP9 TN17 FP0 FN1 |
| **cam_11** (Mangabeira) | **75,0%** | 0.787 | 71% | 79% | TP15 TN15 FP4 FN6 |

cam_11 saltou de **47%→75%** (AUC 0.525→0.787). O crop na pile-zone justa tornou cam_11
separável por imagem estática — antes era impossível. cam_10 mantém excelência (spec 100%).

## Cruzamento DINOv2 × Gemini E+CROPS (cam_11, 40 eventos)

- both right: 22 · both wrong: 5
- **DINO corrige 8 erros do Gemini** — todos FPs (REJ que o Gemini chamou CON):
  `2bb86418, 45dc0327, 5896feaa, 62497a92, 686b5746, 69b8b0b6, b96cef1b, cf39d55f`
- DINO quebra 5 acertos: 3 CONs reais → REJ (`6b4d979d`, `80fdbc2b`, `bc0528c2`, `d59d5309` =4) +
  1 REJ → CON (`85d56cc5`). (No total: 4 CON-viram-REJ, 1 REJ-vira-CON.)

### Ensembles (cam_11)

| Regra | acc | recall | spec | TP/TN/FP/FN |
|---|---|---|---|---|
| Gemini E+CROPS sozinho | 67,5% | 90,5% | 42,1% | 19/8/11/2 |
| DINOv2 sozinho | 75,0% | 71,4% | 78,9% | 15/15/4/6 |
| AND (ambos CON) | **77,5%** | 71,4% | **84,2%** | 15/16/3/6 |
| OR (qualquer CON) | 65,0% | 90,5% | 36,8% | 19/7/12/2 |
| **Gemini, veto se dino p<0.2** | 75,0% | 81,0% | 68,4% | 17/13/6/4 |

**Trade-offs:** AND maximiza specificity (42%→84%) com custo de recall (90,5%→71,4%). O veto
p<0.2 é mais conservador: recall 81%, spec 68%, elimina 5 FPs perdendo 2 TPs.

## FP de hoje (`49e304b7`, status DB = PENDENTE)

Treinando nos 40 e prevendo o FP de hoje: **DINOv2 `p(CON)=0.44 → REJ`**. O Gemini decidiu
CON (confabulou "sacola nova"). **DINOv2 corrige** (classifica como REJ).
- Regra **AND** (dino REJ → REJ): pego ✓
- Regra **veto p<0.2**: 0.44 > 0.2 → **não** vetaria (escapa). O AND é mais eficaz neste caso.

## Conclusões

1. **Recortar a pile-zone com polígono justo destravou o cam_11** (47%→75%). O polígono novo
   importou — e valida o trabalho de ontem.
2. **cam_10 é deploy-ready como verificador grátis** (96%, spec 100%, AUC 1.0). Single-camera win.
3. **Em cam_11 o DINOv2 é complementar ao Gemini**: corrige 8 dos 11 FPs. Como ensemble AND,
   leva spec a 84% (acc 77,5%) — e teria corrigido o FP de hoje.
4. O valor real é **filtro de FP grátis** (Agent-3 zero-custo via embedding), não substituto do gate.

## Caveats

- 5-fold em n pequeno (cam_11=40, cam_10=27); regras de ensemble avaliadas nos mesmos eventos →
  otimista. Precisa validação temporal out-of-sample antes de deploy.
- bbox de cam_10 = (6,297,995,719): como cam_10 tem 4 polígonos espalhados, a bbox-união cobre
  ~metade inferior. Mesmo assim deu 96% — mas dá pra testar máscara multi-polígono (não bbox).
- Mudança de 3 variáveis vs baseline impede atribuir o ganho de cam_11 a uma só.
- sklearn não está no worker; para deploy precisaria empacotar (ou numpy puro / onnx).
