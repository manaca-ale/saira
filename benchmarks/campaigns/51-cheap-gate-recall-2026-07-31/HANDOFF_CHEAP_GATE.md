# HANDOFF — Camp 51: existe um gate barato que preserve recall?

> Ler primeiro numa sessão nova. Origem: sessão de 30-31/07 que subiu o shadow kimi
> (Camp 49 → `HANDOFF_SHADOW_KIMI.md`) e rodou o replay do Camp 50.

## A pergunta

O Camp 49 concluiu que **o detail é substituível e o gate não é**. A sessão de 31/07
mediu por que: o kimi em chamada única custa **3,8× a produção** porque paga a janela
cheia em 100% dos eventos, enquanto a produção só paga o detail em **3,5%**. Com
qualquer gate na frente, a economia inverte.

Daí a pergunta desta campanha:

> **Existe um modelo barato que sirva de gate — preservando os TPs e sem deixar passar
> mais FPs do que o gate atual?**

Não é "existe um modelo que decide flagrante". O gate não precisa julgar; precisa
**filtrar sem perder**. Quem julga é o detail.

## ⚠️ O que já se sabe — e desanima

**`gemma-3-4b` NUNCA foi testado.** Ele entrou nas contas de custo por ser o mais barato
do catálogo (US$ 0,04/0,08 por 1M), não por ter passado em algum teste.

O que existe é o *screen* do Camp 48, com **16-18 eventos** por modelo
(`campaigns/48-.../results/bench_bedrock_screen_summary.json`):

| modelo | n | recall TP | taxa de FP | dispara em baseline | US$/ev |
|---|---|---|---|---|---|
| gemma-3-12b | 16 (2 erros) | 100% (2/2) | **100% (5/5)** | **33% (2/6)** | 0,00092 |
| gemma-3-27b | 18 | 100% (3/3) | **100% (6/6)** | **50% (3/6)** | 0,00221 |
| ministral-3-14b | 18 | — | — | — | ver json |
| palmyra-vision-7b | 18 | — | — | teto de 5 imagens | ver json |

Os dois gemma confirmam **todo** FP e disparam em 1/3 a 1/2 das cenas vazias. n é
minúsculo e o braço era cascata completa (não isola o gate), mas o sinal é ruim.

**Consequência direta:** as linhas `gate gemma-3-4b + detail kimi` da planilha
`custos/custos_modelos_arquiteturas_2026-07-31.xlsx` (US$ 0,000428 e US$ 0,001047/evento)
assumem que o gate barato reproduz a seletividade do Gemini (3,5% / 11,2% de passagem).
**Essa premissa é o que esta campanha existe para testar, e a evidência atual sugere que
é falsa.** Não citar aqueles números como se fossem medidos.

## Critério de aceite (o pedido do usuário, literal)

> "O foco é manter os TPs e não criar novos FPs, principalmente."

Traduzindo em métrica — e a ordem importa:

1. **Recall do gate ≥ 100% do gate atual.** De todo evento que vira TP confirmado pelo
   operador, o gate candidato tem que deixar passar. Perder um TP no gate é definitivo:
   o detail nunca vê. Este é o critério eliminatório.
2. **FP de ponta a ponta ≤ o de hoje.** Dos eventos que o operador REJEITOU, a
   combinação `gate barato + detail kimi` não pode confirmar mais que a produção.
3. **Taxa de passagem** — é o que paga a conta. Para a arquitetura empatar com a produção
   (US$ 0,00134/ev) com o kimi a US$ 0,00804 no detail, a passagem precisa ficar
   **abaixo de ~15%**. Acima de 25% o candidato perde para o Gemini e não interessa.
4. **Disponibilidade**: 0 erro em ≥500 chamadas. O Camp 49 viu 3 de 6 open-weight caírem
   em 24 h; o Camp 48 viu o gemma-3-12b errar 2 de 18.

Um candidato que corte custo mas perca 1 TP está **reprovado**. Nesta câmera o problema
declarado é recall.

## Insumo que já existe — não refazer

| ativo | onde | o que dá |
|---|---|---|
| Dataset oficial `cam_picam001` | `data/datasets/official/cam_picam001/` | 122 eventos, **rótulos revisados por humano** na Fase 0 do Camp 49: 35 tp · 32 fp · 40 baseline · 15 ind |
| **Replay Camp 50** | `data/camp50_gate_kimi.jsonl` (nesta pasta) | **287 eventos de tráfego real** com a decisão do detail kimi já computada + status do operador. Roda a simulação de gate **de graça**: basta ver quais desses o candidato deixaria passar |
| Ledger do shadow 3.1 | prod: `STATE_DIR/shadow_model_audit/` | 4.190 eventos com cena e decisão do gate 3.1 (2 fases de prompt — filtrar por `prompt`) |
| Cliente Bedrock | `services/yolo-worker-vm/src/worker/detector_bedrock.py` | Já em produção: teto de payload, degradação tool→texto, deadline, breaker |
| Runner | `campaigns/49-.../scripts/bench_bedrock.py` | Arms/perfis, janela idêntica à prod, resumível |
| Prompts | `campaigns/49-.../scripts/_prompts_v4picam.py`, `worker/_prompts_g3.py` | V4 (flagrante+catador) e g3 (recall-first) |

## Linha de base a bater (medida, não estimada)

| gate | passa | recall (do que o operador confirmou) | US$/chamada |
|---|---|---|---|
| **produção 2.5-flash-lite (V1)** | **3,5%** | referência | 0,000998 |
| gemini-3.1-flash-lite + prompt **g3** | 11,2% | **86% (51/59)** | 0,001089 |
| gemini-3.1-flash-lite + prompt `current` | 0,7% | **28% (5/18)** | 0,001089 |

O prompt muda o gate mais que o modelo — mesmo 3.1, 28% contra 86% de recall. **Qualquer
candidato tem que ser testado com prompt recall-first, não com o V1 nem com o V4.**

## Desenho sugerido

**Fase 0 — simulação grátis (fazer primeiro, custa ~US$ 2)**
Rodar só o *gate* dos candidatos sobre os 287 eventos do `camp50_gate_kimi.jsonl`. O
detail do kimi já está decidido ali, então dá para montar a matriz completa
(gate passa × kimi confirma × operador) sem uma única chamada de detail. Se o candidato
já falhar aqui, para por aqui.

**Fase 1 — dataset oficial (122 eventos, rótulo humano)**
Os que sobreviverem rodam no `cam_picam001`, que tem baseline de verdade (40 eventos) —
é onde se mede se o gate dispara em cena vazia.

**Candidatos**, do mais barato ao mais caro:

| alias | US$/1M in | US$/1M out | situação |
|---|---|---|---|
| `gemma-3-4b` | 0,04 | 0,08 | **nunca testado** |
| `nemotron-nano-12b` | 0,06 | 0,23 | ⚠️ indisponibilidade no Camp 48 |
| `gemma-3-12b` | 0,09 | 0,29 | screen ruim (n=16) |
| `ministral-3-14b` | 0,20 | 0,20 | screen n=18, ver json |
| `gemini-3.1-flash-lite` | 0,125 | 0,75 | **referência a bater**, 86% recall |

---

## 🔑 O QUE JÁ ESTÁ MEDIDO — reprocessado em 31/07, sem gastar nada

Os braços de **cascata** dos camps 48/49 gravaram `gate_fire` por evento. Isso é a decisão
do GATE isolada, e ninguém tinha olhado. (Os braços `single` **não** servem: ali o runner
aliasa `gate_fire = disposal`.)

**Camp 48 — 122 eventos, rótulos antigos (30 tp / 37 fp / 40 baseline):**

| gate | passa TP | passa FP | passa baseline | passa tudo | US$/chamada |
|---|---|---|---|---|---|
| **magistral-small + g3** | **30/30 · 100%** | 86% | 20% | 67% | 0,00194 |
| **kimi-k2.5 + g3** | 29/30 · 97% | 84% | 12% | 63% | 0,00257 |
| kimi-k2.5 + v1 | 28/30 · 93% | 70% | 10% | 53% | 0,00257 |
| magistral-small + v1 | 28/30 · 93% | 86% | 12% | 62% | 0,00194 |
| qwen3-vl-235b + g3 | 27/30 · 90% | 68% | 15% | 55% | 0,00227 |
| **`current` — Gemini, CONTROLE** | **26/30 · 87%** | 62% | **5%** | 51% | **0,00100** |
| qwen3-vl-235b + v1 | 21/30 · 70% | 41% | 5% | 35% | 0,00227 |

**Camp 49 — 122 eventos, rótulos revisados, prompt V4:** todos desabam.
`kimi:v4_casc_5f` 57% · `kimi:v4_casc` 54% · `magistral:v4_casc` 26% · `magistral:v4_casc_5f`
20%, contra 86% do controle. **O V4 é veneno para gate open-weight.**

### Três conclusões que mudam o desenho

1. **Cinco modelos já batem o gate do Gemini em recall.** O `magistral-small` com g3 é o
   único que não perdeu **nenhum** TP (30/30), e teve 0 erro nos dois camps.
2. **O prompt domina o modelo.** O mesmo magistral: v1 → 93%, g3 → 100%, V4 → 26%. Testar
   candidato novo com prompt errado é desperdiçar a campanha. **Usar g3 como base.**
3. **Os que funcionam não são baratos e os baratos não funcionam.** magistral 0,00194,
   kimi 0,00257, qwen 0,00227 — todos acima do gate Gemini (0,00100). Os gemma são
   baratos (0,00035 e 0,00083) e são justamente os que disparam em 33-50% de baseline.

⚠️ **A coluna "passa tudo" NÃO é taxa de passagem de produção.** O dataset é enriquecido:
67 dos 122 eventos são casos que a produção confirmou, contra ~1% no tráfego real. Por
isso o controle Gemini aparece com 51% ali e passa 3,5% em prod. Para extrapolar, use a
razão de disparo em **baseline** (Gemini 5% ↔ 3,5% em prod) — magistral a 20% daria ~14%
de passagem, kimi-g3 a 12% daria ~8%. **É estimativa com premissa declarada, não medição.**

### Custo estimado das arquiteturas com esses gates

| arquitetura | US$/evento | vs produção |
|---|---|---|
| gate Gemini-3.1-g3 + detail kimi | 0,00199 | 1,49× |
| gate magistral-g3 + detail kimi | ~0,00307 | ~2,3× |
| gate kimi-g3 + detail kimi | ~0,00324 | ~2,4× |

Ou seja: **nenhum gate open-weight já testado é mais barato que o Gemini.** A campanha só
se justifica se um modelo ainda não testado (gemma-3-4b, nemotron-nano) sustentar recall.
Se a resposta for não, a pergunta muda de "como baratear" para "vale pagar 1,5× por um
Plano B que não depende do Google" — que é decisão de orçamento, não de engenharia.

### Reordenação sugerida da campanha

Testar **primeiro** `gemma-3-4b` e `nemotron-nano-12b` com prompt g3 na Fase 0. São os
dois únicos que poderiam mudar a conclusão. Se ambos falharem, **encerrar a campanha** e
registrar `magistral-small + g3` como o gate open-weight de melhor recall já medido
(100%), a ser usado se a prioridade for recall e não custo.

⚠️ `gemma-3-4b` não está na tabela `MODELS` do `worker/detector_bedrock.py` (só kimi e
magistral sobreviveram ao porte). Está em
`campaigns/49-.../scripts/_bedrock_client.py`. Adicionar ao registro do bench, **não** ao
worker.

**Entrada do gate**: 5 quadros (1º + 3 mid + último), 640px q70 — igual à prod.
Não mandar a janela cheia: o custo do gate é o ponto.

## O prompt do gate é a variável principal — e há uma pista nova

O gate candidato **não deve** receber o prompt de flagrante. Pista de 31/07, de um FN
real (`evt-20260731_052742`, homem deposita móvel com carroça e sai vazio):

- **gate V1 rejeitou** — *"No vehicles are stopped"*: o schema V1 exige veículo parado.
- **gate V4 rejeitou com confiança 90** — a cláusula de catador **inverteu a direção do
  material** e leu deposição como coleta.
- **detail V1 e V4 confirmaram** (98 e 95).

Ou seja: os dois prompts sofisticados erram no gate, e o detail acerta sozinho. Sugestão
forte para esta campanha: escrever um **prompt de gate mínimo**, que responda a pergunta
fácil —

> "Alguma pessoa, veículo ou carroça INTERAGE com a zona da pilha nesta janela?
> Não julgue se houve descarte."

— e deixar o julgamento inteiro para o kimi. É a pergunta que um modelo de 4B tem chance
de acertar; "houve flagrante?" não é.

## Armadilhas registradas (não repetir)

- **Circularidade**: "o operador rejeitou" só existe para eventos em que a **produção
  criou detecção**. Um gate que recupera algo que a produção jogou fora não tem rótulo.
  O Camp 48 já marcou `baseline_fire` como métrica circular — *"nunca usar para reprovar
  candidato"*. Os 287 do Camp 50 têm **87 positivos do kimi sem rótulo**; eles são lista
  de revisão humana, não numerador.
- **Sub-amostrar invalida** (camps 20/21). A janela tem que ser a mesma da prod.
- **`toolConfig` é aceito e ignorado** por vários modelos — o gemma devolveu `confidence`
  em vez de `confidence_0_100`. Usar `force_mode="text"`.
- **Teto de payload do Bedrock**: 4 MB de corpo (~2,7 MB de imagem crua). Com 5 quadros a
  640px não chega perto, mas o `n_dropped` tem que ser logado assim mesmo.
- **Custo**: somar thinking ao output. E no Cost Explorer filtrar `RECORD_TYPE=Usage` —
  a conta `codex-ops` roda em crédito e sem esse filtro tudo aparece como US$ 0.

## Orçamento

Fase 0: ~287 × 5 candidatos × US$ 0,0002 ≈ **US$ 0,30**.
Fase 1: 122 × sobreviventes ≈ **US$ 1-2**.
Cabe no crédito AWS (saldo ~US$ 8.356) sem discussão.

## Definition of Done

1. Tabela recall-do-gate × taxa-de-passagem para cada candidato, nas duas fases.
2. Veredito explícito por candidato contra os 4 critérios de aceite.
3. Se algum passar: custo/evento da arquitetura completa recalculado e a planilha
   `custos/custos_modelos_arquiteturas_2026-07-31.xlsx` atualizada, trocando as duas
   linhas ESTIMADAS de `gate gemma-3-4b` por medidas.
4. Se nenhum passar: registrar na memória que gate barato open-weight está **descartado**
   e que o Plano B de 16/out é gate Gemini-3.1 + detail kimi (US$ 0,00199/ev, 1,49× a
   produção de hoje) — e aí a conversa vira orçamento, não engenharia.
