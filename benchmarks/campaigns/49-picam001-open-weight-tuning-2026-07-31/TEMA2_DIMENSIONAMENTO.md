# Tema 2 — Dimensionamento e custo self-hosted (30–31/07/2026)

Responde ao `HANDOFF_SELF_HOSTED.md`. **Tudo aqui é medido**, exceto o que está
explicitamente marcado como estimativa. Fontes: `gemini_call_log` de PRODUÇÃO (30 d,
somente-leitura), AWS Pricing API e `describe_spot_price_history` na conta `codex-ops`.

---

## 1. A linha de base do handoff estava errada por 10×

| | handoff | **medido** | erro |
|---|---|---|---|
| custo por evento | US$ 0,00725 | **US$ 0,002204** | 3,3× |
| eventos/dia (`pi-cam-001`) | ~600 | **300,7** | 2,0× |
| **100 câmeras/mês** | **~US$ 13.050** | **US$ 1.278** | **10,2×** |
| tokens de entrada/dia (100 cam) | 540 M | ~94 M | 5,7× |

Medido em 34.774 eventos / 76,66 USD / 6 câmeras / 30 dias.

**Por que a diferença.** O `US$ 0,00725` é o custo de um evento que roda **gate + detail**
— o que acontece em quase todo evento do *dataset* de bench, e em quase nenhum evento de
*produção*. Em tráfego real o gate mata a maioria a US$ 0,001:

| device | gate (chamadas · US$/chamada) | detail (chamadas · US$/chamada) | % que chega ao detail | US$/evento |
|---|---|---|---|---|
| `pi-cam-001` | 9.022 · 0,001016 | 345 · 0,009562 | **3,8%** | **0,001382** |
| `esp32_002` | 9.778 · 0,001460 | 1.702 · 0,012467 | 17,4% | 0,003659 |
| frota (6 cam) | 34.775 · — | 3.140 · — | 9,0% | **0,002204** |

O `estimated_cost_usd` do banco é confiável: soma `thinking_tokens` na taxa de output
([detector_gemini.py:718](../../../services/yolo-worker-vm/src/worker/detector_gemini.py))
e usa a tabela de preço de produção (2.5-flash = 0,30/2,50). Não há subestimação escondida.
⚠️ Já a coluna `output_tokens` **exclui** thinking — não usar essa coluna para custo.

**Consequência:** toda comparação contra US$ 0,00725/ev favorece indevidamente arquiteturas
de chamada única, que pagam a janela cheia em **todo** evento e não têm caminho barato.

---

## 2. Carga real: o pico é 6,5× a média

Eventos/hora, 30 dias, hora local de Brasília:

| escopo | média/h | p50 | p95 | p99 | **máx** |
|---|---|---|---|---|---|
| `pi-cam-001` | 23,5 | 24 | 41 | 57 | 130 |
| **frota (6 cam)** | **48,3** | 42 | **88** | **230** | **313** |

Escalado linearmente para 100 câmeras:

| | eventos/s |
|---|---|
| média | 0,22 |
| p95 | 0,41 |
| p99 | 1,07 |
| **pico (máx medido)** | **1,45** |

O pico concentra-se às **16h–18h** (17h é a hora mais movimentada em 30 dias) — descarte
tem hora do dia, e isso é **correlacionado entre câmeras**. Por isso escalar o pico
linearmente é a hipótese conservadora correta: se os picos decorrelacionassem, o agregado
cresceria mais devagar que linear, nunca mais rápido.

**Implicação de dimensionamento:** uma GPU dimensionada pela média (0,22 ev/s) fica
**6,5× subdimensionada** no pico. E a ociosidade é o espelho disso — a GPU fica parada a
maior parte do dia, enquanto o gerenciado só cobra o que usa.

---

## 3. Preço real das GPUs (AWS Pricing API, us-east-1, Linux, shared)

`$/mês` = tarifa × 730 h.

| instância | GPU | on-demand $/h | **$/mês OD** | RI 1a NU $/h | **$/mês RI** | spot médio 7 d $/h | **$/mês spot** |
|---|---|---|---|---|---|---|---|
| `g6.xlarge` | 1× L4 24 GB | 0,8048 | 588 | 0,5239 | **382** | 0,6330 | 462 |
| `g5.xlarge` | 1× A10G 24 GB | 1,0060 | 734 | 0,6338 | 463 | 0,6665 | 487 |
| `g6e.xlarge` | 1× L40S 48 GB | 1,8610 | 1.359 | 1,1724 | 856 | **1,8610** | 1.359 |
| `g6e.12xlarge` | 4× L40S 192 GB | 10,4926 | 7.660 | 6,6104 | 4.826 | 7,3770 | 5.385 |
| `p4d.24xlarge` | 8× A100 320 GB | 21,9576 | 16.030 | 13,9211 | **10.162** | 15,3640 | 11.216 |
| `p5.48xlarge` | 8× H100 640 GB | 55,0400 | 40.179 | — | — | 20,9871 | 15.321 |

Dois achados que mudam a conta:
- **RI de 1 ano sem entrada dá 35–37% em toda a linha G.** Para carga 24/7 previsível é a
  opção certa, como o handoff supunha — e agora está medido.
- **`g6e.xlarge` não tem desconto spot**: o preço spot está *pinado no on-demand* (mín =
  máx = 1,8610 em 7 dias, 4 AZs). A L40S de 1 GPU é disputada. Já a `p5.48xlarge` dá 62%
  de desconto spot — o oposto do que a intuição sugere.

EBS gp3 medido: **US$ 0,08/GB-mês**.

---

## 4. O que cada modelo exige (tamanhos confirmados)

| modelo | params | licença | VRAM int4 | VRAM int8 | instância mínima viável |
|---|---|---|---|---|---|
| **magistral-small-2509** | **24 B denso** | **Apache 2.0** | ~12 GB | ~24 GB | `g6.xlarge` (L4 24 GB) em int4 |
| **qwen3-vl-235b-a22b** | 235 B tot / 22 B ativos | Apache 2.0 | ~118 GB | ~235 GB | `p4d.24xlarge` (8× A100, 320 GB) |
| **kimi-k2.5** | **1 T tot / 32 B ativos** | Modified MIT | ~500 GB | ~1 TB | `p5.48xlarge` (8× H100, 640 GB) |

Fontes: [Magistral-Small-2509](https://huggingface.co/mistralai/Magistral-Small-2509)
(24 B, Apache 2.0, encoder de visão), [Kimi K2.5](https://comfyui-wiki.com/en/news/2026-01-27-moonshot-ai-kimi-k2-5-release)
(1 T total, 32 B ativos, 384 experts, multimodal nativo).

⚠️ Correção à tabela do handoff: ela dava "1× A10G 24 GB em int8" para o magistral. **Não
fecha** — 24 B em int8 são ~24 GB só de pesos, sem sobrar nada para KV-cache e ativações
numa placa de 24 GB. Em 24 GB o magistral roda em **int4**; para int8 é preciso os 48 GB
da L40S.

**MoE não ajuda em memória** (confirmado): todos os pesos ficam residentes; só o *compute*
por token usa poucos experts. Por isso o kimi de 32 B ativos custa uma instância de 8×
H100 para hospedar.

---

## 5. A curva de break-even

Gerenciado: **US$ 12,78 por câmera/mês** (medido; a câmera do arquétipo de expansão,
`pi-cam-001`, dá US$ 12,47 — os dois números concordam).
Self-hosted: custo **fixo**, independente do número de câmeras até saturar a GPU.

Break-even = custo fixo mensal ÷ 12,78.

| configuração | $/mês | **break-even (câmeras)** | com redundância N+1 |
|---|---|---|---|
| magistral · `g6.xlarge` RI | 382 | **30** | 60 |
| magistral · `g6.xlarge` spot | 462 | 36 | 72 |
| magistral · `g6.xlarge` OD | 588 | 46 | 92 |
| magistral · `g6e.xlarge` RI (int8) | 856 | 67 | 134 |
| magistral · `g6e.xlarge` OD | 1.359 | 106 | 213 |
| **qwen · `p4d.24xlarge` RI** | 10.162 | **795** | 1.591 |
| **kimi · `p5.48xlarge` spot** | 15.321 | **1.199** | 2.398 |
| kimi · `p5.48xlarge` OD | 40.179 | 3.145 | 6.289 |

Somando o TCO que não é a GPU (EBS 100 GB = US$ 8/mês; transferência das câmeras já existe
hoje e não muda) e uma linha **explicitamente estimada** de operação — 4 h/mês de
engenharia a ~US$ 30/h = **US$ 120/mês**, que é um piso otimista para um serviço de
inferência 24/7 — o cenário mais favorável ao self-host fica:

> magistral · `g6.xlarge` RI · N+1 · EBS · operação = 764 + 16 + 120 = **US$ 901/mês
> ⇒ break-even em 71 câmeras.**

### O baseline certo é o de DEPOIS de 16/out, não o de hoje

Comparar contra o Gemini-2.5 seria comparar contra algo que deixa de existir. O Plano B
(`gemini-3.1-flash-lite`) já roda em shadow na `pi-cam-001` e está medido no mesmo
`gemini_call_log`: 4.328 chamadas de gate a US$ 0,00108964 + 299 de detail a US$ 0,00252892
⇒ **US$ 0,001264/evento, 8,5% MAIS BARATO que o 2.5**.

Ou seja: o alvo não afrouxa em outubro, aperta. Para 100 câmeras do arquétipo de expansão
(300,7 ev/dia):

| opção | US$/evento | **100 câmeras/mês** |
|---|---|---|
| Gemini 2.5 (hoje) | 0,001382 | 1.247 |
| **Gemini 3.1-flash-lite (Plano B)** | **0,001264** | **1.141** |
| kimi via Bedrock (shadow em prod) | 0,00546 | 4.925 |
| **self-host magistral** (`g6.xlarge` RI) | — | **382** |
| **self-host kimi** (`p5.48xlarge` spot) | — | **15.321** |

---

## 6. Conclusão

**A 100 câmeras, o self-host só ganha para o modelo que não serve.**

1. **kimi e qwen — os dois únicos com qualidade aceitável — perdem por 1 a 2 ordens de
   grandeza.** Hospedar o kimi custa **US$ 15.321/mês no melhor caso (spot)** contra
   **US$ 1.278** de fatura gerenciada: **12× mais caro**. O qwen, 8×. Não existe ajuste de
   engenharia que feche esse buraco; é consequência de precisar de 8 GPUs para segurar os
   pesos residentes.
2. **O magistral fecha a conta e não faz o serviço.** É o único hospedável barato
   (break-even 71 câmeras com redundância e operação), mas mede **36,8% de recall** contra
   94,7% da produção. Comparar o custo dos dois é comparar sistemas que não fazem o mesmo
   trabalho.
3. **A pesquisa antiga (break-even em 40–70 câmeras) estava certa pelo motivo errado.** Ela
   acertou a faixa — mas só vale para o modelo de 24 B. Para os modelos que realmente
   substituem o Gemini, o break-even está em **800–2.400 câmeras**.

### A incerteza que sobrou, e por que ela não muda a conclusão

Não foi medido o **throughput por GPU** (decisão do usuário de não gastar em instância).
Sem ele não se sabe quantas GPUs cada configuração exige no pico de **1,45 ev/s**.

Isso é uma incerteza **unidirecional**: o número que falta só pode fazer o self-host
precisar de **mais** GPUs, nunca menos. Todas as linhas da tabela são portanto **pisos** de
custo. A conclusão — kimi e qwen perdem por 8–12× — é robusta a qualquer valor plausível de
throughput, porque nenhum throughput reduz o custo de manter 8 GPUs ligadas.

Onde a incerteza **importa de verdade** é na linha do magistral: se uma L4 não aguentar
1,45 ev/s (plausível — o prefill de 23 imagens é caro), o break-even de ~70 câmeras vira
140 ou mais. Ou seja: a única linha que hoje favorece o self-host é justamente a menos
firme. Medir custaria ~US$ 3 numa `g6.xlarge` por 3 h.

### O que isso entrega ao Tema 3

Reforça o ponto do usuário, com número: o magistral é o **único** dos três que cabe numa
GPU só e o único cujo break-even fica dentro de um horizonte realista de câmeras. Se
consertar o recall dele (few-shot, prompt intermediário, ou LoRA nos 122 eventos rotulados
— que só existe no cenário self-hosted), há um caminho econômico. Se não consertar, o
self-host não tem candidato.

---

## Procedência dos números

| número | origem | tipo |
|---|---|---|
| custo/evento, % que chega ao detail, US$/câmera-mês | `gemini_call_log` prod, 30 d, SELECT | **medido** |
| eventos/dia, p50/p95/p99/máx por hora | idem | **medido** |
| preço OD / RI 1a das instâncias | AWS Pricing API `get_products` | **medido** |
| preço spot (média 7 d, todas as AZs) | `describe_spot_price_history` | **medido** |
| EBS gp3 US$ 0,08/GB-mês | AWS Pricing API | **medido** |
| params e licença dos 3 modelos | model cards / release notes | **verificado** |
| VRAM por quantização | 2/1/0,5 byte por parâmetro | **cálculo** |
| escala linear 6 → 100 câmeras | hipótese conservadora (picos correlacionados) | **projeção** |
| operação US$ 120/mês (4 h × US$ 30) | arbitrado; piso otimista | **estimativa** |
| throughput por GPU | **não medido** | **lacuna (unidirecional)** |
