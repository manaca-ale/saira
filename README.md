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
| [infra](services/infra/) | Infraestrutura como codigo | Terraform (AWS) |
| [db](services/db/) | Banco de dados geoespacial | PostgreSQL 15 + PostGIS 3.4 |

## Inicio Rapido

**Pre-requisitos:** Docker e Docker Compose instalados.

```bash
cd services

# Subir todos os servicos
docker-compose -p saira-dev up -d --build

# Executar migracoes
docker-compose -p saira-dev exec backend alembic upgrade head

# Popular banco com dados de teste
docker-compose -p saira-dev exec backend python seed_db.py
```

**Acessos:**

| Recurso | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API Docs (Swagger) | http://localhost:8001/docs |
| pgAdmin | http://localhost:5050 |

**Credenciais de teste:** `admin@saira.com` / `admin123`

## Ambientes

```bash
# Desenvolvimento (padrao)
docker-compose -p saira-dev up -d --build

# Teste
docker-compose -f docker-compose.override.yml -p saira-test up -d --build

# Producao (simulado)
docker-compose -f docker-compose.prod.yml -p saira-prod up -d --build
```

## Estrutura do Repositorio

```
saira/
├── services/
│   ├── frontend/          # SPA React
│   ├── backend/           # API FastAPI
│   ├── yolo-worker-vm/    # Worker de deteccao YOLO
│   ├── nginx/             # Gateway reverso
│   ├── infra/             # Terraform (AWS)
│   ├── db/                # Migracoes SQL
│   ├── docs/              # Documentacao tecnica
│   ├── scripts/           # Scripts de utilidade
│   ├── docker-compose.yml
│   ├── docker-compose.override.yml
│   └── docker-compose.prod.yml
└── README.md
```

## Licenca

Projeto interno - todos os direitos reservados.
