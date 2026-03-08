# Contexto do Projeto: SAIRA

Sistema de monitoramento de descarte irregular urbano com câmeras ESP32,
detecção YOLO, API FastAPI e frontend React. Desenvolvido para a Prefeitura
do Recife / EMPREL.

---

## Stack Tecnológica

- **Backend:** FastAPI + SQLAlchemy async + Alembic + PostGIS (PostgreSQL)
- **Frontend:** React 18 + TypeScript + Vite + TailwindCSS
- **Worker IA:** Python + Ultralytics YOLO (dois modelos: resíduo + infrator)
- **Hardware:** ESP32-CAM com firmware C++ (upload HTTP periódico + OTA remota)
- **Auth:** JWT (Argon2 hash) + OIDC Conecta Recife
- **Mensageria:** Redis (Pub/Sub + SSE para notificações em tempo real)
- **WhatsApp:** integração WAHA (ativa)
- **Infra:** Docker Compose (local/teste/produção) + NGINX gateway + GitHub Actions CI/CD

## Estrutura de Diretórios

```
saira/
├── services/
│   ├── docker-compose.yml          # ambiente principal (web, backend, db, redis, worker)
│   ├── docker-compose.test.yml     # portas diferentes — ambiente de teste
│   ├── docker-compose.prod.yml     # produção (sem pgadmin, com gateway)
│   ├── backend/
│   │   ├── app/
│   │   │   ├── main.py             # FastAPI app, CORS, lifecycle Redis, roteamento /api/v1
│   │   │   ├── core/               # config, database, security, redis
│   │   │   ├── api/v1/endpoints/   # auth, users, cameras, detections, dashboard,
│   │   │   │                       #   notifications, offenders, conecta
│   │   │   ├── models/             # user, camera, detection, notification, offender
│   │   │   └── schemas/            # contratos Pydantic de entrada/saída
│   │   ├── alembic/versions/       # migrações (initial → offenders → conecta identity)
│   │   ├── tests/                  # suite focada em notificações
│   │   ├── seed_db.py              # seed completo de exemplo
│   │   └── start.sh                # alembic upgrade head + uvicorn :8001
│   ├── frontend/
│   │   └── src/
│   │       ├── App.tsx             # rotas: login, dashboard, detections, users
│   │       ├── contexts/           # AuthContext (JWT + Conecta), NotificationContext (SSE)
│   │       ├── services/           # api.ts (Axios + interceptors JWT), detectionService,
│   │       │                       #   dashboardService, notificationService
│   │       └── pages/              # Login, Dashboard, Detections, UsersPage
│   ├── yolo-worker-vm/
│   │   └── src/worker/
│   │       ├── main.py             # loop scan UPLOAD_DIR → detecção → DB → Redis
│   │       ├── detector_yolo.py    # inferência real (2 modelos YOLO)
│   │       ├── detector_mock.py    # mock para testes sem pesos
│   │       └── db.py               # Postgres sync + Redis pub
│   └── nginx/gateway.conf          # reverse proxy /api e /health → backend:8001
├── esp32-server/
│   └── server.py                   # Flask: /upload, /status, OTA (/ota/*), config remota
└── firmware/
    └── espcam-saira/
        └── src/
            ├── main.cpp            # ESP32-CAM: upload periódico + OTA
            └── ipcam_relay.cpp     # relay snapshot câmera IP → /upload
```

## Padrões e Convenções

- **Migrations:** sempre via Alembic (`alembic revision --autogenerate` → `alembic upgrade head`)
- **Auth:** todos os endpoints protegidos com `get_current_user` (dep FastAPI)
- **Roles:** `admin` e `operator` (gerenciado via JWT claims)
- **Testes backend:** `pytest` na pasta `services/backend/tests/`
- **CI/CD:** `.github/workflows/deploy.yml` — deploy SSH automatizado para teste e produção
- **Line endings:** usar LF (Unix) — histórico de `\r` em `start.sh` causou falhas

## Módulos Existentes

- `auth` — login local (Argon2 + JWT) + OIDC Conecta Recife
- `cameras` — CRUD de câmeras com geometrias PostGIS
- `detections` — CRUD, filtros, transições de status (análise → resolvido)
- `dashboard` — KPIs e agregações
- `notifications` — listagem REST + stream SSE + marcação de leitura
- `offenders` — perfis de infratores + vínculos por detecção + dashboards
- `yolo-worker` — pipeline automático ESP32 → imagem → YOLO → banco → notificação

## Variáveis de Ambiente Relevantes (backend)

```
DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/saira
REDIS_URL=redis://redis:6379
JWT_SECRET_KEY=...
JWT_ALGORITHM=HS256
CONECTA_CLIENT_ID=...
CONECTA_CLIENT_SECRET=...
WAHA_URL=http://waha:3000
```

## Dependências Críticas a Considerar

- PostGIS obrigatório no Postgres — usar imagem `postgis/postgis`
- Worker YOLO conecta ao banco via hostname `db` (mesmo compose network)
- Não quebrar endpoints `/api/v1/*` — frontend e ESP32 dependem deles
- Migrations devem ser reversíveis (Alembic downgrade suportado)
- Logs de produção: usar `logging` Python (nunca `print` em produção)
- `start.sh` deve ter LF (evitar `\r` que quebra execução no container)
