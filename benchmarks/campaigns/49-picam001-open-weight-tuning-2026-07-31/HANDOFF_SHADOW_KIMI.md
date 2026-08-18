# HANDOFF — Shadow `kimi-k2.5` single-call em produção (pi-cam-001)

> Ler primeiro numa sessão nova. Substitui o shadow Gemini-3.1 que roda hoje.
> Origem: Camp 49 (`report.md` nesta pasta).

## Objetivo

Colocar em **shadow log-only** na `pi-cam-001` o candidato open-weight que venceu o
Camp 49, e **desligar o shadow Gemini-3.1** atual (Camp 47), que já cumpriu seu papel.

**Configuração vencedora — `kimi-k2.5:v4_single`:**

| parâmetro | valor |
|---|---|
| modelo | `moonshotai.kimi-k2.5` (Bedrock, conta `codex-ops` 818680680175, `us-east-1`) |
| arquitetura | **1 chamada só** — sem gate, janela cheia direto no detail |
| janela | a mesma de prod: `subsample_frames(48)` → `fit_frames_to_payload(8 MB)` |
| imagens | **640 px de largura, JPEG q70** (~55 KB/frame) |
| teto de payload | **2,7 MB de imagem crua** (Bedrock corta em corpo de 4 MB) |
| prompt | `_prompts_v4picam.V4_DETAIL_PROMPT` (flagrante + cláusula de catador) |
| structured output | **JSON-em-texto** — o kimi aceita `toolConfig` e o IGNORA |
| max_output_tokens | 8192 · temperature 0 |
| schema | `GeminiInfractionReport` (o de produção, sem alteração) |

**Desempenho medido** (122 eventos, rótulos revisados por humano na Fase 0):

| | recall/det | precisão | alarmes falsos | $/ev |
|---|---|---|---|---|
| prod hoje (V1) | 17/19 · 89,5% | 63,0% | 10 | 0,00725 |
| **kimi `v4_single`** | **19/19 · 100%** | 57,6% | 14 | **0,00657 (−9%)** |

A 600 ev/dia: **+9 descartes/dia, zero perdidos, +20 alarmes falsos/dia.**
O shadow existe para verificar se isso se sustenta fora do dataset.

---

## 1. Desligar o shadow Gemini-3.1 (Camp 47)

No `.env` de produção em `services/`:

```bash
SHADOW_MODEL_ENABLED=false
```

`docker compose -p saira-prod ... up -d --no-deps --profile worker yolo-worker` para
aplicar. Não apagar as variáveis — só desligar, para poder religar se precisar
comparar. O ledger antigo em `STATE_DIR/shadow_model_audit/` fica preservado.

⚠️ Antes de desligar, **exportar o acumulado** do shadow 3.1 (roda desde 22/07): é a
base de comparação Gemini-2.5 vs 3.1 que nunca foi fechada
(`compare_shadow.py` era o pendente do Camp 47).

## 2. Credenciais AWS — VERIFICAR PRIMEIRO

**A tubulação já existe**, não precisa criar:

- `config.py:550-551` → `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
- `docker-compose.prod.yml:327-328` → já injeta as duas no worker
- `config.py:534` → `HAIKU_AWS_PROFILE` default **`codex-ops`** (mesma conta do Bedrock)
- `requirements.txt:10` → `boto3>=1.34.0` já instalado

**O que checar antes de codar:**

```bash
ssh saira-prod
docker exec saira-yolo-worker-prod env | grep AWS_          # as chaves estão setadas?
docker exec saira-yolo-worker-prod python -c "
import boto3; print(boto3.client('sts').get_caller_identity())"   # cai em 818680680175?
docker exec saira-yolo-worker-prod python -c "
import boto3; c=boto3.client('bedrock-runtime',region_name='us-east-1')
print(c.converse(modelId='moonshotai.kimi-k2.5',
  messages=[{'role':'user','content':[{'text':'diga OK'}]}],
  inferenceConfig={'maxTokens':8})['output'])"                    # tem permissão?
```

Se **não** estiverem setadas: criar um IAM user no `codex-ops` com política mínima
(`bedrock:InvokeModel` no recurso `moonshotai.kimi-k2.5`), pôr as chaves no `.env` de
prod. **Não** usar as credenciais pessoais SSO — elas expiram.

## 3. Código — o seam que falta

O shadow atual é **amarrado ao Gemini**:

| ponto | arquivo:linha | o que é |
|---|---|---|
| hook | `worker/main.py:2748` | chama `_run_shadow_model(window_paths, ...)` dentro de `_process_event_device`, guardado por `SHADOW_MODEL_ENABLED and device_id in SHADOW_MODEL_DEVICES` |
| implementação | `worker/main.py:2181` | `_get_shadow_client()` (genai), `ModelOverride`, gate+detail |
| override | `worker/detector_gemini.py:324` | `ModelOverride.client` é um cliente **genai** |
| ledger | `worker/main.py:2158` | `_append_shadow_model_audit` → `STATE_DIR/shadow_model_audit/{data}/{device}.jsonl` |

**Recomendação: NÃO generalizar `_run_shadow_model`.** Criar um
`_run_shadow_bedrock(...)` irmão, com o mesmo contrato e o mesmo ledger. Motivo: o
caminho Gemini é o de produção; mexer nele para acomodar um shadow arrisca o que já
funciona. Duplicar ~60 linhas é mais barato que um bug em prod.

**Código pronto para portar** (de
`benchmarks/campaigns/49-picam001-open-weight-tuning-2026-07-31/scripts/`):

- `_bedrock_client.py` — copiar para `worker/detector_bedrock.py`. Já traz: teto de
  payload (`MAX_RAW_BYTES=2_700_000`), `prepare_images(mode="low")` (640px q70 +
  corte uniforme se estourar), degradação `toolConfig`→texto, clamp de `max_tokens`
  por modelo, fallback sem-`system`, tabela de preço, retry/backoff.
  ⚠️ Trocar `boto3.Session(profile_name=PROFILE)` por `boto3.client(...)` puro —
  em container não há perfil SSO, as credenciais vêm do ambiente.
- `_prompts_v4picam.py` → `worker/_prompts_v4picam.py` (só o `V4_DETAIL_PROMPT`).

**O que `_run_shadow_bedrock` faz** (espelhando `_run_shadow_model`):

1. `win = event_windows.fit_frames_to_payload(window_paths, GEMINI_MAX_PAYLOAD_BYTES)`
   — a MESMA janela que prod usou (o `subsample_frames` já foi aplicado antes)
2. `pay = detector_bedrock.prepare_images(win, mode="low")`
3. `cc = _shadow_camera_context(camera, device_id, win[-1].name)` (já existe)
4. `user = detector_gemini._user_prompt(camera_context=cc, frame_names=[p.name for p in win], mosaic_mode="off")`
5. `res = detector_bedrock.converse(alias, V4_DETAIL_PROMPT, user, pay.blobs, GeminiInfractionReport, max_tokens=8192)`
6. Gravar no ledger: `would_confirm = bool(res.report.infraction_confirmed)`,
   `detail_conf`, `waste_type`, `evidence_summary`, `tok_in/out`, `cost_usd`,
   `latency_ms`, `json_mode`, `n_images`, `payload_mb`, `prod_disposal`,
   `prod_detection_id`, `event_ref`
7. **`persist=False` sempre.** Envolver TUDO em `try/except` amplo — o shadow nunca
   pode derrubar prod (o `_run_shadow_model` já faz isso; copiar o padrão)

## 4. Flags novas

`config.py` (ao lado das `SHADOW_MODEL_*`):

```python
SHADOW_BEDROCK_ENABLED = os.getenv("SHADOW_BEDROCK_ENABLED", "false")... 
SHADOW_BEDROCK_DEVICES = {...}                       # "pi-cam-001"
SHADOW_BEDROCK_MODEL   = os.getenv("SHADOW_BEDROCK_MODEL", "moonshotai.kimi-k2.5")
SHADOW_BEDROCK_REGION  = os.getenv("SHADOW_BEDROCK_REGION", "us-east-1")
SHADOW_BEDROCK_IMG_WIDTH   = int(os.getenv("SHADOW_BEDROCK_IMG_WIDTH", "640"))
SHADOW_BEDROCK_IMG_QUALITY = int(os.getenv("SHADOW_BEDROCK_IMG_QUALITY", "70"))
SHADOW_BEDROCK_MAX_OUTPUT_TOKENS = int(os.getenv(..., "8192"))
```

🚨 **PEGADINHA CONHECIDA:** o worker usa `environment:` explícita no compose, **não**
`env_file`. Toda flag nova precisa ser adicionada ao `docker-compose.prod.yml` **e**
ao `docker-compose.test.yml`, senão não chega no container. Isso já custou os PRs
#73/#75/#76 no Camp 47.

## 5. Validação antes do deploy

1. **Local**: `MOCK_MODE=true`, forçar um evento, conferir que o ledger é escrito e que
   nenhuma detecção é criada.
2. **test-saira primeiro** (`docker-compose.test.yml`), não direto em prod.
3. Conferir no log: `{"event":"shadow_bedrock", ...}` a cada evento da pi-cam-001.
4. Conferir que `detections` **não** ganhou linha nova pelo shadow.

## 6. Comparação (o entregável do shadow)

Ledger em `STATE_DIR/shadow_bedrock_audit/{data}/pi-cam-001.jsonl`. Depois de 1-2
semanas, join por `prod_detection_id` / `event_ref` contra `detections.status`
(CONFIRMADO/REJEITADO pelo operador) e calcular:

- recall: dos que o operador CONFIRMOU, quantos o kimi teria confirmado
- alarmes falsos: dos que o operador REJEITOU, quantos o kimi teria confirmado
- custo real vs os US$ 0,00657/ev estimados
- **quadrantes**: onde kimi e prod discordam — é a lista de eventos para revisar à mão

⚠️ Filtrar o ledger por `model` — a pasta pode conter registros do shadow antigo.

## 7. Custo esperado

~600 eventos/dia × US$ 0,00657 = **~US$ 4/dia, ~US$ 56 em 14 dias**. Como é single-call,
**não há caminho barato de "só gate"** — todo evento paga a janela cheia. Se o custo
incomodar, o `v4_casc_5f` custa US$ 0,00443/ev mas cai para 73,7% de recall.

Billing sai na conta AWS `codex-ops`, **não** na conta GCP da Prefeitura.

## 8. Rollback

`SHADOW_BEDROCK_ENABLED=false` + recreate do worker. Como é `persist=False` e está tudo
em `try/except`, o pior caso é latência extra por evento (p50 ~12 s medidos no bench,
em paralelo ao fluxo normal).

## 9. Critério de aceite do shadow

Manter o candidato vivo se, em 2 semanas de tráfego real:
- recall ≥ o de prod (não perder nada que o operador confirmou), **e**
- alarmes falsos ≤ 1,5× os de prod, **e**
- custo real ≤ US$ 0,008/evento, **e**
- **zero** incidente de disponibilidade (o Camp 49 viu 3 de 6 open-weight caírem em
  24 h; kimi teve 0 erros em ~1.500 chamadas, mas 2 semanas é outro teste)

## Contexto que evita retrabalho

- **Não tentar cascata.** O Camp 49 mediu: o gate do kimi barra recall sem ganho
  compensatório, e a confiança dele só tem 3 valores (85/92/95) — não dá para calibrar.
- **Não tentar filtro CV para os alarmes falsos.** Testado: duração dos falsos alarmes
  é 108 s vs 107 s dos descartes reais. BGSUB/structural reagem ao catador igual.
- **O prompt V4 também melhora o Gemini** (recall 89,5→94,7%, precisão 63→69,2%, mesmo
  custo). É um deploy separado e independente deste — ver
  `project_prompt_v4_flagrante_catador_2026-07-31` na memória.
