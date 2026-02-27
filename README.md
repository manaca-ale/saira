# SAIRA - Sistema Automatizado de Identificacao de Residuos e Alertas

Sistema de monitoramento urbano para deteccao automatica de descarte irregular de residuos solidos, com visao computacional (YOLO), georreferenciamento (PostGIS) e painel de gestao em tempo real.

## Arquitetura

```
                  +-------------------+
                  |   Frontend (React)|  :3000
                  +--------+----------+
                           |
                  +--------v----------+
                  |  Nginx (Gateway)  |  :5000
                  +--------+----------+
                           |
                  +--------v----------+
                  | Backend (FastAPI) |  :8001
                  +--------+----------+
                           |
              +------------+------------+
              |                         |
    +---------v---------+    +----------v---------+
    | PostgreSQL/PostGIS |    |  YOLO Worker (EC2) |
    |       :5432        |    |  SQS + S3          |
    +--------------------+    +--------------------+
```

## Servicos

| Servico | Descricao | Tecnologia |
|---------|-----------|------------|
| [frontend](services/frontend/) | Interface web (SPA) | React 18, Vite, Tailwind CSS, Leaflet |
| [backend](services/backend/) | API REST | FastAPI, SQLAlchemy, Alembic, PostGIS |
| [yolo-worker-vm](services/yolo-worker-vm/) | Deteccao por visao computacional | YOLO, SQS, S3 |
| [nginx](services/nginx/) | API Gateway / Reverse proxy | Nginx |
| [db](services/db/) | Banco de dados geoespacial | PostgreSQL 15 + PostGIS 3.4 |

## Inicio Rapido

**Pre-requisitos:** Docker e Docker Compose instalados.

```bash
cd services

# Subir todos os servicos
docker compose up -d --build

# Executar migracoes
docker compose exec backend alembic upgrade head

# Popular banco com dados de teste
docker compose exec backend python seed_db.py
```

**Acessos:**

| Recurso | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API Docs (Swagger) | http://localhost:8001/docs |
| pgAdmin | http://localhost:5050 |

**Credenciais de teste:**

| Servico | Email | Senha |
| ------- | ----- | ----- |
| Frontend (hardcoded) | `admin@gmail.com` | `12345` |
| Backend API | `admin@saira.com` | `admin123` |

> O frontend ainda nao esta integrado ao backend. Usa login hardcoded temporario.

## Ambientes

Cada ambiente usa um arquivo standalone (`-f`) com nomes de container e portas unicos, permitindo coexistencia no mesmo servidor.

```bash
# Desenvolvimento (local)
docker compose up -d --build

# Teste (servidor)
docker compose -p saira-test -f docker-compose.test.yml up -d --build

# Producao (servidor)
docker compose -p saira-prod -f docker-compose.prod.yml up -d --build
```

| Recurso | Dev | Teste | Producao |
| ------- | --- | ----- | -------- |
| Frontend | :3000 | :3001 | :3000 |
| Backend | :8001 | :8002 | :8001 |
| DB | :5432 | :5433 | :5432 |
| Gateway | - | :5001 | :5000 |
| pgAdmin | :5050 | :5051 | - |

## Estrutura do Repositorio

```
saira/
├── services/
│   ├── frontend/          # SPA React
│   ├── backend/           # API FastAPI
│   ├── yolo-worker-vm/    # Worker de deteccao YOLO
│   ├── nginx/             # Gateway reverso
│   ├── db/                # Migracoes SQL
│   ├── docs/              # Documentacao tecnica
│   ├── scripts/           # Scripts de utilidade
│   ├── docker-compose.yml          # Dev (local)
│   ├── docker-compose.test.yml     # Teste (servidor)
│   └── docker-compose.prod.yml     # Producao (servidor)
└── README.md
```

## Licenca

Projeto interno - todos os direitos reservados.

