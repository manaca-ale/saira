# Campanha 54 — plano de rollout para janeiro de 2027 (funil A)

Escrito em 21/11/2026 (missão 11, slot `noiteA`). Funil escolhido pelo Alexandre em 21/11 às 17:03: **A, "por enquanto"**. Nada daqui foi aplicado em test nem em produção. Números em `results/final54__aval.md` (avaliação, uma rodada) e `results/finalistas54__dev.md` (configuração congelada).

## O funil

| Etapa | Hoje | Funil A |
|---|---|---|
| Filtro antes do gate | não há | Decisions `gemini-decision-1`, pergunta `wl_v2`, os 5 frames do gate em `low`; segue se a nota for ≥ 0,30 |
| Gate | `gemini-2.5-flash-lite`, V1, thinking 2048 (Vertex) | Amazon Nova Lite no Bedrock, prompt `v1p`, 640 px; dispara com `new_litter` e confiança ≥ 85 |
| Detail | `gemini-2.5-flash`, V1 (Vertex) | `gemini-3.8-flash`, prompt `g3`, thinking `low`, mídia `low` (Vertex) |

Por que mudar, mesmo com o projeto parado: no Vertex, o gate e o detail de hoje têm aposentadoria oficial em 20/10/2026 (já passou; respondiam em 18/11) e podem parar sem aviso.

## O que foi medido (pi-cam-001, 14/07 a 08/09/2026, conjunto de avaliação de 2.964 eventos)

| Funil | Confirmadas | Rejeitadas | Alertas por 1.000 [95%] | Custo por evento contra hoje |
|---|---|---|---|---|
| Hoje refeito no replay | 32 de 47 | 50 de 100 | 16,7 [13,3 a 20,6] | −51% (filtro + gate e detail de hoje) |
| **A** | **30 de 47** | **35 de 100** | **17,6 [13,7 a 21,9]** | **−17% a −23%** |
| B (alternativa: 3.1-flash-lite + 3.8-flash) | 37 de 47 | 44 de 100 | 26,8 [21,7 a 32,4] | −12% a −17% |

- A × hoje refeito: empate nas confirmadas (7 × 9 nos pares, p = 0,80) e nos alertas; menos rejeitadas (p = 0,04).
- A × B: o B mantém mais confirmadas (8 × 1, p = 0,04) e levanta cerca de 10 alertas a mais por 1.000 eventos, a maioria falsos pela leitura a olho (catador, latão, revirar à noite).
- Nenhum funil chega a 90% das confirmadas de produção no replay, nem o gate de hoje refeito (68%). O número absoluto é do replay; a comparação entre funis é o que vale.

## Pré-requisitos (decisões e ações do Alexandre)

1. **Código**: PR #93 (detail configurável) e PR #95 (filtro, gate Bedrock, gate Gemini 3; empilhado no #93) revisados e mesclados em `develop`/`main`. Com as variáveis vazias, o worker faz o que faz hoje (285 testes passam no #95).
2. **Chave do AI Studio para o Decisions** (`GATE_PREFILTER_API_KEY`): o Decisions só existe na API do AI Studio, mesmo com o resto no Vertex. Usar uma chave nova, não as que apareceram em conversa.
3. **Bedrock**: permissão `bedrock:InvokeModel` no `amazon.nova-lite-v1:0` para a credencial AWS do worker, na região de `SHADOW_BEDROCK_REGION`; e a decisão de contrato de mandar os 5 frames do gate para a AWS.
4. **Troca das chaves expostas** (pendências 2 e 3 do handoff).

## Ordem

Cada passo só começa se o anterior passou no critério. Tudo pela pi-cam (`*_DEVICES` com o id dela); em janeiro todas as câmeras são do tipo dela.

**Passo 1 — detail novo (semana 1).** Variáveis do `ROLLOUT.md` da campanha 53: `GEMINI_MODEL=gemini-3.8-flash`, `GEMINI_DETAIL_PROMPT_VERSION=g3`, `GEMINI_DETAIL_THINKING_LEVEL=low`, `GEMINI_DETAIL_MEDIA_RESOLUTION=low`, `GEMINI_REQUIRE_BBOX=false`, **`GEMINI_TIMEOUT_SECONDS=90`**. O timeout é obrigatório: no Vertex o 3.8-flash teve p50 20,0 s e p90 46,8 s; dos 58 detalhes medidos, 8 passaram de 45 s (o corte de hoje) e 1 de 90 s. Com 45 s, uma em sete chamadas daria timeout e seria paga duas vezes.
Critério: erro do detail abaixo de 2% no `gemini_call_log`; custo por chamada perto de US$ 0,019.

**Passo 2 — filtro só registrando (semana 1, junto).** `GATE_PREFILTER_ENABLED=true`, `GATE_PREFILTER_DEVICES=<pi-cam>`, `GATE_PREFILTER_LOG_ONLY=true` (padrão). O filtro chama, grava a nota e não barra nada.
Critério: nota ≥ 0,30 em cerca de 15% a 30% das janelas avaliadas pelo gate (no replay: 839 de 2.964 eventos da avaliação, 28%, contando todos os confirmados; a amostra tem mais eventos com detecção que a produção); nenhuma confirmada pelo operador com nota abaixo de 0,30 (no replay o filtro barrou 2 de 72 eventos confirmados); erro do Decisions abaixo de 1%; custo do filtro perto de US$ 0,00017 por janela.

**Passo 3 — filtro barrando e gate Nova Lite (semana 2).** `GATE_PREFILTER_LOG_ONLY=false`, `GATE_BEDROCK_ENABLED=true`, `GATE_BEDROCK_DEVICES=<pi-cam>`. Nunca ligar o Bedrock sem o filtro barrando: o Nova Lite só foi medido atrás dele. `GATE_BEDROCK_FALLBACK_GEMINI=true` (padrão): se o Bedrock falhar, o gate Gemini configurado assume.
Critério, depois de 2 semanas: alertas por 1.000 eventos dentro de 13 a 22 (o A mediu 17,6); confirmadas pelo operador por semana sem queda clara contra as semanas de julho a setembro; p90 do gate Nova abaixo de 8 s (medido: 4,0 e 6,1 s); queda para o Gemini em menos de 2% das janelas; custo por evento abaixo de US$ 0,00133 (o de hoje).

**Gate Gemini de reserva.** O gate de hoje (`gemini-2.5-flash-lite`) é o que assume quando o Bedrock falha, e ele está aposentado no Vertex. Quando parar de responder, trocar a reserva pelo gate do B: `GEMINI_AGENT1_MODEL=gemini-3.1-flash-lite`, `GEMINI_AGENT1_THINKING_LEVEL=minimal`, `GEMINI_AGENT1_MEDIA_RESOLUTION=low`, `GEMINI_GATE_PROMPT_VARIANT=v1p`. Essas variáveis valem para todas as câmeras com o gate V1. O `gemini-3.1-flash-lite` tem desligamento anunciado no AI Studio em 07/05/2027; conferir a data no Vertex antes.

## Como voltar atrás

Cada etapa desliga sozinha pela variável: `GATE_BEDROCK_ENABLED=false` volta ao gate Gemini; `GATE_PREFILTER_ENABLED=false` (ou `GATE_PREFILTER_LOG_ONLY=true`) tira o filtro; o detail volta pelas variáveis antigas do `ROLLOUT.md` da campanha 53, enquanto o `gemini-2.5-flash` responder.

## Ajustes feitos no worker depois da medição (PR #95)

- Corte de cada tentativa do Bedrock em 15 s (`GATE_BEDROCK_ATTEMPT_TIMEOUT_S`); antes valiam os 60 s do shadow. Só pesa quando há falha.
- **Janela barrada pelo filtro mantém o aviso da janela anterior** (decisão de 21/11, com dados): a missão 9 propôs zerar o aviso nesse caso, mas em produção o gate mandou o aviso "a janela anterior já tinha lixo" em 98,7% das chamadas da pi-cam e em 98,6% das janelas logo depois de uma que o filtro barraria (`scripts/probe_prior_after_skip54.py`). Zerar afastaria o worker do que foi medido.

## Riscos e limites

- **Uma câmera, um período, 47 confirmadas.** A régua da medição final (finalista ≥ controle − 2) barra desastre, não perda moderada; a margem de 30 de 47 vai de cerca de 50% a 76%.
- **Plataforma.** O replay rodou na API do AI Studio; no Vertex o detail 3.8-flash concordou em 54 de 57 eventos e manteve as mesmas 30 confirmadas, mas só os S2C foram repetidos lá.
- **Latência do detail no Vertex** (p90 46,8 s, máximo 345 s), resolvida pelo timeout de 90 s; a nova tentativa depois do timeout é paga.
- **Dois fornecedores novos** no caminho de produção (API de Decisões do AI Studio e AWS Bedrock), cada um com credencial, cota e falha próprias. O worker falha aberto nos dois (sem filtro, a janela vai ao gate; sem Bedrock, ao gate Gemini).
- **Se o objetivo virar detectar mais**, o B é a alternativa medida: mais 7 confirmadas em 47 e cerca de 10 alertas a mais por 1.000 eventos, tudo no Google.
