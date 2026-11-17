# Camp 53 — rollout do detail novo (rascunho de 16/11/2026)

Rascunho. Os itens da seção "A conferir" ainda não foram checados contra o compose e o `.env` do servidor. Nada aqui foi aplicado em test nem em produção.

## O que muda

Só o detail. O gate fica como está (gemini-2.5-flash-lite, prompt V1).

| Variável | Valor novo | Hoje |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.8-flash` | `gemini-2.5-flash` (roteado para gemini-3.5-flash-lite em 01/12/2026) |
| `GEMINI_DETAIL_PROMPT_VERSION` | `g3` | vazio |
| `GEMINI_DETAIL_THINKING_LEVEL` | `low` | vazio |
| `GEMINI_DETAIL_MEDIA_RESOLUTION` | `low` | vazio |

Pré-requisitos:

- Código com os commits 464adb8 e 5e90e43 desta branch (sem eles as três últimas variáveis não têm efeito).
- `GEMINI_MAX_OUTPUT_TOKENS` ≥ 8192 e `GEMINI_TIMEOUT_SECONDS` ≥ 90.
- `GEMINI_DETAIL_PROMPT_VERSION` vazio no `.env` antes da troca (confirma que o ponto de partida é o medido).

## O que foi medido (picam001)

| | Reais | Falsos | "Sem ocorrência" |
|---|---|---|---|
| Hoje (`d25f_v1`, 2 repetições), oficial | 15/19 e 17/19 | 12/25 e 14/25 | 1/40 |
| Recomendado (3 repetições), oficial | 16/19 | 4/25 a 5/25 | 1/40 a 2/40 |
| Hoje, holdout | 26/44 | 18/45 | — |
| Recomendado (2 repetições), holdout | 24/44 e 25/44 | 13/45 e 15/45 | — |

Custo por evento da cascata: 4% menor que hoje com os preços atuais, 10% maior com os preços anunciados para 2027. Latência do detail menor.

## Decisão que acompanha o rollout: a regra do bbox

O worker troca um "sim" do modelo por "não" com confiança 0 quando nenhuma caixa tem entre 1% e 60% da imagem (`_validate_bbox`, com `GEMINI_REQUIRE_BBOX=true`, o padrão). O 3.8-flash desenha caixas justas, e nesta câmera uma pessoa ocupa menos de 1% do quadro. Na repetição 3, com a resposta crua gravada (`python scripts/agg_min_area.py`):

| Área mínima | Reais | Falsos | "Sem ocorrência" |
|---|---|---|---|
| 1,00% (hoje) | 16/19 | 4/25 | 2/40 |
| 0,75% | 17/19 | 4/25 | 2/40 |
| 0,50% ou menos | 18/19 | 6/25 | 2/40 |

Opções: (a) manter, vale o que foi medido; (b) `GEMINI_REQUIRE_BBOX=false`, que já existe, mas também aceita "sim" sem caixa nenhuma; (c) tornar a área mínima configurável (hoje é fixa no código) e baixar para 0,5%. O tamanho da caixa não separa real de falso: é uma troca de recall por falsos, com margem de um ou dois eventos. A decisão é do Alexandre.

## Ordem

1. Test primeiro. O `.env` do servidor é um só e o compose de teste lê as mesmas `GEMINI_*`: editar o `.env` muda os dois ambientes assim que cada container for recriado. Recriar só o worker de teste, observar, e só então recriar o de produção, com o ok do Alexandre.
2. Observar em test por pelo menos um dia: confirmações por dia contra a semana anterior; quantos details voltam com `infraction_confirmed=false` e confiança 0 (o veto); latência; erros e timeouts; custo por chamada em `gemini_call_log`.
3. Produção antes de 01/12/2026, para não passar pelo roteamento automático.

## Como voltar atrás

Devolver as quatro variáveis ao valor de hoje e recriar o worker. Até 30/11 isso volta ao comportamento atual. De 01/12 em diante `gemini-2.5-flash` passa a ser atendido pelo gemini-3.5-flash-lite: o "voltar" vira o cenário roteado (`d35l_v1_routed`, medido no bloco A), não o de hoje.

## A conferir antes de usar

- Outras câmeras: `GEMINI_MODEL` é uma variável só e vale para todas. Mangabeira e Imbiribeira ainda não foram medidas (bloco H). Até lá a recomendação vale para a picam001.
- Nomes dos serviços e comandos de recriação no servidor (test e prod).
- Valores atuais de `GEMINI_MAX_OUTPUT_TOKENS`, `GEMINI_TIMEOUT_SECONDS` e `GEMINI_REQUIRE_BBOX` em produção (leitura pendente com o Alexandre).
- Se a tabela de preços do worker conhece o `gemini-3.8-flash`, para o custo registrado em `gemini_call_log` sair certo.
- O gate Decisions (segunda proposta) não faz parte deste rollout: entra depois, em shadow.
