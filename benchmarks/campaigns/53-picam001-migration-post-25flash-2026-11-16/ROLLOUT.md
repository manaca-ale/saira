# Camp 53 — rollout do detail novo (17/11/2026)

> **Rótulos corrigidos em 17/11/2026 (correções do Gabriel Candelária em três eventos).** As contagens deste documento usam os rótulos corrigidos: 18 detecções reais e 26 falsas no oficial; 46 confirmados e 43 rejeitados no holdout. Nenhuma conclusão mudou; detalhes no início de Resultados do `report.md`. Ele não revisou todos os eventos caso a caso: os demais rótulos podem ter ruído.

Conferido contra os composes, o `config.py` e o `deploy.yml` desta branch. As variáveis dos dois workers foram lidas no servidor em 17/11/2026 (seção "Lido em produção"). Nada aqui foi aplicado em test nem em produção. Números e método no [`report.md`](report.md).

> **Correções de 18 e 19/11/2026.** (1) O custo por evento da cascata com o detail novo é **13% maior** que o de hoje (+9% a +17% conforme a semana), não 10%: a passagem do gate em produção, medida no registro de chamadas de 14/07 a 08/09/2026, é 3,2% e não 2,2%. Continua dentro do limite de 20%. (2) A produção roda no Vertex, e lá o `gemini-2.5-flash` **e o gate `gemini-2.5-flash-lite`** têm aposentadoria oficial em 20/10/2026 (já passou; os dois ainda respondiam em 18/11). A data de 01/12/2026 citada neste documento é a do roteamento no AI Studio. A escolha da plataforma é do Alexandre e está em aberto; nada neste documento troca o gate. (3) Bloco M (18/11): o prompt V1 no 3.8-flash também passa nas duas regras (oficial 17/18, 4/26, 0/40 sem o veto do bbox; holdout mantém 25 de 27) e o V4 falha (13/18). O recomendado continua g3; só muda para V1 depois de uma repetição. Detalhes no aviso do topo do [`report.md`](report.md).

## O que muda

Só o detail. O gate fica como está (gemini-2.5-flash-lite, prompt V1).

| Variável | Valor novo | Hoje |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.8-flash` | `gemini-2.5-flash` (no AI Studio, roteado para gemini-3.5-flash-lite em 01/12/2026; no Vertex, aposentadoria oficial em 20/10/2026) |
| `GEMINI_DETAIL_PROMPT_VERSION` | `g3` | vazio |
| `GEMINI_DETAIL_THINKING_LEVEL` | `low` | vazio |
| `GEMINI_DETAIL_MEDIA_RESOLUTION` | `low` | vazio |
| `GEMINI_TIMEOUT_SECONDS` | `90` | `45` em prod, `30` em test (lido em 17/11) |
| `GEMINI_REQUIRE_BBOX` | `false` | não definida: vale o padrão `true` |
| `GEMINI_BBOX_MIN_AREA_RATIO` | `0.0025` (opcional) | não definida: vale o padrão `0.01` |

`GEMINI_MAX_OUTPUT_TOKENS` já está em `8192` nos dois workers: não muda.

Por que o timeout: a medição usou timeout de 180 s. Em modo padrão, 7 de 110 chamadas do detail novo passaram de 45 s (mediana de 9 a 10 s, p90 de 26 a 30 s, máximo de 99 s); o detail de hoje, na mesma noite, teve 4 de 57 acima de 45 s. Quando dá timeout o worker chama de novo e paga duas vezes.

Pré-requisito de código: os commits 464adb8, 5e90e43, cd78f19 e cc13846 desta branch precisam estar no ambiente.

- 464adb8: o worker passa a ler `GEMINI_DETAIL_THINKING_LEVEL` e `GEMINI_DETAIL_MEDIA_RESOLUTION`, e os três composes passam a repassá-las.
- 5e90e43: `GEMINI_DETAIL_PROMPT_VERSION=g3` troca só o prompt do detail. Os composes já repassavam a variável, mas o worker não a lia.
- cc13846: os composes passam a repassar `GEMINI_REQUIRE_BBOX` (a variável existia no `config.py`, mas não chegava ao container) e a área mínima da caixa vira configurável (`GEMINI_BBOX_MIN_AREA_RATIO`).
- cd78f19: a tabela de preços do worker passa a conhecer o `gemini-3.8-flash`. Sem ele o custo gravado em `gemini_call_log` sairia pelo preço do 2.5-flash, cerca de 2,5 vezes menor que o cobrado.

Com as variáveis vazias o código novo se comporta como o de hoje (241 testes do worker passam), então ele pode ir para `develop` e `main` antes da troca de configuração.

## O que foi medido (pi-cam-001)

| | Reais | Falsos | "Sem ocorrência" |
|---|---|---|---|
| Hoje (`d25f_v1`, 2 repetições), oficial | 15/18 e 17/18 | 12/26 e 14/26 | 1/40 |
| Recomendado com o veto do bbox (3 repetições), oficial | 16/18 | 4/26 a 5/26 | 1/40 a 2/40 |
| **Recomendado sem o veto do bbox** (repetição 3, resposta do modelo), oficial | **18/18** | 6/26 | 2/40 |
| Hoje, holdout | 27/46 | 17/43 | — |
| Recomendado (2 repetições), holdout | 25/46 e 26/46 | 12/43 e 14/43 | — |

Custo por evento da cascata: 13% maior que hoje (corrigido em 18/11 com a passagem medida de 3,2%; +9% a +17% conforme a semana), com o preço do Vertex conferido no catálogo de cobrança em 17/11 (US$ 1,50 / 7,50 por 1M no 3.8-flash). Latência mediana do detail menor.

## A regra do bbox: decidido em 17/11/2026

O worker troca um "sim" do modelo por "não" com confiança 0 quando nenhuma caixa tem entre 1% e 60% da imagem (`_validate_bbox`, com `GEMINI_REQUIRE_BBOX=true`). O 3.8-flash desenha caixas justas, e nesta câmera uma pessoa ocupa menos de 1% do quadro: 2 das 19 detecções reais do conjunto oficial foram confirmadas pelo modelo e vetadas pelo worker.

**Decisão do Alexandre (17/11): "não preciso de bbox".** O rollout usa `GEMINI_REQUIRE_BBOX=false`: vale a resposta do modelo. Medido na repetição 3, que guardou a resposta crua (`python scripts/agg_min_area.py`):

| Regra | Reais | Falsos | "Sem ocorrência" |
|---|---|---|---|
| Veto de 1% (como está hoje) | 16/18 | 4/26 | 2/40 |
| **Sem veto (`GEMINI_REQUIRE_BBOX=false`)** | **18/18** | 6/26 | 2/40 |

No holdout o recall quase não muda (quem limita é o gate) e entram de 2 a 3 falsos a mais em 43 (estimativa pelas repetições sem a resposta crua). O pipeline de hoje, no oficial, faz 15/18 a 17/18 reais com 12/26 a 14/26 falsos.

Efeito colateral a saber: o relatório diário tem o indicador I3, "qualidade da identificação" (`backend/app/services/daily_report_service.py`): percentual de detecções com caixa do infrator, com meta de 80%. Medido na repetição 3: das 39 respostas "sim" do modelo, 34 têm caixa do infrator com 1% ou mais da imagem (87%, acima da meta) e as 39 têm caixa com 0,25% ou mais (100%). O indicador não corre risco com o piso de hoje; baixá-lo para 0,25% (`GEMINI_BBOX_MIN_AREA_RATIO=0.0025`) só grava as 5 caixas que faltam. Com `GEMINI_REQUIRE_BBOX=false` essa variável não muda nenhuma decisão, só quais caixas ficam no banco. O frontend não usa as caixas.

## Lido em produção em 17/11/2026 (06:55, somente leitura)

A pedido do Alexandre. Comando, com lista fechada de nomes (não mostra chave):

```
docker exec saira-yolo-worker-prod env | grep -E '^(GEMINI_(MODEL|AGENT1_MODEL|AGENT1_THINKING_BUDGET|AGENT1_TRIGGER_MIN_CONFIDENCE|AGENT1_TIMEOUT_SECONDS|AGENT1_MAX_OUTPUT_TOKENS|DETAIL_[A-Z_]+|PROMPT_VERSION|TIMEOUT_SECONDS|MAX_OUTPUT_TOKENS|MAX_RETRIES|REQUIRE_BBOX|USE_VERTEX|CASCADE_ENABLED|CASCADE_MAX_FRAMES|GATE_MID_FRAMES|GATE_REVOTE_ENABLED|TEMPERATURE|MOSAIC_AGENT1|MOSAIC_AGENT2)|DETAIL_(PILECROP|HIGHBAR)_DEVICES|EVENT_DRIVEN_DEVICES|AI_MODE|GCP_LOCATION|GCP_LOCATION_FALLBACK|BGSUB_PREFILTER_ENABLED)=' | sort
```

| Variável | Produção | Test |
|---|---|---|
| `GEMINI_AGENT1_MODEL` (gate) | **`gemini-2.5-flash-lite`** | `gemini-2.5-flash-lite` |
| `GEMINI_MODEL` (detail) | `gemini-2.5-flash` | `gemini-2.5-flash` |
| `GEMINI_PROMPT_VERSION` | não definida (padrão `current`, o V1) | `v3` |
| `GEMINI_DETAIL_PROMPT_VERSION` | vazia | vazia |
| `GEMINI_AGENT1_THINKING_BUDGET` | não definida (padrão 2048) | não definida |
| `GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE` | 85 | 85 |
| `GEMINI_CASCADE_MAX_FRAMES` | 48 | 48 |
| `GEMINI_GATE_MID_FRAMES` | não definida (padrão 3) | 10 |
| `GEMINI_GATE_REVOTE_ENABLED` | não definida (padrão `false`) | `true` |
| `GEMINI_TEMPERATURE` | 0.0 | 0.0 |
| `GEMINI_MAX_OUTPUT_TOKENS` | 8192 | 8192 |
| `GEMINI_TIMEOUT_SECONDS` (detail) | 45 | 30 |
| `GEMINI_AGENT1_TIMEOUT_SECONDS` (gate) | 15 | 15 |
| `GEMINI_AGENT1_MAX_OUTPUT_TOKENS` | 4096 | 4096 |
| `GEMINI_MAX_RETRIES` | 2 | 2 |
| `GEMINI_REQUIRE_BBOX` | não definida (padrão `true`) | não definida |
| `GEMINI_USE_VERTEX` | `true` (`GCP_LOCATION=global`, reserva `us-central1`) | `false` (chave do AI Studio) |
| `GEMINI_DETAIL_PILECROP_ENABLED` | `true` (12 frames, upscale 2) | `true` |
| `DETAIL_PILECROP_DEVICES` | `esp32_002` | `esp32_002` |
| `DETAIL_HIGHBAR_DEVICES` | `esp32_002` | não definida |
| `EVENT_DRIVEN_DEVICES` | `pi-cam-001` | `pi-cam-001` |

O que isso responde:

1. **O gate de produção é o `gemini-2.5-flash-lite`**, o mesmo medido na campanha. Só o detail usa o modelo que será roteado em 01/12 no AI Studio. (Corrigido em 18/11: no Vertex, onde a produção roda, o gate também tem aposentadoria oficial em 20/10/2026; ver o aviso no topo.)
2. **A campanha mediu a produção**: modelo do gate, thinking 2048, limiar 85, 48 frames, 3 frames intermediários, sem re-voto, prompt V1, temperatura 0 e 8192 tokens de saída no detail batem com o runner. As diferenças são só de timeout (o runner usou 180 s).
3. `GEMINI_DETAIL_PROMPT_VERSION` está vazia: o ponto de partida é o medido.
4. `GEMINI_MAX_OUTPUT_TOKENS` já é 8192. Só o timeout do detail precisa subir (45 → 90).
5. **Timeout do gate em 15 s**: na campanha o gate levou de 9 a 12 s por chamada. Fica perto do corte; quando passa, o worker chama de novo e paga duas vezes. Não faz parte desta troca, mas vale olhar nos logs (`gemini gate timeout`).
6. Na Mangabeira (esp32_002) o detail usa o prompt próprio com recortes e o gate de barra alta: lá o `g3` não entra (ver "Limites desta recomendação").
7. **O worker de test não é espelho do de produção**: gate com prompt `v3`, 10 frames intermediários e re-voto ligado, e chamadas pela API do AI Studio em vez do Vertex. Um teste do detail novo em test roda sob outro gate e outra API; para valer como ensaio, igualar essas quatro variáveis no comando (abaixo) e confirmar que a chave do AI Studio de test tem crédito e enxerga o `gemini-3.8-flash`.

Não foi lido (não estava no pedido): a taxa de passagem do gate em `gemini_call_log`, que fecha a régua de custo. É uma consulta de leitura ao banco de produção; fica como pendência.

## Ordem e comandos

No servidor, os composes ficam em `/home/ubuntu/saira/services`. O serviço se chama `yolo-worker` nos dois composes, atrás do perfil `worker`. O `.env` é um só: `GEMINI_MODEL`, as três `GEMINI_DETAIL_*`, `GEMINI_TIMEOUT_SECONDS`, `GEMINI_REQUIRE_BBOX` e `GEMINI_BBOX_MIN_AREA_RATIO` valem para test e prod.

**1. Código.** PR desta branch para `develop` (o merge dispara o deploy de test) e depois `main` (deploy de produção). Com as variáveis ainda vazias nada muda.

**2. Test, sem tocar no `.env`.** Variáveis no ambiente do comando têm precedência sobre o `.env`; assim só o worker de test muda:

```
cd /home/ubuntu/saira/services
GEMINI_MODEL=gemini-3.8-flash GEMINI_DETAIL_PROMPT_VERSION=g3 \
GEMINI_DETAIL_THINKING_LEVEL=low GEMINI_DETAIL_MEDIA_RESOLUTION=low \
GEMINI_TIMEOUT_SECONDS=90 GEMINI_REQUIRE_BBOX=false GEMINI_BBOX_MIN_AREA_RATIO=0.0025 \
docker compose -p saira-test --profile worker -f docker-compose.test.yml up -d --no-deps --force-recreate yolo-worker
```

Para o gate de test ficar igual ao de produção nesse ensaio, acrescentar ao mesmo comando `TEST_GEMINI_PROMPT_VERSION=current GEMINI_GATE_MID_FRAMES=3 GEMINI_GATE_REVOTE_ENABLED=false` (são os nomes que o compose de test lê). Conferir com o `docker exec ... env | grep` acima e com a linha `GEMINI_MODEL = ...` no log de partida do worker. Um deploy de test (push em `develop`) recria o container com os valores do `.env` e desfaz essa troca.

**3. Observar em test** por pelo menos um dia com eventos: confirmações por dia contra a semana anterior; quantos details voltam com `infraction_confirmed=false` e confiança 0 (com `GEMINI_REQUIRE_BBOX=false` não deve haver nenhum); latência e timeouts; custo por chamada de detail em `gemini_call_log` (esperado: cerca de US$ 0,017). Em 13/11 nenhuma câmera gerava detecção desde 28/09: se continuar assim, test não mostra nada e a validação é a do dataset.

**4. Produção, com o ok do Alexandre, antes de as câmeras voltarem.** O projeto está parado (nenhuma câmera gera detecção desde 28/09) e volta em janeiro de 2027. Sem eventos, o roteamento de 01/12 não derruba nada na prática; mas qualquer evento que chegue depois de 01/12 com a configuração de hoje cai no detail roteado, de recall medido em 9/18. Por isso a troca deve estar feita antes de a primeira câmera ser religada. Aplicar com o projeto parado é o momento de menor risco. Gravar no `.env` as variáveis da tabela "O que muda" e recriar só o worker de produção:

```
cd /home/ubuntu/saira/services
cp .env .env.bak-$(date +%Y%m%d-%H%M)
# editar o .env: as variáveis da tabela "O que muda"
docker compose -p saira-prod --profile worker -f docker-compose.prod.yml up -d --no-deps --force-recreate yolo-worker
docker exec saira-yolo-worker-prod env | grep -E '^GEMINI_(MODEL|DETAIL_[A-Z_]+|TIMEOUT_SECONDS|MAX_OUTPUT_TOKENS|REQUIRE_BBOX|BBOX_MIN_AREA_RATIO)='
```

Atenção: depois de editado o `.env`, qualquer deploy (test ou prod) recria o respectivo worker já com os valores novos. Não editar o `.env` antes da hora de trocar a produção.

## Como voltar atrás

Restaurar o `.env` da cópia (`.env.bak-...`) e repetir o comando de recriação do worker de produção. Até 30/11 isso volta ao comportamento atual. De 01/12 em diante `gemini-2.5-flash` passa a ser atendido pelo gemini-3.5-flash-lite: o "voltar" vira o cenário roteado (`d35l_v1_routed`, 9/18 de recall), não o de hoje. Depois de 01/12, a alternativa de retorno medida é `GEMINI_MODEL=gemini-3.5-flash-lite` com `GEMINI_DETAIL_PROMPT_VERSION=g3`, `GEMINI_DETAIL_THINKING_LEVEL=high` e `GEMINI_DETAIL_MEDIA_RESOLUTION=low` (`d35l_g3_low_high`).

## Limites desta recomendação

- **Só câmeras do tipo da pi-cam-001.** Decisão do Alexandre em 17/11: o projeto volta em janeiro de 2027 com todas as câmeras no estilo da Raspberry, e as câmeras ESP32 (Mangabeira, Imbiribeira e as demais) ficam fora de escopo; não foram medidas com o detail novo e não serão. Se alguma delas voltar a operar, vale o aviso: `GEMINI_MODEL`, o thinking e a resolução são variáveis únicas para todas as câmeras, e na Mangabeira (esp32_002) o prompt próprio com recortes tem precedência sobre o `g3`.
- **Um ponto só.** A medição é de uma câmera num ponto. As câmeras novas ficam em outros pontos: nos primeiros dias de cada uma, conferir a taxa de falsos e, se o gate Decisions vier a ser usado, o limiar.
- **Preço**: no Vertex o 3.8-flash custa US$ 1,50 / 7,50 por 1M, e a conta de +13% usa esse preço. A página da API do AI Studio lista a metade até 31/12/2026, mas não é o que o Vertex cobra; as primeiras versões deste documento diziam −4% por causa disso.
- **Gate Decisions** (segunda proposta) não faz parte deste rollout: entra depois, em shadow. Desenho em [`DECISIONS-GATE-DESIGN.md`](DECISIONS-GATE-DESIGN.md).
