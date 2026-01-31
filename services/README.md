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

Cada arquivo e **standalone** (nao depende de merge com outro). Isso evita conflitos de `container_name` e portas.

- **`docker-compose.yml`** - Desenvolvimento local. Portas 3000, 8001, 5432, 5050.
- **`docker-compose.test.yml`** - Teste (servidor). Portas 3001, 8002, 5433, 5001, 5051.
- **`docker-compose.prod.yml`** - Producao (servidor). Portas 3000, 8001, 5432, 5000.

### Comandos

```bash
# Dev (local)
docker compose up -d --build
docker compose logs -f backend
docker compose exec backend alembic upgrade head
docker compose exec backend python seed_db.py
docker compose down

# Teste (servidor)
docker compose -p saira-test -f docker-compose.test.yml up -d --build
docker compose -p saira-test -f docker-compose.test.yml down

# Producao (servidor)
docker compose -p saira-prod -f docker-compose.prod.yml up -d --build
docker compose -p saira-prod -f docker-compose.prod.yml down
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
├── docker-compose.yml          # Dev
├── docker-compose.test.yml     # Teste
└── docker-compose.prod.yml     # Producao
```
