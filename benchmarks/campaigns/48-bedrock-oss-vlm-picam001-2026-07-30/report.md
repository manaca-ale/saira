# Campanha 48 — VLMs open-weight no Bedrock vs Gemini-2.5 (2026-07-30)

## Hipótese

O gate `gemini-2.5-flash-lite` e o detail `gemini-2.5-flash` de produção **são
desligados em 16/out/2026**. O [Camp 47](../47-picam001-model-migration-2026-07-22/report.md)
mostrou que o caminho oficial (Gemini-3) só **empata** com prod (`unified_low_2s`:
93% recall, ~$0,0025/ev) e mantém o lock-in de fornecedor. Existe algum VLM de **peso
aberto** no Amazon Bedrock que sirva de Plano B — recall/detecção ≥85%, custo ≤ o do
caminho Gemini-3, e pesos publicados (opção de self-host)?

## Configuração

| Item | Valor |
|------|-------|
| Conta | Bedrock `codex-ops` (818680680175), `us-east-1`, tier on-demand |
| Dataset | `cam_picam001` (N=122: 30 tp / 16 det · 37 fp / 28 det · 40 baseline · 15 indefinido) |
| Caminho | `data/datasets/official/cam_picam001` |
| Janela | `subsample_frames(48)` → `fit_frames_to_payload(8 MB)` — código de prod importado |
| Gate | 1º + 3 mid + último, trigger ≥85, post-gates V1 de prod aplicados |
| Prompts | V1 (`detector_gemini.SYSTEM_PROMPT` / `NEW_LITTER_SYSTEM_PROMPT`) e g3 (`_prompts_g3`) |
| Controle | `current` = gemini-2.5-flash-lite + gemini-2.5-flash, V1, re-rodado NESTE harness |
| Foco | model-selection |
| Validação humana | Fase 0 — 122/122 aprovados (aprovação global do operador, 30/07) |

---

## Fase 0 — validação visual da janela

`scripts/export_review.py` exportou, por evento, os frames que vão ao gate e ao
detail em pastas separadas + contact sheets (frames do gate destacados em vermelho)
em `cam_picam001/_review_camp48/`. O operador aprovou os 122 eventos.

**Achado desta fase:** o teto de 8 MB de payload corta muito mais que o limite de 48
frames. Em **27 dos 122 eventos o modelo vê menos da metade** do evento bruto:

| categoria | <25% | 25-50% | 50-75% | 75-99% | 100% |
|---|---|---|---|---|---|
| tp | 0 | 8 | 1 | 0 | 21 |
| fp | 1 | 18 | 4 | 2 | 12 |
| indefinido | 0 | 0 | 0 | 2 | 13 |
| baseline | 0 | 0 | 0 | 0 | 40 |

Pior caso `fp/evt-20260718_074618`: 100 frames brutos → 24 na janela. Entre os TP,
`tp/evt-20260715_165230` cai de 85 para 26.

---

## Restrição descoberta: o Bedrock aceita 1/3 do payload do Gemini

Um probe inicial com JPEGs **sintéticos** de 20 KB concluiu "48 imagens cabem" — e
estava errado. Com frames **reais** 1280×720 (~297 KB), o limite não é contagem de
imagens, é tamanho de corpo, e é **uniforme nos 5 candidatos** (logo, do endpoint):

| payload | resultado |
|---|---|
| 9 frames originais = 2,65 MB | OK |
| 10 frames originais = 2,95 MB | `Failed to buffer the request body` |

2,65 MB em base64 dão 3,53 MB e 2,95 MB dão 3,93 MB → o teto é um **corpo de 4 MB**.
Orçamento seguro de imagem crua: **2,7 MB**, contra os **8 MB** que prod manda ao
Gemini (mediana real 3,04 MB). Alternativas medidas na janela cheia de 48 frames:

| codificação | tamanho | cabe |
|---|---|---|
| 640px q70 (`low`) | 2,65 MB | sim |
| mosaico 4×3 em folhas de 12 | 1,79 MB | sim |
| 854px q72 | 4,93 MB | não |
| 960px q70 | 6,05 MB | não |

Por isso **não existe braço em resolução original**. O modo `low` é o análogo direto
do `media_resolution=low` do Gemini, que o Camp 47 provou não custar recall
(1101→265 tok/img, recall manteve 100%). No dry-run, em `low` a janela inteira cabe
com 1,10 MB de mediana e **zero eventos** sofrem corte de frames.

### Teto de imagens por modelo (probe com 40 chamadas)

| modelo | teto | consequência |
|---|---|---|
| gemma-3-27b/12b, qwen3-vl-235b, nemotron-nano-12b, kimi-k2.5, magistral-small | 48+ | acertaram em qual quadro o objeto aparece, em 48 frames |
| `writer.palmyra-vision-7b` | 5 | só gate ou mosaico |
| `us.meta.llama4-scout` / `-maverick` | **3** | **ELIMINADOS** — não rodam nem o gate de 5 frames |
| `us.mistral.pixtral-large-2502` | s/ teto de validação | throttle agressivo, ~10× o preço |

---

## Fase A — screen de capacidade (18 eventos: 6 tp + 6 fp + 6 baseline)

| modelo | A1 JSON | A3 recall TP | FP | baseline | A4 pt-BR | $/ev | p50 | veredicto |
|---|---|---|---|---|---|---|---|---|
| kimi-k2.5 | 100% | **6/6** | **1/6** | 0/6 | 100% | 0,00784 | 7,3 s | passa |
| magistral-small | 100% | **6/6** | 3/6 | 0/6 | 100% | 0,00678 | 21,0 s | passa |
| qwen3-vl-235b | 100% | 4/6 | **0/6** | 0/6 | 100% | 0,00485 | 11,9 s | passa |
| gemma-3-27b | 100% | 5/6 | 6/6 | 3/6 | 57% | 0,00221 | 32,2 s | degenerado |
| gemma-3-12b | 89% | 5/5 | 5/5 | 2/6 | 100% | 0,00092 | 18,6 s | degenerado |
| ministral-3-14b | 44% | — | — | — | — | 0,00172 | 5,2 s | **corta (A1)** |
| nemotron-nano-12b | — | — | — | — | — | — | — | endpoint indisponível |
| palmyra-vision-7b | — | — | — | — | — | — | — | endpoint indisponível |

**Finalistas:** `kimi-k2.5`, `magistral-small`, `qwen3-vl-235b`.

### Três correções de método aplicadas antes de julgar

1. **`palmyra-vision-7b` reprovou por bug do runner, não por incapacidade.** Seu teto
   de saída é 4096 e o runner pedia 8192 → `ValidationException` em 18/18. Ele também
   **não aceita bloco `system`** ("Conversation roles must alternate"). Ambos agora se
   auto-corrigem no cliente (aprende o teto da mensagem de erro; dobra o system dentro
   da mensagem do usuário).
2. **O ranking inicial ignorava FP** e colocava `gemma-3-27b` no pódio com "5/6 TP",
   enquanto ele dispara em **6/6 dos FP e 3/6 do baseline**. Foi adicionada uma guarda
   de degenerescência: quem dispara em ≥80% dos negativos vai para o fim da fila. Com
   N=6, o portão de recall sozinho não distingue "acerta" de "diz sim para tudo".
3. **A porta A4 (pt-BR) foi rebaixada de eliminatória para informativa.** O prompt V1
   de detail é escrito em português mas **nunca pede o idioma** — o Gemini infere, os
   open-weight respondem em inglês. Cortar por isso mediria uma linha de prompt
   faltando, não capacidade.

### Não avaliados

`nemotron-nano-12b` e `palmyra-vision-7b` devolveram `ServiceUnavailableException` em
praticamente toda chamada, mesmo com 5 retentativas e backoff exponencial — inclusive
em chamadas que haviam funcionado minutos antes. É indisponibilidade do Bedrock para
esses modelos menores, **não veredicto de capacidade**. Registrado porque, para um
Plano B de produção, disponibilidade de endpoint é critério de seleção por si só.

---

## Auditoria de paridade (portão da Fase B)

O braço de controle reproduz o gate real de produção
(`label.json.agent1_confidence`), medido **por detecção** — 30 eventos TP colapsam em
16 detecções e as caudas coalescidas herdam a confiança do pai:

| métrica | Camp 48 | Camp 47 |
|---|---|---|
| gate igual ao de prod | **13/15 (87%)** | 15/16 (94%) |
| disposal confirmado | **14/15 (93%)** | 87,5% |

Uma primeira versão deste check comparava **por evento** e mediu 79%, reprovando um
harness que estava correto — o erro era a unidade, não a janela.

---

## Resultados — Fase B

13 braços × 122 eventos = **1.586 chamadas, zero erros**.

| braço | recall/det | precisão* | FP/det | baseline-fire | $/ev | p50 | critérios |
|---|---|---|---|---|---|---|---|
| `magistral-small:casc_g3_low` | 100.0% (16/16) | 32.7% | 89.3% (25/28) | 20.0% (8/40) | 0.00789 | 26.1 s | reprova |
| `kimi-k2.5:single_g3_low` | 100.0% (16/16) | 32.7% | 89.3% (25/28) | 20.0% (8/40) | 0.00658 | 12.0 s | reprova |
| `magistral-small:single_g3_low` | 100.0% (16/16) | 19.0% | 100.0% (28/28) | 100.0% (40/40) | 0.00494 | 16.6 s | reprova |
| `kimi-k2.5:single_g3_mosaic` | 100.0% (16/16) | 30.8% | 85.7% (24/28) | 30.0% (12/40) | 0.00461 | 7.9 s | reprova |
| `magistral-small:single_g3_mosaic` | 100.0% (16/16) | 19.0% | 100.0% (28/28) | 100.0% (40/40) | 0.00306 | 9.4 s | reprova |
| `kimi-k2.5:casc_g3_low` | 93.8% (15/16) | 37.5% | 75.0% (21/28) | 10.0% (4/40) | 0.00984 | 19.5 s | **passa** |
| `magistral-small:casc_v1_low` | 93.8% (15/16) | 34.1% | 85.7% (24/28) | 12.5% (5/40) | 0.00732 | 24.0 s | reprova |
| `kimi-k2.5:casc_v1_low` | 87.5% (14/16) | 38.9% | 64.3% (18/28) | 10.0% (4/40) | 0.00874 | 15.8 s | **passa** |
| **`current` (controle)** | 87.5% (14/16) | 51.9% | 46.4% (13/28) | 0.0% (0/40) | 0.00725 | 18.5 s | **passa** |
| `qwen3-vl-235b:casc_g3_low` | 87.5% (14/16) | 42.4% | 50.0% (14/28) | 12.5% (5/40) | 0.00666 | 18.7 s | reprova |
| `qwen3-vl-235b:single_g3_low` | 81.2% (13/16) | 37.1% | 60.7% (17/28) | 12.5% (5/40) | 0.00459 | 15.0 s | reprova |
| `qwen3-vl-235b:casc_v1_low` | 75.0% (12/16) | 50.0% | 35.7% (10/28) | 5.0% (2/40) | 0.00540 | 11.0 s | reprova |
| `qwen3-vl-235b:single_g3_mosaic` | 75.0% (12/16) | 34.3% | 60.7% (17/28) | 15.0% (6/40) | 0.00316 | 10.3 s | reprova |

\* precisão = TPs disparados / total de disparos (tp + fp + baseline), nível detecção.
Não é precisão de produção (o conjunto `fp` é enviesado), mas é comparável **entre
braços** porque todos veem os mesmos eventos.

### O padrão

Cinco braços atingem **100% de recall** — e todos pagam caro por isso. Os dois
`magistral-small:single_*` disparam em **40/40 baselines e 28/28 FPs**: recall
perfeito por dizer sim a tudo, o mesmo colapso degenerado que cortou os dois gemma
na Fase A. Tirar o gate esparso leva o recall ao teto e destrói a especificidade —
**exatamente o que o Camp 47 observou com o Gemini-3** (`unified_single`: 100% recall,
77% FP, 27,5% baseline-fire). O achado se reproduz num fornecedor e numa família de
modelos completamente diferentes, o que sugere que é propriedade da tarefa, não do
Gemini: o gate de 5 frames não é só um filtro de custo, é o que segura o FP.

O controle tem a **melhor precisão dos 13 braços** (51,9%) e é o **único com
baseline-fire zero**.

### Apenas dois braços Bedrock atendem aos critérios pré-registrados

(recall/det ≥85% **e** baseline-fire ≤10%)

| braço | recall | precisão | $/ev | vs controle |
|---|---|---|---|---|
| `kimi-k2.5:casc_g3_low` | 93,8% (+6,3 pp) | 37,5% (**−14,4 pp**) | 0,00984 (**+36%**) | troca precisão por recall |
| `kimi-k2.5:casc_v1_low` | 87,5% (empate) | 38,9% (**−13,0 pp**) | 0,00874 (**+21%**) | pior em tudo |
| `current` | 87,5% | **51,9%** | **0,00725** | — |

Em números operacionais: o `kimi:casc_g3_low` recupera **1 detecção TP a mais** (15 de
16 contra 14) e em troca gera **8 alarmes falsos a mais** (21 FP + 4 baseline contra
13 FP + 0 baseline).

### O caso do qwen3-vl-235b

`qwen3-vl-235b:casc_v1_low` é o único candidato mais **específico** que o controle:
35,7% de FP contra 46,4%, com apenas 2/40 baseline-fires. Mas a 75% de recall — 12,5 pp
abaixo. Com o prompt g3 ele sobe para 87,5% de recall (empatando o controle) e
mantém FP em 50%, mas o baseline-fire vai a 12,5% e reprova por 2,5 pp. É o perfil que
mais merece um segundo olhar, porque erra na direção conservadora — a que não gera
trabalho para o operador.

---

## Decisão

**NÃO migrar para nenhum VLM open-weight do Bedrock. O `unified_low_2s` do Gemini-3
segue como Plano B único para 16/out/2026.**

Nenhum dos 13 braços domina o pipeline atual. O melhor candidato compra +6,3 pp de
recall com −14,4 pp de precisão e +36% de custo — e num sistema cujo gargalo declarado
é FP em Mangabeira (16 campanhas, 37 alavancas), pagar precisão por recall é o
trade-off errado.

Três achados que sobrevivem à decisão negativa:

1. **O teto de payload do Bedrock (4 MB de corpo) inviabiliza paridade com prod.**
   Qualquer migração futura para lá exige repensar a janela, não só o modelo.
2. **O gate esparso é o que segura o FP**, e isso se confirmou em dois fornecedores
   independentes. Reforça a arquitetura de cascade contra a tentação do single-call.
3. **O `qwen3-vl-235b` erra conservador.** Se algum dia o objetivo virar
   especificidade (e não recall), ele é o ponto de partida — não o kimi.

### Custo real do pipeline atual: correção de ~7×

O runner do Camp 47 precifica `gemini-2.5-flash` a (0,15 / 0,60) por 1M
(`bench_picam.py:351`); a tabela de produção (`detector_gemini._MODEL_PRICES`:676) usa
**(0,30 / 2,50)**, que é a tarifa pública real. Como *thinking* é cobrado como output e
o detail pensa ~3,3k tokens/evento, o erro se concentra onde mais pesa.

| caminho | tok_in | tok_out | thinking | tabela prod | tabela camp 47 |
|---|---|---|---|---|---|
| gate + detail | 10.458 | 588 | 3.318 | **0,01290** | 0,00391 |
| só gate | 2.016 | 207 | 717 | **0,00291** | 0,00086 |

O `$0,00099/ev` publicado no Camp 47 corresponde ao caminho *só-gate* na tabela errada
— nunca representou o cascade completo. **O custo real é US$ 0,00725/evento.**

Consequência que inverte uma conclusão registrada: o `unified_low_2s` do Gemini-3
(~US$ 0,0025/ev, preço do `3.1-flash-lite`, idêntico nas duas tabelas) não é "2,5×
mais caro que o atual" — é **~3× mais barato**. Isso *fortalece* o caso do Gemini-3
como Plano B.

### Custo da campanha

| fase | fornecedor | chamadas | US$ |
|---|---|---|---|
| Fase A (screen, 8 candidatos) | Bedrock | 126 | 0,42 |
| Fase B | Bedrock | 1.464 | ~9,3 |
| Fase B — controle + auditoria | Gemini (Saira-Testes) | 152 | 1,22 |
| **total** | | **1.742** | **~10,9** |

Orçado no plano: US$ 30-60. Ficou em ~1/3 porque os finalistas saíram baratos
(`pixtral-large`, a US$ 2/6 por M, nunca chegou à Fase B) e o modo `low` cortou os
tokens de imagem, que são ~90% do input numa janela CCTV.

⚠️ **Reconciliação de custo PENDENTE.** O Cost Explorer da conta `codex-ops` ainda
reporta US$ 0,00 para 30/07 — o faturamento AWS atrasa 24-48h. Os números acima são
**estimados a partir dos tokens** com a tabela da AWS Pricing API. Re-rodar em
01-02/08:

```bash
aws ce get-cost-and-usage --profile codex-ops   --time-period Start=2026-07-30,End=2026-07-31 --granularity DAILY   --metrics UnblendedCost   --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon Bedrock"]}}'
```

Divergência >20% significa que a tabela de preço está errada, não a medição.


## Caveats

- **N pequeno**: 16 detecções TP. Diferenças <10pp não são significativas.
- O conjunto `fp` são os FPs do **modelo atual** → `fp_rate` mede re-disparo, não
  especificidade pura. `baseline` (40 eventos, nunca vistos por modelo nenhum) é o
  sinal limpo.
- Os 40 baseline vêm todos de 22/07 — não fazer corte temporal ingênuo.
- A validação da Fase 0 foi **global** (operador aprovou os 122 de uma vez), não
  evento-a-evento. `evt-20260715_085108` (van) segue com rótulo ambíguo.
- Nenhum braço Bedrock roda em resolução original — é impossível pelo teto de 4 MB do
  endpoint. A comparação com o controle Gemini tem essa assimetria embutida.
- Preço `flex` do Bedrock é ~metade do on-demand; medimos on-demand para a latência
  ser comparável.
- **Bug latente de prod encontrado de passagem** (não corrigido): `build_mosaic_4x3`
  trunca em 12 frames (`mosaic.py:94`), então `GEMINI_MOSAIC_AGENT2=4x3` numa janela
  de 48 mostraria só os 12 primeiros. Está `off` na pi-cam-001, mas é armadilha para
  quem ligar. O braço de mosaico desta campanha fatia em folhas de 12 com
  `label_offset` contínuo.
