# CLAUDE.md

## 1) Objetivo do repositorio

Este repositorio concentra o sistema SAIRA, focado em monitoramento de descarte irregular com:
- captura de imagens (ESP32),
- processamento de deteccoes (YOLO worker),
- API de gestao (FastAPI + PostGIS),
- frontend web (React),
- notificacoes em tempo real (Redis/SSE) e WhatsApp.

Escopo deste documento:
- mapear a estrutura de codigo ativa,
- descrever a funcao dos arquivos principais,
- registrar como o sistema esta funcionando agora.

Observacao: o repositorio possui muitos artefatos de dados (imagens/datasets/logs). Este arquivo foca nos arquivos de execucao e manutencao.

---

## 2) Estrutura geral (alto nivel)

- `README.md`: visao geral da arquitetura SAIRA.
- `services/`: stack principal da aplicacao.
- `esp32-server/`: receptor HTTP de imagens e OTA/config remota para dispositivos.
- `firmware/`: firmware ESP32 (variante Wi-Fi ativa no repositorio).
- `docs/` e `services/docs/`: documentacao funcional/tecnica (parte com arquivos vazios).
- `.github/workflows/deploy.yml`: deploy automatizado para teste/producao via SSH.

---

## 3) Mapa de arquivos e funcionalidades

## 3.1 Orquestracao e ambiente (`services/`)

| Arquivo | Funcionalidade |
|---|---|
| `services/docker-compose.yml` | Ambiente principal local. Sobe frontend (`web`), backend, db, redis, pgadmin, esp32-server e `yolo-worker` via profile `worker`. |
| `services/docker-compose.test.yml` | Compose standalone de teste (portas diferentes). |
| `services/docker-compose.prod.yml` | Compose standalone de producao (sem pgadmin, com gateway). |
| `services/.env.example` | Variaveis de ambiente de referencia para backend/frontend/integracoes. |
| `services/README.md` | Guia operacional dos 3 compose files e variaveis centrais. |
| `services/test_worker_integration.py` | Teste E2E de upload -> worker -> backend (script manual). |
| `services/EXECUTAR_AGORA.sh` | Script auxiliar para subir stack, migrar banco e seed. |

## 3.2 Backend API (`services/backend/`)

### Bootstrap

| Arquivo | Funcionalidade |
|---|---|
| `services/backend/Dockerfile` | Build do backend FastAPI em Python 3.11 com deps de PostGIS. |
| `services/backend/start.sh` | Executa `alembic upgrade head` e sobe uvicorn na porta 8001. |
| `services/backend/requirements.txt` | Dependencias do backend (FastAPI, SQLAlchemy async, Alembic, Redis, etc.). |
| `services/backend/README.md` | Descricao funcional da API e endpoints principais. |
| `services/backend/pytest.ini` | Config padrao dos testes. |

### Core app

| Arquivo | Funcionalidade |
|---|---|
| `services/backend/app/main.py` | Inicializacao FastAPI, CORS, lifecycle Redis e roteamento `/api/v1`. |
| `services/backend/app/core/config.py` | Settings via env (`DATABASE_URL`, auth, Conecta, WhatsApp, Redis). |
| `services/backend/app/core/database.py` | Engine SQLAlchemy async e session factory. |
| `services/backend/app/core/security.py` | Hash de senha (Argon2) e JWT (create/decode token). |
| `services/backend/app/core/redis.py` | Inicializacao/encerramento do client Redis async. |
| `services/backend/app/api/deps.py` | Dependencias de auth e sessao de banco (`get_current_user`, etc.). |

### Roteamento e endpoints

| Arquivo | Funcionalidade |
|---|---|
| `services/backend/app/api/v1/router.py` | Agrega todos os endpoints v1. |
| `services/backend/app/api/v1/endpoints/auth.py` | Login local, registro e `/me`. |
| `services/backend/app/api/v1/endpoints/conecta.py` | OIDC Conecta Recife: login-url, callback, ticket exchange, logout-url, revoke-consent. |
| `services/backend/app/api/v1/endpoints/users.py` | CRUD de usuarios. |
| `services/backend/app/api/v1/endpoints/cameras.py` | CRUD de cameras. |
| `services/backend/app/api/v1/endpoints/detections.py` | CRUD/consulta de deteccoes, filtros, transicoes de status (analise/resolvido). |
| `services/backend/app/api/v1/endpoints/dashboard.py` | KPIs e agregacoes de dashboard. |
| `services/backend/app/api/v1/endpoints/notifications.py` | Listagem, resumo, stream SSE e marcacao de leitura. |
| `services/backend/app/api/v1/endpoints/offenders.py` | CRUD de perfis de infratores + vinculos por deteccao + dashboards de infratores. |
| `services/backend/app/api/v1/endpoints/test.py` | Rota de teste WhatsApp com rate limit (condicional por env). |

### Services

| Arquivo | Funcionalidade |
|---|---|
| `services/backend/app/services/notification_service.py` | Cria notificacoes, publica eventos no Redis e dispara WhatsApp. |
| `services/backend/app/services/whatsapp_service.py` | Integracao WAHA (ativa) e stub para Meta API (nao implementada). |
| `services/backend/app/services/conecta_service.py` | Cliente HTTP para endpoints OIDC do Conecta Recife. |
| `services/backend/app/services/geospatial_service.py` | Queries espaciais PostGIS (utilitario). |

### Modelos/schemas

| Arquivo | Funcionalidade |
|---|---|
| `services/backend/app/models/user.py` | Modelo `users`. |
| `services/backend/app/models/camera.py` | Modelo `cameras` com geometrias. |
| `services/backend/app/models/detection.py` | Modelo `detections` e enum de status. |
| `services/backend/app/models/notification.py` | Modelo `notifications` e enum de tipo. |
| `services/backend/app/models/offender.py` | Modelos `offenders` e `detection_offenders`. |
| `services/backend/app/schemas/*.py` | Contratos de entrada/saida da API. |

### Migracoes e dados

| Arquivo | Funcionalidade |
|---|---|
| `services/backend/alembic/versions/9820af489db3_initial_migration.py` | Tabelas iniciais (`users`, `cameras`, `detections`). |
| `services/backend/alembic/versions/b3c4d5e6f7a8_add_occurrence_treatment_fields.py` | Campos de tratamento de ocorrencia. |
| `services/backend/alembic/versions/c4d5e6f7a8b9_add_notifications.py` | Sistema de notificacoes + `last_login_at`. |
| `services/backend/alembic/versions/d5e6f7a8b9c0_add_offenders_tables.py` | Tabelas de infratores. |
| `services/backend/alembic/versions/e6f7a8b9c0d1_add_conecta_identity_fields.py` | Campos de identidade externa para Conecta. |
| `services/backend/seed_db.py` | Seed completo para dados de exemplo (deteccoes/infratores/cameras). |
| `services/backend/seed_cameras.py` | Seed de cameras reais por `device_id`. |
| `services/backend/simulate_occurrence.py` | Gera ocorrencia simulada e dispara notificacoes. |
| `services/backend/init_db.py` | Inicializacao via metadata + triggers geoespaciais (via script). |
| `services/backend/tests/*.py` | Suite focada em notificacoes e endpoints associados. |

## 3.3 Frontend (`services/frontend/`)

| Arquivo | Funcionalidade |
|---|---|
| `services/frontend/package.json` | Scripts e dependencias React/Vite. |
| `services/frontend/vite.config.ts` | Proxy local de `/api` para backend em `localhost:8001`. |
| `services/frontend/Dockerfile` | Build multi-stage e publicacao via Nginx. |
| `services/frontend/nginx.conf` | SPA fallback + proxy `/api` para `backend:8001`. |
| `services/frontend/src/main.tsx` | Bootstrap app + providers de auth/notificacao. |
| `services/frontend/src/App.tsx` | Rotas principais (`/login`, `/dashboard`, `/detections`, `/users`, `/history`). |
| `services/frontend/src/contexts/AuthContext.tsx` | Login local e Conecta, persistencia de token/usuario. |
| `services/frontend/src/contexts/NotificationContext.tsx` | Consumo REST + SSE de notificacoes. |
| `services/frontend/src/services/api.ts` | Axios com interceptors de JWT e 401. |
| `services/frontend/src/services/detectionService.ts` | Busca/filtro paginado de deteccoes e transicoes de status. |
| `services/frontend/src/services/dashboardService.ts` | APIs de KPIs do dashboard. |
| `services/frontend/src/services/userService.ts` | CRUD de usuarios. |
| `services/frontend/src/services/notificationService.ts` | REST + EventSource para notificacoes. |
| `services/frontend/src/pages/Login.tsx` | Tela de login local + botao Conecta Recife. |
| `services/frontend/src/pages/ConectaCallback.tsx` | Finaliza login via ticket do backend. |
| `services/frontend/src/pages/Dashboard.tsx` | Dashboard com mapa, filtros, KPIs e tab de infratores. |
| `services/frontend/src/pages/Detections.tsx` | Tabela paginada de deteccoes com filtros e acoes. |
| `services/frontend/src/pages/UsersPage.tsx` | Gestao de usuarios. |

## 3.4 Worker YOLO (`services/yolo-worker-vm/`)

| Arquivo | Funcionalidade |
|---|---|
| `services/yolo-worker-vm/Dockerfile` | Container Python com OpenCV headless e worker entrypoint. |
| `services/yolo-worker-vm/requirements.txt` | Dependencias (psycopg2, ultralytics, opencv, redis). |
| `services/yolo-worker-vm/src/worker/main.py` | Loop de scan em `UPLOAD_DIR`, deteccao, insercao no DB e publicacao no Redis. |
| `services/yolo-worker-vm/src/worker/config.py` | Configuracoes por env (modelos, DB, Redis, mock mode, etc.). |
| `services/yolo-worker-vm/src/worker/detector_yolo.py` | Inferencia real com dois modelos YOLO (residuo e infrator). |
| `services/yolo-worker-vm/src/worker/detector_mock.py` | Inferencia mock para testes sem pesos reais. |
| `services/yolo-worker-vm/src/worker/db.py` | Conexao sync no Postgres e publicacao de eventos Redis. |
| `services/yolo-worker-vm/src/worker/models.py` | Dataclasses internas (camera, detection, offender). |
| `services/yolo-worker-vm/src/worker/queue_sqs.py` | Placeholder vazio. |
| `services/yolo-worker-vm/src/worker/storage_s3.py` | Placeholder vazio. |
| `services/yolo-worker-vm/systemd/saira-yolo-worker.service` | Placeholder vazio no repositorio atual. |

## 3.5 ESP32 receiver (`esp32-server/`)

| Arquivo | Funcionalidade |
|---|---|
| `esp32-server/server.py` | API Flask para `/upload`, `/status`, OTA (`/ota/*`) e config remota por dispositivo (`/device/<id>/config*`). |
| `esp32-server/Dockerfile` | Servico com gunicorn. |
| `esp32-server/docker-compose.yml` | Compose local do receptor. |
| `esp32-server/docker-compose.test.yml` | Compose de teste. |
| `esp32-server/docker-compose.prod.yml` | Compose de producao (inclui `fake-worker` mock). |
| `esp32-server/requirements.txt` | Dependencias Flask/gunicorn. |

## 3.6 Gateway/Nginx

| Arquivo | Funcionalidade |
|---|---|
| `services/nginx/gateway.conf` | Reverse proxy para `/api` e `/health` no backend. |
| `services/nginx/README.md` | Guia de uso do gateway. |

## 3.7 Banco (`services/db/`)

| Arquivo | Funcionalidade |
|---|---|
| `services/db/migrations/schema.sql` | Arquivo presente, mas vazio no estado atual. |

## 3.8 Firmware (`firmware/`)

### `firmware/espcam-saira/` (Wi-Fi)

| Arquivo | Funcionalidade |
|---|---|
| `firmware/espcam-saira/src/main.cpp` | Fluxo de camera onboard ESP32-CAM com upload periodico e OTA/config remota. |
| `firmware/espcam-saira/src/ipcam_relay.cpp` | Relay de snapshot de camera IP para `/upload`, com fila local, auth digest/basic e upload HTTP. |
| `firmware/espcam-saira/include/*.h` | Config de rede/OTA/remoto. |

---

## 4) Como o sistema esta funcionando no momento (diagnostico atual)

Data da verificacao: `2026-02-27`.

### 4.1 Estado de containers observado

Servicos SAIRA ativos:
- `vite-react-ts-app` (frontend) - `Up`.
- `saira-backend-api` (backend) - `Up`.
- `saira-postgres-db` - `Up (healthy)`.
- `saira-pgadmin` - `Up`.
- `saira-esp32-server` - `Up`.
- `saira-api-gateway-test` - `Up`.
- `saira-yolo-worker` - `Restarting` (loop de falha).

### 4.2 Checks de saude executados

- Backend direto: `http://localhost:8001/health` -> `{"status":"healthy"}`.
- Gateway teste: `http://localhost:5001/health` -> `{"status":"healthy"}`.
- Frontend: `http://localhost:3000` -> HTTP 200.
- ESP32 receiver: `POST http://localhost:5002/status` -> `Received`.

### 4.3 Falha ativa identificada

`yolo-worker` em restart continuo.
Erro recorrente em log:
- `psycopg2.OperationalError: could not translate host name "db" to address`.

Impacto funcional:
- Upload de imagem para `esp32-server` funciona.
- Backend/frontend estao online.
- Pipeline automatico de deteccao (worker -> banco -> notificacao) fica interrompido enquanto o worker nao conectar ao banco.

### 4.4 Fluxo teorico vs fluxo efetivo agora

Fluxo teorico do sistema:
1. Dispositivo envia imagem para `esp32-server` (`/upload`).
2. Worker processa imagem e grava `detections` no Postgres.
3. Backend disponibiliza dados e cria notificacoes.
4. Frontend consume REST + SSE em tempo real.

Fluxo efetivo no estado atual:
- Passos 1, 3 e 4 estao operacionais.
- Passo 2 esta quebrado por falha de conectividade do worker com hostname `db`.

---

## 5) Inconsistencias estruturais (estado atual)

1. Resolvido em `2026-02-27`:
- removidos diretorios duplicados com espacos no nome:
  `services/  infra`, `services/ db`, `services/api/       src/         api`.

2. Modulos/arquivos vazios (placeholders) ainda presentes em partes importantes:
- `services/api/*` praticamente vazio (1-2 bytes por arquivo).
- `services/db/migrations/schema.sql` vazio.
- `services/yolo-worker-vm/src/worker/queue_sqs.py` vazio.
- `services/yolo-worker-vm/src/worker/storage_s3.py` vazio.
- `services/yolo-worker-vm/systemd/saira-yolo-worker.service` vazio.
- Parte de `services/docs/*` e `services/scripts/*` vazia.

3. Artefatos grandes no repositorio:
- muitas imagens/datasets/logs versionados, o que aumenta ruido de manutencao e custo de checkout.
- em `services/yolo-worker-vm`, os artefatos de experimento `experiments/dataset/` e
  `experiments/final_saved_models/` foram removidos em `2026-02-27`.

4. Evidencia de padronizacao incompleta de line endings/scripts:
- logs do backend mostram warning de `\r` em `start.sh` durante boot (`$'\r': command not found`).

---

## 6) Resumo executivo

- O core do produto esta implementado em `services/backend`, `services/frontend`, `esp32-server` e `services/yolo-worker-vm`.
- Backend, frontend e receiver estao online e respondendo.
- O worker de deteccao esta falhando em runtime por resolucao de hostname do banco (`db`), impedindo o processamento automatico ponta-a-ponta.
- Existem blocos importantes ainda em estado placeholder (API secundaria e partes do worker).

Este documento deve ser mantido como referencia de onboarding tecnico e estado operacional do repositorio.

