# Camp 53 — rollout do detail novo (17/11/2026)

Conferido contra os composes, o `config.py` e o `deploy.yml` desta branch. O `.env` do servidor não foi lido: o que depende dele está em "Ler em produção antes de aplicar". Nada aqui foi aplicado em test nem em produção. Números e método no [`report.md`](report.md).

## O que muda

Só o detail. O gate fica como está (gemini-2.5-flash-lite, prompt V1).

| Variável | Valor novo | Hoje |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.8-flash` | `gemini-2.5-flash` (roteado para gemini-3.5-flash-lite em 01/12/2026) |
| `GEMINI_DETAIL_PROMPT_VERSION` | `g3` | vazio |
| `GEMINI_DETAIL_THINKING_LEVEL` | `low` | vazio |
| `GEMINI_DETAIL_MEDIA_RESOLUTION` | `low` | vazio |
| `GEMINI_MAX_OUTPUT_TOKENS` | `8192` | a ler (padrão dos composes: 2048) |
| `GEMINI_TIMEOUT_SECONDS` | `90` | a ler (padrão: 45 em prod, 30 em test) |

Por que as duas últimas: a medição usou 8192 tokens de saída e timeout de 180 s. Em modo padrão, 7 de 110 chamadas do detail novo passaram de 45 s (mediana de 9 a 10 s, p90 de 26 a 30 s, máximo de 99 s); o detail de hoje, na mesma noite, teve 4 de 57 acima de 45 s. Quando dá timeout o worker chama de novo e paga duas vezes.

Pré-requisito de código: os commits 464adb8, 5e90e43 e cd78f19 desta branch precisam estar no ambiente.

- 464adb8: o worker passa a ler `GEMINI_DETAIL_THINKING_LEVEL` e `GEMINI_DETAIL_MEDIA_RESOLUTION`, e os três composes passam a repassá-las.
- 5e90e43: `GEMINI_DETAIL_PROMPT_VERSION=g3` troca só o prompt do detail. Os composes já repassavam a variável, mas o worker não a lia.
- cd78f19: a tabela de preços do worker passa a conhecer o `gemini-3.8-flash`. Sem ele o custo gravado em `gemini_call_log` sairia pelo preço do 2.5-flash, cerca de 2,5 vezes menor que o cobrado.

Com as variáveis vazias o código novo se comporta como o de hoje (234 testes do worker passam), então ele pode ir para `develop` e `main` antes da troca de configuração.

## O que foi medido (pi-cam-001)

| | Reais | Falsos | "Sem ocorrência" |
|---|---|---|---|
| Hoje (`d25f_v1`, 2 repetições), oficial | 15/19 e 17/19 | 12/25 e 14/25 | 1/40 |
| Recomendado (3 repetições), oficial | 16/19 | 4/25 a 5/25 | 1/40 a 2/40 |
| Hoje, holdout | 26/44 | 18/45 | — |
| Recomendado (2 repetições), holdout | 24/44 e 25/44 | 13/45 e 15/45 | — |

Custo por evento da cascata: 4% menor que hoje com os preços atuais, 10% maior com os preços anunciados para 2027. Latência mediana do detail menor.

## Decisão que acompanha o rollout: a regra do bbox

O worker troca um "sim" do modelo por "não" com confiança 0 quando nenhuma caixa tem entre 1% e 60% da imagem (`_validate_bbox`, com `GEMINI_REQUIRE_BBOX=true`). O 3.8-flash desenha caixas justas, e nesta câmera uma pessoa ocupa menos de 1% do quadro. Na repetição 3, com a resposta crua gravada (`python scripts/agg_min_area.py`):

| Área mínima | Reais | Falsos | "Sem ocorrência" |
|---|---|---|---|
| 1,00% (hoje) | 16/19 | 4/25 | 2/40 |
| 0,75% | 17/19 | 4/25 | 2/40 |
| 0,50% ou menos | 18/19 | 6/25 | 2/40 |

Opções:

- (a) Manter. Vale o que foi medido.
- (b) `GEMINI_REQUIRE_BBOX=false`. A variável existe no `config.py` (padrão `true`), mas **nenhum compose a repassa**: para usá-la é preciso acrescentar a linha `- GEMINI_REQUIRE_BBOX=${GEMINI_REQUIRE_BBOX:-true}` nos composes. Também aceita "sim" sem caixa nenhuma.
- (c) Tornar a área mínima configurável (hoje é 1% fixo no código) e baixar para 0,5%. Mudança pequena no worker, com teste.

O tamanho da caixa não separa real de falso: é uma troca de recall por falsos, com margem de um ou dois eventos. A decisão é do Alexandre.

## Ler em produção antes de aplicar

Só leitura, só nomes não secretos. O filtro abaixo não mostra chave nenhuma:

```
docker exec saira-yolo-worker-prod env | grep -E '^GEMINI_(MODEL|AGENT1_MODEL|DETAIL_[A-Z_]+|PROMPT_VERSION|TIMEOUT_SECONDS|MAX_OUTPUT_TOKENS|AGENT1_TIMEOUT_SECONDS|AGENT1_MAX_OUTPUT_TOKENS|REQUIRE_BBOX|USE_VERTEX)='
docker exec saira-yolo-worker-test env | grep -E '^GEMINI_(MODEL|AGENT1_MODEL|DETAIL_[A-Z_]+|PROMPT_VERSION|TIMEOUT_SECONDS|MAX_OUTPUT_TOKENS|AGENT1_TIMEOUT_SECONDS|AGENT1_MAX_OUTPUT_TOKENS|REQUIRE_BBOX|USE_VERTEX)='
```

O que conferir na saída:

1. **`GEMINI_AGENT1_MODEL` tem de ser `gemini-2.5-flash-lite`.** O padrão dos composes e do `.env.example` é `gemini-2.5-flash`. Se a variável não estiver no `.env`, o gate também usa o modelo que será roteado em 01/12, e esta campanha mediu outro gate. O worker só usa `GEMINI_MODEL` no detail (e no gate apenas se `GEMINI_AGENT1_MODEL` vier vazio).
2. `GEMINI_DETAIL_PROMPT_VERSION` vazio (ou um valor antigo, que é inerte). Confirma que o ponto de partida é o medido.
3. `GEMINI_MAX_OUTPUT_TOKENS` e `GEMINI_TIMEOUT_SECONDS` atuais, para saber de onde se parte.
4. `GEMINI_REQUIRE_BBOX` não deve aparecer (nenhum compose repassa): vale o padrão `true`.
5. `GEMINI_PROMPT_VERSION`: o compose de test lê `TEST_GEMINI_PROMPT_VERSION` (padrão `v3`), não a de produção. Para o teste valer, o gate de test precisa estar com o mesmo prompt de produção.

## Ordem e comandos

No servidor, os composes ficam em `/home/ubuntu/saira/services`. O serviço se chama `yolo-worker` nos dois composes, atrás do perfil `worker`. O `.env` é um só: `GEMINI_MODEL`, as três `GEMINI_DETAIL_*`, `GEMINI_MAX_OUTPUT_TOKENS` e `GEMINI_TIMEOUT_SECONDS` valem para test e prod.

**1. Código.** PR desta branch para `develop` (o merge dispara o deploy de test) e depois `main` (deploy de produção). Com as variáveis ainda vazias nada muda.

**2. Test, sem tocar no `.env`.** Variáveis no ambiente do comando têm precedência sobre o `.env`; assim só o worker de test muda:

```
cd /home/ubuntu/saira/services
GEMINI_MODEL=gemini-3.8-flash GEMINI_DETAIL_PROMPT_VERSION=g3 \
GEMINI_DETAIL_THINKING_LEVEL=low GEMINI_DETAIL_MEDIA_RESOLUTION=low \
GEMINI_MAX_OUTPUT_TOKENS=8192 GEMINI_TIMEOUT_SECONDS=90 \
docker compose -p saira-test --profile worker -f docker-compose.test.yml up -d --no-deps --force-recreate yolo-worker
```

Conferir com o `docker exec ... env | grep` acima e com a linha `GEMINI_MODEL = ...` no log de partida do worker. Um deploy de test (push em `develop`) recria o container com os valores do `.env` e desfaz essa troca.

**3. Observar em test** por pelo menos um dia com eventos: confirmações por dia contra a semana anterior; quantos details voltam com `infraction_confirmed=false` e confiança 0 (o veto do bbox); latência e timeouts; custo por chamada de detail em `gemini_call_log` (esperado: cerca de US$ 0,0085). Em 13/11 nenhuma câmera gerava detecção desde 28/09: se continuar assim, test não mostra nada e a validação é a do dataset.

**4. Produção, com o ok do Alexandre, antes de 01/12/2026.** Gravar as seis variáveis no `.env` e recriar só o worker de produção:

```
cd /home/ubuntu/saira/services
cp .env .env.bak-$(date +%Y%m%d-%H%M)
# editar o .env: as seis variáveis da tabela "O que muda"
docker compose -p saira-prod --profile worker -f docker-compose.prod.yml up -d --no-deps --force-recreate yolo-worker
docker exec saira-yolo-worker-prod env | grep -E '^GEMINI_(MODEL|DETAIL_[A-Z_]+|TIMEOUT_SECONDS|MAX_OUTPUT_TOKENS)='
```

Atenção: depois de editado o `.env`, qualquer deploy (test ou prod) recria o respectivo worker já com os valores novos. Não editar o `.env` antes da hora de trocar a produção.

## Como voltar atrás

Restaurar o `.env` da cópia (`.env.bak-...`) e repetir o comando de recriação do worker de produção. Até 30/11 isso volta ao comportamento atual. De 01/12 em diante `gemini-2.5-flash` passa a ser atendido pelo gemini-3.5-flash-lite: o "voltar" vira o cenário roteado (`d35l_v1_routed`, 9/19 de recall), não o de hoje. Depois de 01/12, a alternativa de retorno medida é `GEMINI_MODEL=gemini-3.5-flash-lite` com `GEMINI_DETAIL_PROMPT_VERSION=g3`, `GEMINI_DETAIL_THINKING_LEVEL=high` e `GEMINI_DETAIL_MEDIA_RESOLUTION=low` (`d35l_g3_low_high`).

## Limites desta recomendação

- **Outras câmeras**: `GEMINI_MODEL` é uma variável só e vale para todas. Mangabeira e Imbiribeira ainda não foram medidas (bloco H). Até lá a recomendação vale para a pi-cam-001.
- **Preço**: o 3.8-flash dobra de preço em 01/01/2027 (anunciado). A conta de +10% já considera isso.
- **Gate Decisions** (segunda proposta) não faz parte deste rollout: entra depois, em shadow. Desenho em [`DECISIONS-GATE-DESIGN.md`](DECISIONS-GATE-DESIGN.md).
