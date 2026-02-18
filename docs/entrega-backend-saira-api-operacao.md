# Entrega: Backend SAIRA - Arquitetura, APIs e Operacao

## Status

Data de referencia: 18 de fevereiro de 2026.

Este documento consolida o funcionamento do backend do SAIRA para entrega tecnica do projeto.

## 1. Visao Geral

O backend do SAIRA e uma API REST em FastAPI que atende:

- autenticacao local e integracao OIDC com Conecta Recife;
- gestao de usuarios, cameras e deteccoes;
- tratamento de ocorrencias (analise e resolucao);
- gestao de infratores e vinculos com ocorrencias;
- dashboards analiticos;
- notificacoes em tempo real (SSE + Redis).

## 2. Stack Tecnica

- Linguagem: Python 3.11
- Framework: FastAPI
- ORM: SQLAlchemy 2 (async)
- Migracoes: Alembic
- Banco: PostgreSQL 15 + PostGIS 3.4
- Cache/pubsub: Redis
- Auth local: JWT (python-jose)
- Hash de senha: Argon2 (pwdlib)
- HTTP client externo: httpx
- Deploy local: Docker Compose

## 3. Arquitetura de Execucao

### 3.1 Entrypoint da API

Arquivo: `services/backend/app/main.py`

- inicializa FastAPI;
- configura CORS;
- registra rotas em `/api/v1`;
- inicializa Redis no lifespan da aplicacao;
- publica endpoints de `health`.

### 3.2 Dependencias de runtime

- Banco: `DATABASE_URL`
- Redis: `REDIS_URL`
- Seguranca: `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`
- Ambiente: `ENVIRONMENT`, `LOG_LEVEL`
- Conecta Recife: variaveis `CONECTA_*`

### 3.3 Topologia Docker (dev)

- Backend: `localhost:8001`
- Frontend: `localhost:3000`
- Postgres: `localhost:5432`
- Redis: `localhost:6379`
- pgAdmin: `localhost:5050`

## 4. Modelo de Autenticacao

### 4.1 Login Local

- endpoint: `POST /api/v1/auth/login`
- recebe email/senha (OAuth2PasswordRequestForm)
- retorna JWT interno SAIRA
- controlado por flag: `ENABLE_LOCAL_LOGIN`

### 4.2 Login Conecta Recife (OIDC)

- endpoints sob `/api/v1/integrations/conecta`
- fluxo: `login-url -> callback -> exchange-ticket`
- backend sincroniza usuario local e emite JWT SAIRA
- controlado por flag: `ENABLE_CONECTA_LOGIN`

### 4.3 Autorizacao das rotas

- dependencia principal: `get_current_user`
- valida JWT interno e carrega usuario no banco
- bloqueia usuario inativo (`403`)

## 5. Catalogo de APIs

Prefixo global: `/api/v1`

### 5.1 Auth

- `POST /auth/login`
- `POST /auth/register`
- `GET /auth/me`

### 5.2 Integracao Conecta

- `GET /integrations/conecta/login-url`
- `GET /integrations/conecta/callback`
- `POST /integrations/conecta/exchange-ticket`
- `GET /integrations/conecta/logout-url`
- `POST /integrations/conecta/revoke-consent`

### 5.3 Cameras

- `GET /cameras/`
- `GET /cameras/{camera_id}`
- `POST /cameras/`
- `PATCH /cameras/{camera_id}`
- `DELETE /cameras/{camera_id}`

### 5.4 Detections

- `GET /detections/`
- `GET /detections/{detection_id}`
- `POST /detections/`
- `PATCH /detections/{detection_id}`
- `DELETE /detections/{detection_id}`
- `POST /detections/{detection_id}/resolve`
- `POST /detections/{detection_id}/start-analysis`

### 5.5 Dashboard

- `GET /dashboard/stats`
- `GET /dashboard/occurrences-by-month`
- `GET /dashboard/recurrent-locations`
- `GET /dashboard/volume-by-rpa`

### 5.6 Notifications

- `GET /notifications/`
- `GET /notifications/summary`
- `GET /notifications/stream` (SSE)
- `PATCH /notifications/{notification_id}/read`
- `PATCH /notifications/read-all`

### 5.7 Users

- `GET /users/`
- `GET /users/{user_id}`
- `POST /users/`
- `PATCH /users/{user_id}`
- `DELETE /users/{user_id}`

### 5.8 Offenders

- CRUD de perfis de infrator
- vinculo manual/automatico com ocorrencias
- analytics por tipo, reincidencia, placas e cor de veiculo

### 5.9 Test

- `POST /test/whatsapp`

## 6. Modelo de Dados (Resumo)

### 6.1 users

Campos principais:

- identidade: `id`, `name`, `email`, `phone`
- organizacao: `secretaria`, `cargo`, `rpa`
- auth: `password_hash`, `auth_provider`, `external_subject`, `is_active`
- auditoria: `last_login_at`, `created_at`, `updated_at`

### 6.2 cameras

Campos principais:

- identificacao: `id`, `name`, `device_id`
- localizacao: `logradouro`, `bairro`, `rpa`, `latitude`, `longitude`, `geom`
- captura: `rtsp_url`, `capture_interval_seconds`, `is_active`, `last_capture_at`

### 6.3 detections

Campos principais:

- ocorrencia: `id`, `camera_id`, `timestamp`
- localizacao: `logradouro`, `bairro`, `rpa`, `latitude`, `longitude`, `geom`
- classificacao: `waste_type`, `material_type`, `volume_m3`, `confidence_score`
- status: `PENDENTE`, `EM_ANALISE`, `RESOLVIDO`
- tratamento: `resolved_at`, `resolved_by`, `resolution_justification`, `forwarded_to_sector`, `analysis_started_at`, `analysis_started_by`

### 6.4 offenders / detection_offenders

- `offenders`: cadastro de perfil recorrente
- `detection_offenders`: avistamentos vinculados a deteccoes (manual/AI)

## 7. Notificacoes e Tempo Real

- notificacoes persistidas no banco
- evento em tempo real via Redis pub/sub
- frontend recebe stream por SSE em `/notifications/stream`
- autenticacao SSE via token na query string

## 8. Integracao com Sistemas Externos

### 8.1 Conecta Recife Login

- OIDC para autenticacao federada
- introspeccao de token para revogacao
- logout SSO

### 8.2 WhatsApp

- provedores configuraveis por variavel de ambiente
- rota de teste condicionada a flag (`ENABLE_WHATSAPP_TEST_ROUTE`)

## 9. Operacao e Manutencao

### 9.1 Subida do ambiente

```bash
cd services
docker compose up -d --build
```

### 9.2 Migracoes

```bash
docker compose exec backend alembic upgrade head
```

### 9.3 Seed da base

```bash
docker compose exec -T backend python seed_db.py
```

Dataset atual de teste (apos seed):

- users: 2
- cameras: 9
- detections: 1170
- offenders: 5
- detection_offenders: 681

### 9.4 Health checks

- `GET /health` -> status da API
- `GET /` -> metadata da aplicacao

## 10. Seguranca e Governanca

- JWT com expiracao configuravel
- hash de senha com Argon2
- controle de CORS por lista de origens
- trilha para revogacao de dados pessoais (Conecta Labs)
- separacao de segredos por variaveis de ambiente

## 11. Pendencias e Recomendacoes

- ampliar testes automatizados do fluxo Conecta (callback, revogacao, erros OIDC)
- incluir monitoramento centralizado (metrics/logs) por ambiente
- padronizar auditoria de eventos sensiveis (login, logout, revogacao, alteracoes de ocorrencia)

## 12. Conclusao

O backend do SAIRA esta funcional para operacao do produto e pronto para integracao federada com o Conecta Recife em modo hibrido, mantendo compatibilidade com o login local durante a fase de homologacao.
