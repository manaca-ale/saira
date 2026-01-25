# Especificação Técnica - Backend API SAIRA

## 1. Visão Geral

Este documento consolida a especificação técnica para implementação do backend da plataforma SAIRA (Sistema de Monitoramento de Descarte Irregular), baseado em FastAPI + PostgreSQL + PostGIS, containerizado com Docker.

### Objetivo
Implementar uma API REST robusta e escalável para gerenciar:
- **Detecções de descarte irregular** capturadas por câmeras IP
- **Usuários e fiscais** do sistema
- **Câmeras** distribuídas pela cidade
- **Dados geoespaciais** com PostGIS para análises geográficas

---

## 2. Análise do Frontend - Entidades Identificadas

### 2.1 Usuários (Users)
Campos identificados em `UsersPage.tsx` e `UserModal.tsx`:
- `id` (int, PK)
- `name` (string) - Nome completo
- `email` (string, unique)
- `phone` (string) - Formato: (XX) 9 XXXX-XXXX
- `secretaria` (string) - Ex: EMLURB
- `cargo` (string) - Ex: Fiscal Ambiental, Analista de Fiscalização Urbana
- `rpa` (string) - RPA 1 a 6
- `password_hash` (string) - Senha hasheada (Argon2)
- `is_active` (boolean) - Usuário ativo/inativo
- `created_at` (timestamp)
- `updated_at` (timestamp)

### 2.2 Detecções/Ocorrências (Detections)
Campos identificados em `Detections.tsx` e `OccurrenceModal.tsx`:
- `id` (uuid, PK)
- `camera_id` (int, FK) - Câmera que capturou
- `timestamp` (timestamp) - Data e hora da detecção
- `logradouro` (string) - Rua/Avenida
- `bairro` (string) - Bairro
- `rpa` (string) - RPA 1 a 6
- `latitude` (decimal)
- `longitude` (decimal)
- `geom` (geometry, POINT) - PostGIS para consultas espaciais
- `waste_type` (string) - Tipo de resíduo (Entulho, Lixo domiciliar, Resíduos de poda)
- `material_type` (string) - Tipo de material (Plástico, Papel, Vidro, etc.)
- `volume_m3` (decimal) - Volumetria aproximada em m³
- `offenders` (string) - Infratores identificados (Pessoa, Veículo, Não Identificado)
- `status` (enum) - Pendente, Em análise, Resolvido
- `image_url` (string) - URL da imagem de evidência no S3
- `confidence_score` (decimal) - Score de confiança da IA (0-1)
- `created_at` (timestamp)
- `updated_at` (timestamp)

### 2.3 Câmeras (Cameras)
Campos inferidos da arquitetura:
- `id` (int, PK)
- `name` (string) - Nome/identificador da câmera
- `logradouro` (string)
- `bairro` (string)
- `rpa` (string)
- `latitude` (decimal)
- `longitude` (decimal)
- `geom` (geometry, POINT)
- `rtsp_url` (string) - URL RTSP para captura
- `capture_interval_seconds` (int) - Intervalo de captura (default: 30s)
- `is_active` (boolean)
- `last_capture_at` (timestamp)
- `created_at` (timestamp)
- `updated_at` (timestamp)

### 2.4 Dashboards - Métricas Calculadas
Dados do `Dashboard.tsx`:
- Total de ocorrências (agregação)
- Volume diário de resíduos em m³ (SUM por dia)
- Ocorrências por mês (GROUP BY month)
- Locais reincidentes (GROUP BY location + COUNT)
- Média diária de volumetria por RPA (AVG por RPA)

---

## 3. Stack Tecnológico

### 3.1 Backend
- **Python**: 3.11+
- **Framework**: FastAPI 0.109+
- **ORM**: SQLAlchemy 2.0+ (modo async)
- **Validação**: Pydantic 2.0+
- **Migrações**: Alembic
- **Autenticação**: python-jose (JWT), pwdlib (Argon2)
- **Async Driver**: asyncpg (PostgreSQL)
- **Geospatial**: GeoAlchemy2

### 3.2 Banco de Dados
- **PostgreSQL**: 15+
- **Extensões**:
  - PostGIS 3.4+ (geoespacial)
  - uuid-ossp (geração de UUIDs)

### 3.3 Infraestrutura
- **Containerização**: Docker + Docker Compose
- **Servidor HTTP**: Uvicorn (com workers)
- **Reverse Proxy**: Nginx (futuro, para HTTPS)

### 3.4 Testes
- **Framework**: pytest
- **Async**: pytest-asyncio
- **HTTP**: httpx

---

## 4. Estrutura de Diretórios do Backend

```
services/backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # Aplicação FastAPI principal
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # Configurações (pydantic-settings)
│   │   ├── security.py            # JWT, hash de senhas
│   │   └── database.py            # Conexão async com PostgreSQL
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py                # Modelo SQLAlchemy User
│   │   ├── detection.py           # Modelo Detection
│   │   └── camera.py              # Modelo Camera
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── user.py                # Pydantic schemas para User
│   │   ├── detection.py           # Schemas para Detection
│   │   ├── camera.py              # Schemas para Camera
│   │   └── auth.py                # Schemas de autenticação (Login, Token)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                # Dependências (get_db, get_current_user)
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py          # Router principal v1
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── auth.py        # /auth/login, /auth/register
│   │           ├── users.py       # CRUD de usuários
│   │           ├── detections.py  # CRUD de detecções
│   │           ├── cameras.py     # CRUD de câmeras
│   │           └── dashboard.py   # Endpoints de métricas
│   ├── services/
│   │   ├── __init__.py
│   │   ├── user_service.py        # Lógica de negócio para usuários
│   │   ├── detection_service.py   # Lógica de detecções
│   │   └── geospatial_service.py  # Queries espaciais com PostGIS
│   └── utils/
│       ├── __init__.py
│       └── logger.py              # Configuração de logs
├── alembic/
│   ├── versions/                  # Migrações do banco
│   ├── env.py
│   └── alembic.ini
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Fixtures do pytest
│   ├── test_auth.py
│   ├── test_users.py
│   └── test_detections.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env
└── .env.example
```

---

## 5. Schema do Banco de Dados (PostgreSQL + PostGIS)

### 5.1 Tabela: `users`
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20),
    secretaria VARCHAR(100),
    cargo VARCHAR(100),
    rpa VARCHAR(10),
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_rpa ON users(rpa);
```

### 5.2 Tabela: `cameras`
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE cameras (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    logradouro VARCHAR(255),
    bairro VARCHAR(100),
    rpa VARCHAR(10),
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    geom GEOMETRY(Point, 4326),  -- PostGIS Point com SRID 4326 (WGS84)
    rtsp_url VARCHAR(512),
    capture_interval_seconds INTEGER DEFAULT 30,
    is_active BOOLEAN DEFAULT TRUE,
    last_capture_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_cameras_geom ON cameras USING GIST(geom);
CREATE INDEX idx_cameras_rpa ON cameras(rpa);
CREATE INDEX idx_cameras_is_active ON cameras(is_active);

-- Trigger para auto-popular campo geom
CREATE OR REPLACE FUNCTION update_camera_geom()
RETURNS TRIGGER AS $$
BEGIN
    NEW.geom = ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER camera_geom_trigger
BEFORE INSERT OR UPDATE ON cameras
FOR EACH ROW
EXECUTE FUNCTION update_camera_geom();
```

### 5.3 Tabela: `detections`
```sql
CREATE TYPE detection_status AS ENUM ('Pendente', 'Em análise', 'Resolvido');

CREATE TABLE detections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    camera_id INTEGER REFERENCES cameras(id) ON DELETE SET NULL,
    timestamp TIMESTAMP NOT NULL,
    logradouro VARCHAR(255),
    bairro VARCHAR(100),
    rpa VARCHAR(10),
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    geom GEOMETRY(Point, 4326),
    waste_type VARCHAR(100),
    material_type VARCHAR(100),
    volume_m3 DECIMAL(10, 2),
    offenders VARCHAR(255),
    status detection_status DEFAULT 'Pendente',
    image_url VARCHAR(512),
    confidence_score DECIMAL(3, 2),  -- 0.00 a 1.00
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_detections_timestamp ON detections(timestamp DESC);
CREATE INDEX idx_detections_status ON detections(status);
CREATE INDEX idx_detections_rpa ON detections(rpa);
CREATE INDEX idx_detections_camera_id ON detections(camera_id);
CREATE INDEX idx_detections_geom ON detections USING GIST(geom);

-- Trigger para auto-popular campo geom
CREATE OR REPLACE FUNCTION update_detection_geom()
RETURNS TRIGGER AS $$
BEGIN
    NEW.geom = ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER detection_geom_trigger
BEFORE INSERT OR UPDATE ON detections
FOR EACH ROW
EXECUTE FUNCTION update_detection_geom();
```

---

## 6. Arquitetura da API (FastAPI)

### 6.1 Configuração Base (`app/core/config.py`)
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # S3/Storage
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    S3_BUCKET_NAME: str
    S3_REGION: str = "us-east-1"

    # Application
    PROJECT_NAME: str = "SAIRA API"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"

    class Config:
        env_file = ".env"
```

### 6.2 Conexão com Banco de Dados (`app/core/database.py`)
```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# Async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=True if settings.ENVIRONMENT == "development" else False,
    future=True
)

# Async session
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

### 6.3 Autenticação JWT (`app/core/security.py`)
```python
from datetime import datetime, timedelta
from jose import JWTError, jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

password_hash = PasswordHash((Argon2Hasher(),))

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return password_hash.hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt
```

### 6.4 Modelos SQLAlchemy com PostGIS (`app/models/detection.py`)
```python
from sqlalchemy import Column, Integer, String, DateTime, Numeric, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry
import uuid
import enum

class DetectionStatus(str, enum.Enum):
    PENDENTE = "Pendente"
    EM_ANALISE = "Em análise"
    RESOLVIDO = "Resolvido"

class Detection(Base):
    __tablename__ = "detections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"))
    timestamp = Column(DateTime, nullable=False)
    logradouro = Column(String(255))
    bairro = Column(String(100))
    rpa = Column(String(10))
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    geom = Column(Geometry("POINT", srid=4326))  # PostGIS
    waste_type = Column(String(100))
    material_type = Column(String(100))
    volume_m3 = Column(Numeric(10, 2))
    offenders = Column(String(255))
    status = Column(Enum(DetectionStatus), default=DetectionStatus.PENDENTE)
    image_url = Column(String(512))
    confidence_score = Column(Numeric(3, 2))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 6.5 Schemas Pydantic (`app/schemas/detection.py`)
```python
from pydantic import BaseModel, UUID4, Field
from datetime import datetime
from typing import Optional
from enum import Enum

class DetectionStatus(str, Enum):
    PENDENTE = "Pendente"
    EM_ANALISE = "Em análise"
    RESOLVIDO = "Resolvido"

class DetectionBase(BaseModel):
    camera_id: Optional[int] = None
    timestamp: datetime
    logradouro: Optional[str] = None
    bairro: Optional[str] = None
    rpa: Optional[str] = None
    latitude: float
    longitude: float
    waste_type: Optional[str] = None
    material_type: Optional[str] = None
    volume_m3: Optional[float] = None
    offenders: Optional[str] = None
    status: DetectionStatus = DetectionStatus.PENDENTE
    image_url: Optional[str] = None
    confidence_score: Optional[float] = Field(None, ge=0, le=1)

class DetectionCreate(DetectionBase):
    pass

class DetectionUpdate(BaseModel):
    status: Optional[DetectionStatus] = None
    offenders: Optional[str] = None

class DetectionResponse(DetectionBase):
    id: UUID4
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

### 6.6 Endpoints RESTful (`app/api/v1/endpoints/detections.py`)
```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import List, Optional
from datetime import datetime

router = APIRouter()

@router.get("/", response_model=List[DetectionResponse])
async def get_detections(
    skip: int = 0,
    limit: int = 10,
    rpa: Optional[str] = None,
    status: Optional[DetectionStatus] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    """Lista detecções com filtros"""
    query = select(Detection)

    filters = []
    if rpa:
        filters.append(Detection.rpa == rpa)
    if status:
        filters.append(Detection.status == status)
    if start_date:
        filters.append(Detection.timestamp >= start_date)
    if end_date:
        filters.append(Detection.timestamp <= end_date)

    if filters:
        query = query.where(and_(*filters))

    query = query.offset(skip).limit(limit).order_by(Detection.timestamp.desc())
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/{detection_id}", response_model=DetectionResponse)
async def get_detection(
    detection_id: UUID4,
    db: AsyncSession = Depends(get_db)
):
    """Busca uma detecção por ID"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")
    return detection

@router.post("/", response_model=DetectionResponse, status_code=201)
async def create_detection(
    detection: DetectionCreate,
    db: AsyncSession = Depends(get_db)
):
    """Cria uma nova detecção"""
    db_detection = Detection(**detection.dict())
    db.add(db_detection)
    await db.commit()
    await db.refresh(db_detection)
    return db_detection

@router.patch("/{detection_id}", response_model=DetectionResponse)
async def update_detection(
    detection_id: UUID4,
    detection_update: DetectionUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Atualiza uma detecção (status, infratores)"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")

    for key, value in detection_update.dict(exclude_unset=True).items():
        setattr(detection, key, value)

    await db.commit()
    await db.refresh(detection)
    return detection
```

### 6.7 Queries Geoespaciais com PostGIS (`app/services/geospatial_service.py`)
```python
from sqlalchemy import select, func
from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID

async def get_detections_near_point(
    db: AsyncSession,
    latitude: float,
    longitude: float,
    radius_meters: float = 1000
) -> List[Detection]:
    """Busca detecções dentro de um raio em metros"""
    point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)

    query = select(Detection).where(
        ST_DWithin(
            Detection.geom,
            point,
            radius_meters / 111000  # Conversão aproximada para graus
        )
    )

    result = await db.execute(query)
    return result.scalars().all()

async def get_cameras_near_detection(
    db: AsyncSession,
    detection_id: UUID4,
    radius_meters: float = 500
) -> List[Camera]:
    """Busca câmeras próximas a uma detecção"""
    detection_result = await db.execute(
        select(Detection).where(Detection.id == detection_id)
    )
    detection = detection_result.scalar_one()

    query = select(Camera).where(
        ST_DWithin(
            Camera.geom,
            detection.geom,
            radius_meters / 111000
        )
    )

    result = await db.execute(query)
    return result.scalars().all()
```

---

## 7. Docker Compose Setup

### 7.1 Estrutura
```yaml
version: "3.8"

services:
  # Frontend (já existente)
  web:
    build: ./frontend
    ports:
      - "3000:80"
    container_name: vite-react-ts-app
    restart: always
    depends_on:
      - backend

  # Backend API (FastAPI)
  backend:
    build: ./backend
    container_name: saira-backend-api
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/saira_db
      - SECRET_KEY=${SECRET_KEY}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - S3_BUCKET_NAME=${S3_BUCKET_NAME}
      - ENVIRONMENT=production
    depends_on:
      db:
        condition: service_healthy
    restart: always
    volumes:
      - ./backend:/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

  # PostgreSQL + PostGIS
  db:
    image: postgis/postgis:15-3.4
    container_name: saira-postgres-db
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=saira_db
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always

  # pgAdmin (opcional, para desenvolvimento)
  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: saira-pgadmin
    environment:
      - PGADMIN_DEFAULT_EMAIL=admin@saira.com
      - PGADMIN_DEFAULT_PASSWORD=admin
    ports:
      - "5050:80"
    depends_on:
      - db
    restart: always

volumes:
  postgres_data:
```

### 7.2 Dockerfile do Backend
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema para PostGIS
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Expor porta
EXPOSE 8000

# Comando padrão
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 7.3 requirements.txt
```
fastapi==0.109.0
uvicorn[standard]==0.27.0
sqlalchemy==2.0.25
alembic==1.13.1
asyncpg==0.29.0
pydantic==2.5.3
pydantic-settings==2.1.0
python-jose[cryptography]==3.3.0
pwdlib[argon2]==0.2.0
python-multipart==0.0.6
geoalchemy2==0.14.3
shapely==2.0.2
boto3==1.34.34
httpx==0.26.0
pytest==7.4.4
pytest-asyncio==0.23.3
```

---

## 8. Endpoints da API

### 8.1 Autenticação
- `POST /api/v1/auth/login` - Login e geração de JWT
- `POST /api/v1/auth/register` - Cadastro de novo usuário (admin only)
- `GET /api/v1/auth/me` - Dados do usuário logado

### 8.2 Usuários
- `GET /api/v1/users` - Listar usuários (paginado, filtros: rpa, cargo)
- `GET /api/v1/users/{id}` - Buscar usuário por ID
- `POST /api/v1/users` - Criar usuário
- `PATCH /api/v1/users/{id}` - Atualizar usuário
- `DELETE /api/v1/users/{id}` - Deletar usuário

### 8.3 Detecções
- `GET /api/v1/detections` - Listar detecções (filtros: rpa, status, período, bairro)
- `GET /api/v1/detections/{id}` - Buscar detecção por ID
- `POST /api/v1/detections` - Criar detecção (IA Worker)
- `PATCH /api/v1/detections/{id}` - Atualizar status/infratores
- `GET /api/v1/detections/nearby` - Detecções próximas a um ponto (PostGIS)

### 8.4 Câmeras
- `GET /api/v1/cameras` - Listar câmeras (filtros: rpa, is_active)
- `GET /api/v1/cameras/{id}` - Buscar câmera por ID
- `POST /api/v1/cameras` - Criar câmera
- `PATCH /api/v1/cameras/{id}` - Atualizar câmera
- `DELETE /api/v1/cameras/{id}` - Deletar câmera

### 8.5 Dashboard (Métricas)
- `GET /api/v1/dashboard/stats` - Métricas gerais (total ocorrências, volume diário)
- `GET /api/v1/dashboard/occurrences-by-month` - Ocorrências por mês
- `GET /api/v1/dashboard/recurrent-locations` - Locais reincidentes
- `GET /api/v1/dashboard/volume-by-rpa` - Volumetria por RPA

---

## 9. Padrões de Implementação Externos

### 9.1 Autenticação JWT (Baseado em FastAPI Docs)
**Fonte**: [FastAPI OAuth2 JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)

**Implementação**:
- Usar `OAuth2PasswordBearer` para extração do token
- Validar token com `python-jose`
- Hash de senhas com `pwdlib` (Argon2)
- Tokens com expiração de 30 minutos
- Refresh tokens (futuro)

### 9.2 Estrutura de Projeto FastAPI
**Fonte**: [FastAPI Best Practices](https://github.com/zhanymkanov/fastapi-best-practices)

**Padrões adotados**:
- Separação clara entre `models` (DB), `schemas` (API) e `services` (lógica)
- Dependências injetadas via `Depends()`
- Configuração centralizada com `pydantic-settings`
- Versionamento de API (`/api/v1/`)

### 9.3 FastAPI + PostGIS
**Fonte**: [fastapi-postgis](https://github.com/grillazz/fastapi-postgis)

**Implementação**:
- GeoAlchemy2 para tipos geométricos
- SRID 4326 (WGS84) para coordenadas lat/lon
- Funções PostGIS: `ST_Distance`, `ST_DWithin`, `ST_MakePoint`
- Índices GIST para performance em queries espaciais

### 9.4 Docker Compose para Produção
**Fonte**: [Production FastAPI Docker](https://blog.greeden.me/en/2026/01/20/complete-guide-to-deploying-fastapi-in-production-reliable-operations-with-uvicorn-multi-workers-docker-and-a-reverse-proxy/)

**Configuração**:
- Uvicorn com múltiplos workers (4 workers para 4 vCPUs)
- PostgreSQL com healthcheck
- Separação de redes Docker
- Volumes nomeados para persistência

---

## 10. Arquivos Afetados/Criados

### 10.1 Arquivos Existentes (Sem Alteração)
- `services/frontend/**` - Frontend React (sem mudanças)
- `services/docker-compose.yml` - Será ATUALIZADO

### 10.2 Novos Diretórios/Arquivos
```
services/backend/               # NOVO
services/backend/app/           # NOVO
services/backend/tests/         # NOVO
services/backend/alembic/       # NOVO
services/backend/Dockerfile     # NOVO
services/backend/requirements.txt  # NOVO
services/backend/.env           # NOVO
services/backend/.env.example   # NOVO
```

### 10.3 Migrações Alembic
```bash
# Inicializar Alembic
alembic init alembic

# Criar primeira migração
alembic revision --autogenerate -m "Initial schema"

# Aplicar migrações
alembic upgrade head
```

---

## 11. Próximos Passos de Implementação

### Fase 1: Setup Inicial
1. Criar estrutura de diretórios do backend
2. Configurar Docker Compose com PostgreSQL + PostGIS
3. Implementar modelos SQLAlchemy (User, Camera, Detection)
4. Criar schemas Pydantic
5. Configurar Alembic e executar primeira migração

### Fase 2: API Core
6. Implementar autenticação JWT
7. Criar endpoints de usuários (CRUD)
8. Criar endpoints de câmeras (CRUD)
9. Criar endpoints de detecções (CRUD)

### Fase 3: Features Avançadas
10. Implementar queries geoespaciais com PostGIS
11. Criar endpoints de dashboard (métricas)
12. Adicionar paginação e filtros avançados
13. Implementar testes unitários e de integração

### Fase 4: Integração
14. Conectar frontend ao backend (alterar URLs de mock para API real)
15. Testar autenticação end-to-end
16. Validar fluxo completo: Login → Dashboard → Detecções → Usuários

### Fase 5: Produção
17. Configurar Nginx como reverse proxy
18. Adicionar HTTPS com Let's Encrypt
19. Configurar CI/CD (GitHub Actions)
20. Deploy em AWS EC2

---

## 12. Variáveis de Ambiente (.env.example)

```bash
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/saira_db

# Security
SECRET_KEY=your-secret-key-min-32-chars-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# AWS S3
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
S3_BUCKET_NAME=saira-evidence-prod
S3_REGION=us-east-1

# CORS
BACKEND_CORS_ORIGINS=["http://localhost:3000","http://localhost"]

# Application
PROJECT_NAME=SAIRA API
VERSION=1.0.0
ENVIRONMENT=development
LOG_LEVEL=INFO
```

---

## 13. Referências Técnicas

### Documentação Oficial
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [PostGIS Documentation](https://postgis.net/documentation/)
- [Pydantic V2 Documentation](https://docs.pydantic.dev/latest/)

### Tutoriais e Guias
- [FastAPI Best Practices](https://github.com/zhanymkanov/fastapi-best-practices)
- [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template)
- [FastAPI + PostGIS Integration](https://github.com/grillazz/fastapi-postgis)
- [Securing FastAPI with JWT](https://testdriven.io/blog/fastapi-jwt-auth/)
- [Production FastAPI Docker Guide](https://blog.greeden.me/en/2026/01/20/complete-guide-to-deploying-fastapi-in-production-reliable-operations-with-uvicorn-multi-workers-docker-and-a-reverse-proxy/)

### Artigos Técnicos
- [Working with Spatial Data using FastAPI and GeoAlchemy](https://medium.com/@notarious2/working-with-spatial-data-using-fastapi-and-geoalchemy-797d414d2fe7)
- [Dockerizing FastAPI with PostgreSQL](https://medium.com/@kevinkoech265/dockerizing-fastapi-and-postgresql-effortless-containerization-a-step-by-step-guide-68b962c3e7eb)
- [Authentication and Authorization with FastAPI](https://betterstack.com/community/guides/scaling-python/authentication-fastapi/)

---

## 14. Considerações de Segurança

### 14.1 Autenticação e Autorização
- ✅ JWT com expiração de 30 minutos
- ✅ Senhas hasheadas com Argon2 (resistente a ataques GPU)
- ✅ HTTPS obrigatório em produção (via Nginx)
- ✅ CORS configurado para domínios específicos
- ⚠️ Implementar rate limiting (SlowAPI)
- ⚠️ Adicionar refresh tokens

### 14.2 Banco de Dados
- ✅ SQLAlchemy ORM (proteção contra SQL injection)
- ✅ Pydantic para validação de entrada
- ✅ Conexões com pool de conexões
- ⚠️ Backup automático do PostgreSQL

### 14.3 Infraestrutura
- ✅ Secrets em variáveis de ambiente (não no código)
- ✅ PostgreSQL sem IP público (apenas rede interna Docker)
- ✅ IAM Roles para acesso ao S3 (sem credenciais no código)
- ⚠️ Implementar AWS Secrets Manager

---

## Resumo Executivo

Esta especificação define a implementação completa do backend SAIRA com:

- **Stack**: FastAPI + PostgreSQL 15 + PostGIS + Docker
- **Entidades**: Users, Cameras, Detections
- **APIs**: 20+ endpoints RESTful com autenticação JWT
- **Geoespacial**: Queries avançadas com PostGIS (raio, proximidade)
- **Segurança**: Argon2, JWT, CORS, validação Pydantic
- **Deploy**: Docker Compose com 3 serviços (frontend, backend, db)

A estrutura segue padrões modernos de FastAPI (2026), com código assíncrono, type hints completos e separação clara de responsabilidades (models, schemas, services, endpoints).
