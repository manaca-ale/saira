# Backend - SAIRA API

API REST para o sistema SAIRA, responsavel por autenticacao, gestao de ocorrencias, cameras, usuarios e metricas do dashboard.

## Stack

- **FastAPI** (framework async)
- **SQLAlchemy 2.0** (ORM async com asyncpg)
- **Alembic** (migracoes de banco)
- **PostgreSQL 15** + **PostGIS 3.4** (banco geoespacial)
- **GeoAlchemy2** (suporte a geometrias no ORM)
- **python-jose** (JWT)
- **pwdlib** (hashing de senhas)
- **Pydantic 2** (validacao de schemas)
- **Boto3** (integracao AWS S3)

## Estrutura

```text
app/
├── main.py                          # Inicializacao FastAPI, CORS, routers
│
├── api/
│   ├── deps.py                      # Dependencias (get_db, get_current_user)
│   └── v1/
│       ├── router.py                # Agregador de rotas /api/v1
│       └── endpoints/
│           ├── auth.py              # POST /login, POST /register, GET /me
│           ├── users.py             # CRUD de usuarios
│           ├── cameras.py           # CRUD de cameras
│           ├── detections.py        # CRUD de deteccoes + filtros
│           └── dashboard.py         # Metricas e agregacoes
│
├── models/
│   ├── user.py                      # Modelo User (email, cargo, RPA, etc.)
│   ├── camera.py                    # Modelo Camera (RTSP, geom POINT)
│   └── detection.py                 # Modelo Detection (UUID, status, geom POINT)
│
├── schemas/
│   ├── auth.py                      # Token, LoginRequest
│   ├── user.py                      # UserCreate, UserUpdate, UserResponse
│   ├── camera.py                    # CameraCreate, CameraResponse
│   ├── detection.py                 # DetectionCreate, DetectionUpdate, DetectionResponse
│   └── dashboard.py                 # DashboardStats, OccurrencesByMonth, VolumeByRPA
│
├── core/
│   ├── config.py                    # Settings via pydantic-settings (.env)
│   ├── database.py                  # Engine async + SessionLocal
│   └── security.py                  # create_access_token, verify_password
│
├── services/
│   └── geospatial_service.py        # Queries espaciais PostGIS
│
└── utils/                           # Utilitarios diversos
```

## Endpoints

### Auth (`/api/v1/auth`)

| Metodo | Rota | Descricao |
| ------ | ---- | --------- |
| POST | `/login` | Autentica usuario (OAuth2 password flow), retorna JWT |
| POST | `/register` | Cria novo usuario |
| GET | `/me` | Retorna dados do usuario autenticado |

### Conecta Recife (`/api/v1/integrations/conecta`)

| Metodo | Rota | Descricao |
| ------ | ---- | --------- |
| GET | `/login-url` | Gera URL de autorizacao OIDC (Conecta Recife) |
| GET | `/callback` | Callback OIDC (troca `code`, sincroniza usuario, gera ticket) |
| POST | `/exchange-ticket` | Troca ticket temporario por JWT interno SAIRA |
| GET | `/logout-url` | Retorna URL de logout SSO no Conecta |
| POST | `/revoke-consent` | Revogacao de dados pessoais com introspeccao de token |

### Detections (`/api/v1/detections`)

| Metodo | Rota | Descricao |
| ------ | ---- | --------- |
| GET | `/` | Lista deteccoes com filtros (RPA, status, bairro, periodo) e paginacao |
| GET | `/{id}` | Busca deteccao por UUID |
| POST | `/` | Cria nova deteccao |
| PATCH | `/{id}` | Atualiza deteccao (status, infratores, etc.) |
| DELETE | `/{id}` | Remove deteccao |

### Dashboard (`/api/v1/dashboard`)

| Metodo | Rota | Descricao |
| ------ | ---- | --------- |
| GET | `/stats` | KPIs: total de ocorrencias, volume diario, contagem por status |
| GET | `/occurrences-by-month` | Ocorrencias agrupadas por mes (ultimos 12) |
| GET | `/recurrent-locations` | Top 10 locais reincidentes |
| GET | `/volume-by-rpa` | Volumetria media e total por RPA |

### Users (`/api/v1/users`)

CRUD completo de usuarios do sistema.

### Cameras (`/api/v1/cameras`)

CRUD de cameras de monitoramento com coordenadas PostGIS.

## Modelos de Dados

### Detection
- `id` (UUID) - Identificador unico
- `camera_id` (FK) - Camera de origem
- `timestamp` - Data/hora da deteccao
- `logradouro`, `bairro`, `rpa` - Localizacao textual
- `latitude`, `longitude`, `geom` (POINT 4326) - Georreferenciamento
- `waste_type`, `material_type` - Classificacao do residuo
- `volume_m3` - Volumetria estimada
- `offenders` - Infratores identificados
- `status` - PENDENTE, CONFIRMADO, REJEITADO, INDETERMINADO
- `image_url` - URL da imagem no S3
- `confidence_score` - Confianca do modelo YOLO

## Desenvolvimento

```bash
# Instalar dependencias
pip install -r requirements.txt

# Rodar localmente
uvicorn app.main:app --reload --port 8001

# Migracoes
alembic upgrade head

# Seed do banco
docker compose exec backend python seed_db.py
```

## Variaveis de Ambiente

| Variavel | Descricao |
| -------- | --------- |
| `DATABASE_URL` | Connection string PostgreSQL (asyncpg) |
| `SECRET_KEY` | Chave secreta para assinatura JWT (min 32 chars) |
| `ENABLE_LOCAL_LOGIN` | Habilita login local (email/senha) |
| `ENABLE_CONECTA_LOGIN` | Habilita login via Conecta Recife |
| `ENVIRONMENT` | `development`, `test` ou `production` |
| `CONECTA_CLIENT_ID` | Client ID da aplicacao no Conecta |
| `CONECTA_CLIENT_SECRET` | Client secret (quando client confidential) |
| `CONECTA_REDIRECT_URI` | URI de callback cadastrada no Conecta |
| `AWS_ACCESS_KEY_ID` | Credencial AWS para S3 (opcional) |
| `AWS_SECRET_ACCESS_KEY` | Credencial AWS para S3 (opcional) |
| `S3_BUCKET_NAME` | Nome do bucket S3 para imagens (opcional) |
