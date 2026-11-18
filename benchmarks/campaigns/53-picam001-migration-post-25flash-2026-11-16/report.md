# Camp 53 — pi-cam-001 depois do `gemini-2.5-flash`: qual detail e qual gate

**Data**: 16 e 17/11/2026 · **Custo de API**: US$ 11,22 de um teto de US$ 15,00 (conta "Saira - Testes"; estimativa: tokens conferidos com a medição do Google, preço do catálogo do Vertex), mais US$ 0,18 na chave do AI Studio, que tem créditos separados · **Runner**: `scripts/bench53.py` e `scripts/bench_decisions.py`, que importam o código real do worker · **Estado**: pi-cam-001 medida; Mangabeira e Imbiribeira ainda não (bloco H).

Documentos irmãos nesta pasta: [`ROLLOUT.md`](ROLLOUT.md) (como aplicar a troca do detail), [`DECISIONS-GATE-DESIGN.md`](DECISIONS-GATE-DESIGN.md) (desenho do shadow do gate Decisions) e [`results/exemplos.md`](results/exemplos.md) (análise de erros olhando os frames).

## Hipótese

Em 01/12/2026 o `gemini-2.5-flash`, que é o detail de produção, passa a ser atendido pelo `gemini-3.5-flash-lite`. O gate (`gemini-2.5-flash-lite`) não tem data de desligamento. Três perguntas:

1. O que acontece com o recall se ninguém mexer em nada?
2. Existe uma configuração de detail em modelo Gemini 3 que mantenha recall de pelo menos 70% por detecção, sem mais falsos, com custo por evento até 20% acima do atual?
3. Vale trocar também o gate por `gemini-decision-1` (API de Decisões, lançada em 11/11/2026)?

Critério de aprovação, fixado antes de medir: recall por detecção ≥ 70%; falsos não piores que a linha de base + 10 pontos; "sem ocorrência" ≤ 5%; custo por evento ≤ 1,20 × o de hoje. Com 19 detecções reais, uma ou duas de diferença é ruído: todo número vai como fração e os braços principais têm de 2 a 4 repetições.

## Configuração

| Campo | Valor |
|---|---|
| Gate | `gemini-2.5-flash-lite`, prompt V1, thinking 2048, 5 frames (produção hoje). Alternativa medida: `gemini-decision-1`, 6 perguntas, os mesmos 5 frames em resolução baixa |
| Detail | linha de base `gemini-2.5-flash` (V1); candidatos `gemini-3.5-flash-lite` e `gemini-3.8-flash` com prompts V1, V4 e g3, `thinking_level` e `media_resolution` variados |
| Thinking budget | gate 2048; detail: padrão do modelo, `minimal`, `low`, `medium` ou `high` conforme o braço |
| Prompt | gate V1; detail V1, V4 e g3 (`worker/_prompts_g3.py`) |
| Dataset | oficial `cam_picam001`: 122 eventos = 34 tp (18 detecções), 33 fp (26 detecções), 15 indefinido, 40 "sem ocorrência". Holdout `pi-inicial-v1` (testspace): 89 eventos de 23/07 a 07/09/2026 fora do oficial, 46 confirmados e 43 rejeitados pelo operador (contagens com as três correções de rótulo de 17/11/2026; ver o aviso no início de Resultados) |
| Caminho | Vertex AI com token do gcloud (projeto `saira-tests-260520`); Decisions pela API do AI Studio (v1beta), que é onde ele existe |
| Filtro | o detail roda nos eventos tp, fp e baseline que passaram no gate (57 no oficial com o gate de hoje) |
| Foco | recall por detecção contra o rótulo do operador; falsos; custo por evento no mix de produção |

Unidade: detecção (dispara se qualquer evento dela dispara). Custo por evento = gate + 2,2% × detail; 2,2% é a fração de eventos que chega ao detail, deduzida do custo medido em produção (US$ 0,00135 por evento, 28/07 a 04/08). Cerca de 80% do custo por evento é do gate. Entre parênteses, intervalo de 95% (Wilson).

## Resultados

> **Rótulos corrigidos em 17/11/2026.** O Gabriel Candelária corrigiu três rótulos e confirmou que os originais estavam errados: `evt-20260717_180936` (oficial, de real para falso; era a única ocorrência da detecção 1d04290a) e `evt-20260815_114903` e `evt-20260818_160927` (holdout, de rejeitado para confirmado). Todas as contagens abaixo usam os rótulos corrigidos (`results/label_overrides.json`; `BENCH_NO_LABEL_OVERRIDES=1` reproduz as anteriores: 19 reais e 25 falsas no oficial, 44 confirmados e 45 rejeitados no holdout). Nenhuma conclusão mudou. No oficial só mudaram os denominadores, porque o evento reclassificado não passa em nenhum dos gates medidos; no holdout, um dos dois eventos passa no gate de hoje e todos os details o confirmam. Ele não revisou todos os eventos caso a caso: os demais rótulos podem ter ruído.

### 1. Detail no conjunto oficial, com o gate de hoje

O gate de hoje passou 18/18 detecções reais, 18/26 falsas e 3/40 "sem ocorrência", a US$ 0,0011 por chamada.

| Detail | Reais | Falsos | "Sem ocorrência" | US$ por chamada | US$ por evento | Δ custo |
|---|---|---|---|---|---|---|
| `d25f_v1`: 2.5-flash, V1 (**hoje**), 2 repetições | 15/18 e 17/18 | 12/26 e 14/26 | 1/40 e 1/40 | 0,0108 | 0,00134 | — |
| `d35l_v1_routed`: 3.5-flash-lite, requisição idêntica (**01/12 sem mexer**) | **9/18 = 50%** (29–71) | 4/26 | 1/40 | 0,0098 | 0,00132 | −2% |
| `d35l_v1_low_high`: 3.5-flash-lite, V1, thinking alto, resolução baixa, 2 repetições | 15/18 e 16/18 | 8/26 e 10/26 | 0/40 e 0/40 | 0,0094 | 0,00131 | −2% |
| `d35l_g3_low_high`: idem com prompt g3, 2 repetições | 16/18 e 15/18 | 10/26 e 11/26 | 2/40 e 1/40 | 0,0102 | 0,00133 | −1% |
| `d38f_g3_low_low`: **3.8-flash**, g3, thinking baixo, resolução baixa (**recomendado**), 3 repetições | **16/18, 16/18 e 16/18** | **5/26, 4/26 e 4/26** | 2/40, 1/40 e 2/40 | 0,0169 | 0,00148 | **+10%** |
| `d38f_g3_low_med`: 3.8-flash, g3, thinking médio | 17/18 | 5/26 | 2/40 | 0,0299 | 0,00176 | +31% |
| `d35l_v1_low_min`: 3.5-flash-lite, V1, sem thinking, resolução baixa | 13/18 | 6/26 | 0/40 | 0,0036 | 0,00118 | −12% |
| `d35l_v4_low_high`: 3.5-flash-lite, V4, thinking alto | 10/18 | 0/26 | 0/40 | 0,0090 | 0,00130 | −3% |
| `d35l_v4_low_min`: 3.5-flash-lite, V4, sem thinking | 8/18 | 1/26 | 0/40 | 0,0037 | 0,00119 | −11% |

- **Sem mexer, o recall cai de 15–17/18 para 9/18 em 01/12**, com o mesmo custo. O 3.5-flash-lite não raciocina por padrão (0 tokens de thinking, contra cerca de 3,1 mil no 2.5-flash) e nega 14 dos 27 eventos reais que o modelo atual confirma.
- **Thinking é a alavanca principal.** Com o mesmo prompt V1, `thinking_level=high` e `media_resolution=low` devolvem o recall de hoje com menos falsos.
- **O prompt V4 é rígido demais para o 3.5-flash-lite**: quase zero falsos, recall de 42% a 53%.
- **O 3.8-flash com thinking baixo é o melhor braço**: mesmo recall e um terço dos falsos. A chamada de detail sai 56% mais cara que a de hoje (US$ 0,0169 contra 0,0108), o que vira +10% por evento porque só ~2% dos eventos chegam ao detail. Ele não aceita `thinking_level=minimal` (HTTP 400): o piso é `low`.

Tabela de todos os pares: `python bench53.py matrix --max-missing 7` (grava `results/matrix.json`).

### 2. Detail no holdout (eventos que a produção confirmou na época)

O gate de hoje, rodado em 16/11, disparou em só 27/46 confirmados e 26/43 rejeitados, embora todos tenham disparado em produção. Qualquer cascata medida hoje nesse conjunto fica limitada a ~59% por causa do gate; por isso o detail é comparado sozinho, nos eventos que passaram.

| Detail | Confirmados que passaram no gate (27) | Rejeitados que passaram no gate (26) |
|---|---|---|
| `d25f_v1` (hoje) | 27/27 (88–100) | 17/26 |
| `d35l_g3_low_high` | 23/27 (68–94) | 18/26 |
| `d35l_v1_low_high` | 20/27 (55–87) | 11/26 |
| `d35l_g3_med_high` (resolução média) | 21/27 | 19/26 |
| `d38f_g3_low_low` (**recomendado**), Flex e modo padrão | **26/27 e 25/27** | **12/26 e 14/26** |
| `d38f_g3_low_med` | 26/27 | 15/26 |

- O conjunto favorece o modelo atual: só tem eventos em que ele mesmo criou detecção. Ainda assim o recomendado perde 1 ou 2 em 27 e confirma menos rejeitados.
- O 3.5-flash-lite perde de 4 a 7 em 27 nesse conjunto. Mais resolução não ajuda. Um dos perdidos foi conferido nos frames (`evt-20260819_093004`): é descarte real, erro de percepção do modelo.

### 3. Latência do recomendado em modo padrão

Mediana de 9 a 10 s, p90 de 26 a 30 s, máximo de 77 a 99 s; 7 de 110 chamadas passaram de 45 s (com 5 chamadas simultâneas). O 2.5-flash, na mesma noite: mediana 25 s, p90 42 s, 4 de 57 acima de 45 s. O compose de produção usa 45 s de timeout por padrão.

### 4. Parte do "não" do detail é veto do worker

`_sanitize_report` troca um "sim" do modelo por "não" com confiança 0 quando nenhuma caixa tem entre 1% e 60% da imagem (`GEMINI_REQUIRE_BBOX=true`, o padrão). O 3.8-flash desenha caixas justas, e nesta câmera uma pessoa ocupa menos de 1% do quadro. Na repetição 3, com a resposta crua gravada (`python agg_min_area.py`):

| Área mínima | Reais | Falsos | "Sem ocorrência" |
|---|---|---|---|
| 1,00% (hoje) | 16/18 | 4/26 | 2/40 |
| 0,75% | 17/18 | 4/26 | 2/40 |
| 0,50% ou menos | 18/18 | 6/26 | 2/40 |

No modelo atual o veto só segura falsos (0 reais, 1 a 2 falsos por repetição). No 3.8-flash segura as 2 detecções reais que o recomendado "perde" no detail e 2 falsas. O tamanho da caixa não separa real de falso: é uma troca de recall por falsos com margem de um ou dois eventos. No holdout, tirar o veto quase não muda o recall e solta 2 a 3 falsos em 43.

### 5. `gemini-decision-1` como gate

Seis perguntas na mesma requisição, os mesmos 5 frames do gate de produção em resolução baixa (`q1_gate5_low`): 2.097 tokens de entrada, zero de saída, **US$ 0,00021 por chamada** (o gate de hoje custa US$ 0,0011). Limiar sobre a probabilidade da pergunta `deposit`:

| Gate | Oficial: reais | Oficial: falsos | Oficial: "sem ocorrência" | Holdout: confirmados |
|---|---|---|---|---|
| Hoje (2.5-flash-lite, V1) | 18/18 | 18/26 | 3/40 | 27/46 |
| Decisions, limiar 0,20 | 18/18 | 20/26 | 10/40 | 42/46 |
| Decisions, limiar 0,25 | 18/18 | 16/26 | 5/40 | 35/46 |
| Decisions, limiar 0,30 | 18/18 | 14/26 | 4/40 | 32/46 |
| Decisions, limiar 0,40 | 16/18 | 11/26 | 0/40 | — |
| Decisions, limiar 0,50 | 15/18 | 8/26 | 0/40 | — |

AUC por evento de `deposit`: reais × falsos 0,73; reais × "sem ocorrência" 0,95. Mais frames (12) ou resolução média não melhoram e custam mais.

Cascata completa com o detail recomendado (`python agg_cascade.py`). O custo é projeção: a taxa de passagem em produção foi escalada pelas 40 cenas "sem ocorrência" (gate de hoje 3/40 → 2,2%; Decisions 0,30 → 2,9%; 0,25 → 3,7%; 0,20 → 7,3%).

| Gate + detail | Oficial: reais / falsos / "sem ocorrência" | Holdout: reais / falsos | US$ por evento | Δ custo |
|---|---|---|---|---|
| Hoje: 2.5-flash-lite + 2.5-flash | 15/18 / 12/26 / 1/40 | 27/46 / 17/43 | 0,00134 | — |
| Gate de hoje + detail recomendado | 16/18 / 5/26 / 2/40 | 26/46 / 12/43 | 0,00148 | +10% |
| Decisions 0,30 + detail recomendado | 16/18 / 9/26 / 3/40 | 31/46 / 14/43 | 0,00072 | −46% |
| Decisions 0,25 + detail recomendado | 16/18 / 10/26 / 3/40 | 33/46 / 16/43 | 0,00084 | −38% |
| Decisions 0,20 + detail recomendado | 16/18 / 10/26 / 3/40 | 40/46 / 17/43 | 0,00142 | +6% |

Os três limiares dão o mesmo recall no oficial; quem os separa é o holdout. Escolher o limiar pelo holdout é otimista, por isso os três ficam reportados.

**Volume em 488 eventos (17/11, parcial).** O Decisions rodou nos 488 eventos do `pi-avancado-v1` do testspace (pi-cam-001, 14/07 a 08/09/2026; 378 sem detecção em produção, 109 rejeitados pelo operador e 1 confirmado; os 12 que também estão no oficial ficam de fora). Passam para o detail, por evento: limiar 0,20 → 213/488 = 43,6% (sem detecção 125/378 = 33,1%; rejeitados 88/109 = 80,7%); 0,25 → 121/488 = 24,8% (55/378 = 14,6%; 66/109 = 60,6%); 0,30 → 82/488 = 16,8% (29/378 = 7,7%; 53/109 = 48,6%). O único confirmado do conjunto (`evt-20260731_163409`) tem `deposit` = 0,192 e não passa em nenhum dos três limiares. `python agg_gate_pass.py`. **Essas frações não são a taxa de produção**: não se sabe como os eventos foram escolhidos, e cerca de 23% deles têm detecção (a produção tinha cerca de 2%). O número que serve para o custo é a razão contra o gate de hoje nos mesmos eventos, e o gate de hoje ainda não rodou neles (a sessão do gcloud expirou em 17/11 às 23:11). Até lá, a projeção de custo acima continua apoiada nas 40 cenas.

### 6. Repetibilidade

- **Gate de hoje**: quatro execuções (16/11 às 20:59, 23:10 e 23:15; 17/11 às 02:11) deram o mesmo voto nos 122 eventos. `python agg_gate_reps.py`.
- **Decisions**: quatro execuções (16/11 às 22:24 e 22:25; 17/11 às 02:11 e às 23:13, esta 25 horas depois da primeira) devolveram probabilidades idênticas até o último dígito nos 122 eventos e nas 6 perguntas. `python agg_dgate_reps.py`. A igualdade exata se manteve de um dia para o outro: ou o modelo é determinístico para a mesma entrada, ou o cache do lado do Google dura mais de um dia. Nos dois casos o limiar se comporta de modo repetível.
- **Detail**: a linha de base oscila entre 15/18 e 17/18; o recomendado deu 16/18 nas três repetições, com falsos de 4/26 a 5/26.
- A camp 51 viu os positivos do gate se reproduzirem só ~50% entre dias, e o holdout repete isso (27/46). Nas horas desta campanha o gate não variou; a diferença entre dias segue sem medida direta.

### 7. Erros vistos nos frames

Detalhes em [`results/exemplos.md`](results/exemplos.md).

- Das 3 detecções reais que a cascata recomendada perde no oficial, 2 são veto do worker (item 4) e 1 (`evt-20260717_180936`) não passa em gate nenhum e tem evidência fraca nos frames. Em nenhuma o detail novo diz "não" a um descarte visível.
- Os falsos que o detail novo deixa de confirmar são casos claros (limpeza urbana, pessoa remexendo o monte). Os que ainda confirma são quase todos "pessoa com saco ou carrinho junto ao monte", que o próprio operador descreve como "não percebemos o momento do descarte", mais o descarte no contêiner, em que o rótulo é inconsistente (2 falsos e 3 reais com a mesma descrição).
- "Sem ocorrência" não é rótulo de operador: é "classificado SEM descarte pelo pipeline". As duas que o recomendado confirma com o gate de hoje são catadores (erro do modelo; numa delas o detail atual erra igual). Das três que entram com o gate Decisions, uma parece descarte real que a produção não viu (`evt-20260722_114117`).
- No holdout, os 4 confirmados que ficam entre 0,178 e 0,199 no Decisions são descarte real visível. O limiar 0,20 corta descarte de verdade por margem de milésimos.

## Decisão

1. ❌ **Não deixar o roteamento acontecer sozinho.** Com a requisição de hoje no 3.5-flash-lite o recall medido cai para 9/18 (50%), abaixo do critério.
2. ✅ **Trocar o detail antes de 01/12** por `gemini-3.8-flash`, prompt g3, `thinking_level=low`, `media_resolution=low`, com `GEMINI_REQUIRE_BBOX=false` (item 3). Passa em todos os critérios nos dois conjuntos: no oficial, 18/18 de recall e 6/26 de falsos sem o veto do bbox (16/18 e 4–5/26 com ele), contra 15–17/18 e 12–14/26 de hoje; custo por evento 10% maior que o de hoje, dentro do limite de 20%. É só configuração, com os commits 464adb8, 5e90e43, cd78f19 e cc13846 desta branch. Passos em [`ROLLOUT.md`](ROLLOUT.md). **Vale para câmeras do tipo da pi-cam-001**, que é o que o projeto terá quando voltar, em janeiro de 2027 (decisão do Alexandre em 17/11: as câmeras ESP32 ficam fora de escopo e não foram medidas).
3. ✅ **Regra do bbox: decidido em 17/11.** O Alexandre respondeu "não preciso de bbox": o rollout usa `GEMINI_REQUIRE_BBOX=false` e vale a resposta do modelo (18/18 reais, 6/26 falsos, 2/40 "sem ocorrência" no oficial, pela repetição 3 com a resposta crua). O commit cc13846 faz os composes repassarem a variável e torna a área mínima da caixa configurável (`GEMINI_BBOX_MIN_AREA_RATIO`), para as caixas justas do 3.8-flash poderem ser gravadas. O relatório diário tem um indicador (I3, meta de 80%) que conta detecções com caixa do infrator: na repetição 3, 34 das 39 confirmações do modelo têm caixa com 1% ou mais da imagem (87%) e as 39 têm com 0,25% ou mais.
4. ⚠️ **Gate Decisions: shadow primeiro.** No dataset ele iguala o gate de hoje em recall, recupera confirmados do holdout que o gate de hoje não repete e custa um quinto por chamada. Mas o modelo tem uma semana de vida, só existe na API do AI Studio, o custo da cascata é projeção e o limiar foi visto em uma câmera. Desenho em [`DECISIONS-GATE-DESIGN.md`](DECISIONS-GATE-DESIGN.md), sem implementação.

Alternativas de detail, se o 3.8-flash não puder ser usado: `d35l_g3_low_high` (3.5-flash-lite; custo igual ao de hoje e sem aumento anunciado; recall igual no oficial, 23/27 no holdout, falsos como os de hoje) e `d38f_g3_low_med` (qualidade igual à do recomendado; +31% de custo, fora do critério).

## Caveats

- **Uma câmera, um ponto.** Tudo foi medido na pi-cam-001. O projeto volta em janeiro de 2027 só com câmeras desse tipo, mas em outros pontos: enquadramento e cena mudam, e a taxa de falsos (e o limiar do Decisions, se for usado) precisa ser conferida nos primeiros dias de cada câmera nova. As câmeras ESP32 ficaram fora de escopo por decisão do Alexandre.
- **Amostra pequena.** 18 detecções reais no oficial: o intervalo de 16/18 vai de 67% a 97%. O holdout tem 46 confirmados, mas só mede o detail em eventos escolhidos pela produção.
- **Validação offline.** Em 13/11 nenhuma câmera gerava detecção desde 28/09; não há tráfego para um teste ao vivo.
- **Preço do 3.8-flash: corrigido em 17/11.** No Vertex, que é o que os testes e a produção usam, ele custa US$ 1,50 / 7,50 por 1M de tokens (catálogo de cobrança do Google Cloud, `python benchmarks/scripts/vertex_sku_prices.py`). A página de preços da API do AI Studio lista a metade até 31/12/2026, e as primeiras versões deste relatório usaram esse valor: diziam −4% de custo por evento para o recomendado. O certo é +10%. Com thinking médio seria +31%, fora dos 20%. Os demais modelos (2.5-flash, 2.5-flash-lite, 3.5-flash-lite) batem com o catálogo.
- **Gasto dos testes: estimado, com os tokens conferidos.** O registro de gastos soma tokens × preço. Os tokens batem exatamente com a medição do Google no projeto (Cloud Monitoring, 14,95 milhões de entrada nos quatro modelos; `python benchmarks/scripts/vertex_usage_check.py`). O preço vem do catálogo. A fatura, em reais e com impostos, só aparece no console de faturamento, com atraso.
- **Custo da cascata com o Decisions é projeção** a partir de 40 cenas. Só um shadow dá a taxa de passagem real.
- **Paridade com produção conferida em 17/11/2026** (leitura das variáveis do `saira-yolo-worker-prod`, a pedido do Alexandre; tabela no `ROLLOUT.md`). O gate de produção é o `gemini-2.5-flash-lite` e modelo, thinking 2048, limiar 85, 48 frames, 3 frames intermediários, sem re-voto, prompt V1, temperatura 0 e 8192 tokens de saída no detail batem com o runner. Diferem os timeouts: produção usa 45 s no detail e 15 s no gate; o runner usou 180 s. O worker de test NÃO é espelho do de produção (gate com prompt `v3`, 10 frames intermediários, re-voto, API do AI Studio).
- **Flex.** Parte das repetições rodou em Flex PayGo (metade do preço, latência maior). O recomendado foi repetido em modo padrão nos dois conjuntos, com o mesmo resultado.
- **Rótulos.** "Sem ocorrência" vem do pipeline, não do operador, e o rótulo de descarte no contêiner é inconsistente.

## Como reproduzir

De dentro de `scripts/`, com o venv da árvore de trabalho. Toda execução paga passa por `benchmarks/scripts/bench_budget.py`: `--dry-run` antes, `--max-usd` sempre.

```
python bench53.py list
python bench53.py gate --arm g25l_v1 --rep 1 --max-usd 0.20
python bench53.py detail --arm d38f_g3_low_low --rep 2 --events-from g25l_v1:1 --cats tp,fp,baseline --max-usd 0.60
python bench53.py matrix --max-missing 7
python bench_decisions.py run --qset q1 --frames gate5 --res low --rep 1 --max-usd 0.05
python bench_decisions.py sweep --tag q1_gate5_low
python agg_cascade.py ; python agg_holdout.py ; python agg_grounding.py ; python agg_min_area.py
python agg_gate_reps.py ; python agg_dgate_reps.py
```

Holdout: `--dataset pi-inicial-v1` antes do subcomando; resultados em `results/pi-inicial-v1/`.
