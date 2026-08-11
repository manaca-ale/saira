# Camp 51 — existe um gate barato que preserve recall?

> Fase A concluída em 31/07/2026. 1.342 chamadas, US$ 0,72.
> Pergunta e critérios: `HANDOFF_CHEAP_GATE.md`.

## Resposta

**Não.** Nenhum dos quatro candidatos open-weight serve de gate. Os quatro preservam o
recall, todos acima da produção (97–100 % contra 80 %), mas **nenhum filtra**: disparam em
85 % a 100 % do dataset, incluindo cenas comprovadamente vazias. Um gate que deixa
passar tudo não é um gate; é um custo a mais antes do detail.

O achado colateral é mais valioso que a resposta: **o gate de produção perde 7 dos 35
TPs rotulados por humano** nesta câmera, e trocar só o modelo do gate por
`gemini-3.1-flash-lite` recupera **6 desses 7**.

## Método

Só o estágio 1, sem detail nenhum. 122 eventos do dataset oficial `cam_picam001`
(35 tp · 32 fp · 40 baseline · 15 indefinido), rótulos revisados por humano na Fase 0
do Camp 49.

- **Janela idêntica à prod**: `subsample_frames(48)` → `fit_frames_to_payload(8 MB)` →
  gate = 1º + 3 mid + último = **5 quadros**, 640 px q70 (~258 KB).
- **Mesmos bytes para todos os provedores.** As 5 imagens são codificadas uma vez por
  `_bedrock_client.prepare_images(mode="low")` e as MESMAS vão ao Bedrock e ao Gemini.
  O controle Gemini do Camp 49 mandava imagem original; comparar recall entre
  provedores com entradas diferentes mediria resolução, não modelo.
- **Duas regras de decisão registradas por chamada**, sem custo extra:
  `raw` = o que o próprio prompt decidiu; `v1` = o mesmo report depois do pós-gate
  determinístico de prod (`scene==DUMPING` **e** 2-de-3 booleanos). Sem separar as
  duas não dá para saber se quem errou foi o modelo ou a pós-regra.
- `force_mode="text"` em todo o Bedrock (armadilha do Camp 48: vários modelos aceitam
  `toolConfig` e o ignoram).

### Dois desvios do desenho do handoff, deliberados

1. **A ordem foi invertida** — dataset oficial primeiro, réplica de tráfego depois. A
   Fase 0 proposta decidiria recall sobre os **12 eventos CONFIRMADOS** que existem no
   `camp50_gate_kimi.jsonl` (dos 287, só 25 têm status do operador). Um erro ali vale
   8 pp. O dataset oficial tem 35 TPs e 40 baselines com rótulo humano, custa o mesmo e
   não depende de acesso à produção.
2. **Foi acrescentado o braço `gemini-2.5-flash-lite:v1`** — o gate de produção hoje.
   O critério de aceite nº 1 é "recall ≥ 100 % do gate atual" e esse denominador não
   existia: os 3,5 % do handoff são taxa de passagem em tráfego, que não se compara com
   recall em dataset. Sem esse braço a campanha não teria contra o que reprovar.

## Resultados

Regra `raw` salvo indicação. `passa` = fração dos 107 eventos decisivos (tp+fp+baseline)
que o gate deixaria seguir para o detail.

| braço | recall tp | TP perdidos | dispara fp | dispara baseline | passa | US$/chamada | p50 | erros |
|---|---|---|---|---|---|---|---|---|
| **`gemini-2.5-flash-lite:v1`** (produção) | **80,0 %** | **7** | 65,6 % | **7,5 %** | **48,6 %** | 0,000582 | 6,0 s | 0 |
| `gemini-3.1-flash-lite:min` | **97,1 %** | 1 | 90,6 % | 25,0 % | 68,2 % | 0,001053 | 2,7 s | 0 |
| `gemini-3.1-flash-lite:min` (regra v1) | 97,1 % | 1 | 75,0 % | 20,0 % | 61,7 % | 0,001053 | 2,7 s | 0 |
| `gemini-3.1-flash-lite:g3` | 94,3 % | 2 | 65,6 % | 12,5 % | 55,1 % | 0,001201 | 2,6 s | 0 |
| `gemma-3-12b:g3` (regra v1) | 100 % | 0 | 96,9 % | 65,0 % | 86,0 % | 0,000333 | 5,7 s | 0 |
| `gemma-3-12b:min` (regra v1) | 94,3 % | 2 | 65,6 % | 40,0 % | 65,4 % | 0,000325 | 5,4 s | 0 |
| `ministral-3-14b:min` (regra v1) | 94,3 % | 2 | 68,8 % | 17,5 % | 57,9 % | 0,000680 | 3,8 s | 0 |
| `ministral-3-14b:g3` | 97,1 % | 1 | 87,1 % | 20,5 % | 65,4 % | 0,000671 | 3,9 s | **4** |
| `gemma-3-4b:min` (regra v1) | 97,1 % | 1 | 81,2 % | 62,5 % | 79,4 % | 0,000131 | 3,2 s | 0 |
| `gemma-3-4b:min` / `:g3` | 100 % | 0 | 100 % | 100 % | **100 %** | 0,000131 | 3,2 s | 0 |
| `nemotron-nano-12b:min` / `:g3` | 100 % | 0 | 100 % | ~100 % | **~100 %** | 0,000377 | 4,2 s | 0 |

Tabela completa nas duas regras: `results/gate51_faseA_summary.json`.

### Veredito por candidato

Dos 4 critérios de aceite, a Fase A decide 3. O **critério 2** ("FP de ponta a ponta
≤ o de hoje") **não é decidível aqui** — ele se mede depois do detail, e um gate que
dispara mais não gera mais FP se o detail rejeitar o excedente (~63 % de rejeição,
`project_detail_rejection_rate`). Disparo em fp/baseline entra como diagnóstico.
O **critério 3** também não fecha aqui em valor absoluto: o teto de 25 % é passagem em
**tráfego**, e este dataset é montado 35/32/40/15, proporção que não existe na rua
(a própria produção passa 48,6 % nele). O proxy usado é "passa no máximo o que a
produção passa".

| candidato | c1 recall | c3' passagem | c4 erros | veredito |
|---|---|---|---|---|
| `gemma-3-4b` | ✅ 100 % | ❌ 100 % | ✅ 0 | **REPROVADO** |
| `gemma-3-12b` | ✅ 100 % | ❌ 86,0 % | ✅ 0 | **REPROVADO** |
| `ministral-3-14b` | ✅ 97,1 % | ❌ 65,4 % | ❌ 4 | **REPROVADO** |
| `nemotron-nano-12b` | ✅ 100 % | ❌ 99,1 % | ✅ 0 | **REPROVADO** |
| `gemini-3.1-flash-lite` (controle) | ✅ 94–97 % | ❌ 55,1 % | ✅ 0 | reprova no proxy c3' |

## Por que os open-weight falham: confabulação, não calibração

`gemma-3-4b` devolve **JSON válido** em 122 de 122 chamadas — e responde
`scene_type=DUMPING` com **confiança 95 em todas as 122**, com
`person_handling_material=true` em todas. Em cenas `baseline` (vazias, sem ator) ele
descreve o que não existe:

> "In the final frame, a person is observed crouching near the pile and appears to be
> depositing a small amount of waste onto the ground. The pile itself has increased in
> size." — `evt-20260722_000031`, categoria **baseline**

Três consequências:

1. **Não é bug de parsing nem de prompt.** `min` e `g3` produzem o mesmo comportamento,
   dígito por dígito. Reescrever o prompt não é alavanca neste porte de modelo — o
   mesmo beco de `project_audit_prompt_dead_end` (camps 11-16).
2. **Não há limiar para calibrar.** Confiança constante em 95 significa que subir o
   `TRIGGER_MIN_CONFIDENCE` não separa nada: ou passa tudo, ou barra tudo.
3. **A pós-regra V1 é o que dá seletividade a eles, não o modelo.** `gemma-3-4b` cai
   de 100 % para 79,4 % de passagem só quando se aplica `scene==DUMPING` + 2-de-3
   booleanos por cima — e aí perde 1 TP. A seletividade vinha do Python, não da visão.

Isso invalida a premissa da planilha `custos/custos_modelos_arquiteturas_2026-07-31.xlsx`:
as linhas `gate gemma-3-4b + detail kimi` (US$ 0,000428 e US$ 0,001047/evento) assumem
que o gate barato reproduz a seletividade do Gemini (3,5 % / 11,2 % de passagem).
**Medido: a passagem é 100 %.** Com o gate passando tudo, a arquitetura degenera para o
`kimi single-call` e custa os US$ 0,0080/evento dele, ~6× a produção — o oposto do que
a planilha estima. As duas linhas precisam ser marcadas como refutadas.

## O achado colateral: o furo de recall está no gate, e o modelo é a alavanca

O gate de produção (`2.5-flash-lite` + prompt V1) **perde 7 dos 35 TPs**:

```
evt-20260715_165230  evt-20260715_165556  evt-20260715_181251  evt-20260717_170823
evt-20260717_180936  evt-20260720_112538  evt-20260720_153503
```

Trocando **só o modelo do gate** por `gemini-3.1-flash-lite`, **6 dos 7 voltam** — com
qualquer um dos dois prompts (`g3` ou `min`), nas duas regras de decisão. O prompt aqui
não é a variável dominante; o modelo é. (`gemma-3-12b:min` recupera os 7, mas ao preço
de disparar em 100 % das cenas vazias — recuperação sem seletividade não vale.)

O preço dessa troca no gate, que roda em 100 % dos eventos:

| | US$/chamada de gate | passagem no dataset | recall |
|---|---|---|---|
| produção `2.5-flash-lite:v1` | 0,000582 | 48,6 % | 80,0 % |
| `3.1-flash-lite:g3` | 0,001201 (+106 %) | 55,1 % | 94,3 % |
| `3.1-flash-lite:min` (regra v1) | 0,001053 (+81 %) | 61,7 % | 97,1 % |

A 600 eventos/dia o gate sai de ~US$ 0,35 para ~US$ 0,72 por dia. O que pesa não é o
gate — é a passagem maior levar mais eventos ao detail. **Quanto exatamente, a Fase A
não diz**: passagem em dataset não é passagem em tráfego. É o que a Fase B mede.

## Fase B — INTERROMPIDA: as decisões positivas do gate não são reprodutíveis

A Fase B (réplica sobre tráfego real) começou e foi parada depois de 52 chamadas, ao
falhar na verificação de fidelidade. O que apareceu vale mais que o número que ela ia
produzir.

### O sintoma

Replicando o ledger com a mesma janela, mesmos quadros e mesmo prompt, a réplica
concorda com o que o gate 3.1 decidiu **em quase todos os negativos e em cerca de
metade dos positivos**:

| conjunto | backend | quadros | positivos reproduzidos | negativos reproduzidos |
|---|---|---|---|---|
| g3, 22/07 (9 dias) | AI Studio | S3 | **6/14** | 37/38 |
| `current`, 28-30/07 (1-3 dias) | AI Studio | S3 | **6/11** | — |
| `current`, 28-30/07 (1-3 dias) | **Vertex (o da prod)** | S3 | **5/10** | — |
| `current`, 31/07 (mesmo dia) | AI Studio | locais | 1/1 | 23/23 |

### O que foi descartado, com medição

| hipótese | teste | resultado |
|---|---|---|
| janela diferente | `n_window` vs `ledger_window` | idênticos, 52/52 |
| quadros diferentes | `window_first`/`window_last` | idênticos em todos os checados |
| S3 degrada a imagem | leitura de `storage_s3.py` | zip `ZIP_DEFLATED` verbatim, sem resize |
| não-determinismo | 3 repetições × 3 eventos × 2 backends | **3/3 idênticas** em todas |
| prompt mudou | `git log` + md5 do arquivo no container | `_prompts_g3.py` tem commit único (22/07), md5 igual |
| nº de imagens / `media_resolution` | varredura de mids (2→13 imgs) e de tier | ver abaixo |
| deriva do alias em 9 dias | positivos de 1 dia, no Vertex | **5/10** — mesma taxa dos de 9 dias |

O passo que fechou a questão da entrada foi o **contador de tokens**. A réplica no AI
Studio consumia 2.419 tokens contra 3.048 do ledger — 629 de diferença, constante nos
52 eventos. Não era entrada diferente: **é o Vertex e o AI Studio tokenizando imagem de
forma distinta**. Rodando no cliente Vertex da produção, `tok_in = 3048`, **exatamente**
o do ledger. Ou seja, a entrada replicada é comprovadamente a mesma, até o token.

E com a entrada idêntica, no mesmo backend, o mesmo modelo hoje responde
`EMPTY/False/100` onde em 22/07 registrou `DUMPING/True/95` — com evidência específica
no ledger ("pessoa deposita material na pilha, mudança visível").

### O que isso significa

O modelo é determinístico dentro de uma rajada (3/3) mas instável ao longo de dias, e a
instabilidade é **assimétrica**: os negativos, que são a maioria confiante, se repetem;
os positivos, que são o caso limítrofe, viram moeda. Como o gate positivo é justamente
o evento raro (11,2 % do tráfego), a instabilidade cai inteira sobre o que interessa.

⚠️ **Consequência para o handoff:** os **11,2 % de passagem** e os **86 % de recall** do
`gemini-3.1-flash-lite + g3` são medição de amostra única de uma decisão que se repete
~50 % das vezes. Qualquer custo/evento derivado deles carrega essa barra de erro, que
até agora ninguém tinha contabilizado. Isso inclui a comparação 2.5 × 3.1 que o
`compare_shadow.py` deu por fechada.

Continuar a Fase B produziria uma taxa de passagem com margem de erro maior que a
diferença que ela pretende medir — exatamente o que `feedback_bench_match_prod_exactly`
existe para evitar. Parei em 52 chamadas
(`data/camp51_faseB_parcial_aistudio.jsonl`, US$ 0,05).

**O pré-requisito para qualquer decisão de gate agora é medir a reprodutibilidade**:
repetir os mesmos N eventos ao longo de dias e quantificar a variância. Sem isso não há
como distinguir "candidato A é melhor que B" de ruído de serving.

## Infra / operação

- 🚨 **Os braços Gemini da Fase A rodaram no AI Studio, não no Vertex.** O ADC do gcloud
  estava expirado e a renovação exige colar um código no terminal, então usei a key do
  AI Studio documentada como fallback em `services/.env.benchmark` (mesma conta de
  billing *Saira - Testes*). A Fase B depois mostrou que **os dois backends não são
  equivalentes**: o mesmo payload conta 2.419 tokens no AI Studio e 3.048 no Vertex.
  Consequência: os números Gemini desta Fase A (a referência de produção de 80 % e o
  achado dos 7 TPs) valem para o AI Studio; **a produção roda no Vertex**. Os braços
  Bedrock não são afetados (transporte próprio), e a conclusão sobre os open-weight
  também não — eles disparam em ~100 %, margem que nenhum detalhe de backend cobre.
  Para refazer no Vertex: `gcloud auth application-default login` e
  `C51_GEMINI_AUTH=vertex` (366 chamadas, ~US$ 0,35).
- **Credenciais**: o token SSO da AWS (`codex-ops`) também estava expirado; foi renovado.
- **`gemma-3-4b` já estava** no `MODELS` de `49-.../scripts/_bedrock_client.py` — o
  handoff afirma que não. Falta no `worker/detector_bedrock.py`, que é outra coisa.
- **Disponibilidade** (critério 4): 1.342 chamadas, **4 erros**, todos
  `ministral-3-14b:g3` com `sem JSON na resposta (stop=end_turn)`. Os demais 10 braços:
  zero erro. Não se reproduziu a indisponibilidade de endpoint que o Camp 48 viu no
  `nemotron-nano-12b`.
- **Custo**: US$ 0,7153 (Bedrock 0,3693 · Gemini 0,3460).

## Arquivos

| o quê | onde |
|---|---|
| prompt de gate mínimo | `scripts/_prompts_gate51.py` |
| runner da Fase A | `scripts/bench_gate51.py` |
| agregador + veredito | `scripts/agg_gate51.py` |
| decisões por evento | `results/gate51_faseA.csv`, `results/gate51_faseA_gemini.csv` |
| resumo por braço | `results/gate51_faseA_summary.json` |
| runner da Fase B (roda na prod) | `scripts/replay_gate51.py` |
| Fase B parcial, interrompida | `data/camp51_faseB_parcial_aistudio.jsonl` (52 ev) |
