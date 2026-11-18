# Camp 53 — desenho do gate `gemini-decision-1` em shadow (17/11/2026)

Desenho, sem implementação. Nada aqui existe no worker ainda. Os números vêm do [`report.md`](report.md), seção 5.

## Por que shadow e não troca direta

No dataset o Decisions iguala o gate de hoje em recall (18/18 detecções reais passam nos limiares 0,20 a 0,30), repete melhor os confirmados do holdout (30 a 40 de 44, contra 26 do gate de hoje) e custa US$ 0,00021 por chamada, contra US$ 0,0011. O que o dataset não responde:

- **Taxa de passagem em tráfego real.** O custo da cascata depende de quantos eventos chegam ao detail. A projeção (2,9% a 7,3%, conforme o limiar) sai de 40 cenas; em produção o gate de hoje deixa passar cerca de 2,2%.
- **Estabilidade entre dias.** Três execuções em quatro horas devolveram probabilidades idênticas, o que pode ser cache do lado do Google.
- **Limiar.** Os três limiares dão o mesmo recall no oficial; só o holdout os separa, e 4 descartes reais do holdout ficam entre 0,178 e 0,199.
- **Operação.** O modelo foi lançado em 11/11/2026 e só existe na API do AI Studio (v1beta), não no Vertex.

O shadow mede os três primeiros itens sem tocar no que a produção decide.

## A chamada

Igual à de `scripts/bench_decisions.py` (`call_decisions`), que foi a medida:

- `POST https://generativelanguage.googleapis.com/v1beta/decisions`, cabeçalhos `x-goog-api-key` e `Content-Type: application/json`.
- Corpo: `{"model": "gemini-decision-1", "input": [...], "questions": {...}}`.
  - `input`: um bloco de texto com o contexto da cena (`CONTEXT`); para cada frame, um bloco de texto `Frame i of n:` e um bloco `{"type": "image", "mime_type": "image/jpeg", "resolution": "low", "data": <base64>}`.
  - `questions`: o conjunto `q1` (`QSETS["q1"]`), seis perguntas na mesma requisição: `deposit`, `actor_at_pile`, `removal`, `pile_grew`, `carrying_in` (tipo `noul`, sim ou não) e `scene` (tipo `choice`).
- Resposta: `answers[<pergunta>]["noul"]` é a probabilidade de "sim"; nas de escolha, `answers[<pergunta>]["probabilities"][<opção>]`. Zero tokens de saída. O campo `usage` traz os tokens de entrada (2.097 por chamada com 5 frames em resolução baixa).
- Frames: os mesmos 5 do gate de produção, na mesma ordem (`[win[0]] + _gate_mids(win) + [win[-1]]`, depois de `event_windows.fit_frames_to_payload`). Doze frames ou resolução média não melhoraram a separação e custam mais.
- A decisão de gate é `answers["deposit"]["noul"] >= limiar`. As outras cinco perguntas ficam só no registro: custam o mesmo (a entrada é uma só) e servem para análise.

## Onde entra no worker

Um módulo novo, `services/yolo-worker-vm/src/worker/_shadow_decisions.py`, irmão do `_shadow_gate51.py` e com o mesmo contrato. Não generaliza os shadows que existem nem mexe no caminho de produção.

- **Ponto de chamada**: `main.py`, no bloco dos shadows (hoje perto da linha 2889, logo depois de `_shadow_gate51.run(...)`), antes de os frames da janela serem movidos:

  ```python
  if config.SHADOW_DECISIONS_ENABLED and device_id in config.SHADOW_DECISIONS_DEVICES:
      _shadow_decisions.run(
          window_paths, device_id, camera, manifest,
          prod_disposal=final_disposal,
          prod_detection_id=((cascade_payload.get("agent2_result") or {}).get("detection_id")),
          log_call=_log_gemini_call,
      )
  ```

- **`run()`** nunca levanta exceção e nunca cria detecção, com a mesma forma de execução do shadow da camp 51. Passos: conferir disjuntor e orçamento do dia; montar os 5 frames; chamar a API com timeout curto; gravar o registro.
- **Peças copiadas do `_shadow_gate51.py`**: disjuntor próprio (`_BREAKER`), orçamento diário em arquivo (`_budget_path`, `_budget_spent`, `_budget_add`), auditoria em jsonl por dispositivo (`_append_audit`) e seleção de frames (`_gate_mids`).
- **HTTP**: `urllib.request`, como no script da campanha, que é a chamada medida. O `google-genai` 3.4.0 do venv da campanha traz um módulo `decisions`, que não foi usado nem testado aqui; se a implementação preferir o SDK, conferir antes a versão que o worker instala e a paridade de tokens (2.097 por chamada).

### Variáveis novas (`config.py` e os três composes)

| Variável | Padrão | Para quê |
|---|---|---|
| `SHADOW_DECISIONS_ENABLED` | `false` | liga o shadow |
| `SHADOW_DECISIONS_DEVICES` | vazio | lista de dispositivos, separados por vírgula (começar por `pi-cam-001`) |
| `SHADOW_DECISIONS_API_KEY` | vazio | chave do AI Studio; sem chave o shadow fica desligado e registra isso uma vez |
| `SHADOW_DECISIONS_MODEL` | `gemini-decision-1` | modelo |
| `SHADOW_DECISIONS_RESOLUTION` | `low` | resolução das imagens |
| `SHADOW_DECISIONS_THRESHOLDS` | `0.20,0.25,0.30` | limiares registrados (nenhum decide nada) |
| `SHADOW_DECISIONS_TIMEOUT_SECONDS` | `15` | timeout da chamada |
| `SHADOW_DECISIONS_DAILY_BUDGET_USD` | `0.50` | teto diário; estourou, para até o dia seguinte |
| `SHADOW_DECISIONS_DETAIL_ENABLED` | `false` | fase 2: chamar o detail nos eventos que só o Decisions passa |

### O que cada registro guarda

Uma linha por janela no jsonl de auditoria, e uma linha em `gemini_call_log` via `log_call` (estágio `shadow_decisions_gate`):

- horário, dispositivo, câmera, identificador da janela e nomes dos 5 frames;
- as probabilidades das seis perguntas, sem arredondar;
- `fire_t20`, `fire_t25`, `fire_t30` (um por limiar configurado);
- o que a produção fez na mesma janela: se o gate de produção disparou e com que confiança (`agent1_triggered` e `agent1_confidence`, que o `main.py` já monta), `prod_disposal` e `prod_detection_id`;
- tokens de entrada, custo, latência, código HTTP e erro, se houver.

Guardar a probabilidade crua permite reavaliar qualquer limiar depois, sem chamada nova.

## Fases

1. **Fase 1, só o gate.** Mede taxa de passagem por limiar, concordância com o gate de produção, estabilidade, latência e erros. Custo: a pi-cam-001 gerou cerca de 500 eventos por dia entre 28/07 e 04/08 (3.988 em 8 dias); 500 × US$ 0,00021 dá cerca de US$ 0,11 por dia, ou US$ 3 por mês, por câmera.
2. **Fase 2, com detail.** Nos eventos em que o Decisions passa e o gate de produção não, chamar o detail recomendado (um `ModelOverride`, como os shadows atuais) e registrar o resultado, sem criar detecção. É o que diz se os eventos a mais são descarte ou ruído. Custo máximo no limiar 0,20: 7,3% × 500 × US$ 0,017 ≈ US$ 0,62 por dia (o 3.8-flash custa US$ 1,50 / 7,50 por 1M no Vertex). Só ligar depois de a fase 1 mostrar a taxa de passagem real.

## Critério para sair do shadow

Duas semanas de tráfego. Em 13/11 nenhuma câmera gerava detecção desde 28/09: antes de ligar, conferir se há eventos chegando ao gate, porque sem tráfego o shadow não mede nada. Olhar:

- taxa de passagem por limiar contra a do gate de produção: é ela que fecha a conta de custo;
- das detecções que o operador confirmar no período, quantas o Decisions teria deixado passar em cada limiar (recall do gate contra o rótulo do operador, não contra a produção);
- dos eventos que só o Decisions passa, uma amostra vista por alguém (folhas de frames, como em `results/exemplos.md`), porque a produção não gera detecção para eles e o operador nunca os vê;
- a mesma janela reenviada em dias diferentes devolve a mesma probabilidade? (um reenvio diário de 20 janelas guardadas custa menos de US$ 0,01);
- latência p50 e p95 e taxa de erro, incluindo 429 e 402.

A promoção a gate de verdade é outro desenho: seletor de backend do gate, com queda para o gate atual quando a API falhar, e campanha própria.

## Falhas

- Timeout, 5xx ou 429: conta no disjuntor, registra e segue; sem nova tentativa (é shadow).
- 402 (crédito pré-pago esgotado): desliga até o dia seguinte e registra uma vez; não repetir a cada janela.
- Resposta sem `answers["deposit"]`: registra a resposta bruta truncada e conta como erro.
- Qualquer exceção fica dentro de `run()`.

## Chave e dados

- A chave é do AI Studio, de um projeto com faturamento no nível pago (nesse nível o Google não usa o conteúdo para melhorar produtos). Fica só no `.env` do servidor, como `SHADOW_DECISIONS_API_KEY`; os composes repassam com `${SHADOW_DECISIONS_API_KEY:-}`; nunca em log, registro de auditoria ou repositório.
- A chave usada na campanha passou pelo histórico de um chat e deve ser trocada antes de qualquer uso em servidor.
- O compose de produção prevê o Vertex sem chave (`GEMINI_USE_VERTEX=true`, federação de identidade com `vertex-cred-config.json`); qual caminho está ativo no servidor faz parte da leitura de produção pendente. O Decisions obriga a ter uma chave de API e crédito pré-pago em outro produto do Google: é mais um segredo e mais um saldo para acompanhar.
- As imagens das câmeras passariam a ir também para a API do AI Studio. Conferir se isso cabe no que o contrato diz sobre tratamento de imagens antes de ligar em produção.

## Testes a escrever junto com a implementação

- montagem do corpo: 5 frames, ordem, resolução, as seis perguntas;
- leitura de `noul` e de `probabilities`; resposta malformada;
- limiares: `fire_*` certo nas bordas (0,199 e 0,200);
- desligado por padrão; sem chave não chama; dispositivo fora da lista não chama;
- disjuntor abre e fecha; orçamento do dia barra a chamada; 402 desliga até o dia seguinte;
- `run()` não levanta exceção com a API fora do ar;
- a chave não aparece em nenhum registro.

## Decisões em aberto (do Alexandre)

1. Aceitar uma dependência da API do AI Studio (chave e crédito pré-pago) ao lado do Vertex.
2. Em que projeto e com que saldo a chave de produção seria criada.
3. Envio das imagens ao AI Studio frente ao contrato.
4. Quando haverá tráfego para o shadow medir alguma coisa.
