# Docker: comandos uteis (fluxo deste projeto)

Este guia e focado no ambiente local com `services/docker-compose.yml`.

## Pre-requisito

Execute os comandos a partir de:

```bash
cd services
```

## Servicos deste compose

- `web` (frontend) -> `http://localhost:3000`
- `backend` (FastAPI) -> `http://localhost:8001`
- `db` (Postgres/PostGIS) -> `localhost:5432`
- `pgadmin` -> `http://localhost:5050`

## Ciclo diario (copiar e colar)

```bash
# subir tudo com build
docker compose up -d --build

# ver status
docker compose ps

# acompanhar logs do backend
docker compose logs -f backend

# parar tudo (mantem volumes)
docker compose down
```

## Quando mudar frontend (.env, Vite, assets)

```bash
# recria frontend e dependencias com build
docker compose up -d --build web
```

## Quando mudar backend (codigo, requirements, start.sh)

```bash
# recria backend com build
docker compose up -d --build backend
```

## Reinicio rapido sem rebuild

```bash
docker compose restart web
docker compose restart backend
```

Use `restart` apenas quando a imagem nao precisa ser recompilada.

## Logs e diagnostico

```bash
# logs de todos os servicos
docker compose logs -f

# logs de um servico especifico
docker compose logs -f web
docker compose logs -f backend
docker compose logs -f db

# detalhes tecnicos de container
docker inspect vite-react-ts-app
docker inspect saira-backend-api
```

## Entrar nos containers (shell)

```bash
docker compose exec web sh
docker compose exec backend bash
docker compose exec db bash
```

## Banco, migracoes e seeds (backend)

```bash
# aplicar migracoes
docker compose exec backend alembic upgrade head

# rodar seed principal
docker compose exec backend python seed_db.py

# seed de cameras
docker compose exec backend python seed_cameras.py
```

## Testes no backend (pytest)

```bash
# suite completa
docker compose exec backend pytest -v

# teste especifico
docker compose exec backend pytest -v tests/test_notification_service.py
```

## Simular ocorrencia para testar notificacoes

```bash
# simulacao simples (usa camera ativa aleatoria)
docker compose exec backend python simulate_occurrence.py

# simulacao filtrando por RPA
docker compose exec backend python simulate_occurrence.py --rpa "RPA 1"

# simulacao em camera especifica com payload customizado
docker compose exec backend python simulate_occurrence.py --camera-id 1 --waste-type Entulho --material-type Misto --volume 45 --confidence 0.96 --offender "Teste QA"
```

## Limpeza segura (sem apagar volumes)

```bash
# remove containers e rede deste compose
docker compose down

# remove apenas containers parados
docker container prune -f

# remove imagens dangling (nao referenciadas por tag)
docker image prune -f
```

## Limpeza agressiva (cuidado)

```bash
# remove tudo do compose, incluindo volumes (perde dados do Postgres local)
docker compose down -v

# limpeza global do Docker (pode impactar outros projetos)
docker system prune -a --volumes -f
```

## Ambientes test/prod (referencia rapida)

```bash
# teste
docker compose -p saira-test -f docker-compose.test.yml up -d --build
docker compose -p saira-test -f docker-compose.test.yml down

# producao
docker compose -p saira-prod -f docker-compose.prod.yml up -d --build
docker compose -p saira-prod -f docker-compose.prod.yml down
```
