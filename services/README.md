# services/

Diretorio principal contendo todos os servicos da aplicacao SAIRA.

## Composicao

| Servico | Porta | Descricao |
|---------|-------|-----------|
| `web` (frontend) | 3000 | SPA React servida via Nginx |
| `backend` | 8001 | API REST FastAPI |
| `db` | 5432 | PostgreSQL 15 + PostGIS 3.4 |
| `pgadmin` | 5050 | Interface de administracao do banco (dev) |
| `api-gateway` | 5000 | Nginx reverse proxy (prod/test) |

## Docker Compose

Tres arquivos de composicao para ambientes distintos:

- **`docker-compose.yml`** - Desenvolvimento local. Frontend em hot-reload, backend com volume montado.
- **`docker-compose.override.yml`** - Ambiente de teste. Portas alternativas (3001, 5433, 5001).
- **`docker-compose.prod.yml`** - Producao simulada. Inclui API gateway Nginx na porta 5000.

### Comandos

```bash
# Dev
docker-compose -p saira-dev up -d --build

# Rebuild de um servico especifico
docker-compose -p saira-dev up -d --build web

# Logs em tempo real
docker-compose -p saira-dev logs -f backend

# Migracoes
docker-compose -p saira-dev exec backend alembic upgrade head

# Seed do banco
docker-compose -p saira-dev exec backend python seed_db.py

# Derrubar tudo (mantendo dados)
docker-compose -p saira-dev down

# Derrubar tudo + apagar volumes
docker-compose -p saira-dev down -v
```

## Variaveis de Ambiente

Copie `.env.example` para `.env` e configure:

| Variavel | Descricao | Padrao |
|----------|-----------|--------|
| `SECRET_KEY` | Chave para assinatura JWT | (obrigatoria) |
| `DATABASE_URL` | Connection string PostgreSQL | via docker-compose |
| `AWS_ACCESS_KEY_ID` | Credencial AWS (S3) | (opcional) |
| `AWS_SECRET_ACCESS_KEY` | Credencial AWS (S3) | (opcional) |
| `S3_BUCKET_NAME` | Bucket para imagens | (opcional) |
| `VITE_API_URL` | URL da API para o frontend | `http://localhost:8001/api/v1` |

## Estrutura de Diretorios

```
services/
├── frontend/           # React + Vite + TypeScript
├── backend/            # FastAPI + SQLAlchemy
├── yolo-worker-vm/     # Worker YOLO (EC2)
├── nginx/              # Configuracao do gateway
├── infra/              # Terraform (AWS)
├── db/                 # Migracoes SQL manuais
├── docs/               # Documentacao e runbooks
│   ├── architecture.md
│   └── runbooks/
├── scripts/            # Scripts de utilidade
│   ├── install.sh
│   └── download_weights.sh
├── docker-compose.yml
├── docker-compose.override.yml
└── docker-compose.prod.yml
```
