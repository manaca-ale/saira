# Plano de Finalização do Pipeline de Dados — Projeto SAIRA

> Documento gerado em: 2026-02-08 (v3)
> Baseado em: `[ART-02] Arquitetura de Software` + análise completa do código
> Escopo: **Pipeline de dados** (ingestão → armazenamento → fake worker → banco)
> Fora de escopo: IA/YOLO real (time separado), Frontend, Ingester RTSP (futuro)

---

## 1. Situação Atual — Como as imagens chegam hoje

O fluxo real é **push-based** (ESP32 envia via HTTP):

```text
Câmera IP (campo)
    │  HTTP GET /snap.jpg (basic/digest auth)
    ▼
ESP32 (firmware ipcam_relay.cpp)
    │  HTTP POST /upload  (multipart, campo "imageFile")
    │  ⚠ SEM METADADOS (sem device_id, sem camera_id)
    ▼
esp32-server (Flask - server.py)
    │  Salva em: uploads/YYYY/MM/DD/HH-MM-SS.jpg
    │  ⚠ SEM vínculo com câmera
    ▼
Disco local (EC2)
```

### Problemas críticos identificados

| # | Problema | Onde |
|---|---|---|
| **P1** | ESP32 não envia `device_id` no POST | Firmware (`ipcam_relay.cpp`) |
| **P2** | Servidor não organiza imagens por câmera | `esp32-server/server.py` |
| **P3** | Não há vínculo imagem → câmera no banco | Servidor |
| **P4** | Filename genérico (`snapshot_relay.jpg`) | Firmware |
| **P5** | Não existe limpeza de disco | Infra |
| **P6** | Firmware bloqueia durante upload (perde intervalo) | Firmware |
| **P7** | Sem worker para testar o pipeline end-to-end | Worker |

---

## 2. Visão Geral — O que está pronto vs. o que falta

| Componente | Status | Observação |
|---|---|---|
| **Frontend (React)** | Pronto | Dashboard, CRUD, mapas, exportação PDF |
| **Backend API (FastAPI)** | Pronto | Auth, CRUD detections/cameras, Dashboard analytics |
| **Banco de Dados (PostgreSQL + PostGIS)** | Pronto | Migrations, modelos, índices GIST |
| **ESP32 firmware (ipcam-relay)** | ~70% | Funciona mas sem metadados e sem fila |
| **esp32-server (Flask)** | ~60% | Recebe imagens mas sem organização |
| **Fake Worker (teste)** | **0%** | Necessário para validar pipeline |
| **YOLO Worker real** | **0% (stubs)** | Responsabilidade do time de IA |
| **Limpeza de disco** | **0%** | Não existe |
| **Batch upload S3** | **0%** | Não existe |
| **Notificações (WhatsApp)** | **0%** | Não existe |

---

## 3. Decisões Arquiteturais (Desvios do ART-02)

| ART-02 (Original) | Arquitetura Adaptada | Motivo |
|---|---|---|
| Ingestão ativa (RTSP pull) | **Ingestão passiva** (ESP32 push via HTTP) | ESP32 faz ponte com câmeras em campo |
| Landing zone em S3 | **Landing zone no disco local** (EC2 EBS) | Custo de PUTs (~864k/dia) |
| SQS entre ingester → worker | **Filesystem** (worker lê disco local) | Tudo local, sem necessidade de fila |
| Evidências em S3 imediato | **Batch upload para S3** (2-3x/dia) | Redução de custos |
| Alertas via Telegram | **Alertas via WhatsApp** | Requisito do projeto |

---

## 4. O que falta implementar — Detalhamento

### 4.1 Firmware ESP32: Metadados + Fila de imagens (Prioridade: CRÍTICA)

**Arquivo:** `firmware/espcam-saira/src/ipcam_relay.cpp`

#### 4.1.1 Enviar `X-Device-Id` no upload

Hoje a ESP32 envia o JPEG sem nenhum contexto. O `SAIRA_DEVICE_ID` já existe como macro mas **não é incluído no request**.

**Mudança na função `uploadSnapshot()` (~5 linhas):**

Adicionar header após a linha `sock->print(String("Content-Length: ") + ...)`:

```cpp
sock->print(String("X-Device-Id: ") + String(SAIRA_DEVICE_ID) + "\r\n");
```

#### 4.1.2 Fila de imagens (captura desacoplada do upload)

**Problema atual:** O loop faz download + upload sequencialmente. Se a câmera demora 3s e o upload demora 15s, o ciclo total é 18s — mesmo com `timerDelayMs = 15000`, as imagens chegam a cada ~18s, não a cada 15s.

**Solução: separar captura de upload com fila na PSRAM**

O ESP32 tem ~4MB de PSRAM. Cada imagem tem ~40-80KB. Cabe ~50 imagens na fila.

```text
ANTES (sequencial, bloqueia):
  loop() → downloadSnapshot() → uploadSnapshot() → delay
  Intervalo real: max(timerDelay, downloadTime + uploadTime)

DEPOIS (fila, não bloqueia o intervalo):
  Timer fixo a cada N ms:
    → downloadSnapshot() → enfileira na PSRAM

  Sempre que a fila não estiver vazia:
    → desenfileira → uploadSnapshot()

  Intervalo real de captura: sempre N ms (constante)
```

**Estrutura da fila:**

```cpp
struct QueuedImage {
    uint8_t* data;       // ponteiro PSRAM
    int      length;     // tamanho JPEG
    uint32_t capturedAt; // millis() da captura
};

// Fila circular (máx ~20 imagens para segurança de memória)
static QueuedImage imageQueue[20];
static int queueHead = 0;
static int queueTail = 0;
static int queueCount = 0;
```

**Lógica do `loop()`:**

```text
1. Se millis() >= nextCaptureAt:
   a. downloadSnapshot() da câmera IP (~1-3s)
   b. Se sucesso: enfileira imagem na PSRAM
   c. Se fila cheia: descarta imagem mais antiga (overwrite)
   d. nextCaptureAt = nextCaptureAt + timerDelayMs (não millis()!)

2. Se fila não vazia E não está fazendo upload:
   a. Desenfileira imagem mais antiga
   b. uploadSnapshot() para o servidor
   c. free() da memória

3. OTA check + remote config (rate-limited, como hoje)
```

**Benefício:** A captura sempre acontece no intervalo configurado. Se o upload é lento, as imagens se acumulam na fila e são enviadas assim que possível. O servidor recebe as imagens com um pequeno delay mas **sem perda de cobertura temporal**.

---

### 4.2 esp32-server: Organizar imagens por câmera (Prioridade: CRÍTICA)

**Arquivo:** `esp32-server/server.py`

**Mudanças no endpoint `POST /upload`:**

1. **Ler `X-Device-Id`** do header HTTP
2. **Path por câmera:** `uploads/{device_id}/{YYYY}/{MM}/{DD}/{HH-MM-SS}.jpg`
3. **Fallback:** Se header não vier → `unknown_device/` + log warning
4. **Resposta enriquecida:** Retornar `device_id`, path e `image_url` no JSON

```python
@app.route("/upload", methods=["POST"])
def upload_file():
    device_id = request.headers.get("X-Device-Id", "").strip()
    if not device_id or not _sanitize_device_id(device_id):
        device_id = "unknown_device"
        print(f"WARNING: upload sem X-Device-Id, usando fallback", flush=True)

    # ... validação do arquivo ...

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}.jpg"
    rel_path = os.path.join(device_id, datetime.utcnow().strftime("%Y/%m/%d"), filename)
    # ... save + return ...
```

**O `image_url` retornado é a chave que liga a imagem ao banco.**

Formato: `http://EC2_IP:5000/uploads/{device_id}/2026/02/08/14-30-00.jpg`

---

### 4.3 Migration: `device_id` na tabela `cameras` (Prioridade: CRÍTICA)

O modelo `Camera` atual não tem campo `device_id`. Adicionar via Alembic:

```python
# Nova coluna
device_id = Column(String(64), unique=True, index=True, nullable=True)
```

Este campo é a **chave de ligação** entre todos os componentes:

```text
firmware (SAIRA_DEVICE_ID)
    → header X-Device-Id
    → path no disco uploads/{device_id}/...
    → lookup cameras.device_id
    → obtém lat, lon, bairro, rpa, logradouro
    → insere na detection com esses dados
```

---

### 4.4 Fake Worker — Teste end-to-end do pipeline (Prioridade: ALTA)

**Objetivo:** Validar o pipeline completo (imagem chega → detecção aparece no dashboard) sem depender do time de IA.

**Localização:** `services/yolo-worker-vm/src/worker/` (já tem os stubs vazios)

O fake worker monitora o diretório de uploads e, para cada imagem nova, cria uma detection fake no banco de dados com todos os campos que o frontend espera.

#### Campos que o frontend consome (extraídos de `Detections.tsx` + `detectionService.ts`):

| Campo BD (`detections`) | Tipo | Exemplo | Fonte |
|---|---|---|---|
| `camera_id` | int (FK) | `1` | Lookup por `device_id` na tabela `cameras` |
| `timestamp` | datetime | `2026-02-08 14:30:00` | Extraído do nome do arquivo |
| `logradouro` | string | `Rua do Apolo, 235` | Herdado da câmera (lookup) |
| `bairro` | string | `Recife Antigo` | Herdado da câmera (lookup) |
| `rpa` | string | `RPA 1` | Herdado da câmera (lookup) |
| `latitude` | decimal | `-8.063170` | Herdado da câmera (lookup) |
| `longitude` | decimal | `-34.871140` | Herdado da câmera (lookup) |
| `waste_type` | string | `Entulho` | **Fake:** random entre opções |
| `material_type` | string | `Concreto` | **Fake:** random |
| `volume_m3` | decimal | `2.5` | **Fake:** random 0.1-50.0 |
| `offenders` | string/null | `Veículo identificado` | **Fake:** random (30% chance) |
| `status` | enum | `Pendente` | Sempre `Pendente` |
| `image_url` | string | `http://host/uploads/cam_01/...` | URL da imagem no esp32-server |
| `confidence_score` | decimal | `0.87` | **Fake:** random 0.5-0.99 |

#### Como o `image_url` vincula imagem → detection:

```text
1. ESP32 envia imagem com X-Device-Id: cam_01_coque
2. Servidor salva em: uploads/cam_01_coque/2026/02/08/14-30-00.jpg
3. Servidor retorna: image_url = http://host:5000/uploads/cam_01_coque/2026/02/08/14-30-00.jpg
4. Worker encontra o arquivo no disco: uploads/cam_01_coque/2026/02/08/14-30-00.jpg
5. Worker extrai device_id = "cam_01_coque" do path
6. Worker faz lookup: SELECT * FROM cameras WHERE device_id = 'cam_01_coque'
7. Worker insere detection com:
   - Dados geográficos da câmera (lat, lon, bairro, rpa, logradouro)
   - image_url = "http://host:5000/uploads/cam_01_coque/2026/02/08/14-30-00.jpg"
   - Dados de detecção (fake ou real)
8. Frontend exibe no dashboard com foto clicável (photoUrl → image_url)
```

#### Implementação do fake worker:

**`main.py`** — Loop de filesystem polling:

```python
"""Fake YOLO worker — monitora uploads/ e cria detections fake no banco."""
while True:
    for device_dir in Path(UPLOAD_DIR).iterdir():
        if not device_dir.is_dir():
            continue
        device_id = device_dir.name
        camera = resolve_camera(device_id)  # lookup no banco
        if not camera:
            continue
        for jpg in sorted(device_dir.rglob("*.jpg")):
            if is_already_processed(jpg):
                continue
            detection = generate_fake_detection(camera, jpg)
            insert_detection(detection)
            mark_as_processed(jpg)
    sleep(POLL_INTERVAL)
```

**Controle de "já processado":** Usar arquivo marker `.processed` ou mover para subdir `processed/`.

**`db.py`** — Insert simples via psycopg2 ou SQLAlchemy (sync, sem async):

```python
def insert_detection(det: dict) -> str:
    """Insere detection e retorna o UUID."""
    # INSERT INTO detections (...) VALUES (...) RETURNING id
```

**`config.py`** — Variáveis de ambiente:

```python
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/opt/saira/data/uploads")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://...")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
FAKE_MODE = os.getenv("FAKE_MODE", "true").lower() == "true"
```

Quando o time de IA tiver o worker real, basta trocar `FAKE_MODE=false` e substituir `generate_fake_detection()` pela inferência YOLO real. O resto do pipeline (paths, lookup, insert, image_url) permanece idêntico.

---

### 4.5 Limpeza de disco — Landing Zone (Prioridade: ALTA)

**Cálculo com 10 câmeras a cada 15s:**

- 10 × 4/min × 60 × 24 × ~80KB ≈ **45 GB/dia**
- Disco EC2: 50 GB SSD → **lota em ~1 dia**

**Situação atual:** Já existe o script `services/scripts/backup_uploads_if_low_space.sh` no repositório. Comportamento:

1. Checa espaço livre no disco (`df -P /`)
2. Se livre >= 30% → sai sem ação
3. Se disco apertado → `rclone copy` de `uploads/` inteiro para Google Drive (folder ID hardcoded)
4. Após backup → `find $UPLOAD_DIR -mindepth 1 -delete` (apaga tudo)

**Problemas identificados:**

- Se `rclone` não está instalado ou `gdrive` remote não configurado, o script **falha e não limpa nada** (`set -euo pipefail`)
- Não distingue imagens processadas de não-processadas — apaga tudo cegamente
- Backup ao Drive é só para testes, não faz sentido em produção
- Path hardcoded (`/home/ubuntu/saira/esp32-server/uploads`)

**Ação:** Evoluir o script existente:

- **Flag `ENABLE_DRIVE_BACKUP`** (env var, default `false`) — quando `false`, pula o rclone e vai direto para a limpeza
- Usar `UPLOAD_DIR` do env var (já existe no docker-compose) em vez de path hardcoded
- Apagar apenas imagens já processadas (marker `.processed` ou subdir `processed/`)
- Manter imagens com detecção positiva até batch upload para S3
- Fallback: se rclone falhar mas `ENABLE_DRIVE_BACKUP=true`, logar erro mas **ainda limpar** imagens processadas
- Monitoramento de espaço em disco (alerta se < 20% livre)
- Cron a cada hora ou integrado no worker

---

### 4.6 Batch Upload para S3 — Evidências (Prioridade: MÉDIA)

Apenas imagens com detecção positiva vão para S3.

**Implementar:** `scripts/batch_upload_evidence.py`

- Varrer diretório `evidence/` local
- Upload em lote para `s3://saira-evidence-prod/`
- Atualizar `image_url` na tabela `detections` com URL S3
- Apagar local após confirmação
- Cron 3x/dia (06:00, 14:00, 22:00)

---

### 4.7 Notificações via WhatsApp (Prioridade: MÉDIA)

**Opções:**

| Opção | Custo | Complexidade |
|---|---|---|
| **WhatsApp Business API (Meta Cloud API)** | ~$0.05/msg | Média |
| **Twilio WhatsApp** | ~$0.005/msg | Baixa |
| **Evolution API (self-hosted)** | Gratuito | Média-Alta |

**Implementar:** Módulo que, ao inserir uma detection, envia alerta com foto + localização + tipo de infração para grupo de fiscalização.

---

### 4.8 Health check de câmeras (Prioridade: MÉDIA)

- Rastrear último upload por `device_id` no esp32-server
- Endpoint `GET /cameras/status` com lista de câmeras + tempo desde último upload
- Alerta se câmera offline por mais de X minutos

---

## 5. Diagrama do Pipeline Completo

```text
┌─────────────────┐     ┌─────────────────┐
│  Câmera IP #1   │     │  Câmera IP #N   │
└────────┬────────┘     └────────┬────────┘
         │ HTTP /snap.jpg        │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  ESP32 #1       │     │  ESP32 #N       │
│  PSRAM queue    │     │  PSRAM queue    │
│  captura fixa   │     │  captura fixa   │
│  a cada 15s     │     │  a cada 15s     │
└────────┬────────┘     └────────┬────────┘
         │ POST /upload          │
         │ + X-Device-Id         │
         └──────────┬────────────┘
                    ▼
  ┌──────────────────────────────────────────┐
  │  esp32-server (Flask)                    │
  │  - Lê X-Device-Id                       │
  │  - Salva: uploads/{device_id}/YYYY/...  │
  │  - Retorna image_url                    │
  │  - Rastreia última img por device       │
  └──────────────────┬───────────────────────┘
                     │ filesystem polling
                     ▼
  ┌──────────────────────────────────────────┐
  │  Worker (fake agora / YOLO depois)       │
  │  - Encontra nova imagem                  │
  │  - Extrai device_id do path              │
  │  - Lookup câmera → (lat, lon, bairro...) │
  │  - Gera detection (fake ou YOLO)         │
  │  - INSERT detections com image_url       │
  │  - Marca imagem como processada          │
  │  - [futuro] Dispara alerta WhatsApp      │
  └─────────┬──────────────────┬─────────────┘
            │                  │
            ▼                  ▼
  ┌──────────────┐   ┌────────────────────┐
  │ PostgreSQL   │   │ evidence/ (local)  │
  │ + PostGIS    │   └────────┬───────────┘
  │ (detections) │            │ cron 3x/dia
  └──────┬───────┘            ▼
         │           ┌────────────────────┐
         │           │ S3 saira-evidence  │
         │           └────────────────────┘
         ▼
  ┌──────────────────────────────────────────┐
  │  Frontend (React)                        │
  │  - GET /detections → tabela + filtros    │
  │  - image_url → foto clicável no modal    │
  │  - lat/lon → heatmap no dashboard        │
  └──────────────────────────────────────────┘
```

---

## 6. Resumo de Ações — Ordem de Execução

### Fase 1 — Rastreabilidade + Teste E2E (fazer primeiro)

| # | Tarefa | Componente | Esforço |
|---|---|---|---|
| 1 | Firmware: header `X-Device-Id` no upload | Firmware ESP32 | Pequeno |
| 2 | Firmware: fila PSRAM (captura desacoplada do upload) | Firmware ESP32 | Médio |
| 3 | Servidor: organizar uploads por `device_id` | esp32-server | Pequeno |
| 4 | Servidor: retornar `image_url` completo | esp32-server | Trivial |
| 5 | Migration: `device_id` na tabela `cameras` | Backend | Pequeno |
| 6 | Fake worker: polling + insert fake detection | Worker | Médio |
| 7 | OTA flash nos ESP32 em campo | Deploy | Médio |

**Resultado:** Pipeline funcional end-to-end. Imagens aparecem no dashboard com dados fake.

### Fase 2 — Sustentabilidade

| # | Tarefa | Componente | Esforço |
|---|---|---|---|
| 8 | Script de limpeza de disco | Scripts | Médio |
| 9 | Cron de limpeza (1x/hora) | Infra | Pequeno |
| 10 | Monitoramento de espaço em disco | Infra | Pequeno |
| 11 | Cadastrar câmeras reais no banco | Backend/API | Pequeno |

**Resultado:** Sistema sustentável 24/7.

### Fase 3 — Contrato com Time de IA

| # | Tarefa | Componente | Esforço |
|---|---|---|---|
| 12 | Documentar contrato (paths, metadata, DB schema) | Docs | Pequeno |
| 13 | Utilitários: `resolve_camera()`, `save_evidence()` | Lib | Pequeno |
| 14 | Batch upload de evidências para S3 | Scripts | Médio |

**Resultado:** Time de IA só precisa trocar `generate_fake_detection()` por inferência real.

### Fase 4 — Comunicação e Monitoramento

| # | Tarefa | Componente | Esforço |
|---|---|---|---|
| 15 | Bot WhatsApp para alertas | Notificações | Médio |
| 16 | Health check de câmeras | esp32-server | Pequeno |
| 17 | Alerta de câmera offline | Notificações | Pequeno |

### Fase 5 — Hardening

| # | Tarefa | Componente | Esforço |
|---|---|---|---|
| 18 | Systemd services | Infra | Pequeno |
| 19 | Docker Compose atualizado | Docker | Pequeno |
| 20 | CI/CD (GitHub Actions) | DevOps | Médio |
| 21 | Backup PostgreSQL | Infra | Pequeno |

---

## 7. Riscos e Recomendações

| Risco | Impacto | Mitigação |
|---|---|---|
| **Disco lotando** (45GB/dia) | Sistema para | Limpeza agressiva + monitoramento |
| **ESP32 PSRAM insuficiente para fila** | Perda de imagens | Limitar fila a 20 slots; descartar mais antiga |
| **Câmera offline sem alerta** | Perda de cobertura | Health check + alerta WhatsApp |
| **image_url quebra se mudar IP do servidor** | Fotos não carregam | Usar `PUBLIC_BASE_URL` configurável; ou path relativo |
| **Fake worker em produção** | Dados falsos no banco | Flag `FAKE_MODE` explícito; log claro |

---

## 8. Configuração Recomendada

```env
# ---- ESP32 Firmware (.env por device) ----
SAIRA_DEVICE_ID=cam_01_coque
SAIRA_SERVER_BASE=http://EC2_IP:5000
SAIRA_TIMER_DELAY_MS=15000
SAIRA_IP_CAM_URL=http://192.168.0.142:80/snap.jpg
SAIRA_IP_CAM_USER=admin
SAIRA_IP_CAM_PASS=admin

# ---- esp32-server (.env) ----
UPLOAD_DIR=/opt/saira/data/uploads
PUBLIC_BASE_URL=http://EC2_IP:5000

# ---- Fake Worker (.env) ----
UPLOAD_DIR=/opt/saira/data/uploads
DATABASE_URL=postgresql://postgres:senha@localhost:5432/saira_db
PUBLIC_BASE_URL=http://EC2_IP:5000
POLL_INTERVAL=5
FAKE_MODE=true

# ---- WhatsApp (.env) ----
WHATSAPP_API_URL=https://graph.facebook.com/v17.0/PHONE_ID/messages
WHATSAPP_API_TOKEN=<token>
WHATSAPP_GROUP_ID=<group_id>
```

---

## 9. Conclusão

Com as novas definições, o foco se concentra em 3 blocos de trabalho:

1. **Firmware inteligente** — Adicionar `X-Device-Id` e fila PSRAM para manter intervalo fixo de captura independente do tempo de upload. Mudança essencial para rastreabilidade e qualidade temporal dos dados.

2. **Servidor organizado** — Salvar imagens por `{device_id}/YYYY/MM/DD/`, retornar `image_url` completo. É o elo que conecta o arquivo físico ao registro no banco.

3. **Fake worker** — Permite testar o pipeline end-to-end sem esperar o time de IA. Monitora o disco, faz lookup da câmera, insere detection com `image_url` apontando para a foto real. Quando o YOLO real estiver pronto, é só trocar a função de geração de detecção — todo o resto do pipeline permanece igual.

O `image_url` é o campo que fecha o ciclo: o frontend usa ele para exibir a foto no modal de ocorrência, e o path no disco permite ao worker extrair o `device_id` para lookup no banco.
