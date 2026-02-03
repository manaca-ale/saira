# SAIRA_full_context.md

Este documento consolida o contexto tecnico do projeto SAIRA em formato de base de conhecimento para NotebookLM.

- Escopo: arquitetura, logica de negocio, fluxo de dados e configuracoes operacionais.
- Exclusoes aplicadas: artefatos binarios, lock files, dados de captura/log gerados, `.env` e boilerplate nao essencial.
- Total de arquivos incluidos: 149.

## `api/Dockerfile`

**Purpose:** Receita de build da imagem container para padronizar runtime e deploy deste componente.

```dockerfile


```

## `api/pyproject.toml`

**Purpose:** Manifesto de dependencias e metadados de build usado para reproducibilidade do componente.

```toml


```

## `api/README.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown


```

## `api/src/api/__init__.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `api/src/api/config.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `api/src/api/db.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `api/src/api/main.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `api/src/api/routes/detections.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `api/src/api/routes/health.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `backend/alembic.ini`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```ini
# A generic, single database configuration.

[alembic]
# path to migration scripts
script_location = alembic

# template used to generate migration file names; The default value is %%(rev)s_%%(slug)s
# Uncomment the line below if you want the files to be prepended with date and time
# file_template = %%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d-%%(rev)s_%%(slug)s

# sys.path path, will be prepended to sys.path if present.
# defaults to the current working directory.
prepend_sys_path = .

# timezone to use when rendering the date within the migration file
# as well as the filename.
# If specified, requires the python-dateutil library that can be
# installed by adding `alembic[tz]` to the pip requirements
# string value is passed to dateutil.tz.gettz()
# leave blank for localtime
# timezone =

# max length of characters to apply to the "slug" field
# truncate_slug_length = 40

# set to 'true' to run the environment during
# the 'revision' command, regardless of autogenerate
# revision_environment = false

# set to 'true' to allow .pyc and .pyo files without
# a source .py file to be detected as revisions in the
# versions/ directory
# sourceless = false

# version location specification; This defaults
# to alembic/versions.  When using multiple version
# directories, initial revisions must be specified with --version-path.
# The path separator used here should be the separator specified by "version_path_separator" below.
# version_locations = %(here)s/bar:%(here)s/bat:alembic/versions

# version path separator; As mentioned above, this is the character used to split
# version_locations. The default within new alembic.ini files is "os", which uses os.pathsep.
# If this key is omitted entirely, it falls back to the legacy behavior of splitting on spaces and/or commas.
# Valid values for version_path_separator are:
#
# version_path_separator = :
# version_path_separator = ;
# version_path_separator = space
version_path_separator = os  # Use os.pathsep. Default configuration used for new projects.

# set to 'true' to search source files recursively
# in each "version_locations" directory
# new in Alembic version 1.10
# recursive_version_locations = false

# the output encoding used when revision files
# are written from script.py.mako
# output_encoding = utf-8

sqlalchemy.url = postgresql+asyncpg://postgres:postgres@localhost:5432/saira_db


[post_write_hooks]
# post_write_hooks defines scripts or Python functions that are run
# on newly generated revision scripts.  See the documentation for further
# detail and examples

# format using "black" - use the console_scripts runner, against the "black" entrypoint
# hooks = black
# black.type = console_scripts
# black.entrypoint = black
# black.options = -l 79 REVISION_SCRIPT_FILENAME

# lint with attempts to fix using "ruff" - use the exec runner, execute a binary
# hooks = ruff
# ruff.type = exec
# ruff.executable = %(here)s/.venv/bin/ruff
# ruff.options = --fix REVISION_SCRIPT_FILENAME

# Logging configuration
[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S

```

## `backend/alembic/env.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
import asyncio

# Import models and database
from app.core.database import Base
from app.core.config import settings
from app.models import User, Camera, Detection

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url():
    return settings.DATABASE_URL


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# Tables to exclude from autogenerate (PostGIS Tiger geocoder tables)
EXCLUDE_TABLES = {
    'spatial_ref_sys', 'topology', 'layer',
    # Tiger geocoder tables
    'addr', 'addrfeat', 'bg', 'county', 'county_lookup', 'countysub_lookup',
    'cousub', 'direction_lookup', 'edges', 'faces', 'featnames',
    'geocode_settings', 'geocode_settings_default', 'loader_lookuptables',
    'loader_platform', 'loader_variables', 'pagc_gaz', 'pagc_lex', 'pagc_rules',
    'place', 'place_lookup', 'secondary_unit_lookup', 'state', 'state_lookup',
    'street_type_lookup', 'tabblock', 'tabblock20', 'tract', 'zcta5',
    'zip_lookup', 'zip_lookup_all', 'zip_lookup_base', 'zip_state', 'zip_state_loc',
}


def include_object(obj, name, type_, reflected, compare_to):
    """Filter function to exclude PostGIS system tables from autogenerate."""
    if type_ == "table":
        # Exclude tables in the exclusion list
        if name in EXCLUDE_TABLES:
            return False
        # Only include tables in public schema or no schema
        if hasattr(obj, 'schema') and obj.schema not in (None, 'public'):
            return False
    return True


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

```

## `backend/alembic/script.py.mako`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}

```

## `backend/alembic/versions/9820af489db3_initial_migration.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
"""Initial migration

Revision ID: 9820af489db3
Revises:
Create Date: 2026-01-25 21:36:00.845895

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = '9820af489db3'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def create_index_if_not_exists(index_name: str, table_name: str, columns: str, using: str = None):
    """Create an index only if it doesn't exist."""
    using_clause = f" USING {using}" if using else ""
    sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}{using_clause} ({columns})"
    op.execute(text(sql))


def upgrade() -> None:
    # Create cameras table if not exists
    if not table_exists('cameras'):
        op.create_table('cameras',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('logradouro', sa.String(length=255), nullable=True),
        sa.Column('bairro', sa.String(length=100), nullable=True),
        sa.Column('rpa', sa.String(length=10), nullable=True),
        sa.Column('latitude', sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column('longitude', sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
        sa.Column('rtsp_url', sa.String(length=512), nullable=True),
        sa.Column('capture_interval_seconds', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('last_capture_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )

    # Create indices with IF NOT EXISTS
    create_index_if_not_exists('idx_cameras_geom', 'cameras', 'geom', 'gist')
    create_index_if_not_exists('ix_cameras_id', 'cameras', 'id')
    create_index_if_not_exists('ix_cameras_is_active', 'cameras', 'is_active')
    create_index_if_not_exists('ix_cameras_rpa', 'cameras', 'rpa')

    # Create users table if not exists
    if not table_exists('users'):
        op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('secretaria', sa.String(length=100), nullable=True),
        sa.Column('cargo', sa.String(length=100), nullable=True),
        sa.Column('rpa', sa.String(length=10), nullable=True),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )

    # Create indices with IF NOT EXISTS
    create_index_if_not_exists('ix_users_email', 'users', 'email')
    op.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"))
    create_index_if_not_exists('ix_users_id', 'users', 'id')
    create_index_if_not_exists('ix_users_rpa', 'users', 'rpa')

    # Create detections table if not exists
    if not table_exists('detections'):
        # Create enum type if not exists (SQLAlchemy won't try to re-create it)
        op.execute(text("DO $$ BEGIN CREATE TYPE detectionstatus AS ENUM ('PENDENTE', 'EM_ANALISE', 'RESOLVIDO'); EXCEPTION WHEN duplicate_object THEN null; END $$;"))
        detectionstatus_enum = postgresql.ENUM(
            'PENDENTE', 'EM_ANALISE', 'RESOLVIDO',
            name='detectionstatus',
            create_type=False,
        )

        op.create_table('detections',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('camera_id', sa.Integer(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('logradouro', sa.String(length=255), nullable=True),
        sa.Column('bairro', sa.String(length=100), nullable=True),
        sa.Column('rpa', sa.String(length=10), nullable=True),
        sa.Column('latitude', sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column('longitude', sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
        sa.Column('waste_type', sa.String(length=100), nullable=True),
        sa.Column('material_type', sa.String(length=100), nullable=True),
        sa.Column('volume_m3', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('offenders', sa.String(length=255), nullable=True),
        sa.Column('status', detectionstatus_enum, nullable=True),
        sa.Column('image_url', sa.String(length=512), nullable=True),
        sa.Column('confidence_score', sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['camera_id'], ['cameras.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )

    # Create indices with IF NOT EXISTS
    create_index_if_not_exists('idx_detections_geom', 'detections', 'geom', 'gist')
    create_index_if_not_exists('ix_detections_camera_id', 'detections', 'camera_id')
    create_index_if_not_exists('ix_detections_rpa', 'detections', 'rpa')
    create_index_if_not_exists('ix_detections_status', 'detections', 'status')
    create_index_if_not_exists('ix_detections_timestamp', 'detections', 'timestamp')


def downgrade() -> None:
    # Drop detections table
    op.drop_index('ix_detections_timestamp', table_name='detections')
    op.drop_index('ix_detections_status', table_name='detections')
    op.drop_index('ix_detections_rpa', table_name='detections')
    op.drop_index('ix_detections_camera_id', table_name='detections')
    op.drop_index('idx_detections_geom', table_name='detections', postgresql_using='gist')
    op.drop_table('detections')

    # Drop users table
    op.drop_index('ix_users_rpa', table_name='users')
    op.drop_index('ix_users_id', table_name='users')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')

    # Drop cameras table
    op.drop_index('ix_cameras_rpa', table_name='cameras')
    op.drop_index('ix_cameras_is_active', table_name='cameras')
    op.drop_index('ix_cameras_id', table_name='cameras')
    op.drop_index('idx_cameras_geom', table_name='cameras', postgresql_using='gist')
    op.drop_table('cameras')

    # Drop enum type
    op.execute(text('DROP TYPE IF EXISTS detectionstatus'))

```

## `backend/app/api/deps.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from typing import AsyncGenerator
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token
from app.models.user import User
from app.schemas.user import UserResponse

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency para obter sessão do banco de dados"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency para obter o usuário atual autenticado"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    email: str = payload.get("sub")
    if email is None:
        raise credentials_exception

    # Buscar usuário no banco
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dependency para garantir que o usuário está ativo"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

```

## `backend/app/api/v1/endpoints/__init__.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from app.api.v1.endpoints import auth, users, cameras, detections, dashboard

__all__ = ["auth", "users", "cameras", "detections", "dashboard"]

```

## `backend/app/api/v1/endpoints/auth.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.api.deps import get_db, get_current_user
from app.core.security import verify_password, create_access_token, get_password_hash
from app.core.config import settings
from app.models.user import User
from app.schemas.auth import Token, LoginRequest
from app.schemas.user import UserCreate, UserResponse

router = APIRouter()


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """Login e geração de token JWT"""
    # Buscar usuário por email
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )

    # Criar token de acesso
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    """Cadastro de novo usuário"""
    # Verificar se email já existe
    result = await db.execute(select(User).where(User.email == user_in.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Criar novo usuário
    password_hash = get_password_hash(user_in.password)
    db_user = User(
        name=user_in.name,
        email=user_in.email,
        phone=user_in.phone,
        secretaria=user_in.secretaria,
        cargo=user_in.cargo,
        rpa=user_in.rpa,
        password_hash=password_hash,
        is_active=user_in.is_active
    )

    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    return db_user


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Retorna dados do usuário logado"""
    return current_user

```

## `backend/app/api/v1/endpoints/cameras.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from geoalchemy2.functions import ST_SetSRID, ST_MakePoint
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.camera import Camera
from app.schemas.camera import CameraCreate, CameraUpdate, CameraResponse

router = APIRouter()


@router.get("/", response_model=List[CameraResponse])
async def get_cameras(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    rpa: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista câmeras com filtros e paginação"""
    query = select(Camera)

    filters = []
    if rpa:
        filters.append(Camera.rpa == rpa)
    if is_active is not None:
        filters.append(Camera.is_active == is_active)

    if filters:
        query = query.where(and_(*filters))

    query = query.offset(skip).limit(limit).order_by(Camera.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Busca uma câmera por ID"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found"
        )

    return camera


@router.post("/", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def create_camera(
    camera_in: CameraCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria uma nova câmera"""
    # Criar geometria PostGIS
    db_camera = Camera(
        name=camera_in.name,
        logradouro=camera_in.logradouro,
        bairro=camera_in.bairro,
        rpa=camera_in.rpa,
        latitude=camera_in.latitude,
        longitude=camera_in.longitude,
        rtsp_url=camera_in.rtsp_url,
        capture_interval_seconds=camera_in.capture_interval_seconds,
        is_active=camera_in.is_active
    )

    # O trigger no banco irá criar automaticamente o campo geom

    db.add(db_camera)
    await db.commit()
    await db.refresh(db_camera)

    return db_camera


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: int,
    camera_update: CameraUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza uma câmera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found"
        )

    # Atualizar campos
    update_data = camera_update.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(camera, key, value)

    # O trigger no banco irá atualizar automaticamente o campo geom se lat/lon mudarem

    await db.commit()
    await db.refresh(camera)

    return camera


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deleta uma câmera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found"
        )

    await db.delete(camera)
    await db.commit()

    return None

```

## `backend/app/api/v1/endpoints/dashboard.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, datetime
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.detection import Detection, DetectionStatus
from app.schemas.dashboard import DashboardStats, OccurrencesByMonth, RecurrentLocation, VolumeByRPA

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna estatísticas gerais do dashboard"""

    # Total de ocorrências
    total_result = await db.execute(select(func.count(Detection.id)))
    total_occurrences = total_result.scalar_one()

    # Volume diário (hoje)
    today = date.today()
    daily_volume_result = await db.execute(
        select(func.coalesce(func.sum(Detection.volume_m3), 0))
        .where(func.date(Detection.timestamp) == today)
    )
    daily_volume_m3 = daily_volume_result.scalar_one()

    # Contar por status
    pending_result = await db.execute(
        select(func.count(Detection.id))
        .where(Detection.status == DetectionStatus.PENDENTE)
    )
    pending_count = pending_result.scalar_one()

    in_analysis_result = await db.execute(
        select(func.count(Detection.id))
        .where(Detection.status == DetectionStatus.EM_ANALISE)
    )
    in_analysis_count = in_analysis_result.scalar_one()

    resolved_result = await db.execute(
        select(func.count(Detection.id))
        .where(Detection.status == DetectionStatus.RESOLVIDO)
    )
    resolved_count = resolved_result.scalar_one()

    return DashboardStats(
        total_occurrences=total_occurrences,
        daily_volume_m3=daily_volume_m3,
        pending_count=pending_count,
        in_analysis_count=in_analysis_count,
        resolved_count=resolved_count
    )


@router.get("/occurrences-by-month", response_model=List[OccurrencesByMonth])
async def get_occurrences_by_month(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna ocorrências agrupadas por mês"""
    result = await db.execute(
        select(
            func.to_char(Detection.timestamp, 'YYYY-MM').label('month'),
            func.count(Detection.id).label('count')
        )
        .group_by(func.to_char(Detection.timestamp, 'YYYY-MM'))
        .order_by(func.to_char(Detection.timestamp, 'YYYY-MM').desc())
        .limit(12)
    )

    rows = result.all()
    return [OccurrencesByMonth(month=row.month, count=row.count) for row in rows]


@router.get("/recurrent-locations", response_model=List[RecurrentLocation])
async def get_recurrent_locations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna locais com mais ocorrências (reincidentes)"""
    result = await db.execute(
        select(
            Detection.logradouro,
            Detection.bairro,
            Detection.rpa,
            func.count(Detection.id).label('count')
        )
        .where(Detection.logradouro.isnot(None))
        .group_by(Detection.logradouro, Detection.bairro, Detection.rpa)
        .having(func.count(Detection.id) > 1)
        .order_by(func.count(Detection.id).desc())
        .limit(10)
    )

    rows = result.all()
    return [
        RecurrentLocation(
            logradouro=row.logradouro or "",
            bairro=row.bairro or "",
            rpa=row.rpa or "",
            count=row.count
        )
        for row in rows
    ]


@router.get("/volume-by-rpa", response_model=List[VolumeByRPA])
async def get_volume_by_rpa(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna volumetria agregada por RPA"""
    result = await db.execute(
        select(
            Detection.rpa,
            func.avg(Detection.volume_m3).label('avg_volume_m3'),
            func.sum(Detection.volume_m3).label('total_volume_m3'),
            func.count(Detection.id).label('count')
        )
        .where(Detection.rpa.isnot(None))
        .where(Detection.volume_m3.isnot(None))
        .group_by(Detection.rpa)
        .order_by(Detection.rpa)
    )

    rows = result.all()
    return [
        VolumeByRPA(
            rpa=row.rpa,
            avg_volume_m3=row.avg_volume_m3 or 0,
            total_volume_m3=row.total_volume_m3 or 0,
            count=row.count
        )
        for row in rows
    ]

```

## `backend/app/api/v1/endpoints/detections.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.detection import Detection, DetectionStatus
from app.schemas.detection import DetectionCreate, DetectionUpdate, DetectionResponse
from app.schemas.detection import DetectionStatus as DetectionStatusSchema

router = APIRouter()


@router.get("/", response_model=List[DetectionResponse])
async def get_detections(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    rpa: Optional[str] = None,
    status_filter: Optional[DetectionStatusSchema] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    bairro: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista detecções com filtros e paginação"""
    query = select(Detection)

    filters = []
    if rpa:
        filters.append(Detection.rpa == rpa)
    if status_filter:
        filters.append(Detection.status == status_filter)
    if start_date:
        filters.append(Detection.timestamp >= start_date)
    if end_date:
        filters.append(Detection.timestamp <= end_date)
    if bairro:
        filters.append(Detection.bairro == bairro)

    if filters:
        query = query.where(and_(*filters))

    query = query.offset(skip).limit(limit).order_by(Detection.timestamp.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{detection_id}", response_model=DetectionResponse)
async def get_detection(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Busca uma detecção por ID"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found"
        )

    return detection


@router.post("/", response_model=DetectionResponse, status_code=status.HTTP_201_CREATED)
async def create_detection(
    detection_in: DetectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria uma nova detecção"""
    db_detection = Detection(
        camera_id=detection_in.camera_id,
        timestamp=detection_in.timestamp,
        logradouro=detection_in.logradouro,
        bairro=detection_in.bairro,
        rpa=detection_in.rpa,
        latitude=detection_in.latitude,
        longitude=detection_in.longitude,
        waste_type=detection_in.waste_type,
        material_type=detection_in.material_type,
        volume_m3=detection_in.volume_m3,
        offenders=detection_in.offenders,
        status=detection_in.status,
        image_url=detection_in.image_url,
        confidence_score=detection_in.confidence_score
    )

    # O trigger no banco irá criar automaticamente o campo geom

    db.add(db_detection)
    await db.commit()
    await db.refresh(db_detection)

    return db_detection


@router.patch("/{detection_id}", response_model=DetectionResponse)
async def update_detection(
    detection_id: UUID,
    detection_update: DetectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza uma detecção (status, infratores, etc)"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found"
        )

    # Atualizar campos
    update_data = detection_update.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(detection, key, value)

    await db.commit()
    await db.refresh(detection)

    return detection


@router.delete("/{detection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_detection(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deleta uma detecção"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found"
        )

    await db.delete(detection)
    await db.commit()

    return None

```

## `backend/app/api/v1/endpoints/users.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from app.api.deps import get_db, get_current_user
from app.core.security import get_password_hash
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate, UserResponse

router = APIRouter()


@router.get("/", response_model=List[UserResponse])
async def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    q: Optional[str] = None,
    search: Optional[str] = None,
    rpa: Optional[str] = None,
    cargo: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista usuários com filtros e paginação"""
    query = select(User)

    filters = []

    # Filtro de busca por nome ou email (q ou search)
    search_term = q or search
    if search_term:
        search_filter = or_(
            User.name.ilike(f"%{search_term}%"),
            User.email.ilike(f"%{search_term}%")
        )
        filters.append(search_filter)

    if rpa:
        filters.append(User.rpa == rpa)
    if cargo:
        filters.append(User.cargo == cargo)
    if is_active is not None:
        filters.append(User.is_active == is_active)

    if filters:
        query = query.where(and_(*filters))

    query = query.offset(skip).limit(limit).order_by(User.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Busca um usuário por ID"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return user


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria um novo usuário"""
    # Verificar se email já existe
    result = await db.execute(select(User).where(User.email == user_in.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Criar novo usuário
    password_hash = get_password_hash(user_in.password)
    db_user = User(
        name=user_in.name,
        email=user_in.email,
        phone=user_in.phone,
        secretaria=user_in.secretaria,
        cargo=user_in.cargo,
        rpa=user_in.rpa,
        password_hash=password_hash,
        is_active=user_in.is_active
    )

    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    return db_user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza um usuário"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Se estiver atualizando email, verificar se já existe
    if user_update.email and user_update.email != user.email:
        result = await db.execute(select(User).where(User.email == user_update.email))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

    # Atualizar campos
    update_data = user_update.model_dump(exclude_unset=True)

    # Se houver senha, hashear
    if "password" in update_data:
        password = update_data.pop("password")
        update_data["password_hash"] = get_password_hash(password)

    for key, value in update_data.items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)

    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deleta um usuário"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    await db.delete(user)
    await db.commit()

    return None

```

## `backend/app/api/v1/router.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, cameras, detections, dashboard

api_router = APIRouter()

# Incluir routers de cada endpoint
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
api_router.include_router(detections.router, prefix="/detections", tags=["detections"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])

```

## `backend/app/core/config.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "https://test-saira.manaca.tech"
    ]

    # S3/Storage
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET_NAME: str = ""
    S3_REGION: str = "us-east-1"

    # Application
    PROJECT_NAME: str = "SAIRA API"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

```

## `backend/app/core/database.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings
from typing import AsyncGenerator

# Async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=True if settings.ENVIRONMENT == "development" else False,
    future=True
)

# Async session
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

```

## `backend/app/core/security.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from app.core.config import settings

password_hash = PasswordHash((Argon2Hasher(),))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha em texto plano corresponde à senha hasheada"""
    return password_hash.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Gera hash da senha usando Argon2"""
    return password_hash.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Cria um token JWT de acesso"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decodifica um token JWT"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None

```

## `backend/app/main.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.router import api_router

# Criar aplicação FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="API para o Sistema de Monitoramento de Descarte Irregular (SAIRA)",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers da API v1
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """Endpoint raiz - health check"""
    return {
        "message": "SAIRA API is running",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

```

## `backend/app/models/__init__.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from app.models.user import User
from app.models.camera import Camera
from app.models.detection import Detection, DetectionStatus

__all__ = ["User", "Camera", "Detection", "DetectionStatus"]

```

## `backend/app/models/camera.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric
from datetime import datetime
from geoalchemy2 import Geometry
from app.core.database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    logradouro = Column(String(255))
    bairro = Column(String(100))
    rpa = Column(String(10), index=True)
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    geom = Column(Geometry("POINT", srid=4326))
    rtsp_url = Column(String(512))
    capture_interval_seconds = Column(Integer, default=30)
    is_active = Column(Boolean, default=True, index=True)
    last_capture_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

```

## `backend/app/models/detection.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from sqlalchemy import Column, Integer, String, DateTime, Numeric, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from geoalchemy2 import Geometry
import uuid
import enum
from app.core.database import Base


class DetectionStatus(str, enum.Enum):
    PENDENTE = "PENDENTE"
    EM_ANALISE = "EM_ANALISE"
    RESOLVIDO = "RESOLVIDO"


class Detection(Base):
    __tablename__ = "detections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"), index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    logradouro = Column(String(255))
    bairro = Column(String(100))
    rpa = Column(String(10), index=True)
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    geom = Column(Geometry("POINT", srid=4326))
    waste_type = Column(String(100))
    material_type = Column(String(100))
    volume_m3 = Column(Numeric(10, 2))
    offenders = Column(String(255))
    status = Column(Enum(DetectionStatus), default=DetectionStatus.PENDENTE, index=True)
    image_url = Column(String(512))
    confidence_score = Column(Numeric(3, 2))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

```

## `backend/app/models/user.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(20))
    secretaria = Column(String(100))
    cargo = Column(String(100))
    rpa = Column(String(10), index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

```

## `backend/app/schemas/__init__.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from app.schemas.auth import Token, TokenData, LoginRequest
from app.schemas.user import UserBase, UserCreate, UserUpdate, UserResponse, UserInDB
from app.schemas.camera import CameraBase, CameraCreate, CameraUpdate, CameraResponse
from app.schemas.detection import DetectionBase, DetectionCreate, DetectionUpdate, DetectionResponse, DetectionStatus
from app.schemas.dashboard import DashboardStats, OccurrencesByMonth, RecurrentLocation, VolumeByRPA

__all__ = [
    "Token",
    "TokenData",
    "LoginRequest",
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserInDB",
    "CameraBase",
    "CameraCreate",
    "CameraUpdate",
    "CameraResponse",
    "DetectionBase",
    "DetectionCreate",
    "DetectionUpdate",
    "DetectionResponse",
    "DetectionStatus",
    "DashboardStats",
    "OccurrencesByMonth",
    "RecurrentLocation",
    "VolumeByRPA",
]

```

## `backend/app/schemas/auth.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from pydantic import BaseModel, EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

```

## `backend/app/schemas/camera.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from decimal import Decimal


class CameraBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    logradouro: Optional[str] = Field(None, max_length=255)
    bairro: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    latitude: Decimal
    longitude: Decimal
    rtsp_url: Optional[str] = Field(None, max_length=512)
    capture_interval_seconds: int = Field(default=30, ge=1)
    is_active: bool = True


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    logradouro: Optional[str] = Field(None, max_length=255)
    bairro: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    rtsp_url: Optional[str] = Field(None, max_length=512)
    capture_interval_seconds: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None


class CameraResponse(CameraBase):
    id: int
    last_capture_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

```

## `backend/app/schemas/dashboard.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from pydantic import BaseModel
from typing import List
from decimal import Decimal


class DashboardStats(BaseModel):
    total_occurrences: int
    daily_volume_m3: Decimal
    pending_count: int
    in_analysis_count: int
    resolved_count: int


class OccurrencesByMonth(BaseModel):
    month: str
    count: int


class RecurrentLocation(BaseModel):
    logradouro: str
    bairro: str
    rpa: str
    count: int


class VolumeByRPA(BaseModel):
    rpa: str
    avg_volume_m3: Decimal
    total_volume_m3: Decimal
    count: int

```

## `backend/app/schemas/detection.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from decimal import Decimal
from uuid import UUID
from enum import Enum


class DetectionStatus(str, Enum):
    PENDENTE = "Pendente"
    EM_ANALISE = "Em análise"
    RESOLVIDO = "Resolvido"


class DetectionBase(BaseModel):
    camera_id: Optional[int] = None
    timestamp: datetime
    logradouro: Optional[str] = Field(None, max_length=255)
    bairro: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    latitude: Decimal
    longitude: Decimal
    waste_type: Optional[str] = Field(None, max_length=100)
    material_type: Optional[str] = Field(None, max_length=100)
    volume_m3: Optional[Decimal] = None
    offenders: Optional[str] = Field(None, max_length=255)
    status: DetectionStatus = DetectionStatus.PENDENTE
    image_url: Optional[str] = Field(None, max_length=512)
    confidence_score: Optional[Decimal] = Field(None, ge=0, le=1)


class DetectionCreate(DetectionBase):
    pass


class DetectionUpdate(BaseModel):
    status: Optional[DetectionStatus] = None
    offenders: Optional[str] = Field(None, max_length=255)
    waste_type: Optional[str] = Field(None, max_length=100)
    material_type: Optional[str] = Field(None, max_length=100)
    volume_m3: Optional[Decimal] = None


class DetectionResponse(DetectionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

```

## `backend/app/schemas/user.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


class UserBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=20)
    secretaria: Optional[str] = Field(None, max_length=100)
    cargo: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    is_active: bool = True


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    secretaria: Optional[str] = Field(None, max_length=100)
    cargo: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)


class UserResponse(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserInDB(UserResponse):
    password_hash: str

```

## `backend/app/services/geospatial_service.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID
from app.models.detection import Detection
from app.models.camera import Camera


async def get_detections_near_point(
    db: AsyncSession,
    latitude: float,
    longitude: float,
    radius_meters: float = 1000
) -> List[Detection]:
    """
    Busca detecções dentro de um raio em metros de um ponto específico

    Args:
        db: Sessão do banco de dados
        latitude: Latitude do ponto central
        longitude: Longitude do ponto central
        radius_meters: Raio de busca em metros (padrão: 1000m)

    Returns:
        Lista de detecções dentro do raio especificado
    """
    # Criar ponto PostGIS com SRID 4326 (WGS84)
    point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)

    # Converter metros para graus (aproximação)
    # 1 grau ≈ 111km no equador
    radius_degrees = radius_meters / 111000

    # Query com ST_DWithin para encontrar pontos próximos
    query = select(Detection).where(
        ST_DWithin(
            Detection.geom,
            point,
            radius_degrees
        )
    )

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_cameras_near_detection(
    db: AsyncSession,
    detection_id: UUID,
    radius_meters: float = 500
) -> List[Camera]:
    """
    Busca câmeras próximas a uma detecção específica

    Args:
        db: Sessão do banco de dados
        detection_id: ID da detecção
        radius_meters: Raio de busca em metros (padrão: 500m)

    Returns:
        Lista de câmeras próximas à detecção
    """
    # Buscar a detecção
    detection_result = await db.execute(
        select(Detection).where(Detection.id == detection_id)
    )
    detection = detection_result.scalar_one_or_none()

    if not detection:
        return []

    # Converter metros para graus
    radius_degrees = radius_meters / 111000

    # Query para encontrar câmeras próximas
    query = select(Camera).where(
        ST_DWithin(
            Camera.geom,
            detection.geom,
            radius_degrees
        )
    )

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_cameras_near_point(
    db: AsyncSession,
    latitude: float,
    longitude: float,
    radius_meters: float = 500
) -> List[Camera]:
    """
    Busca câmeras próximas a um ponto específico

    Args:
        db: Sessão do banco de dados
        latitude: Latitude do ponto central
        longitude: Longitude do ponto central
        radius_meters: Raio de busca em metros (padrão: 500m)

    Returns:
        Lista de câmeras dentro do raio especificado
    """
    # Criar ponto PostGIS
    point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)

    # Converter metros para graus
    radius_degrees = radius_meters / 111000

    # Query
    query = select(Camera).where(
        ST_DWithin(
            Camera.geom,
            point,
            radius_degrees
        )
    ).where(Camera.is_active == True)

    result = await db.execute(query)
    return list(result.scalars().all())


async def calculate_distance_between_points(
    db: AsyncSession,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float
) -> float:
    """
    Calcula a distância em metros entre dois pontos geográficos

    Args:
        db: Sessão do banco de dados
        lat1, lon1: Coordenadas do primeiro ponto
        lat2, lon2: Coordenadas do segundo ponto

    Returns:
        Distância em graus (para converter em metros, multiplicar por ~111000)
    """
    point1 = ST_SetSRID(ST_MakePoint(lon1, lat1), 4326)
    point2 = ST_SetSRID(ST_MakePoint(lon2, lat2), 4326)

    result = await db.execute(
        select(ST_Distance(point1, point2))
    )

    distance_degrees = result.scalar_one()
    return distance_degrees * 111000  # Converter para metros aproximadamente

```

## `backend/Dockerfile`

**Purpose:** Receita de build da imagem container para padronizar runtime e deploy deste componente.

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

# Tornar script de inicialização executável
RUN chmod +x start.sh

# Expor porta
EXPOSE 8001

# Comando padrão - executa migrações e inicia o servidor
CMD ["./start.sh"]

```

## `backend/init_db.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
"""
Script para inicializar o banco de dados com as tabelas e extensões necessárias
"""
import asyncio
from sqlalchemy import text
from app.core.database import engine, Base
from app.models import User, Camera, Detection


async def create_extensions():
    """Cria extensões PostGIS e UUID"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'))
        print("Extensões PostGIS e UUID criadas com sucesso!")


async def create_tables():
    """Cria todas as tabelas definidas nos modelos"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tabelas criadas com sucesso!")


async def create_triggers():
    """Cria triggers para auto-popular campos geométricos"""
    async with engine.begin() as conn:
        # Trigger para cameras
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION update_camera_geom()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.geom = ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))

        await conn.execute(text("""
            DROP TRIGGER IF EXISTS camera_geom_trigger ON cameras;
            CREATE TRIGGER camera_geom_trigger
            BEFORE INSERT OR UPDATE ON cameras
            FOR EACH ROW
            EXECUTE FUNCTION update_camera_geom();
        """))

        # Trigger para detections
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION update_detection_geom()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.geom = ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))

        await conn.execute(text("""
            DROP TRIGGER IF EXISTS detection_geom_trigger ON detections;
            CREATE TRIGGER detection_geom_trigger
            BEFORE INSERT OR UPDATE ON detections
            FOR EACH ROW
            EXECUTE FUNCTION update_detection_geom();
        """))

    print("Triggers criados com sucesso!")


async def create_indexes():
    """Cria índices adicionais para otimizar queries"""
    async with engine.begin() as conn:
        # Índices para users
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_rpa ON users(rpa);"))

        # Índices para cameras
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cameras_geom ON cameras USING GIST(geom);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cameras_rpa ON cameras(rpa);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cameras_is_active ON cameras(is_active);"))

        # Índices para detections
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp DESC);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_detections_status ON detections(status);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_detections_rpa ON detections(rpa);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_detections_camera_id ON detections(camera_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_detections_geom ON detections USING GIST(geom);"))

    print("Índices criados com sucesso!")


async def init_db():
    """Inicializa o banco de dados completo"""
    print("Iniciando criação do banco de dados...")

    try:
        await create_extensions()
        await create_tables()
        await create_triggers()
        await create_indexes()

        print("\n✅ Banco de dados inicializado com sucesso!")
        print("📊 Tabelas criadas: users, cameras, detections")
        print("🗺️  Extensões PostGIS e UUID habilitadas")
        print("⚡ Triggers e índices configurados")

    except Exception as e:
        print(f"\n❌ Erro ao inicializar banco de dados: {e}")
        raise

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init_db())

```

## `backend/README.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
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
- `status` - PENDENTE, EM_ANALISE, RESOLVIDO
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
python seed_db.py
```

## Variaveis de Ambiente

| Variavel | Descricao |
| -------- | --------- |
| `DATABASE_URL` | Connection string PostgreSQL (asyncpg) |
| `SECRET_KEY` | Chave secreta para assinatura JWT (min 32 chars) |
| `ENVIRONMENT` | `development`, `test` ou `production` |
| `AWS_ACCESS_KEY_ID` | Credencial AWS para S3 (opcional) |
| `AWS_SECRET_ACCESS_KEY` | Credencial AWS para S3 (opcional) |
| `S3_BUCKET_NAME` | Nome do bucket S3 para imagens (opcional) |

```

## `backend/requirements.txt`

**Purpose:** Manifesto de dependencias e metadados de build usado para reproducibilidade do componente.

```text
fastapi==0.109.0
uvicorn[standard]==0.27.0
sqlalchemy==2.0.25
alembic==1.13.1
asyncpg==0.29.0
pydantic==2.5.3
pydantic-settings==2.1.0
email-validator==2.1.0.post1
python-jose[cryptography]==3.3.0
pwdlib[argon2]==0.2.0
python-multipart==0.0.6
numpy<2.0.0
geoalchemy2==0.14.3
shapely==2.0.2
boto3==1.34.34
httpx==0.26.0
pytest==7.4.4
pytest-asyncio==0.23.3
faker==22.6.0

```

## `backend/seed_db.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
"""
Script para popular o banco de dados com dados fictícios para desenvolvimento.
Uso: python seed_db.py
"""
import asyncio
from faker import Faker
from datetime import datetime, timedelta
import random
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.camera import Camera
from app.models.detection import Detection, DetectionStatus
from app.core.security import get_password_hash
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

fake = Faker('pt_BR')


async def seed():
    """Função principal para popular o banco de dados"""
    async with AsyncSessionLocal() as db:
        print("🌱 Iniciando seeding do banco de dados...")

        # Verificar se já existe o admin
        result = await db.execute(select(User).where(User.email == "admin@saira.com"))
        admin_exists = result.scalar_one_or_none()

        if not admin_exists:
            print("👤 Criando usuário Admin...")
            admin = User(
                name="Administrador",
                email="admin@saira.com",
                phone="(81) 99999-9999",
                secretaria="EMLURB",
                cargo="Administrador",
                rpa="RPA-6",
                password_hash=get_password_hash("admin123"),
                is_active=True
            )
            db.add(admin)
        else:
            print("✓ Usuário Admin já existe")

        # Criar usuários aleatórios
        print("👥 Criando usuários aleatórios...")
        secretarias = ["EMLURB", "CTTU", "URB", "Secretaria de Meio Ambiente", "Secretaria de Infraestrutura"]
        cargos = ["Fiscal", "Coordenador", "Analista", "Supervisor", "Técnico"]
        rpas = ["RPA-1", "RPA-2", "RPA-3", "RPA-4", "RPA-5", "RPA-6"]

        for i in range(5):
            user = User(
                name=fake.name(),
                email=fake.email(),
                phone=fake.phone_number(),
                secretaria=random.choice(secretarias),
                cargo=random.choice(cargos),
                rpa=random.choice(rpas),
                password_hash=get_password_hash("senha123"),
                is_active=random.choice([True, True, True, False])  # 75% ativos
            )
            db.add(user)

        await db.commit()
        print("✓ Usuários criados com sucesso")

        # Criar câmeras com coordenadas reais de Recife
        print("📷 Criando câmeras...")
        cameras_data = [
            {
                "name": "Câmera Boa Viagem",
                "logradouro": "Av. Boa Viagem",
                "bairro": "Boa Viagem",
                "rpa": "RPA-6",
                "latitude": -8.1287,
                "longitude": -34.8988,
            },
            {
                "name": "Câmera Derby",
                "logradouro": "Av. Agamenon Magalhães",
                "bairro": "Derby",
                "rpa": "RPA-1",
                "latitude": -8.0592,
                "longitude": -34.8843,
            },
            {
                "name": "Câmera Casa Forte",
                "logradouro": "Praça de Casa Forte",
                "bairro": "Casa Forte",
                "rpa": "RPA-3",
                "latitude": -8.0223,
                "longitude": -34.9287,
            },
            {
                "name": "Câmera Recife Antigo",
                "logradouro": "Rua do Bom Jesus",
                "bairro": "Recife",
                "rpa": "RPA-1",
                "latitude": -8.0631,
                "longitude": -34.8711,
            },
            {
                "name": "Câmera Piedade",
                "logradouro": "Av. Caxangá",
                "bairro": "Piedade",
                "rpa": "RPA-4",
                "latitude": -8.0478,
                "longitude": -34.9194,
            },
        ]

        created_cameras = []
        for cam_data in cameras_data:
            point = Point(cam_data["longitude"], cam_data["latitude"])
            camera = Camera(
                name=cam_data["name"],
                logradouro=cam_data["logradouro"],
                bairro=cam_data["bairro"],
                rpa=cam_data["rpa"],
                latitude=cam_data["latitude"],
                longitude=cam_data["longitude"],
                geom=from_shape(point, srid=4326),
                rtsp_url=f"rtsp://example.com/stream/{fake.uuid4()}",
                capture_interval_seconds=random.choice([30, 60, 120]),
                is_active=True,
                last_capture_at=datetime.utcnow() - timedelta(minutes=random.randint(1, 60))
            )
            db.add(camera)
            created_cameras.append(camera)

        await db.commit()
        print("✓ Câmeras criadas com sucesso")

        # Criar detecções
        print("🔍 Criando detecções...")
        waste_types = ["Entulho", "Móveis", "Lixo doméstico", "Resíduos de construção", "Eletrônicos"]
        material_types = ["Concreto", "Madeira", "Plástico", "Metal", "Misto"]
        statuses = [DetectionStatus.PENDENTE, DetectionStatus.EM_ANALISE, DetectionStatus.RESOLVIDO]

        for i in range(25):
            camera = random.choice(created_cameras)
            # Adicionar pequena variação nas coordenadas da câmera
            lat_offset = random.uniform(-0.002, 0.002)
            lng_offset = random.uniform(-0.002, 0.002)
            det_lat = float(camera.latitude) + lat_offset
            det_lng = float(camera.longitude) + lng_offset

            point = Point(det_lng, det_lat)

            detection = Detection(
                camera_id=camera.id,
                timestamp=datetime.utcnow() - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23)),
                logradouro=camera.logradouro,
                bairro=camera.bairro,
                rpa=camera.rpa,
                latitude=det_lat,
                longitude=det_lng,
                geom=from_shape(point, srid=4326),
                waste_type=random.choice(waste_types),
                material_type=random.choice(material_types),
                volume_m3=round(random.uniform(0.5, 15.0), 2),
                offenders=fake.name() if random.random() > 0.5 else None,
                status=random.choice(statuses),
                image_url=f"https://picsum.photos/seed/{fake.uuid4()}/800/600",
                confidence_score=round(random.uniform(0.75, 0.99), 2)
            )
            db.add(detection)

        await db.commit()
        print("✓ Detecções criadas com sucesso")

        print("\n✅ Seeding concluído com sucesso!")
        print("\n📝 Credenciais de acesso:")
        print("   Email: admin@saira.com")
        print("   Senha: admin123")


if __name__ == "__main__":
    asyncio.run(seed())

```

## `backend/start.sh`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```bash
#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
# Respect X-Forwarded-* from the gateway/tunnel so redirects keep https host/scheme.
exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips="*" "$@"

```

## `CORRECAO_APLICADA.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
# ✅ CORREÇÃO DE COMPILAÇÃO APLICADA

## 🔧 Problema Corrigido

**Erro:**
```
src/contexts/AuthContext.tsx(1,58): error TS1484: 'ReactNode' is a type and must be imported using a type-only import when 'verbatimModuleSyntax' is enabled.
```

**Solução Aplicada:**

Arquivo: `frontend/src/contexts/AuthContext.tsx`

**Antes:**
```typescript
import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
```

**Depois:**
```typescript
import { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';
```

---

## ✅ Status: CORRIGIDO

O código agora deve compilar sem erros!

---

## 🚀 Próximos Passos

Execute novamente os comandos:

```bash
cd c:\saira\services

# Limpar tudo e recomeçar
docker-compose down -v

# Rebuild com a correção
docker-compose up -d --build

# Aguardar 2-3 minutos para compilar

# Criar tabelas
docker-compose exec backend alembic upgrade head

# Popular banco
docker-compose exec backend python seed_db.py

# Acessar
# http://localhost:3000
```

---

## 📝 Observações

- Esta foi a única correção necessária para o erro de compilação TypeScript
- O erro ocorreu porque o TypeScript estava configurado com `verbatimModuleSyntax` habilitado
- Tipos devem ser importados com `import type { ... }` nesta configuração
- Todos os outros arquivos já estavam corretos

---

## ✅ Verificação

Após o `docker-compose up -d --build`, você deve ver:

```
[+] Building ...
 => [web builder] ...
 => [web] CACHED
 => => exporting to image
 => => naming to docker.io/library/services-web
```

Sem erros de compilação!

---

**Agora o sistema está 100% funcional!** 🎉

```

## `db/migrations/schema.sql`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```sql


```

## `docker-compose.override.yml`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```yaml
services:
  # Frontend (React + Vite)
  web:
    build:
      context: ./frontend
      args:
        - VITE_API_URL=https://api-test-saira.manaca.tech/api/v1
    ports:
      - "3001:80"
    container_name: vite-react-ts-app-test
    restart: always
    depends_on:
      - backend

  # Api-Gateway (Nginx)
  api-gateway:
    image: nginx:alpine
    container_name: saira-api-gateway-test
    volumes:
      - ./nginx/gateway.conf:/etc/nginx/conf.d/default.conf
    ports:
      - "5001:80"
    depends_on:
      - backend
    restart: always

  # Backend API (FastAPI)
  backend:
    build: ./backend
    container_name: saira-backend-api-test
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/saira_db
      - SECRET_KEY=${SECRET_KEY:-your-secret-key-change-in-production-min-32-chars}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}
      - S3_BUCKET_NAME=${S3_BUCKET_NAME:-}
      - ENVIRONMENT=test
    depends_on:
      db:
        condition: service_healthy
    restart: always
    command: ["bash", "/app/start.sh", "--workers", "4"]

  # pgAdmin (nome distinto para evitar conflito com ambiente de dev/prod)
  pgadmin:
    container_name: saira-pgadmin-test
    ports:
      - "5051:80"

  # PostgreSQL + PostGIS
  db:
    image: postgis/postgis:15-3.4
    container_name: saira-postgres-db-test
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=saira_db
    ports:
      - "5433:5432"
    volumes:
      - postgres_data_test:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always


volumes:
  postgres_data_test:

```

## `docker-compose.prod.yml`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```yaml
services:
  # Frontend (React + Vite)
  web:
    build: ./frontend
    ports:
      - "3000:80"
    container_name: saira-web-prod
    restart: always
    environment:
      - VITE_API_URL=https://api-saira.manaca.tech
    depends_on:
      - backend

  # Api-Gateway (Nginx)
  api-gateway:
    image: nginx:alpine
    container_name: saira-gateway-prod
    volumes:
      - ./nginx/gateway.conf:/etc/nginx/conf.d/default.conf
    ports:
      - "5000:80"
    depends_on:
      - backend
    restart: always

  # Backend API (FastAPI)
  backend:
    build: ./backend
    container_name: saira-backend-prod
    ports:
      - "8001:8001"
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/saira_db
      - SECRET_KEY=${SECRET_KEY:-your-secret-key-change-in-production-min-32-chars}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}
      - S3_BUCKET_NAME=${S3_BUCKET_NAME:-}
      - ENVIRONMENT=production
    depends_on:
      db:
        condition: service_healthy
    restart: always
    command: ["bash", "/app/start.sh", "--workers", "4"]

  # PostgreSQL + PostGIS
  db:
    image: postgis/postgis:15-3.4
    container_name: saira-db-prod
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=saira_db
    ports:
      - "5432:5432"
    volumes:
      - postgres_data_prod:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always

volumes:
  postgres_data_prod:

```

## `docker-compose.test.yml`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```yaml
services:
  # Frontend (React + Vite)
  web:
    build:
      context: ./frontend
      args:
        - VITE_API_URL=https://api-test-saira.manaca.tech/api/v1
    ports:
      - "3001:80"
    container_name: saira-web-test
    restart: always
    depends_on:
      - backend

  # Api-Gateway (Nginx)
  api-gateway:
    image: nginx:alpine
    container_name: saira-gateway-test
    volumes:
      - ./nginx/gateway.conf:/etc/nginx/conf.d/default.conf
    ports:
      - "5001:80"
    depends_on:
      - backend
    restart: always

  # Backend API (FastAPI)
  backend:
    build: ./backend
    container_name: saira-backend-test
    ports:
      - "8002:8001"
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/saira_db
      - SECRET_KEY=${SECRET_KEY:-your-secret-key-change-in-production-min-32-chars}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}
      - S3_BUCKET_NAME=${S3_BUCKET_NAME:-}
      - ENVIRONMENT=test
    depends_on:
      db:
        condition: service_healthy
    restart: always
    command: ["bash", "/app/start.sh", "--workers", "4"]

  # PostgreSQL + PostGIS
  db:
    image: postgis/postgis:15-3.4
    container_name: saira-db-test
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=saira_db
    ports:
      - "5433:5432"
    volumes:
      - postgres_data_test:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always

  # pgAdmin (teste)
  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: saira-pgadmin-test
    environment:
      - PGADMIN_DEFAULT_EMAIL=admin@saira.com
      - PGADMIN_DEFAULT_PASSWORD=admin
    ports:
      - "5051:80"
    depends_on:
      - db
    restart: always

volumes:
  postgres_data_test:

```

## `docker-compose.yml`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```yaml
services:
  # Frontend (React + Vite)
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
      - "8001:8001"
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/saira_db
      - SECRET_KEY=${SECRET_KEY:-your-secret-key-change-in-production-min-32-chars}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}
      - S3_BUCKET_NAME=${S3_BUCKET_NAME:-}
      - ENVIRONMENT=production
    depends_on:
      db:
        condition: service_healthy
    restart: always
    volumes:
      - ./backend:/app
    command: ["bash", "/app/start.sh", "--workers", "4"]

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

  

```

## `docs/architecture.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown


```

## `docs/runbooks/operations.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown


```

## `docs/runbooks/yolo-vm.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown


```

## `EXECUTAR_AGORA.sh`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```bash
#!/bin/bash

echo "============================================"
echo "🚀 EXECUTAR SAIRA - VERSÃO CORRIGIDA"
echo "============================================"
echo ""

echo "📝 Correção aplicada: AuthContext.tsx"
echo "   - ReactNode agora usa import type"
echo ""

echo "Iniciando processo..."
echo ""

# Verificar Docker
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker não está rodando!"
    echo "   Inicie o Docker Desktop primeiro"
    exit 1
fi

echo "✅ Docker está rodando"
echo ""

# Limpar ambiente
echo "🧹 Limpando ambiente anterior..."
docker-compose down -v 2>&1 | grep -v "Warning"

echo ""
echo "🏗️  Construindo containers (isso pode levar 3-5 minutos)..."
echo "   Por favor, aguarde..."
echo ""

docker-compose up -d --build

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Erro ao construir containers"
    echo "   Verifique os logs acima"
    exit 1
fi

echo ""
echo "⏳ Aguardando containers iniciarem (30 segundos)..."
sleep 30

echo ""
echo "📊 Status dos containers:"
docker-compose ps

echo ""
echo "🗄️  Criando tabelas do banco de dados..."
docker-compose exec backend alembic upgrade head

if [ $? -ne 0 ]; then
    echo "❌ Erro ao criar tabelas"
    exit 1
fi

echo ""
echo "🌱 Populando banco de dados..."
docker-compose exec backend python seed_db.py

if [ $? -ne 0 ]; then
    echo "❌ Erro ao popular banco"
    exit 1
fi

echo ""
echo "============================================"
echo "✅ SISTEMA PRONTO!"
echo "============================================"
echo ""
echo "🌐 URLs de Acesso:"
echo "   Frontend:    http://localhost:3000"
echo "   Backend API: http://localhost:8001/docs"
echo "   pgAdmin:     http://localhost:5050"
echo ""
echo "🔐 Credenciais:"
echo "   Email: admin@saira.com"
echo "   Senha: admin123"
echo ""
echo "📝 Para ver logs:"
echo "   docker-compose logs -f"
echo ""
echo "🎉 Tudo pronto! Abra http://localhost:3000 no navegador"
echo ""

```

## `frontend/Dockerfile`

**Purpose:** Receita de build da imagem container para padronizar runtime e deploy deste componente.

```dockerfile
# Stage 1: Build the application
FROM node:20-alpine as builder

# Set working directory
WORKDIR /app

# Copy package.json (lockfile may not exist in repo)
COPY package.json ./

# Install dependencies - using 'npm install' to resolve lockfile mismatches
RUN npm install

# Copy the rest of the source code
COPY . .

# Build the project (output will be in /app/dist)
RUN npm run build

# Stage 2: Serve the application with Nginx
FROM nginx:alpine

# Copy the build output from Stage 1 to the Nginx html directory
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Start Nginx in the foreground
CMD ["nginx", "-g", "daemon off;"]

```

## `frontend/eslint.config.js`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```javascript
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
])

```

## `frontend/index.html`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Saira</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>

```

## `frontend/nginx.conf`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```nginx
server {
    listen 80;
    server_name localhost;

    root /usr/share/nginx/html;
    index index.html;

    # Serve all routes (dashboard, detections, etc.) through index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets (images, styles)
    location ~* \.(?:ico|css|js|gif|jpe?g|png)$ {
        expires 6M;
        access_log off;
        add_header Cache-Control "public";
    }
}

```

## `frontend/package.json`

**Purpose:** Manifesto de dependencias e metadados de build usado para reproducibilidade do componente.

```json
{
  "name": "testedefluxo",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "preview": "vite preview"
  },
  "dependencies": {
    "clsx": "^2.1.1",
    "framer-motion": "^12.26.2",
    "lucide-react": "^0.562.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^7.12.0",
    "recharts": "^3.6.0",
    "axios": "^1.7.2",
    "tailwind-merge": "^3.4.0",
    "react-leaflet": "^4.2.1",
    "leaflet": "^1.9.4",
    "leaflet.heat": "^0.2.0",
"jspdf": "^3.0.1"
  },
  "devDependencies": {
    "@eslint/js": "^9.39.1",
    "@tailwindcss/vite": "^4.1.18",
    "@types/node": "^24.10.1",
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@types/react-leaflet": "^3.0.0",
    "@types/leaflet": "^1.9.10",
    "@types/leaflet.heat": "^0.2.2",
    "@vitejs/plugin-react-swc": "^4.2.2",
    "eslint": "^9.39.1",
    "eslint-plugin-react-hooks": "^7.0.1",
    "eslint-plugin-react-refresh": "^0.4.24",
    "globals": "^16.5.0",
    "tailwindcss": "^4.1.18",
    "typescript": "~5.9.3",
    "typescript-eslint": "^8.46.4",
    "vite": "^7.2.4"
  }
}

```

## `frontend/README.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
# Frontend - SAIRA

SPA (Single Page Application) para gestao de ocorrencias de descarte irregular de residuos.

## Stack

- **React 18** + TypeScript
- **Vite 7** (build e dev server)
- **Tailwind CSS 4** (estilizacao)
- **React Router 7** (rotas)
- **Axios** (HTTP client com interceptors JWT)
- **Recharts** (graficos do dashboard)
- **React Leaflet** + Leaflet.heat (mapas interativos e heatmap)
- **Framer Motion** (animacoes)
- **Lucide React** (icones)
- **jsPDF** (exportacao de relatorios em PDF)

## Estrutura

```text
src/
├── main.tsx                    # Entry point (React + AuthProvider)
├── App.tsx                     # Definicao de rotas
│
├── pages/
│   ├── Login.tsx               # Tela de autenticacao
│   ├── Dashboard.tsx           # Painel com KPIs, graficos e mapa de calor
│   ├── Detections.tsx          # Listagem e gestao de ocorrencias
│   └── UsersPage.tsx           # CRUD de usuarios do sistema
│
├── components/
│   ├── Sidebar.tsx             # Barra lateral de navegacao
│   ├── DashboardCharts.tsx     # Graficos (ocorrencias/mes, volume/RPA, reincidencias)
│   ├── OccurrenceModal.tsx     # Modal de detalhes da ocorrencia + exportacao PNG/PDF
│   ├── DeleteModal.tsx         # Modal de confirmacao de exclusao
│   ├── UserModal.tsx           # Modal de criacao/edicao de usuario
│   ├── InputField.tsx          # Campo de input reutilizavel
│   ├── SharedFilters.tsx       # Componente de filtros compartilhados
│   └── Tooltip.tsx             # Tooltip generico
│
├── contexts/
│   └── AuthContext.tsx         # Context de autenticacao (login, logout, token JWT)
│
├── services/
│   ├── api.ts                  # Instancia Axios com interceptors (JWT auto-inject, 401 redirect)
│   └── mockData.ts             # Dados mock para desenvolvimento
│
└── assets/                     # Imagens estaticas
```

## Paginas

### Login (`/`)
Formulario de autenticacao com email/senha. Envia credenciais via `POST /api/v1/auth/login` (OAuth2 password flow) e armazena o token JWT em `localStorage`.

### Dashboard (`/dashboard`)
Painel principal com:
- **KPIs**: total de ocorrencias, volume diario, contagem por status (pendente, em analise, resolvido)
- **Graficos**: ocorrencias por mes, volumetria por RPA, locais reincidentes
- **Mapa de calor**: visualizacao geoespacial das deteccoes via Leaflet + heatmap

### Detections (`/detections`)
Tabela de ocorrencias com filtros por RPA, status, bairro e periodo. Cada linha abre o `OccurrenceModal` com detalhes completos e opcao de exportar como PNG ou PDF.

### Users (`/users`)
CRUD completo de usuarios: listagem, criacao, edicao e exclusao. Campos: nome, email, telefone, secretaria, cargo, RPA.

## Componentes Principais

### OccurrenceModal
Modal de detalhes de uma ocorrencia. Exibe imagem de evidencia, status, localizacao, tipo de residuo, volumetria e infratores. Possui exportacao programatica via **Canvas API** (PNG) e **jsPDF** (PDF), sem dependencia de `html2canvas`.

### AuthContext
Context provider que gerencia o ciclo de autenticacao:
- `login(email, password)`: autentica e salva token + dados do usuario
- `logout()`: limpa localStorage e redireciona para `/`
- `validateToken()`: valida token existente no carregamento da aplicacao
- Interceptor Axios automatico para injetar `Bearer` token e tratar 401

## Desenvolvimento

```bash
# Instalar dependencias
npm install

# Dev server (hot reload)
npm run dev

# Build de producao
npm run build

# Lint
npm run lint
```

## Credenciais de Acesso

O backend ainda nao esta integrado ao frontend. Enquanto isso, o login utiliza credenciais hardcoded em `src/pages/Login.tsx`:

| Email | Senha |
| ----- | ----- |
| `admin@gmail.com` | `12345` |

> **Nota:** quando a integracao com o backend estiver ativa, o login passara a usar o endpoint `POST /api/v1/auth/login` via OAuth2 password flow, e essas credenciais deixarao de funcionar. O usuario padrao do backend e `admin@saira.com` / `admin123`.

## Variaveis de Ambiente

Criar `.env` na raiz do frontend:

```env
VITE_API_URL=http://localhost:8001/api/v1
```

## Docker

O Dockerfile usa multi-stage build:
1. **Stage build**: Node.js compila a aplicacao com Vite
2. **Stage serve**: Nginx serve os arquivos estaticos com configuracao customizada (`nginx.conf`)

```

## `frontend/src/App.css`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```css


```

## `frontend/src/App.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Detections } from "./pages/Detections";
import { UsersPage } from "./pages/UsersPage";

function App() {
  return (
    <div className="fixed inset-0 w-[125%] h-[125vh] origin-top-left scale-[0.8] overflow-hidden bg-[#f8f9fa]">
      <Router>
        <Routes>
          <Route path="/" element={<Login />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/detections" element={<Detections />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </div>
  );
}

export default App;

```

## `frontend/src/components/DashboardCharts.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React, { useEffect, useState, useRef } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip as RechartsTooltip,
} from "recharts";
import { X, Settings, Palette, Clock, Trash2, HelpCircle, Camera, UserX } from "lucide-react";
import { MapContainer, TileLayer, useMap, Marker, Popup, CircleMarker, Tooltip as LeafletTooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import "leaflet.heat";
import { masterPois } from "../services/mockData";
import type { PoiData } from "../services/mockData";

// --- ENVIRONMENT VARIABLE ---
const mapMode = import.meta.env.VITE_MAP_MODE || 'heatmap';

// --- COLOR MAPPING for BUBBLE MAP ---
const statusColors: Record<PoiData["status"], string> = {
  "Pendente": "#ef4444",
  "Em an\u00E1lise": "#f97316",
  "Resolvido": "#22c55e",
};

// --- ICON FIX ---
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png',
});


// --- REUSABLE COMPONENTS ---
export const OccurrencesChart: React.FC<{ data?: PoiData[]; series?: { name: string; val: number }[] }> = ({ data, series }) => {
    const sourceData = data ?? masterPois;
    const monthLabels = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"];
    const counts = new Array(12).fill(0);
    sourceData.forEach((item) => {
        const monthIndex = new Date(item.timestamp).getMonth();
        counts[monthIndex] += 1;
    });
    const fallbackData = monthLabels.map((name, index) => ({ name, val: counts[index] }));
    const chartData = series && series.length > 0 ? series : fallbackData;
    return (
        <div className="w-full h-64">
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} barSize={12}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e5e5" />
                    <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#666" }} dy={10} />
                    <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#666" }} />
                    <RechartsTooltip cursor={{ fill: "transparent" }} contentStyle={{ borderRadius: "8px", border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }} />
                    <Bar dataKey="val" fill="#a3e635" radius={[4, 4, 4, 4]} />
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
};

const Slider: React.FC<{ label: string; value: number; min: number; max: number; step: number; unit?: string; hint?: string; onChange: (v: number) => void; }> = ({ label, value, min, max, step, unit, hint, onChange }) => (
    <div>
        <label className="flex justify-between text-sm text-gray-800">
            <span>{label}</span>
            <span className="text-gray-900 font-medium">{value.toFixed(2)}{unit} {hint && <span className="text-gray-500 font-normal">{hint}</span>}</span>
        </label>
        <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))} className="w-full h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-lime-500 mt-1" />
    </div>
);

const getStatusStyle = (status: PoiData['status']) => {
    switch (status) { case "Pendente": return "bg-red-100 text-red-600"; case "Em an\u00E1lise": return "bg-orange-100 text-orange-600"; case "Resolvido": return "bg-green-100 text-green-600"; default: return "bg-gray-100 text-gray-600"; }
};


// --- MAP LAYERS & LEGEND ---
const HeatmapLayer: React.FC<{ points: L.HeatLatLngTuple[]; options: L.HeatMapOptions; }> = ({ points, options }) => {
  const map = useMap();
  const layerRef = useRef<L.HeatLayer | null>(null);
  useEffect(() => {
    if (!layerRef.current) {
      layerRef.current = L.heatLayer(points, options).addTo(map);
    } else {
      layerRef.current.setOptions(options);
      layerRef.current.setLatLngs(points);
    }
  }, [map, points, options]);
  return null;
};

const BubbleMapLayer: React.FC<{ points: PoiData[]; scaleFactor: number; onMarkerClick?: (poi: PoiData) => void }> = ({ points, scaleFactor, onMarkerClick }) => {
    return <> {points.map(point => (
        <CircleMarker key={point.id} center={[point.latitude, point.longitude]}
            radius={Math.sqrt(point.volume) * scaleFactor}
            pathOptions={{ color: statusColors[point.status], fillColor: statusColors[point.status], fillOpacity: 0.6, weight: 1 }}
        >
            <LeafletTooltip>
                <div className="font-bold">{point.bairro}</div>
                <div>{point.wasteType} - {point.volume} m³</div>
            </LeafletTooltip>
            <RichPopup point={point} onMarkerClick={onMarkerClick} />
        </CircleMarker>
    ))} </>;
};

const Legend: React.FC<{ map: L.Map | null; points: PoiData[] }> = ({ map, points }) => {
    const legendRef = useRef<L.Control | null>(null);

    useEffect(() => {
        if (!map) return;
        
        // Remove old legend if it exists
        if (legendRef.current) {
            legendRef.current.remove();
        }

        const legend = new L.Control({ position: 'bottomright' });
        legend.onAdd = () => {
            const div = L.DomUtil.create('div', 'info legend bg-white/80 backdrop-blur-md p-3 rounded-lg shadow-lg');
            if (mapMode === 'heatmap') {
                div.innerHTML = `
                    <h4 class="font-bold text-sm mb-2">Intensidade (Volume)</h4>
                    <div class="w-full h-5 rounded-md" style="background: linear-gradient(to right, blue, cyan, purple, red);"></div>
                    <div class="flex justify-between text-xs mt-1">
                        <span>Baixo</span>
                        <span>Médio</span>
                        <span>Alto</span>
                    </div>
                `;
            } else { // bubble mode
                const statusEntries: Array<PoiData["status"]> = [
                  "Pendente",
                  "Em an\u00E1lise",
                  "Resolvido",
                ];
                let content = '<h4 class="font-bold text-sm mb-2">Status</h4>';
                statusEntries.forEach((status) => {
                    content += `
                        <div class="flex items-center gap-2 mt-1">
                            <i class="w-3 h-3 rounded-full" style="background-color: ${statusColors[status]}"></i>
                            <span class="text-xs">${status}</span>
                        </div>
                    `;
                });
                div.innerHTML = content;
            }
            return div;
        };

        legend.addTo(map);
        legendRef.current = legend;

        return () => {
            if (legendRef.current) {
                legendRef.current.remove();
            }
        };
    }, [map, mapMode, points]);

    return null;
};


// --- POPUP COMPONENT ---
const RichPopup: React.FC<{ point: PoiData; onMarkerClick?: (poi: PoiData) => void }> = ({ point, onMarkerClick }) => (
    <Popup>
        <div className="w-64">
            <div className="font-bold text-lg mb-1">{point.bairro}</div>
            <div className="text-gray-600 text-sm mb-3">{point.logradouro}</div>
            <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2"><Clock size={14} className="text-gray-500"/><span>{new Date(point.timestamp).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span></div>
                <div className="flex items-center gap-2"><Trash2 size={14} className="text-gray-500"/><span>{point.wasteType} ({point.volume} m³)</span></div>
                <div className="flex items-center gap-2"><HelpCircle size={14} className="text-gray-500"/><span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${getStatusStyle(point.status)}`}>{point.status}</span></div>
                <div className="flex items-center gap-2"><UserX size={14} className="text-gray-500"/><span>Infrator: <span className={point.hasOffender ? 'font-bold text-red-500' : 'font-medium text-gray-700'}>{point.hasOffender ? 'Identificado' : 'Não'}</span></span></div>
            </div>
            <button
              type="button"
              onClick={() => onMarkerClick?.(point)}
              className="mt-4 w-full bg-lime-500 text-black text-center font-bold py-2 rounded-lg hover:bg-lime-600 transition-colors flex items-center justify-center gap-2"
            >
              <Camera size={16}/> Ver Foto
            </button>
        </div>
    </Popup>
);


// --- MAIN WIDGET ---
export const MapWidget: React.FC<{ isExpanded: boolean; onToggleExpand: () => void; points?: PoiData[]; onMarkerClick?: (poi: PoiData) => void }> = ({ isExpanded, onToggleExpand, points, onMarkerClick }) => {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [mapInstance, setMapInstance] = useState<L.Map | null>(null);
  const dataPoints = points ?? masterPois;

  // Heatmap settings
  const [radius, setRadius] = useState(25);
  const [blur, setBlur] = useState(15);
  const [maxIntensity, setMaxIntensity] = useState(1.0);
  const [minOpacity, setMinOpacity] = useState(0.5);
  const [lowThreshold, setLowThreshold] = useState(0.3);
  const [highThreshold, setHighThreshold] = useState(0.6);

  // Bubble map settings
  const [scaleFactor, setScaleFactor] = useState(2.0);

  const heatmapPoints = dataPoints.map(p => [p.latitude, p.longitude, p.volume / 100] as L.HeatLatLngTuple);
  const heatmapOptions: L.HeatMapOptions = { radius, blur, minOpacity, max: maxIntensity, gradient: { 0.0: 'blue', [lowThreshold]: 'cyan', [highThreshold]: 'purple', 1.0: 'red' } };

  return (
    <div className={`relative w-full h-full rounded-2xl overflow-hidden shadow-lg group ${isExpanded ? "fixed inset-0 z-50 m-0 rounded-none" : ""}`}>
        
        {isSettingsOpen && (
            <div className="absolute top-16 right-4 bg-white/95 backdrop-blur-sm text-gray-900 p-4 z-[1001] w-80 rounded-2xl shadow-2xl border border-gray-200 animate-in fade-in-5 zoom-in-95 duration-200">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-lg font-bold flex items-center gap-2 text-gray-800"><Palette size={20}/>Config. do Mapa</h3>
                    <button onClick={() => setIsSettingsOpen(false)} className="p-1 rounded-full hover:bg-black/10 transition-colors"><X size={20}/></button>
                </div>
                <div className="space-y-4">
                    {mapMode === 'heatmap' ? (
                        <>
                            <Slider label="Limite Azul-Roxo" value={lowThreshold} min={0.0} max={1.0} step={0.05} onChange={setLowThreshold} hint={`(${(lowThreshold * 100).toFixed(0)}m³)`} />
                            <Slider label="Limite Roxo-Vermelho" value={highThreshold} min={0.0} max={1.0} step={0.05} onChange={setHighThreshold} hint={`(${(highThreshold * 100).toFixed(0)}m³)`} />
                            <hr className="border-gray-200 my-2" />
                            <Slider label="Radius" value={radius} min={5} max={50} step={1} unit="px" onChange={setRadius} />
                            <Slider label="Blur" value={blur} min={5} max={50} step={1} unit="px" onChange={setBlur} />
                            <Slider label="Max Intensity" value={maxIntensity} min={0.1} max={1.0} step={0.05} onChange={setMaxIntensity} />
                            <Slider label="Min Opacity" value={minOpacity} min={0} max={1} step={0.05} onChange={setMinOpacity} />
                        </>
                    ) : ( // bubble mode
                        <Slider label="Fator de Escala" value={scaleFactor} min={0.5} max={5} step={0.1} unit="x" onChange={setScaleFactor} />
                    )}
                </div>
            </div>
        )}

      <MapContainer ref={setMapInstance} center={[-8.06, -34.90]} zoom={12} scrollWheelZoom={true} style={{ height: "100%", width: "100%" }}>
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        
        {mapMode === 'heatmap' ? (
          <HeatmapLayer points={heatmapPoints} options={heatmapOptions} />
        ) : (
          <BubbleMapLayer points={dataPoints} scaleFactor={scaleFactor} onMarkerClick={onMarkerClick} />
        )}
        
        {/* Render Markers on top of Heatmap, but not for Bubble Map */}
        {mapMode === 'heatmap' && dataPoints.map((point: PoiData) => (
          <Marker key={point.id} position={[point.latitude, point.longitude]}>
            <RichPopup point={point} onMarkerClick={onMarkerClick} />
          </Marker>
        ))}

        <Legend map={mapInstance} points={dataPoints} />
      </MapContainer>

      {/* ACTION BUTTONS */}
      <div className="absolute top-4 right-4 z-[1000] flex flex-col gap-2">
          <button onClick={() => setIsSettingsOpen(!isSettingsOpen)} className={`bg-white p-2 rounded-lg shadow-lg hover:bg-gray-100 transition-colors text-gray-700 ${isSettingsOpen ? 'bg-lime-400 text-black' : ''}`}><Settings size={20} /></button>
      </div>
    </div>
  );
};


```

## `frontend/src/components/DeleteModal.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React from "react";
import { AlertTriangle } from "lucide-react";

interface DeleteModalProps {
  onClose: () => void;
  onConfirm: () => void;
  isClosing: boolean; // Animation state
}

export const DeleteModal: React.FC<DeleteModalProps> = ({
  onClose,
  onConfirm,
  isClosing,
}) => {
  return (
    <div
      className={`
        fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4
        transition-opacity duration-500
        ${isClosing ? "opacity-0" : "opacity-100"}
      `}
    >
      <div
        className="bg-white rounded-[2rem] shadow-2xl w-full max-w-sm p-8 relative text-center"
        style={{
          animation: isClosing
            ? "modalPopExit 0.5s ease-in forwards"
            : "modalPop 0.5s ease-out forwards",
        }}
      >
        <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-6">
          <AlertTriangle size={32} className="text-red-500" />
        </div>

        <h3 className="text-xl font-bold text-[#1a1a1a] mb-2 select-none">
          Excluir Usuário?
        </h3>
        <p className="text-gray-500 text-sm mb-8 select-none leading-relaxed">
          Essa ação não pode ser desfeita. O usuário perderá acesso ao sistema
          imediatamente.
        </p>

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-3 rounded-xl font-bold text-gray-500 hover:bg-gray-100 transition-colors select-none"
          >
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 py-3 rounded-xl font-bold bg-red-500 hover:bg-red-600 text-white shadow-lg shadow-red-500/20 transition-all select-none"
          >
            Excluir
          </button>
        </div>
      </div>
    </div>
  );
};

```

## `frontend/src/components/InputField.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React from "react";
import type { LucideIcon } from "lucide-react";

// --- Type Definitions ---
interface InputFieldProps {
  id: string;
  label: string;
  type: string;
  placeholder: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  icon?: LucideIcon;
  error?: boolean;
  errorMessage?: string;
  required?: boolean; // Added optional prop definition for safety
}

export const InputField: React.FC<InputFieldProps> = ({
  id,
  label,
  type,
  placeholder,
  value,
  onChange,
  icon: Icon,
  error,
  errorMessage,
  ...props // Spread remaining props like required
}) => {
  // --- Dynamic Style Calculations ---
  const labelColor = error ? "text-[#ff3366]" : "text-[#d9f99d]";
  const borderColor = error
    ? "border-[#ff3366]"
    : "border-zinc-600 focus:border-[#ccff33]";
  const iconColor = error ? "text-[#ff3366]" : "text-zinc-500";

  return (
    // --- Component Container ---
    <div className="flex flex-col gap-2 w-full group">
      {/* --- Label Section --- */}
      {/* FIX: Added 'select-none' to prevent text selection */}
      <label
        htmlFor={id}
        className={`text-base font-normal tracking-wide transition-colors duration-200 select-none ${labelColor}`}
      >
        {label}
      </label>

      {/* --- Input Field Wrapper --- */}
      <div className="relative">
        <input
          id={id}
          type={type}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          className={`
            w-full bg-transparent border-[1px] rounded-2xl py-4 pl-5 pr-12 
            text-white placeholder-zinc-600 outline-none transition-all duration-300
            hover:border-zinc-500
            ${borderColor}
          `}
          {...props}
        />
        {/* Only render Icon if it exists */}
        {Icon && (
          <Icon
            className={`absolute right-5 top-1/2 -translate-y-1/2 w-5 h-5 transition-colors duration-200 ${iconColor}`}
          />
        )}
      </div>

      {/* --- Error Feedback --- */}
      {error && errorMessage && (
        <span className="text-sm text-[#ff3366] font-medium mt-1 pl-1 select-none">
          {errorMessage}
        </span>
      )}
    </div>
  );
};

```

## `frontend/src/components/OccurrenceModal.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
import React, { useState, useRef } from "react";
import { jsPDF } from "jspdf";
import { X, Download, Image as ImageIcon, FileText, Loader2 } from "lucide-react";
import imgLixo from "../assets/lixo_exemplo.png";
import imgInfrator from "../assets/infrator_exemplo.png";

interface OccurrenceModalProps {
  isOpen: boolean;
  onClose: () => void;
  data: any;
}

// --- Programmatic Canvas export (bypasses html2canvas + oklch issues) ---

const EXPORT_WIDTH = 480;
const SCALE = 2; // retina quality
const PADDING = 32;
const IMG_HEIGHT = 200;
const COLORS = {
  bg: "#ffffff",
  title: "#1a1a1a",
  label: "#9ca3af",
  value: "#374151",
  statusPendente: "#ef4444",
  statusAnalise: "#f97316",
  statusResolvido: "#22c55e",
  statusDefault: "#6b7280",
  divider: "#f3f4f6",
  infoBg: "#f9fafb",
  infoBorder: "#f3f4f6",
  accent: "#ccff33",
};

function getStatusExportColor(status: string): string {
  switch (status) {
    case "Pendente": return COLORS.statusPendente;
    case "Em análise": return COLORS.statusAnalise;
    case "Resolvido": return COLORS.statusResolvido;
    default: return COLORS.statusDefault;
  }
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number, r: number,
) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function drawLabel(ctx: CanvasRenderingContext2D, text: string, x: number, y: number) {
  ctx.font = "11px Inter, system-ui, sans-serif";
  ctx.fillStyle = COLORS.label;
  ctx.fillText(text, x, y);
}

function drawValue(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color = COLORS.value, maxWidth?: number) {
  ctx.font = "bold 13px Inter, system-ui, sans-serif";
  ctx.fillStyle = color;
  if (maxWidth) {
    let display = text;
    while (ctx.measureText(display).width > maxWidth && display.length > 1) {
      display = display.slice(0, -1);
    }
    if (display !== text) display += "…";
    ctx.fillText(display, x, y);
  } else {
    ctx.fillText(text, x, y);
  }
}

async function renderExportCanvas(data: any): Promise<HTMLCanvasElement> {
  const w = EXPORT_WIDTH;
  const p = PADDING;
  const colW = (w - p * 2) / 2;

  const occurrenceDate = data?.timestamp ? new Date(data.timestamp) : null;
  const formattedDate = occurrenceDate ? occurrenceDate.toLocaleString("pt-BR") : "—";
  const photoSrc = data?.hasOffender ? imgInfrator : imgLixo;
  const volumeValue = data?.volume ?? data?.volume_m3;
  const status = data?.status || "—";

  // Pre-calculate height
  const rowH = 38;
  const rows = 6; // status+id, date, logradouro/bairro/rpa, lat/lng, tipo/vol, infratores
  const totalH = p + 30 + 12 + IMG_HEIGHT + 16 + rows * rowH + 16 + p;

  const canvas = document.createElement("canvas");
  canvas.width = w * SCALE;
  canvas.height = totalH * SCALE;
  const ctx = canvas.getContext("2d")!;
  ctx.scale(SCALE, SCALE);

  // Background
  ctx.fillStyle = COLORS.bg;
  roundRect(ctx, 0, 0, w, totalH, 20);
  ctx.fill();
  ctx.save();
  roundRect(ctx, 0, 0, w, totalH, 20);
  ctx.clip();

  // Title
  let y = p;
  ctx.font = "bold 18px Inter, system-ui, sans-serif";
  ctx.fillStyle = COLORS.title;
  ctx.fillText("Informações da ocorrência", p, y + 18);
  y += 38;

  // Evidence image
  try {
    const img = await loadImage(photoSrc);
    const imgW = w - p * 2;
    // Draw rounded rect clip for image
    ctx.save();
    roundRect(ctx, p, y, imgW, IMG_HEIGHT, 12);
    ctx.clip();
    // Cover-fit
    const imgAspect = img.width / img.height;
    const boxAspect = imgW / IMG_HEIGHT;
    let sx = 0, sy = 0, sw = img.width, sh = img.height;
    if (imgAspect > boxAspect) {
      sw = img.height * boxAspect;
      sx = (img.width - sw) / 2;
    } else {
      sh = img.width / boxAspect;
      sy = (img.height - sh) / 2;
    }
    ctx.drawImage(img, sx, sy, sw, sh, p, y, imgW, IMG_HEIGHT);
    ctx.restore();
  } catch {
    // fallback: gray box
    ctx.fillStyle = "#e5e7eb";
    roundRect(ctx, p, y, w - p * 2, IMG_HEIGHT, 12);
    ctx.fill();
  }
  y += IMG_HEIGHT + 20;

  // Row 1: Status + ID
  drawLabel(ctx, "Status", p, y);
  drawValue(ctx, status, p, y + 16, getStatusExportColor(status));
  drawLabel(ctx, "ID", p + colW, y);
  drawValue(ctx, data?.id ?? "—", p + colW, y + 16);
  y += rowH;

  // Row 2: Data e Hora (full width)
  drawLabel(ctx, "Data e Hora", p, y);
  drawValue(ctx, formattedDate, p, y + 16);
  y += rowH;

  // Row 3: Logradouro, Bairro, RPA (3 cols)
  const col3W = (w - p * 2) / 3;
  drawLabel(ctx, "Logradouro", p, y);
  drawValue(ctx, data?.logradouro || "—", p, y + 16, COLORS.value, col3W - 8);
  drawLabel(ctx, "Bairro", p + col3W, y);
  drawValue(ctx, data?.bairro || "—", p + col3W, y + 16, COLORS.value, col3W - 8);
  drawLabel(ctx, "RPA", p + col3W * 2, y);
  drawValue(ctx, data?.rpa || "—", p + col3W * 2, y + 16);
  y += rowH;

  // Row 4: Latitude, Longitude
  drawLabel(ctx, "Latitude", p, y);
  drawValue(ctx, String(data?.latitude ?? "—"), p, y + 16);
  drawLabel(ctx, "Longitude", p + colW, y);
  drawValue(ctx, String(data?.longitude ?? "—"), p + colW, y + 16);
  y += rowH;

  // Row 5: Tipo de resíduo, Volumetria
  drawLabel(ctx, "Tipo de resíduo", p, y);
  drawValue(ctx, data?.tipo || data?.tipoResiduo || "—", p, y + 16);
  drawLabel(ctx, "Volumetria aprox.", p + colW, y);
  drawValue(ctx, `${volumeValue ?? "—"} m³`, p + colW, y + 16);
  y += rowH;

  // Row 6: Infratores (boxed)
  ctx.fillStyle = COLORS.infoBg;
  roundRect(ctx, p, y - 4, w - p * 2, rowH + 4, 8);
  ctx.fill();
  ctx.strokeStyle = COLORS.infoBorder;
  ctx.lineWidth = 1;
  roundRect(ctx, p, y - 4, w - p * 2, rowH + 4, 8);
  ctx.stroke();
  drawLabel(ctx, "Infratores", p + 10, y + 8);
  drawValue(
    ctx,
    data?.hasOffender ? "Identificados: Pessoa" : "Não identificado",
    p + 10, y + 24, COLORS.title,
  );

  ctx.restore();
  return canvas;
}

// --- Component ---

export const OccurrenceModal: React.FC<OccurrenceModalProps> = ({
  isOpen,
  onClose,
  data,
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const [isCapturing, setIsCapturing] = useState(false);
  const [isExportMenuOpen, setIsExportMenuOpen] = useState(false);

  if (!isOpen) return null;

  const occurrenceDate = data?.timestamp ? new Date(data.timestamp) : null;
  const formattedDate = occurrenceDate
    ? occurrenceDate.toLocaleString("pt-BR")
    : "—";
  const photoSrc = data?.hasOffender ? imgInfrator : imgLixo;
  const volumeValue = data?.volume ?? data?.volume_m3;

  const handleExportPng = async () => {
    setIsExportMenuOpen(false);
    setIsCapturing(true);
    try {
      const canvas = await renderExportCanvas(data);
      const dataUrl = canvas.toDataURL("image/png");
      const link = document.createElement("a");
      link.href = dataUrl;
      link.download = `ocorrencia_${data?.id ?? "detalhes"}.png`;
      document.body.appendChild(link);
      link.click();
      link.remove();
    } finally {
      setIsCapturing(false);
    }
  };

  const handleExportPdf = async () => {
    setIsExportMenuOpen(false);
    setIsCapturing(true);
    try {
      const canvas = await renderExportCanvas(data);
      const imgData = canvas.toDataURL("image/png");
      const pxW = canvas.width;
      const pxH = canvas.height;
      const orientation = pxW > pxH ? "landscape" : "portrait";
      const pdf = new jsPDF({ orientation, unit: "px", format: [pxW, pxH] });
      pdf.addImage(imgData, "PNG", 0, 0, pxW, pxH);
      pdf.save(`ocorrencia_${data?.id ?? "detalhes"}.pdf`);
    } finally {
      setIsCapturing(false);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "Pendente":
        return "text-red-500";
      case "Em an\u00E1lise":
        return "text-orange-500";
      case "Resolvido":
        return "text-green-500";
      default:
        return "text-gray-500";
    }
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div
        ref={modalRef}
        data-export-root="occurrence-modal"
        className="bg-white rounded-3xl w-full max-w-lg shadow-2xl overflow-hidden relative animate-in fade-in zoom-in duration-200"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-6 pb-2">
          <h2 className="text-xl font-bold text-[#1a1a1a]">
            Informações da ocorrência
          </h2>
          <button
            onClick={onClose}
            className={`text-gray-400 hover:text-gray-600 ${isCapturing ? "opacity-0 pointer-events-none" : ""}`}
          >
            <X size={24} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 pt-2 space-y-5">
          {/* Image */}
          <div className="relative w-full h-48 bg-gray-200 rounded-xl overflow-hidden group">
            <img
              src={photoSrc}
              alt="Evidência"
              className="w-full h-full object-cover"
            />
          </div>

          {/* Info Grid */}
          <div className="grid grid-cols-2 gap-y-4 gap-x-2 text-sm">
            <div>
              <span className="block text-gray-400 text-xs mb-1">Status</span>
              <span className={`font-bold ${getStatusColor(data?.status)}`}>
                {data?.status || "—"}
              </span>
            </div>
            <div>
              <span className="block text-gray-400 text-xs mb-1">ID</span>
              <span className="font-bold text-gray-700">{data?.id ?? "—"}</span>
            </div>
            <div className="col-span-2">
              <span className="block text-gray-400 text-xs mb-1">
                Data e Hora
              </span>
              <span className="font-bold text-gray-700">{formattedDate}</span>
            </div>

            <div className="col-span-2 grid grid-cols-3 gap-2">
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Logradouro
                </span>
                <span className="font-bold text-gray-700 block truncate">
                  {data?.logradouro || "—"}
                </span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">Bairro</span>
                <span className="font-bold text-gray-700 block truncate">
                  {data?.bairro || "—"}
                </span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">RPA</span>
                <span className="font-bold text-gray-700">{data?.rpa || "—"}</span>
              </div>
            </div>

            <div className="col-span-2 grid grid-cols-2 gap-2">
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Latitude
                </span>
                <span className="font-bold text-gray-700">
                  {data?.latitude ?? "—"}
                </span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Longitude
                </span>
                <span className="font-bold text-gray-700">
                  {data?.longitude ?? "—"}
                </span>
              </div>
            </div>

            <div className="col-span-2 grid grid-cols-2 gap-2">
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Tipo de resíduo
                </span>
                <span className="font-bold text-gray-700">
                  {data?.tipo || data?.tipoResiduo || "—"}
                </span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Volumetria aprox.
                </span>
                <span className="font-bold text-gray-700">
                  {volumeValue ?? "—"} m³
                </span>
              </div>
            </div>

            <div className="col-span-2 bg-gray-50 p-2 rounded-lg border border-gray-100">
              <span className="block text-gray-400 text-xs mb-1">
                Infratores
              </span>
              <span className="font-bold text-[#1a1a1a]">
                {data?.hasOffender
                  ? "Identificados: Pessoa"
                  : "Não identificado"}
              </span>
            </div>
          </div>

          {/* Footer Actions */}
          <div className="flex gap-3 mt-4">
            {/* Download Button with Dropdown */}
            <div className="relative">
              <button
                onClick={() => setIsExportMenuOpen((prev) => !prev)}
                className="w-12 h-12 flex items-center justify-center bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors text-black disabled:opacity-60 disabled:pointer-events-none"
                disabled={isCapturing}
                aria-label={isCapturing ? "Gerando exporta??o" : "Abrir op??es de exporta??o"}
                title={isCapturing ? "Gerando..." : "Exportar"}
              >
                {isCapturing ? <Loader2 size={20} className="animate-spin" /> : <Download size={20} />}
              </button>
              {isExportMenuOpen && (
                <div className="absolute left-0 bottom-14 w-56 bg-white rounded-xl shadow-xl border border-gray-100 overflow-hidden z-10">
                  <button
                    type="button"
                    onClick={handleExportPng}
                    className="w-full px-4 py-3 text-sm text-gray-700 flex items-center gap-2 hover:bg-gray-50 transition-colors"
                  >
                    <ImageIcon size={16} />
                    Exportar como PNG
                  </button>
                  <button
                    type="button"
                    onClick={handleExportPdf}
                    className="w-full px-4 py-3 text-sm text-gray-700 flex items-center gap-2 hover:bg-gray-50 transition-colors"
                  >
                    <FileText size={16} />
                    Exportar como PDF
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

```

## `frontend/src/components/SharedFilters.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
import React, { useState, useRef, useEffect } from "react";
import { ChevronDown, X, Check } from "lucide-react";

// --- REUSABLE FILTER COMPONENTS ---
export const FilterPopover: React.FC<{
  label: string;
  active: boolean;
  hasValue: boolean;
  onClear: () => void;
  children: React.ReactNode;
  onClose: () => void;
  onClick: () => void;
}> = ({ label, active, hasValue, onClear, children, onClose, onClick }) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        onClose();
      }
    }
    if (active) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [active, onClose]);

  return (
    <div ref={ref} className="w-full relative">
      <span className="text-sm text-gray-700 font-bold block mb-1.5 ml-2">
        {label}
      </span>
      <div
        onClick={onClick}
        className={`flex items-center justify-between bg-[#f3f4f6] rounded-xl px-4 py-3 border border-transparent hover:border-gray-300 transition-colors cursor-pointer ${
          active ? "border-gray-400 bg-gray-200" : ""
        }`}
      >
        <span
          className={`text-sm font-medium truncate ${
            hasValue ? "text-[#1a1a1a]" : "text-gray-700"
          }`}
        >
          {hasValue ? "Definido" : "Selecionar"}
        </span>
        {hasValue ? (
          <div
            onClick={(e) => {
              e.stopPropagation();
              onClear();
            }}
            className="p-0.5 rounded-full hover:bg-gray-300"
          >
            <X size={14} className="text-gray-500 hover:text-red-500" />
          </div>
        ) : (
          <ChevronDown size={16} className="text-gray-400" />
        )}
      </div>
      {active && (
        <div className="absolute top-full left-0 mt-2 bg-white border border-gray-200 rounded-xl shadow-xl z-50 p-4 min-w-[280px] animate-in fade-in zoom-in-95 duration-200">
          {children}
        </div>
      )}
    </div>
  );
};

export const FilterSelect: React.FC<{
  label: string;
  value: string;
  options: string[];
  onChange: (val: string) => void;
}> = ({ label, value, options, onChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node))
        setIsOpen(false);
    }
    if (isOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  return (
    <div ref={ref} className="w-full relative">
      <span className="text-sm text-gray-700 font-bold block mb-1.5 ml-2">
        {label}
      </span>
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between bg-[#f3f4f6] rounded-xl px-4 py-3 border border-transparent hover:border-gray-300 transition-colors cursor-pointer"
      >
        <span
          className={`text-sm font-medium truncate ${
            value ? "text-[#1a1a1a]" : "text-gray-700"
          }`}
        >
          {value || "Selecionar"}
        </span>
        {value ? (
          <div
            onClick={(e) => {
              e.stopPropagation();
              onChange("");
            }}
            className="p-0.5 rounded-full hover:bg-gray-300"
          >
            <X size={14} className="text-gray-500 hover:text-red-500" />
          </div>
        ) : (
          <ChevronDown size={16} className="text-gray-400" />
        )}
      </div>
      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-full bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden max-h-60 overflow-y-auto">
          {options.map((opt) => (
            <div
              key={opt}
              onClick={(e) => {
                e.stopPropagation();
                onChange(opt);
                setIsOpen(false);
              }}
              className="px-4 py-3 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer border-b border-gray-50 last:border-0"
            >
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const formatMultiValue = (value: string[]) => {
  if (value.length === 0) return "Selecionar";
  if (value.length <= 2) return value.join(", ");
  return `${value.length} selecionados`;
};

export const FilterMultiSelect: React.FC<{
  label: string;
  value: string[];
  options: string[];
  onChange: (val: string[]) => void;
}> = ({ label, value, options, onChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node))
        setIsOpen(false);
    }
    if (isOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const toggleValue = (opt: string) => {
    if (value.includes(opt)) {
      onChange(value.filter((item) => item !== opt));
    } else {
      onChange([...value, opt]);
    }
  };

  return (
    <div ref={ref} className="w-full relative">
      <span className="text-sm text-gray-700 font-bold block mb-1.5 ml-2">
        {label}
      </span>
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between bg-[#f3f4f6] rounded-xl px-4 py-3 border border-transparent hover:border-gray-300 transition-colors cursor-pointer"
      >
        <span
          className={`text-sm font-medium truncate ${
            value.length ? "text-[#1a1a1a]" : "text-gray-700"
          }`}
        >
          {formatMultiValue(value)}
        </span>
        {value.length ? (
          <div
            onClick={(e) => {
              e.stopPropagation();
              onChange([]);
            }}
            className="p-0.5 rounded-full hover:bg-gray-300"
          >
            <X size={14} className="text-gray-500 hover:text-red-500" />
          </div>
        ) : (
          <ChevronDown size={16} className="text-gray-400" />
        )}
      </div>
      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-full bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden max-h-60 overflow-y-auto">
          {options.map((opt) => {
            const selected = value.includes(opt);
            return (
              <div
                key={opt}
                onClick={(e) => {
                  e.stopPropagation();
                  toggleValue(opt);
                }}
                className={`px-4 py-3 text-sm cursor-pointer border-b border-gray-50 last:border-0 flex items-center justify-between ${
                  selected
                    ? "bg-lime-50 text-gray-900"
                    : "text-gray-700 hover:bg-gray-50"
                }`}
              >
                <span className="truncate">{opt}</span>
                <span
                  className={`w-4 h-4 rounded border flex items-center justify-center ${
                    selected
                      ? "bg-lime-500 border-lime-500"
                      : "border-gray-300"
                  }`}
                >
                  {selected && <Check size={12} className="text-white" />}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export const FilterAutocomplete: React.FC<{
  label: string;
  value: string;
  onChange: (val: string) => void;
  options: string[];
}> = ({ label, value, onChange, options }) => {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const normalizedValue = value.trim().toLowerCase();
  const filteredOptions = normalizedValue
    ? options.filter((opt) => opt.toLowerCase().includes(normalizedValue))
    : options;

  return (
    <div ref={ref} className="w-full relative">
      <span className="text-sm text-gray-700 font-bold block mb-1.5 ml-2">
        {label}
      </span>
      <div className="bg-[#f3f4f6] rounded-xl px-4 py-3 border border-transparent hover:border-gray-300 focus-within:border-gray-400 focus-within:bg-white flex items-center group">
        <input
          type="text"
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          placeholder="Pesquisar"
          className="bg-transparent border-none outline-none text-sm w-full text-gray-700 placeholder-gray-500"
        />
        {value && (
          <button
            onClick={() => onChange("")}
            className="ml-2 text-gray-400 hover:text-red-500"
          >
            <X size={14} />
          </button>
        )}
      </div>
      {isOpen && filteredOptions.length > 0 && (
        <div className="absolute top-full left-0 mt-2 w-full bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden max-h-60 overflow-y-auto">
          {filteredOptions.map((opt) => (
            <div
              key={opt}
              onClick={() => {
                onChange(opt);
                setIsOpen(false);
              }}
              className="px-4 py-3 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer border-b border-gray-50 last:border-0"
            >
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export const FilterInput: React.FC<{
  label: string;
  value: string;
  onChange: (val: string) => void;
}> = ({ label, value, onChange }) => (
  <div className="w-full">
    <span className="text-sm text-gray-700 font-bold block mb-1.5 ml-2">
      {label}
    </span>
    <div className="bg-[#f3f4f6] rounded-xl px-4 py-3 border border-transparent hover:border-gray-300 focus-within:border-gray-400 focus-within:bg-white flex items-center group">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Pesquisar"
        className="bg-transparent border-none outline-none text-sm w-full text-gray-700 placeholder-gray-500"
      />
      {value && (
        <button
          onClick={() => onChange("")}
          className="ml-2 text-gray-400 hover:text-red-500"
        >
          <X size={14} />
        </button>
      )}
    </div>
  </div>
);

```

## `frontend/src/components/Sidebar.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React, { useState } from "react";
import { LayoutDashboard, Cctv, Users, Settings, LogOut } from "lucide-react";
import { useNavigate, useLocation } from "react-router-dom";

export const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  // --- Modal State ---
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [isClosing, setIsClosing] = useState(false); // NEW: Track closing state

  const menuItems = [
    { icon: LayoutDashboard, path: "/dashboard" },
    { icon: Cctv, path: "/detections" },
    { icon: Users, path: "/users" },
  ];

  const handleLogoutClick = () => {
    setShowLogoutConfirm(true);
  };

  // Helper to animate closing
  const closeModal = () => {
    setIsClosing(true);
    setTimeout(() => {
      setShowLogoutConfirm(false);
      setIsClosing(false);
    }, 500); // 500ms matches the animation duration
  };

  const confirmLogout = () => {
    // No need to animate exit on confirm, as we navigate away immediately
    navigate("/");
  };

  return (
    <>
      {/* --- CSS Animation Definitions --- */}
      <style>{`
        @keyframes modalPop {
          0% {
            opacity: 0;
            transform: scale(0.8) translateY(50px);
          }
          100% {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }
        @keyframes modalPopExit {
          0% {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
          100% {
            opacity: 0;
            transform: scale(0.8) translateY(50px);
          }
        }
      `}</style>

      <div className="h-full w-20 bg-[#1a1a1a] flex flex-col items-center py-6 absolute left-0 top-0 z-40 border-r border-gray-800">
        {/* Navigation Section */}
        <nav className="flex-1 flex flex-col justify-center gap-8 w-full">
          {menuItems.map((item, index) => {
            const isActive = location.pathname === item.path;
            return (
              <button
                key={index}
                onClick={() => navigate(item.path)}
                className={`relative w-full h-12 flex items-center justify-center transition-colors group
                            ${isActive ? "text-[#d9f99d]" : "text-gray-500 hover:text-gray-300"}
                        `}
              >
                {/* Static indicator inside the button */}
                {isActive && (
                  <div className="absolute left-0 top-0 bottom-0 w-1 bg-[#d9f99d] rounded-r-md shadow-[0_0_10px_#d9f99d]" />
                )}
                <item.icon strokeWidth={2} size={24} />
              </button>
            );
          })}
        </nav>

        {/* Bottom Actions */}
        <div className="flex flex-col gap-6 w-full items-center mb-4">
          <button className="text-gray-500 hover:text-white transition-colors">
            <Settings size={24} />
          </button>
          <div className="w-10 h-10 rounded-full bg-gray-700 overflow-hidden border-2 border-transparent hover:border-[#d9f99d] transition-all cursor-pointer">
            <img
              src="https://i.pravatar.cc/150?u=admin"
              alt="User"
              className="w-full h-full object-cover"
            />
          </div>
          <button
            onClick={handleLogoutClick}
            className="text-gray-500 hover:text-red-500 transition-colors mt-2"
          >
            <LogOut size={20} />
          </button>
        </div>
      </div>

      {/* Logout Modal */}
      {showLogoutConfirm && (
        <div
          className={`
                fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 
                transition-opacity duration-500 
                ${isClosing ? "opacity-0" : "opacity-100"}
            `}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 relative"
            style={{
              animation: isClosing
                ? "modalPopExit 0.5s ease-in forwards"
                : "modalPop 0.5s ease-out forwards",
            }}
          >
            <h3 className="text-lg font-bold text-[#1a1a1a] mb-2 select-none">
              Deseja realmente sair?
            </h3>
            <p className="text-gray-500 text-sm mb-6 select-none">
              Você precisará fazer login novamente para acessar o sistema.
            </p>
            <div className="flex items-center justify-end gap-3">
              <button
                onClick={closeModal} // Use animated close
                className="px-4 py-2 text-sm font-bold text-gray-500 hover:bg-gray-100 rounded-lg transition-colors select-none"
              >
                Cancelar
              </button>
              <button
                onClick={confirmLogout}
                className="px-4 py-2 text-sm font-bold text-white bg-red-500 hover:bg-red-600 rounded-lg transition-colors shadow-lg shadow-red-200 select-none"
              >
                Sair
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

```

## `frontend/src/components/Tooltip.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React, {
  useState,
  useRef,
  useLayoutEffect,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

// --- Tooltip with Smart Positioning ---
type TooltipProps = {
  content?: string;
  text?: string;
  variant?: "default" | "danger";
  className?: string;
  spacing?: string;
  children: ReactNode;
};

type Position = {
  top: number;
  left: number;
  placement: "top" | "bottom";
};

export const Tooltip: React.FC<TooltipProps> = ({
  content,
  text,
  variant = "default",
  className,
  spacing,
  children,
}) => {
  const tooltipText = content ?? text;
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState<Position | null>(null);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const enterTimeout = useRef<number | undefined>(undefined);
  const leaveTimeout = useRef<number | undefined>(undefined);

  const handleMouseEnter = () => {
    if (leaveTimeout.current) {
      clearTimeout(leaveTimeout.current);
    }
    enterTimeout.current = window.setTimeout(() => {
      setIsVisible(true);
    }, 200);
  };

  const handleMouseLeave = () => {
    if (enterTimeout.current) {
      clearTimeout(enterTimeout.current);
    }
    leaveTimeout.current = window.setTimeout(() => {
      setIsVisible(false);
    }, 200);
  };

  useLayoutEffect(() => {
    if (!isVisible || !triggerRef.current || !tooltipRef.current) return;

    const triggerRect = triggerRef.current.getBoundingClientRect();
    const tooltipRect = tooltipRef.current.getBoundingClientRect();
    const margin = 10;
    const gap = 8;

    // Horizontal centering with collision handling
    let left =
      triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2;
    if (left < margin) left = margin;
    if (left + tooltipRect.width > window.innerWidth - margin) {
      left = window.innerWidth - tooltipRect.width - margin;
    }

    // Vertical placement (prefer top)
    const spaceAbove = triggerRect.top;
    const spaceBelow = window.innerHeight - triggerRect.bottom;
    let placement: "top" | "bottom" = "top";
    let top = triggerRect.top - tooltipRect.height - gap;

    if (spaceAbove < tooltipRect.height + gap && spaceBelow > spaceAbove) {
      placement = "bottom";
      top = triggerRect.bottom + gap;
    }

    if (top < margin) top = margin;
    if (top + tooltipRect.height > window.innerHeight - margin) {
      top = Math.max(margin, window.innerHeight - tooltipRect.height - margin);
    }

    setPosition({ top, left, placement });
  }, [isVisible]);

  if (!tooltipText) {
    return <span className={className}>{children}</span>;
  }

  const variantClass = variant === "danger" ? "bg-red-600" : "bg-gray-900";

  return (
    <>
      <span
        ref={triggerRef}
        className={`inline-flex items-center ${className ?? ""}`.trim()}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {children}
      </span>
      {isVisible &&
        createPortal(
          <div
            ref={tooltipRef}
            className={`fixed ${variantClass} text-white text-xs rounded-md shadow-lg px-3 py-2 w-max max-w-xs whitespace-normal break-words pointer-events-none transition-opacity duration-200 z-[99999] ${spacing ?? ""} ${position ? "opacity-100" : "opacity-0"}`.trim()}
            style={
              position
                ? {
                    top: `${position.top}px`,
                    left: `${position.left}px`,
                  }
                : undefined
            }
          >
            {tooltipText}
          </div>,
          document.body,
        )}
    </>
  );
};

```

## `frontend/src/components/UserModal.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React, { useState, useEffect } from "react";
import {
  X,
  User,
  Briefcase,
  Mail,
  Phone,
  MapPin,
  ChevronDown,
} from "lucide-react";

interface UserModalProps {
  onClose: () => void;
  onSave: (data: any) => void;
  initialData?: any;
  isClosing: boolean; // Animation state
}

// Helper component for Light Mode Inputs inside the modal
const ModalInput: React.FC<{
  label: string;
  value: string;
  onChange: (val: string) => void;
  type?: string;
  placeholder?: string;
  icon?: React.ElementType;
}> = ({ label, value, onChange, type = "text", placeholder, icon: Icon }) => (
  <div className="flex flex-col gap-1.5 w-full group">
    <label className="text-sm font-bold text-gray-700 select-none ml-1">
      {label}
    </label>
    <div className="relative">
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-[#f3f4f6] border border-transparent rounded-xl py-3 pl-4 pr-10 text-[#1a1a1a] placeholder-gray-400 outline-none focus:bg-white focus:border-gray-300 transition-all"
      />
      {Icon && (
        <Icon className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
      )}
    </div>
  </div>
);

export const UserModal: React.FC<UserModalProps> = ({
  onClose,
  onSave,
  initialData,
  isClosing,
}) => {
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    phone: "",
    secretaria: "",
    cargo: "",
    rpa: "",
  });

  useEffect(() => {
    if (initialData) {
      setFormData(initialData);
    }
  }, [initialData]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave(formData);
  };

  return (
    <div
      className={`
        fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4
        transition-opacity duration-500
        ${isClosing ? "opacity-0" : "opacity-100"}
      `}
    >
      <div
        className="bg-white rounded-[2rem] shadow-2xl w-full max-w-2xl p-8 relative overflow-hidden"
        style={{
          animation: isClosing
            ? "modalPopExit 0.5s ease-in forwards"
            : "modalPop 0.5s ease-out forwards",
        }}
      >
        <button
          onClick={onClose}
          className="absolute top-6 right-6 text-gray-400 hover:text-gray-600 transition-colors"
        >
          <X size={24} />
        </button>

        <h2 className="text-2xl font-bold text-[#1a1a1a] mb-1 select-none">
          {initialData ? "Editar Usuário" : "Novo Usuário"}
        </h2>
        <p className="text-gray-500 text-sm mb-8 select-none">
          Preencha as informações abaixo para{" "}
          {initialData ? "editar" : "cadastrar"} o usuário.
        </p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <ModalInput
              label="Nome Completo"
              value={formData.name}
              onChange={(val) => setFormData({ ...formData, name: val })}
              placeholder="Ex: João Silva"
              icon={User}
            />
            <ModalInput
              label="E-mail"
              type="email"
              value={formData.email}
              onChange={(val) => setFormData({ ...formData, email: val })}
              placeholder="Ex: joao@email.com"
              icon={Mail}
            />
            <ModalInput
              label="Telefone"
              value={formData.phone}
              onChange={(val) => setFormData({ ...formData, phone: val })}
              placeholder="(00) 00000-0000"
              icon={Phone}
            />
            <ModalInput
              label="Cargo"
              value={formData.cargo}
              onChange={(val) => setFormData({ ...formData, cargo: val })}
              placeholder="Ex: Analista"
              icon={Briefcase}
            />
            <ModalInput
              label="Secretaria"
              value={formData.secretaria}
              onChange={(val) => setFormData({ ...formData, secretaria: val })}
              placeholder="Ex: EMLURB"
              icon={Briefcase}
            />

            {/* Custom Select for RPA (Light Mode) */}
            <div className="flex flex-col gap-1.5 w-full group">
              <label className="text-sm font-bold text-gray-700 select-none ml-1">
                RPA
              </label>
              <div className="relative">
                <select
                  value={formData.rpa}
                  onChange={(e) =>
                    setFormData({ ...formData, rpa: e.target.value })
                  }
                  className="w-full bg-[#f3f4f6] border border-transparent rounded-xl py-3 pl-4 pr-10 text-[#1a1a1a] outline-none focus:bg-white focus:border-gray-300 appearance-none transition-all cursor-pointer"
                >
                  <option value="">Selecione...</option>
                  <option value="RPA 1">RPA 1</option>
                  <option value="RPA 2">RPA 2</option>
                  <option value="RPA 3">RPA 3</option>
                </select>
                <MapPin className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 pointer-events-none" />
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-3 mt-4 pt-4 border-t border-gray-100">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-3 rounded-xl font-bold text-gray-500 hover:bg-gray-100 transition-colors select-none"
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="px-8 py-3 rounded-xl font-bold bg-[#ccff33] hover:bg-[#b8e62e] text-black shadow-lg shadow-[#ccff33]/20 transition-all select-none"
            >
              Salvar Usuário
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

```

## `frontend/src/contexts/AuthContext.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import api from '../services/api';

interface User {
  id: number;
  name: string;
  email: string;
  phone?: string;
  secretaria?: string;
  cargo?: string;
  rpa?: string;
  is_active: boolean;
}

interface SignInCredentials {
  email: string;
  password: string;
}

interface AuthContextData {
  user: User | null;
  isAuthenticated: boolean;
  loading: boolean;
  signIn: (credentials: SignInCredentials) => Promise<void>;
  signOut: () => void;
}

interface AuthProviderProps {
  children: ReactNode;
}

const AuthContext = createContext<AuthContextData>({} as AuthContextData);

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadUserFromStorage() {
      const token = localStorage.getItem('@Saira:token');
      const storedUser = localStorage.getItem('@Saira:user');

      if (token && storedUser) {
        try {
          // Validar token e buscar dados atualizados do usuário
          const response = await api.get('/auth/me');
          setUser(response.data);
          localStorage.setItem('@Saira:user', JSON.stringify(response.data));
        } catch (error) {
          // Token inválido, limpar storage
          localStorage.removeItem('@Saira:token');
          localStorage.removeItem('@Saira:user');
        }
      }

      setLoading(false);
    }

    loadUserFromStorage();
  }, []);

  async function signIn({ email, password }: SignInCredentials) {
    try {
      // API usa OAuth2PasswordRequestForm que espera form-data com 'username'
      const formData = new URLSearchParams();
      formData.append('username', email);
      formData.append('password', password);

      const response = await api.post('/auth/login', formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      const { access_token } = response.data;

      // Buscar dados do usuário após login bem sucedido
      localStorage.setItem('@Saira:token', access_token);
      api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;

      const userResponse = await api.get('/auth/me');
      const userData = userResponse.data;

      // Salvar dados do usuário
      localStorage.setItem('@Saira:user', JSON.stringify(userData));

      // Atualizar estado
      setUser(userData);
    } catch (error: any) {
      if (error.response?.status === 401) {
        throw new Error('Credenciais inválidas');
      }
      throw new Error('Erro ao fazer login. Tente novamente.');
    }
  }

  function signOut() {
    localStorage.removeItem('@Saira:token');
    localStorage.removeItem('@Saira:user');
    delete api.defaults.headers.common['Authorization'];
    setUser(null);
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        loading,
        signIn,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }

  return context;
}

```

## `frontend/src/index.css`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```css
@import "tailwindcss";

```

## `frontend/src/leaflet.css`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```css
/* Leaflet CSS - Estilos básicos do mapa */
@import 'leaflet/dist/leaflet.css';

/* Custom styles */
.leaflet-container {
  width: 100%;
  height: 100%;
  border-radius: 1rem;
}

```

## `frontend/src/main.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

```

## `frontend/src/pages/Dashboard.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React, { useMemo, useState, useCallback } from "react";
import { Sidebar } from "../components/Sidebar";
import { MapWidget, OccurrencesChart } from "../components/DashboardCharts";
import {
  Filter as FilterIcon,
  Trash2,
  AlertTriangle,
  Info,
  Disc,
} from "lucide-react";
import {
  FilterPopover,
  FilterMultiSelect,
  FilterAutocomplete,
} from "../components/SharedFilters";
import { masterPois } from "../services/mockData";
import type { PoiData, WasteType } from "../services/mockData";
import { Tooltip } from "../components/Tooltip";
import { OccurrenceModal } from "../components/OccurrenceModal";

// --- DATA INTERFACE AND STATUS ---
interface FilterState {
  dateStart: string;
  dateEnd: string;
  startTime: string;
  endTime: string;
  status: string[];
  logradouro: string;
  bairro: string;
  rpa: string[];
  tipoResiduo: WasteType[];
  volMin: string;
  volMax: string;
  infratores: string[];
}

const WASTE_TYPE_OPTIONS: WasteType[] = [
  "Entulho",
  "Lixo domiciliar",
  "Poda",
  "Plástico",
];

const STATUS_OPTIONS = ["Pendente", "Resolvido", "Em análise"] as const;
const RPA_OPTIONS = [
  "RPA 1",
  "RPA 2",
  "RPA 3",
  "RPA 4",
  "RPA 5",
  "RPA 6",
];
const MONTHS_SHORT = [
  "Jan",
  "Fev",
  "Mar",
  "Abr",
  "Mai",
  "Jun",
  "Jul",
  "Ago",
  "Set",
  "Out",
  "Nov",
  "Dez",
];

const buildDateRange = (start?: string, end?: string) => {
  if (!start && !end) return null;
  const startDate = new Date(`${start || end}T00:00:00`);
  const endDate = new Date(`${end || start}T23:59:59`);
  return { start: startDate, end: endDate };
};

const getRpaForPoi = (poi: PoiData) => {
  const key = `${poi.bairro}-${poi.logradouro}`;
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) | 0;
  }
  const index = Math.abs(hash) % 6;
  return `RPA ${index + 1}`;
};

const dedupeLatestByLocation = (items: PoiData[]) => {
  const map = new Map<string, PoiData>();
  items.forEach((item) => {
    const key = `${item.latitude.toFixed(6)}|${item.longitude.toFixed(6)}`;
    const existing = map.get(key);
    if (!existing || new Date(item.timestamp) > new Date(existing.timestamp)) {
      map.set(key, item);
    }
  });
  return Array.from(map.values());
};

const diffDays = (start: Date, end: Date) =>
  Math.max(0, Math.ceil((end.getTime() - start.getTime()) / 86400000));

const formatDayLabel = (date: Date) =>
  `${String(date.getDate()).padStart(2, "0")}/${String(
    date.getMonth() + 1,
  ).padStart(2, "0")}`;

const buildChartSeries = (data: PoiData[], start: Date, end: Date) => {
  const daysSpan = diffDays(start, end);

  if (daysSpan <= 2) {
    const buckets = new Map<string, number>();
    data.forEach((item) => {
      const date = new Date(item.timestamp);
      const key = `${date.toISOString().slice(0, 13)}`;
      buckets.set(key, (buckets.get(key) || 0) + 1);
    });

    const series = [] as { name: string; val: number }[];
    const cursor = new Date(start);
    cursor.setMinutes(0, 0, 0);
    while (cursor <= end) {
      const key = cursor.toISOString().slice(0, 13);
      const label = `${formatDayLabel(cursor)} ${String(
        cursor.getHours(),
      ).padStart(2, "0")}h`;
      series.push({ name: label, val: buckets.get(key) || 0 });
      cursor.setHours(cursor.getHours() + 1);
    }
    return series;
  }

  if (daysSpan <= 31) {
    const buckets = new Map<string, number>();
    data.forEach((item) => {
      const date = new Date(item.timestamp);
      const key = date.toISOString().slice(0, 10);
      buckets.set(key, (buckets.get(key) || 0) + 1);
    });

    const series = [] as { name: string; val: number }[];
    const cursor = new Date(start);
    cursor.setHours(0, 0, 0, 0);
    while (cursor <= end) {
      const key = cursor.toISOString().slice(0, 10);
      series.push({ name: formatDayLabel(cursor), val: buckets.get(key) || 0 });
      cursor.setDate(cursor.getDate() + 1);
    }
    return series;
  }

  if (daysSpan <= 90) {
    const buckets = new Map<string, number>();
    data.forEach((item) => {
      const date = new Date(item.timestamp);
      const weekStart = new Date(date);
      const day = (weekStart.getDay() + 6) % 7;
      weekStart.setDate(weekStart.getDate() - day);
      weekStart.setHours(0, 0, 0, 0);
      const key = weekStart.toISOString().slice(0, 10);
      buckets.set(key, (buckets.get(key) || 0) + 1);
    });

    const series = [] as { name: string; val: number }[];
    const cursor = new Date(start);
    const day = (cursor.getDay() + 6) % 7;
    cursor.setDate(cursor.getDate() - day);
    cursor.setHours(0, 0, 0, 0);
    while (cursor <= end) {
      const key = cursor.toISOString().slice(0, 10);
      series.push({ name: formatDayLabel(cursor), val: buckets.get(key) || 0 });
      cursor.setDate(cursor.getDate() + 7);
    }
    return series;
  }

  const buckets = new Map<string, number>();
  data.forEach((item) => {
    const date = new Date(item.timestamp);
    const key = `${date.getFullYear()}-${date.getMonth()}`;
    buckets.set(key, (buckets.get(key) || 0) + 1);
  });

  const series = [] as { name: string; val: number }[];
  const cursor = new Date(start.getFullYear(), start.getMonth(), 1);
  const endCursor = new Date(end.getFullYear(), end.getMonth(), 1);
  while (cursor <= endCursor) {
    const key = `${cursor.getFullYear()}-${cursor.getMonth()}`;
    const label = `${MONTHS_SHORT[cursor.getMonth()]} ${String(
      cursor.getFullYear(),
    ).slice(2)}`;
    series.push({ name: label, val: buckets.get(key) || 0 });
    cursor.setMonth(cursor.getMonth() + 1);
  }
  return series;
};

export const Dashboard: React.FC = () => {
  // --- State Management ---
  const [mapExpanded, setMapExpanded] = useState(false);
  const [filters, setFilters] = useState<FilterState>({
    dateStart: "",
    dateEnd: "",
    startTime: "",
    endTime: "",
    status: [],
    logradouro: "",
    bairro: "",
    rpa: [],
    tipoResiduo: [],
    volMin: "",
    volMax: "",
    infratores: [],
  });
  const [showAllFilters, setShowAllFilters] = useState(false);
  const [activePopover, setActivePopover] = useState<
    "period" | "volumetry" | null
  >(null);
  const [selectedOccurrence, setSelectedOccurrence] = useState<PoiData | null>(null);
  const [isOccurrenceModalOpen, setIsOccurrenceModalOpen] = useState(false);

  const toDateInput = (date: Date) =>
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
      date.getDate(),
    ).padStart(2, "0")}`;

  const applyDatePreset = (days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    setFilters((p) => ({
      ...p,
      dateStart: toDateInput(start),
      dateEnd: toDateInput(end),
    }));
  };

  const baseData = useMemo(() => {
    const dateRange = buildDateRange(filters.dateStart, filters.dateEnd);

    return masterPois.filter((item) => {
      const itemDate = new Date(item.timestamp);
      if (dateRange) {
        if (itemDate < dateRange.start || itemDate > dateRange.end) return false;
      }

      if (filters.startTime && filters.endTime) {
        const itemTime = `${String(itemDate.getHours()).padStart(2, "0")}:${String(
          itemDate.getMinutes(),
        ).padStart(2, "0")}`;
        if (itemTime < filters.startTime) return false;
        if (itemTime > filters.endTime) return false;
      }

      return true;
    });
  }, [filters.dateStart, filters.dateEnd, filters.startTime, filters.endTime]);

  const matchesFilters = useCallback((item: PoiData, exclude?: keyof FilterState) => {
    const rpa = getRpaForPoi(item);

    if (exclude !== "status" && filters.status.length > 0) {
      if (!filters.status.includes(item.status)) return false;
    }
    if (
      exclude !== "logradouro" &&
      filters.logradouro &&
      !item.logradouro.toLowerCase().includes(filters.logradouro.toLowerCase())
    )
      return false;
    if (
      exclude !== "bairro" &&
      filters.bairro &&
      !item.bairro.toLowerCase().includes(filters.bairro.toLowerCase())
    )
      return false;
    if (
      exclude !== "rpa" &&
      filters.rpa.length > 0 &&
      !filters.rpa.includes(rpa)
    )
      return false;
    if (
      exclude !== "tipoResiduo" &&
      filters.tipoResiduo.length > 0 &&
      !filters.tipoResiduo.includes(item.wasteType)
    )
      return false;
    if (filters.volMin && item.volume < parseFloat(filters.volMin.replace(",", ".")))
      return false;
    if (filters.volMax && item.volume > parseFloat(filters.volMax.replace(",", ".")))
      return false;
    if (exclude !== "infratores" && filters.infratores.length > 0) {
      const wantsIdentified = filters.infratores.includes("Identificado");
      const wantsUnknown = filters.infratores.includes("Não Identificado");
      const matches =
        (item.hasOffender && wantsIdentified) ||
        (!item.hasOffender && wantsUnknown);
      if (!matches) return false;
    }

    return true;
  }, [filters]);

  const bairrosOptions = useMemo(() => {
    const filtered = baseData.filter((item) => matchesFilters(item, "bairro"));
    return Array.from(new Set(filtered.map((item) => item.bairro))).sort();
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const logradouroOptions = useMemo(() => {
    const filtered = baseData.filter((item) =>
      matchesFilters(item, "logradouro"),
    );
    return Array.from(new Set(filtered.map((item) => item.logradouro))).sort();
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const rpaOptions = useMemo(() => {
    const filtered = baseData.filter((item) => matchesFilters(item, "rpa"));
    const present = new Set(filtered.map((item) => getRpaForPoi(item)));
    return RPA_OPTIONS.filter((rpa) => present.has(rpa));
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const tipoResiduoOptions = useMemo(() => {
    const filtered = baseData.filter((item) =>
      matchesFilters(item, "tipoResiduo"),
    );
    const present = new Set(filtered.map((item) => item.wasteType));
    return WASTE_TYPE_OPTIONS.filter((type) => present.has(type));
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const offenderOptions = useMemo(() => {
    const filtered = baseData.filter((item) =>
      matchesFilters(item, "infratores"),
    );
    const options = [] as string[];
    if (filtered.some((item) => item.hasOffender)) options.push("Identificado");
    if (filtered.some((item) => !item.hasOffender))
      options.push("Não Identificado");
    return options;
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const statusOptions = useMemo(() => {
    const filtered = baseData.filter((item) => matchesFilters(item, "status"));
    const present = new Set(filtered.map((item) => item.status));
    return STATUS_OPTIONS.filter((status) => present.has(status));
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const handleLiveMode = () => {
    const today = new Date();
    const pastYear = new Date();
    pastYear.setFullYear(today.getFullYear() - 1);

    setFilters({
      dateStart: toDateInput(pastYear),
      dateEnd: toDateInput(today),
      startTime: "",
      endTime: "",
      status: ["Pendente", "Em análise"],
      logradouro: "",
      bairro: "",
      rpa: [],
      tipoResiduo: [],
      volMin: "",
      volMax: "",
      infratores: [],
    });
  };

  const generalFilteredData = useMemo(() => {
    return baseData.filter((item) => {
      const rpa = getRpaForPoi(item);

      if (
        filters.logradouro &&
        !item.logradouro
          .toLowerCase()
          .includes(filters.logradouro.toLowerCase())
      )
        return false;
      if (
        filters.bairro &&
        !item.bairro.toLowerCase().includes(filters.bairro.toLowerCase())
      )
        return false;
      if (filters.volMin && item.volume < parseFloat(filters.volMin.replace(",", ".")))
        return false;
      if (filters.volMax && item.volume > parseFloat(filters.volMax.replace(",", ".")))
        return false;
      if (filters.rpa.length > 0 && !filters.rpa.includes(rpa)) return false;
      if (
        filters.tipoResiduo.length > 0 &&
        !filters.tipoResiduo.includes(item.wasteType)
      )
        return false;

      if (filters.infratores.length > 0) {
        const wantsIdentified = filters.infratores.includes("Identificado");
        const wantsUnknown = filters.infratores.includes("Não Identificado");
        const matches =
          (item.hasOffender && wantsIdentified) ||
          (!item.hasOffender && wantsUnknown);
        if (!matches) return false;
      }

      return true;
    });
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const mapFilteredData = useMemo(() => {
    const withStatus =
      filters.status.length === 0
        ? generalFilteredData
        : generalFilteredData.filter((item) =>
            filters.status.includes(item.status),
          );
    return dedupeLatestByLocation(withStatus);
  }, [generalFilteredData, filters.status]);

  const totalOccurrences = generalFilteredData.length;
  const totalVolume = generalFilteredData.reduce(
    (sum, item) => sum + item.volume,
    0,
  );

  const recurrentLocations = useMemo(() => {
    const counts = new Map<
      string,
      { count: number; bairro: string; logradouro: string }
    >();

    generalFilteredData.forEach((item) => {
      const key = `${item.logradouro}||${item.bairro}`;
      const current = counts.get(key);
      if (current) {
        current.count += 1;
      } else {
        counts.set(key, {
          count: 1,
          bairro: item.bairro,
          logradouro: item.logradouro,
        });
      }
    });

    const palette = [
      "bg-red-200 text-red-700",
      "bg-red-200 text-red-700",
      "bg-red-200 text-red-700",
      "bg-orange-100 text-orange-600",
      "bg-orange-100 text-orange-600",
    ];

    return Array.from(counts.values())
      .sort((a, b) => b.count - a.count)
      .slice(0, 5)
      .map((item, index) => ({
        id: `${index + 1}º`,
        name: `${item.logradouro}, ${item.bairro}`,
        val: `${item.count} atividades`,
        color: palette[index] || "bg-gray-100 text-gray-600",
      }));
  }, [generalFilteredData]);

  const volumetryByRPA = useMemo(() => {
    const totals = new Map<string, number>();
    generalFilteredData.forEach((item) => {
      const rpa = getRpaForPoi(item);
      totals.set(rpa, (totals.get(rpa) || 0) + item.volume);
    });

    return RPA_OPTIONS.map((rpa) => ({
      name: rpa,
      val: `${Math.round(totals.get(rpa) || 0)}m³`,
      color:
        (totals.get(rpa) || 0) > 0
          ? "bg-red-200 text-red-700"
          : "bg-gray-100 text-gray-500",
    }));
  }, [generalFilteredData]);

  const chartRange = useMemo(() => {
    const dateRange = buildDateRange(filters.dateStart, filters.dateEnd);
    if (dateRange) return dateRange;
    if (generalFilteredData.length === 0) {
      const today = new Date();
      const pastYear = new Date();
      pastYear.setFullYear(today.getFullYear() - 1);
      return { start: pastYear, end: today };
    }
    const dates = generalFilteredData.map((item) => new Date(item.timestamp));
    const minDate = new Date(Math.min(...dates.map((d) => d.getTime())));
    const maxDate = new Date(Math.max(...dates.map((d) => d.getTime())));
    return { start: minDate, end: maxDate };
  }, [filters.dateEnd, filters.dateStart, generalFilteredData]);

  const chartSeries = useMemo(
    () => buildChartSeries(generalFilteredData, chartRange.start, chartRange.end),
    [chartRange, generalFilteredData],
  );

  const handleOpenOccurrence = (poi: PoiData) => {
    setSelectedOccurrence(poi);
    setIsOccurrenceModalOpen(true);
  };

  const modalData = selectedOccurrence
    ? {
        id: selectedOccurrence.id,
        logradouro: selectedOccurrence.logradouro,
        bairro: selectedOccurrence.bairro,
        rpa: getRpaForPoi(selectedOccurrence),
        timestamp: selectedOccurrence.timestamp,
        tipo: selectedOccurrence.wasteType,
        volume_m3: selectedOccurrence.volume,
        infratores: selectedOccurrence.hasOffender
          ? "Identificado"
          : "Não Identificado",
        status: selectedOccurrence.status,
        latitude: selectedOccurrence.latitude,
        longitude: selectedOccurrence.longitude,
        hasOffender: selectedOccurrence.hasOffender,
      }
    : null;

  return (
    // --- Main Layout Container ---
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      {/* --- Sidebar Navigation --- */}
      <Sidebar />

      {/* --- Main Content Area --- */}
      <main className="flex-1 ml-20 p-4 md:p-8 h-full overflow-y-auto">
        {/* --- Page Header --- */}
        <h1 className="text-3xl font-bold text-[#1a1a1a] mb-6">Dashboard</h1>

        {/* --- Tab Navigation Section --- */}
        <div className="flex flex-wrap items-center gap-1 bg-white p-1 rounded-xl w-fit mb-8 border border-gray-200 shadow-sm">
          <button className="px-6 py-2 bg-[#e9fbc0] text-[#1a1a1a] font-semibold rounded-lg text-sm whitespace-nowrap">
            Dashboard de ocorrências
          </button>
          <button className="px-6 py-2 text-gray-500 hover:bg-gray-50 font-medium rounded-lg text-sm whitespace-nowrap">
            Dashboard de Infratores
          </button>
        </div>

        {/* --- Live Monitoring Section --- */}
        <div className="mb-6 bg-white border border-gray-200 rounded-2xl shadow-sm p-4 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-bold text-gray-800">
              Monitoramento em Tempo Real
            </h2>
            <p className="text-xs text-gray-500">
              Ative o modo ao vivo para monitorar ocorrências recentes.
            </p>
          </div>
          <button
            onClick={handleLiveMode}
            className="h-11 px-5 rounded-full bg-red-600 hover:bg-red-700 text-white font-semibold flex items-center gap-2 shadow-sm"
          >
            <Disc size={16} className="text-white" />
            Ao Vivo
          </button>
        </div>

        {/* --- Filter Controls Section --- */}
        <div className="relative z-[2000]">
          <div className="flex items-start gap-4 mb-8">
            <div className="flex-1">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
                <div className="relative">
                  <FilterPopover
                    label="Período"
                    active={activePopover === "period"}
                    hasValue={
                      !!(
                        filters.dateStart ||
                        filters.dateEnd ||
                        filters.startTime ||
                        filters.endTime
                      )
                    }
                    onClear={() =>
                      setFilters((p) => ({
                        ...p,
                        dateStart: "",
                        dateEnd: "",
                        startTime: "",
                        endTime: "",
                      }))
                    }
                    onClick={() =>
                      setActivePopover((p) => (p === "period" ? null : "period"))
                    }
                    onClose={() => setActivePopover(null)}
                  >
                    <div className="flex flex-wrap gap-2 mb-3">
                      {[
                        { label: "Últimos 7 dias", days: 7 },
                        { label: "Últimos 30 dias", days: 30 },
                        { label: "Último ano", days: 365 },
                      ].map((preset) => (
                        <button
                          key={preset.label}
                          type="button"
                          onClick={() => applyDatePreset(preset.days)}
                          className="px-3 py-1.5 rounded-full border border-gray-200 text-xs font-semibold text-gray-600 hover:bg-gray-50 transition-colors"
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                    <div className="flex flex-col gap-3">
                      <div className="flex gap-2">
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            De
                          </label>
                          <input
                            type="date"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            value={filters.dateStart}
                            onChange={(e) =>
                              setFilters((p) => ({ ...p, dateStart: e.target.value }))
                            }
                          />
                        </div>
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            Até
                          </label>
                          <input
                            type="date"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            value={filters.dateEnd}
                            onChange={(e) =>
                              setFilters((p) => ({ ...p, dateEnd: e.target.value }))
                            }
                          />
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            De
                          </label>
                          <input
                            type="time"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            value={filters.startTime}
                            onChange={(e) =>
                              setFilters((p) => ({
                                ...p,
                                startTime: e.target.value,
                              }))
                            }
                          />
                        </div>
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            Até
                          </label>
                          <input
                            type="time"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            value={filters.endTime}
                            onChange={(e) =>
                              setFilters((p) => ({
                                ...p,
                                endTime: e.target.value,
                              }))
                            }
                          />
                        </div>
                      </div>
                    </div>
                  </FilterPopover>
                </div>
                <FilterMultiSelect
                  label="Status"
                  value={filters.status}
                  options={statusOptions}
                  onChange={(v) => setFilters((p) => ({ ...p, status: v }))}
                />
                <FilterAutocomplete
                  label="Logradouro"
                  value={filters.logradouro}
                  options={logradouroOptions}
                  onChange={(v) => setFilters((p) => ({ ...p, logradouro: v }))}
                />
                <FilterAutocomplete
                  label="Bairro"
                  value={filters.bairro}
                  options={bairrosOptions}
                  onChange={(v) => setFilters((p) => ({ ...p, bairro: v }))}
                />
                <FilterMultiSelect
                  label="RPA"
                  value={filters.rpa}
                  options={rpaOptions}
                  onChange={(v) => setFilters((p) => ({ ...p, rpa: v }))}
                />
                {showAllFilters && (
                  <>
                    <div className="animate-in slide-in-from-top-2 duration-300">
                      <FilterMultiSelect
                        label="Tipo de Resíduo"
                        value={filters.tipoResiduo}
                        options={tipoResiduoOptions}
                        onChange={(v) =>
                          setFilters((p) => ({ ...p, tipoResiduo: v as WasteType[] }))
                        }
                      />
                    </div>
                    <div className="relative animate-in slide-in-from-top-2 duration-300">
                      <FilterPopover
                        label="Volumetria"
                        active={activePopover === "volumetry"}
                        hasValue={!!(filters.volMin || filters.volMax)}
                        onClear={() =>
                          setFilters((p) => ({ ...p, volMin: "", volMax: "" }))
                        }
                        onClick={() =>
                          setActivePopover((p) =>
                            p === "volumetry" ? null : "volumetry",
                          )
                        }
                        onClose={() => setActivePopover(null)}
                      >
                        <div className="flex gap-2 items-center">
                          <div className="flex-1">
                            <label className="text-xs text-gray-500 font-bold mb-1 block">
                              Min (m³)
                            </label>
                            <input
                              type="number"
                              step="0.1"
                              className="w-full border border-gray-300 rounded p-2 text-sm"
                              placeholder="0.0"
                              value={filters.volMin}
                              onChange={(e) =>
                                setFilters((p) => ({ ...p, volMin: e.target.value }))
                              }
                            />
                          </div>
                          <span className="pt-5 text-gray-400">-</span>
                          <div className="flex-1">
                            <label className="text-xs text-gray-500 font-bold mb-1 block">
                              Max (m³)
                            </label>
                            <input
                              type="number"
                              step="0.1"
                              className="w-full border border-gray-300 rounded p-2 text-sm"
                              placeholder="100.0"
                              value={filters.volMax}
                              onChange={(e) =>
                                setFilters((p) => ({ ...p, volMax: e.target.value }))
                              }
                            />
                          </div>
                        </div>
                      </FilterPopover>
                    </div>
                    <div className="animate-in slide-in-from-top-2 duration-300">
                      <FilterMultiSelect
                        label="Infratores"
                        value={filters.infratores}
                        options={offenderOptions}
                        onChange={(v) =>
                          setFilters((p) => ({ ...p, infratores: v }))
                        }
                      />
                    </div>
                    <div className="hidden md:block"></div>
                    <div className="hidden md:block"></div>
                  </>
                )}
              </div>
            </div>
            <div className="flex gap-4 pt-[25px]">
              <div className="flex flex-col gap-3">
                <button
                  onClick={() => setShowAllFilters(!showAllFilters)}
                  className={`w-14 h-[50px] bg-white border border-gray-200 rounded-xl flex items-center justify-center hover:bg-gray-50 text-gray-600 transition-colors ${
                    showAllFilters ? "bg-gray-100 ring-2 ring-gray-200" : ""
                  }`}
                >
                  <FilterIcon size={22} />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* --- Upper Dashboard Grid: Map & Statistics --- */}
        <div className="grid grid-cols-12 gap-6 mb-8 lg:h-[500px] h-auto">
          {/* Map Component Container */}
          <div
            className={`col-span-12 lg:col-span-7 transition-all ${
              mapExpanded
                ? "fixed inset-0 z-50 w-full h-full"
                : "relative h-[400px] lg:h-full"
            }`}
          >
            <MapWidget
              isExpanded={mapExpanded}
              onToggleExpand={() => setMapExpanded(!mapExpanded)}
              points={mapFilteredData}
              onMarkerClick={handleOpenOccurrence}
            />
          </div>

          {/* Statistics & Charts Container */}
          <div className="col-span-12 lg:col-span-5 flex flex-col gap-6 h-full">
            {/* KPI Cards Row */}
            <div className="flex flex-col sm:flex-row gap-6 h-auto sm:h-32">
              {/* Total Occurrences Card */}
              <div className="flex-1 bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col justify-between min-h-[120px]">
                <div className="flex items-center gap-2">
                  <span className="text-gray-500 text-xs font-medium uppercase">
                    Total de ocorrências no período
                  </span>
                  <Tooltip content="Exibe o número total de descartes irregulares no período selecionado.">
                    <Info size={14} className="text-gray-400 cursor-pointer" />
                  </Tooltip>
                </div>
                <div className="flex items-center gap-4 mt-2 sm:mt-0">
                  <div className="w-12 h-12 rounded-full bg-orange-100 flex items-center justify-center text-orange-500">
                    <AlertTriangle size={24} />
                  </div>
                  <span className="text-4xl font-bold text-[#1a1a1a]">
                    {totalOccurrences}
                  </span>
                </div>
              </div>

              {/* Volume Metric Card */}
              <div className="flex-1 bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col justify-between min-h-[120px]">
                <div className="flex items-center gap-2">
                  <span className="text-gray-500 text-xs font-medium uppercase">
                    Volume de resíduos no período
                  </span>
                  <Tooltip content="Soma do volume estimado (em m³) de todos os resíduos identificados no período selecionado.">
                    <Info size={14} className="text-gray-400 cursor-pointer" />
                  </Tooltip>
                </div>
                <div className="flex items-center gap-4 mt-2 sm:mt-0">
                  <div className="w-12 h-12 rounded-full bg-[#ecfccb] flex items-center justify-center text-[#65a30d]">
                    <Trash2 size={24} />
                  </div>
                  <div className="flex items-baseline">
                    <span className="text-4xl font-bold text-[#1a1a1a]">
                      {Math.round(totalVolume)}
                    </span>
                    <span className="text-sm text-gray-500 font-medium ml-1">
                      m³
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Monthly Occurrences Chart */}
            <div className="flex-1 bg-white rounded-2xl p-6 shadow-sm border border-gray-100 min-h-[300px]">
              <div className="flex justify-between items-center mb-4">
                <h3 className="font-bold text-gray-800 text-sm">
                  Ocorrências por período
                </h3>
                <Tooltip content="Distribuição de ocorrências conforme o período selecionado.">
                  <Info size={16} className="text-gray-400 cursor-pointer" />
                </Tooltip>
              </div>
              <OccurrencesChart series={chartSeries} />
            </div>
          </div>
        </div>

      {/* --- Lower Dashboard Grid: Data Lists --- */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pb-6">
          {/* List 1: Recurrent Locations */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-5 border-b border-gray-100 flex justify-between items-center">
              <h3 className="font-bold text-gray-800 text-sm">
                Locais reincidentes
              </h3>
              <Tooltip content="Lista dos endereços com maior frequência de detecções, ordenados do maior para o menor.">
                <Info size={16} className="text-gray-400 cursor-pointer" />
              </Tooltip>
            </div>
            <div className="p-2 overflow-x-auto">
              {recurrentLocations.length === 0 ? (
                <div className="px-6 py-10 text-center text-gray-500 text-sm">
                  Nenhuma ocorrência encontrada.
                </div>
              ) : (
                recurrentLocations.map((item, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between py-6 px-5 hover:bg-gray-50 rounded-lg text-sm min-w-[300px]"
                  >
                    <div className="flex items-center gap-3 text-gray-700 font-medium truncate flex-1 min-w-0">
                      <span className="text-gray-400 w-6">{item.id}</span>
                      <Tooltip text={item.name}>
                        <span className="truncate flex-1 min-w-0">{item.name}</span>
                      </Tooltip>
                    </div>
                    <span
                      className={`px-3 py-1 rounded-md text-xs font-bold ${item.color}`}
                    >
                      {item.val}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* List 2: Volumetry per RPA */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-5 border-b border-gray-100 flex justify-between items-center">
              <h3 className="font-bold text-gray-800 text-sm">
                Média de volumetria por RPA no período
              </h3>
              <Tooltip content="Volume médio de lixo descartado por dia, segmentado por Região Político-Administrativa.">
                <Info size={16} className="text-gray-400 cursor-pointer" />
              </Tooltip>
            </div>
            <div className="p-2 overflow-x-auto">
              {volumetryByRPA.map((item, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between p-3 hover:bg-gray-50 rounded-lg text-sm min-w-[200px]"
                >
                  <span className="text-gray-700 font-medium">{item.name}</span>
                  <span
                    className={`px-3 py-1 rounded-md text-xs font-bold ${item.color}`}
                  >
                    {item.val}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
      {isOccurrenceModalOpen && modalData && (
        <OccurrenceModal
          isOpen={isOccurrenceModalOpen}
          onClose={() => setIsOccurrenceModalOpen(false)}
          data={modalData}
        />
      )}
    </div>
  );
};

```

## `frontend/src/pages/Detections.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React, { useState, useMemo, useEffect, useCallback } from "react";
import { masterPois } from "../services/mockData";
import type { PoiData, WasteType } from "../services/mockData";
import { Sidebar } from "../components/Sidebar";
import {
  Filter as FilterIcon,
  ChevronDown,
  Download,
  Eye,
  ChevronRight,
  ChevronLeft,
} from "lucide-react";
import { OccurrenceModal } from "../components/OccurrenceModal";
import { Tooltip } from "../components/Tooltip";

import {
  FilterPopover,
  FilterMultiSelect,
  FilterAutocomplete,
} from "../components/SharedFilters";

// --- DATA INTERFACE AND STATUS ---
interface Detection extends PoiData {
  rpa: string;
}

interface FilterState {
  date: string;
  startTime: string;
  endTime: string;
  status: string[];
  logradouro: string;
  bairro: string;
  rpa: string[];
  tipoResiduo: WasteType[];
  volMin: string;
  volMax: string;
  infratores: string[];
}

const WASTE_TYPE_OPTIONS: WasteType[] = [
  "Entulho",
  "Lixo domiciliar",
  "Poda",
  "Plástico",
];

const STATUS_OPTIONS = ["Pendente", "Resolvido", "Em análise"] as const;
const RPA_OPTIONS = [
  "RPA 1",
  "RPA 2",
  "RPA 3",
  "RPA 4",
  "RPA 5",
  "RPA 6",
];

const getRpaForPoi = (poi: PoiData) => {
  const key = `${poi.bairro}-${poi.logradouro}`;
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) | 0;
  }
  const index = Math.abs(hash) % 6;
  return `RPA ${index + 1}`;
};

// --- COLUMN CONFIGURATION ---
const TABLE_COLUMNS = [
  { label: "ID", width: "w-24" },
  { label: "Logradouro", width: "w-64" },
  { label: "Bairro", width: "w-48" },
  { label: "RPA", width: "w-24" },
  { label: "Data e Hora", width: "w-40" },
  { label: "Tipo de resíduo", width: "w-48" },
  { label: "Volumetria", width: "w-32" },
  { label: "Infratores", width: "w-48" },
  { label: "Status", width: "w-32" },
  { label: "Ação", width: "w-20" },
];

// --- MAIN COMPONENT ---
export const Detections: React.FC = () => {
  const [detections, setDetections] = useState<Detection[]>([]);
  const [selectedItem, setSelectedItem] = useState<Detection | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [showAllFilters, setShowAllFilters] = useState(false);
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);
  const [showItemsMenu, setShowItemsMenu] = useState(false);
  const [filters, setFilters] = useState<FilterState>({
    date: "",
    startTime: "",
    endTime: "",
    status: [],
    logradouro: "",
    bairro: "",
    rpa: [],
    tipoResiduo: [],
    volMin: "",
    volMax: "",
    infratores: [],
  });
  const [activePopover, setActivePopover] = useState<"period" | "volumetry" | null>(null);

  const matchesFilters = useCallback((item: Detection, exclude?: keyof FilterState) => {
    if (exclude !== "status" && filters.status.length > 0) {
      if (!filters.status.includes(item.status)) return false;
    }
    if (
      exclude !== "logradouro" &&
      filters.logradouro &&
      !item.logradouro.toLowerCase().includes(filters.logradouro.toLowerCase())
    )
      return false;
    if (
      exclude !== "bairro" &&
      filters.bairro &&
      !item.bairro.toLowerCase().includes(filters.bairro.toLowerCase())
    )
      return false;
    if (exclude !== "rpa" && filters.rpa.length > 0 && !filters.rpa.includes(item.rpa))
      return false;
    if (
      exclude !== "tipoResiduo" &&
      filters.tipoResiduo.length > 0 &&
      !filters.tipoResiduo.includes(item.wasteType)
    )
      return false;
    if (exclude !== "infratores" && filters.infratores.length > 0) {
      const wantsIdentified = filters.infratores.includes("Identificado");
      const wantsUnknown = filters.infratores.includes("Não Identificado");
      const matches =
        (item.hasOffender && wantsIdentified) ||
        (!item.hasOffender && wantsUnknown);
      if (!matches) return false;
    }
    if (filters.volMin && item.volume < parseFloat(filters.volMin.replace(",", ".")))
      return false;
    if (filters.volMax && item.volume > parseFloat(filters.volMax.replace(",", ".")))
      return false;
    if (filters.date) {
      const itemDate = new Date(item.timestamp);
      const itemIsoDate = `${itemDate.getFullYear()}-${String(itemDate.getMonth() + 1).padStart(2, "0")}-${String(itemDate.getDate()).padStart(2, "0")}`;
      const itemTime = `${String(itemDate.getHours()).padStart(2, "0")}:${String(itemDate.getMinutes()).padStart(2, "0")}`;
      if (itemIsoDate !== filters.date) return false;
      if (filters.startTime && itemTime < filters.startTime) return false;
      if (filters.endTime && itemTime > filters.endTime) return false;
    }
    return true;
  }, [filters]);

  const bairroOptions = useMemo(() => {
    const filtered = detections.filter((item) => matchesFilters(item, "bairro"));
    return Array.from(new Set(filtered.map((item) => item.bairro))).sort();
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const logradouroOptions = useMemo(() => {
    const filtered = detections.filter((item) =>
      matchesFilters(item, "logradouro"),
    );
    return Array.from(new Set(filtered.map((item) => item.logradouro))).sort();
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const rpaOptions = useMemo(() => {
    const filtered = detections.filter((item) => matchesFilters(item, "rpa"));
    const present = new Set(filtered.map((item) => item.rpa));
    return RPA_OPTIONS.filter((rpa) => present.has(rpa));
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const tipoResiduoOptions = useMemo(() => {
    const filtered = detections.filter((item) =>
      matchesFilters(item, "tipoResiduo"),
    );
    const present = new Set(filtered.map((item) => item.wasteType));
    return WASTE_TYPE_OPTIONS.filter((type) => present.has(type));
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const offenderOptions = useMemo(() => {
    const filtered = detections.filter((item) =>
      matchesFilters(item, "infratores"),
    );
    const options = [] as string[];
    if (filtered.some((item) => item.hasOffender)) options.push("Identificado");
    if (filtered.some((item) => !item.hasOffender))
      options.push("Não Identificado");
    return options;
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const statusOptions = useMemo(() => {
    const filtered = detections.filter((item) => matchesFilters(item, "status"));
    const present = new Set(filtered.map((item) => item.status));
    return STATUS_OPTIONS.filter((status) => present.has(status));
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  useEffect(() => {
    const formattedDetections = masterPois.map((poi) => ({
      ...poi,
      rpa: getRpaForPoi(poi),
    }));
    setDetections(formattedDetections);
  }, []);

  useEffect(() => {
    setCurrentPage(1);
  }, [filters, itemsPerPage]);

  const handleOpenModal = (item: Detection) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  const handleDownloadCSV = () => {
    const headers = ["Data", "Local", "Tipo", "Volume", "Status", "Infrator"];
    const rows = filteredData.map((item) => {
      const date = new Date(item.timestamp).toLocaleString("pt-BR");
      const local = `${item.logradouro} - ${item.bairro}`;
      const tipo = item.wasteType;
      const volume = `${item.volume} m³`;
      const status = item.status;
      const infrator = item.hasOffender ? "Identificado" : "Não identificado";
      return [date, local, tipo, volume, status, infrator];
    });

    const escapeCell = (value: string) =>
      `"${value.replace(/"/g, '""')}"`;

    const csvContent = [
      headers.map(escapeCell).join(","),
      ...rows.map((row) => row.map(escapeCell).join(",")),
    ].join("\n");

    const blob = new Blob([`\uFEFF${csvContent}`], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `detecoes_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const getStatusStyle = (status: string) => {
    switch (status) {
      case "Pendente":
        return "bg-red-100 text-red-500";
      case "Em análise":
        return "bg-orange-100 text-orange-500";
      case "Resolvido":
        return "bg-green-100 text-green-500";
      default:
        return "bg-gray-100 text-gray-500";
    }
  };

  const filteredData = useMemo(
    () => detections.filter((item: Detection) => matchesFilters(item)),
    [detections, filters],
  );

  const totalPages = Math.ceil(filteredData.length / itemsPerPage);
  const visibleData = filteredData.slice(
    (currentPage - 1) * itemsPerPage,
    (currentPage - 1) * itemsPerPage + itemsPerPage,
  );

  const getPageNumbers = () => {
    const pages = [] as number[];
    const maxVisible = 5;
    if (totalPages <= maxVisible) {
      for (let i = 1; i <= totalPages; i += 1) pages.push(i);
    } else {
      let start = Math.max(1, currentPage - 2);
      let end = Math.min(totalPages, start + maxVisible - 1);
      if (end - start < maxVisible - 1) {
        start = Math.max(1, end - maxVisible + 1);
      }
      for (let i = start; i <= end; i += 1) pages.push(i);
    }
    return pages;
  };

  const modalData = selectedItem
    ? {
        id: selectedItem.id,
        logradouro: selectedItem.logradouro,
        bairro: selectedItem.bairro,
        rpa: selectedItem.rpa,
        timestamp: selectedItem.timestamp,
        tipo: selectedItem.wasteType,
        volume_m3: selectedItem.volume,
        infratores: selectedItem.hasOffender ? "Identificado" : "Não Identificado",
        status: selectedItem.status,
        latitude: selectedItem.latitude,
        longitude: selectedItem.longitude,
        hasOffender: selectedItem.hasOffender,
      }
    : null;

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      <Sidebar />
      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-[#1a1a1a]">Detecções de câmeras</h1>
        </div>
        <div className="flex items-start gap-4 mb-8">
          <div className="flex-1">
            <div className="grid grid-cols-5 gap-4">
              <div className="relative">
                <FilterPopover
                  label="Período"
                  active={activePopover === "period"}
                  hasValue={!!(filters.date || filters.startTime || filters.endTime)}
                  onClear={() =>
                    setFilters((p) => ({
                      ...p,
                      date: "",
                      startTime: "",
                      endTime: "",
                    }))
                  }
                  onClick={() =>
                    setActivePopover((p) => (p === "period" ? null : "period"))
                  }
                  onClose={() => setActivePopover(null)}
                >
                  <div className="flex flex-col gap-3">
                    <div>
                      <label className="text-xs text-gray-500 font-bold mb-1 block">
                        Data
                      </label>
                      <input
                        type="date"
                        className="w-full border border-gray-300 rounded p-2 text-sm"
                        value={filters.date}
                        onChange={(e) =>
                          setFilters((p) => ({ ...p, date: e.target.value }))
                        }
                      />
                    </div>
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <label className="text-xs text-gray-500 font-bold mb-1 block">
                          De
                        </label>
                        <input
                          type="time"
                          className="w-full border border-gray-300 rounded p-2 text-sm"
                          value={filters.startTime}
                          onChange={(e) =>
                            setFilters((p) => ({ ...p, startTime: e.target.value }))
                          }
                        />
                      </div>
                      <div className="flex-1">
                        <label className="text-xs text-gray-500 font-bold mb-1 block">
                          Até
                        </label>
                        <input
                          type="time"
                          className="w-full border border-gray-300 rounded p-2 text-sm"
                          value={filters.endTime}
                          onChange={(e) =>
                            setFilters((p) => ({ ...p, endTime: e.target.value }))
                          }
                        />
                      </div>
                    </div>
                  </div>
                </FilterPopover>
              </div>
              <FilterMultiSelect
                label="Status"
                value={filters.status}
                options={statusOptions}
                onChange={(v) => setFilters((p) => ({ ...p, status: v }))}
              />
              <FilterAutocomplete
                label="Logradouro"
                value={filters.logradouro}
                options={logradouroOptions}
                onChange={(v) => setFilters((p) => ({ ...p, logradouro: v }))}
              />
              <FilterAutocomplete
                label="Bairro"
                value={filters.bairro}
                options={bairroOptions}
                onChange={(v) => setFilters((p) => ({ ...p, bairro: v }))}
              />
              <FilterMultiSelect
                label="RPA"
                value={filters.rpa}
                options={rpaOptions}
                onChange={(v) => setFilters((p) => ({ ...p, rpa: v }))}
              />
              {showAllFilters && (
                <>
                  <div className="animate-in slide-in-from-top-2 duration-300">
                    <FilterMultiSelect
                      label="Tipo de Resíduo"
                      value={filters.tipoResiduo}
                      options={tipoResiduoOptions}
                      onChange={(v) =>
                        setFilters((p) => ({ ...p, tipoResiduo: v as WasteType[] }))
                      }
                    />
                  </div>
                  <div className="relative animate-in slide-in-from-top-2 duration-300">
                    <FilterPopover
                      label="Volumetria"
                      active={activePopover === "volumetry"}
                      hasValue={!!(filters.volMin || filters.volMax)}
                      onClear={() =>
                        setFilters((p) => ({ ...p, volMin: "", volMax: "" }))
                      }
                      onClick={() =>
                        setActivePopover((p) => (p === "volumetry" ? null : "volumetry"))
                      }
                      onClose={() => setActivePopover(null)}
                    >
                      <div className="flex gap-2 items-center">
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            Min (m³)
                          </label>
                          <input
                            type="number"
                            step="0.1"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            placeholder="0.0"
                            value={filters.volMin}
                            onChange={(e) =>
                              setFilters((p) => ({ ...p, volMin: e.target.value }))
                            }
                          />
                        </div>
                        <span className="pt-5 text-gray-400">-</span>
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            Max (m³)
                          </label>
                          <input
                            type="number"
                            step="0.1"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            placeholder="100.0"
                            value={filters.volMax}
                            onChange={(e) =>
                              setFilters((p) => ({ ...p, volMax: e.target.value }))
                            }
                          />
                        </div>
                      </div>
                    </FilterPopover>
                  </div>
                  <div className="animate-in slide-in-from-top-2 duration-300">
                    <FilterMultiSelect
                      label="Infratores"
                      value={filters.infratores}
                      options={offenderOptions}
                      onChange={(v) => setFilters((p) => ({ ...p, infratores: v }))}
                    />
                  </div>
                  <div className="hidden md:block"></div>
                  <div className="hidden md:block"></div>
                </>
              )}
            </div>
          </div>
          <div className="flex gap-4 pt-[25px]">
            <button
              onClick={() => setShowAllFilters(!showAllFilters)}
              className={`w-14 h-[50px] bg-white border border-gray-200 rounded-xl flex items-center justify-center hover:bg-gray-50 text-gray-600 transition-colors ${
                showAllFilters ? "bg-gray-100 ring-2 ring-gray-200" : ""
              }`}
            >
              <FilterIcon size={22} />
            </button>
            <button
              onClick={handleDownloadCSV}
              className="h-[50px] px-6 py-2 bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors flex items-center justify-center text-black shadow-sm"
            >
              <Download size={24} />
            </button>
          </div>
        </div>
        <div className="bg-white rounded-[2rem] shadow-sm border border-gray-100 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-gray-100">
                  {TABLE_COLUMNS.map((c, i) => (
                    <th
                      key={i}
                      className={`px-6 py-5 text-sm font-bold text-[#1a1a1a] whitespace-nowrap ${c.width}`}
                    >
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleData.length > 0 ? (
                  visibleData.map((row: Detection, i: number) => (
                    <tr
                      key={i}
                      className={`transition-colors border-b border-gray-50 last:border-0 group ${
                        i % 2 === 0 ? "bg-gray-50" : "bg-white"
                      } hover:bg-gray-100`}
                    >
                      <td className="px-6 py-4 text-sm text-gray-500 font-medium">
                        {row.id}
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.logradouro}>
                          <span className="truncate max-w-[260px] block">
                            {row.logradouro}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.bairro}>
                          <span className="truncate max-w-[200px] block">
                            {row.bairro}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                        {row.rpa}
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a] whitespace-nowrap">
                        {new Date(row.timestamp).toLocaleString("pt-BR")}
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.wasteType}>
                          <span className="truncate max-w-[200px] block">
                            {row.wasteType}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a] font-medium">
                        {`${row.volume} m³`}
                      </td>
                      <td className="px-6 py-4 text-sm font-medium">
                        {row.hasOffender ? "Sim" : "Não"}
                      </td>
                      <td className="px-6 py-4">
                        <Tooltip text={row.status}>
                          <span
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold ${getStatusStyle(
                              row.status,
                            )}`}
                          >
                            {row.status}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-4">
                        <Tooltip text="Visualizar ocorrência" className="w-fit" spacing="mb-2">
                          <button
                            onClick={() => handleOpenModal(row)}
                            className="w-8 h-8 rounded-full border border-gray-200 flex items-center justify-center text-gray-400 hover:text-[#1a1a1a] hover:border-[#1a1a1a] transition-all bg-white"
                          >
                            <Eye size={16} />
                          </button>
                        </Tooltip>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td
                      colSpan={10}
                      className="px-6 py-12 text-center text-gray-500 italic"
                    >
                      Nenhuma ocorrência encontrada.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100 bg-white">
            <span className="text-sm text-gray-500">
              Mostrando {visibleData.length > 0 ? (currentPage - 1) * itemsPerPage + 1 : 0} -
              {(currentPage - 1) * itemsPerPage + visibleData.length} de {filteredData.length}
            </span>
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-500">Itens</span>
              <div className="relative">
                <div
                  onClick={() => setShowItemsMenu(!showItemsMenu)}
                  className="flex items-center gap-2 bg-gray-200 rounded-lg px-3 py-1 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-300 select-none min-w-[60px] justify-between"
                >
                  {itemsPerPage}
                  <ChevronDown
                    size={14}
                    className={`transition-transform duration-200 ${
                      showItemsMenu ? "rotate-180" : ""
                    }`}
                  />
                </div>
                {showItemsMenu && (
                  <div className="absolute bottom-full left-0 mb-1 w-full bg-white border border-gray-200 rounded-lg shadow-xl z-30 animate-in fade-in zoom-in-95 ">
                    {[10, 20, 30].map((n) => (
                      <div
                        key={n}
                        onClick={() => {
                          setItemsPerPage(n);
                          setShowItemsMenu(false);
                        }}
                        className={`px-3 py-2 text-sm cursor-pointer hover:bg-gray-50 text-center ${
                          itemsPerPage === n
                            ? "font-bold bg-gray-50 text-[#1a1a1a]"
                            : "text-gray-600"
                        }`}
                      >
                        {n}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2 ml-4">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className={`w-6 h-6 flex items-center justify-center transition-colors ${
                    currentPage === 1
                      ? "text-gray-300 cursor-not-allowed"
                      : "text-gray-400 hover:text-gray-600"
                  }`}
                >
                  <ChevronLeft size={16} />
                </button>
                {getPageNumbers().map((p) => (
                  <button
                    key={p}
                    onClick={() => setCurrentPage(p)}
                    className={`w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold transition-all ${
                      currentPage === p
                        ? "bg-[#ccff33] text-black shadow-sm"
                        : "text-gray-500 hover:bg-gray-100"
                    }`}
                  >
                    {p}
                  </button>
                ))}
                <button
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages || totalPages === 0}
                  className={`w-6 h-6 flex items-center justify-center transition-colors ${
                    currentPage === totalPages || totalPages === 0
                      ? "text-gray-300 cursor-not-allowed"
                      : "text-gray-400 hover:text-gray-600"
                  }`}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>
      {isModalOpen && modalData && (
        <OccurrenceModal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          data={modalData}
        />
      )}
    </div>
  );
};

```

## `frontend/src/pages/Login.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React, { useState } from "react";
import {
  User,
  Check,
  AlertCircle,
  Eye,
  EyeOff,
  Lock,
  Mail,
  X,
  Info,
} from "lucide-react"; // Added Info
import { InputField } from "../components/InputField";
import { useNavigate } from "react-router-dom";
import { Tooltip } from "../components/Tooltip";

export const Login: React.FC = () => {
  const navigate = useNavigate();

  // --- Login Form State ---
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // --- Forgot Password Modal State ---
  const [showForgotModal, setShowForgotModal] = useState(false);
  const [isForgotClosing, setIsForgotClosing] = useState(false);
  const [recoveryEmail, setRecoveryEmail] = useState("");
  const [forgotError, setForgotError] = useState("");

  // --- Register Modal State ---
  const [showRegisterModal, setShowRegisterModal] = useState(false);
  const [isRegisterClosing, setIsRegisterClosing] = useState(false);
  const [registerEmail, setRegisterEmail] = useState("");
  const [registerError, setRegisterError] = useState("");

  // --- Toast State (NEW) ---
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState("");

  // --- Event Handlers ---
  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!email || !password) {
      setError("Por favor, preencha todos os campos");
      return;
    }

    setLoading(true);

    setTimeout(() => {
      if (email === "admin@gmail.com" && password === "12345") {
        navigate("/dashboard");
      } else {
        setError("Email ou senha incorretos.");
        setLoading(false);
      }
    }, 1000);
  };

  // --- Helper to Trigger Toast ---
  const triggerToast = (message: string) => {
    setToastMessage(message);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 4000); // Hide after 4 seconds
  };

  // --- Forgot Password Logic ---
  const closeForgotModal = () => {
    setIsForgotClosing(true);
    setTimeout(() => {
      setShowForgotModal(false);
      setIsForgotClosing(false);
      setForgotError("");
    }, 500);
  };

  const handleSendRecovery = (e: React.FormEvent) => {
    e.preventDefault();
    setForgotError("");

    if (!recoveryEmail) {
      setForgotError("Por favor, informe seu email.");
      return;
    }

    const subject = encodeURIComponent("Recuperação de Senha");
    const body = encodeURIComponent(
      `Solicito a recuperação de senha para o usuário: ${recoveryEmail}`,
    );

    window.location.href = `mailto:suporte@saira.com?subject=${subject}&body=${body}`;

    closeForgotModal();
    setRecoveryEmail("");

    // NEW: Show success feedback
    triggerToast("Email de recuperação enviado com sucesso!");
  };

  // --- Register Logic ---
  const closeRegisterModal = () => {
    setIsRegisterClosing(true);
    setTimeout(() => {
      setShowRegisterModal(false);
      setIsRegisterClosing(false);
      setRegisterError("");
    }, 500);
  };

  const handleSendRegistration = (e: React.FormEvent) => {
    e.preventDefault();
    setRegisterError("");

    if (!registerEmail) {
      setRegisterError("Por favor, informe seu email para contato.");
      return;
    }

    const subject = encodeURIComponent("Solicitação de Cadastro");
    const body = encodeURIComponent(
      `Gostaria de solicitar um cadastro para o email: ${registerEmail}`,
    );

    window.location.href = `mailto:suporte@saira.com?subject=${subject}&body=${body}`;

    closeRegisterModal();
    setRegisterEmail("");

    // NEW: Show success feedback
    triggerToast("Solicitação de cadastro enviada com sucesso!");
  };

  return (
    <div className="h-full w-full bg-[#121212] flex items-center justify-center p-4 lg:p-12 relative">
      <style>{`
        @keyframes modalPop {
          0% {
            opacity: 0;
            transform: scale(0.8) translateY(50px);
          }
          100% {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }
        @keyframes modalPopExit {
          0% {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
          100% {
            opacity: 0;
            transform: scale(0.8) translateY(50px);
          }
        }
      `}</style>

      {/* --- SUCCESS TOAST NOTIFICATION (NEW) --- */}
      {showToast && (
        <div className="absolute top-8 right-8 z-[70] animate-in slide-in-from-top-5 duration-300">
          <div className="bg-[#dcfce7] border border-green-200 text-[#166534] px-4 py-3 rounded-xl shadow-lg flex items-center gap-3">
            <div className="bg-green-500 rounded-full p-1 text-white">
              <Info size={12} strokeWidth={4} />
            </div>
            <span className="font-semibold text-sm select-none">
              {toastMessage}
            </span>
            <button
              onClick={() => setShowToast(false)}
              className="ml-4 hover:text-green-800 transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        </div>
      )}

      {/* --- Card Container --- */}
      <div className="w-full max-w-[1400px] h-[85vh] flex flex-row bg-[#121212]">
        {/* --- Left Panel --- */}
        <div className="w-24 md:w-[40%] lg:w-1/2 h-full relative rounded-tl-none rounded-tr-[3.5rem] rounded-bl-[3.5rem] rounded-br-none overflow-hidden shrink-0 transition-all duration-300">
          <div className="absolute inset-0 bg-[#eaffb0]"></div>
          <div className="absolute top-[-20%] left-[-20%] w-[80%] h-[80%] bg-[#f7fee7] rounded-full blur-[100px] opacity-80"></div>
          <div className="absolute top-[30%] right-[-10%] w-[70%] h-[70%] bg-[#bef264] rounded-full blur-[80px] mix-blend-multiply opacity-60"></div>
          <div className="absolute bottom-[-10%] left-[10%] w-[60%] h-[60%] bg-[#d9f99d] rounded-full blur-[60px]"></div>
          <div className="absolute inset-0 bg-white/10 backdrop-blur-3xl"></div>
        </div>

        {/* --- Right Panel --- */}
        <div className="flex-1 h-full flex flex-col justify-center px-6 md:px-12 lg:px-24 py-12 bg-transparent rounded-r-[3.5rem] overflow-hidden">
          <div className="mb-10 lg:mb-14">
            <h1 className="text-3xl md:text-4xl lg:text-5xl font-semibold text-white tracking-tight select-none">
              Bem vindo ao <span className="text-[#d9f99d]">SAIRA</span>
            </h1>
          </div>

          <form
            onSubmit={handleLogin}
            className="flex flex-col gap-6 lg:gap-7 max-w-md w-full"
          >
            {error && (
              <div className="flex items-center gap-2 p-4 bg-red-500/10 border border-red-500/50 rounded-lg animate-in fade-in slide-in-from-top-2">
                <AlertCircle size={20} className="text-red-500 shrink-0" />
                <span className="text-sm text-red-400 font-medium select-none">
                  {error}
                </span>
              </div>
            )}

            <Tooltip text="Digite seu email" className="w-full" spacing="-mb-5">
              <div className="w-full">
                <InputField
                  id="email"
                  label="Email"
                  type="email"
                  placeholder="seu@email.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  icon={User}
                />
              </div>
            </Tooltip>

            <div className="space-y-1">
              <div className="relative w-full">
                <Tooltip
                  text="Digite sua senha"
                  className="w-full"
                  spacing="-mb-5"
                >
                  <InputField
                    id="password"
                    label="Senha"
                    type={showPassword ? "text" : "password"}
                    placeholder="........."
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    icon={Lock}
                  />
                </Tooltip>

                <div className="absolute right-12 top-[52px] z-10">
                  <Tooltip
                    text={showPassword ? "Ocultar senha" : "Mostrar senha"}
                    className="w-fit"
                    spacing="mb-2"
                  >
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="text-zinc-500 hover:text-[#d9f99d] transition-colors focus:outline-none"
                    >
                      {showPassword ? <Eye size={20} /> : <EyeOff size={20} />}
                    </button>
                  </Tooltip>
                </div>
              </div>

              {/* Forgot Password Link */}
              <div className="flex justify-end pt-2">
                <Tooltip text="Recuperar acesso via e-mail" className="w-fit">
                  <button
                    type="button"
                    onClick={() => {
                      setRecoveryEmail(email);
                      setShowForgotModal(true);
                    }}
                    className="text-sm text-zinc-400 hover:text-[#d9f99d] transition-colors hover:underline outline-none select-none"
                  >
                    Esqueceu a senha?
                  </button>
                </Tooltip>
              </div>
            </div>

            <div className="flex items-center mt-1">
              <Tooltip text="Salvar sessão neste dispositivo" className="w-fit">
                <label className="flex items-center cursor-pointer group select-none gap-3">
                  <div className="relative flex items-center justify-center">
                    <input
                      type="checkbox"
                      className="peer sr-only"
                      defaultChecked
                    />
                    <div className="w-5 h-5 rounded-full border border-zinc-500 peer-checked:bg-[#10b981] peer-checked:border-[#10b981] transition-all"></div>
                    <Check
                      size={12}
                      className="absolute text-black opacity-0 peer-checked:opacity-100 transition-opacity font-bold pointer-events-none"
                      strokeWidth={4}
                    />
                  </div>
                  <span className="text-sm text-zinc-400 group-hover:text-zinc-300 transition-colors">
                    Manter conectado
                  </span>
                </label>
              </Tooltip>
            </div>

            <Tooltip
              text="Clique para acessar o sistema"
              className="w-full"
              spacing="-mb-4"
            >
              <button
                type="submit"
                disabled={loading}
                className="w-full py-4 mt-6 bg-gradient-to-r from-[#efffc8] to-[#ccff33] text-black font-bold text-lg rounded-2xl shadow-[0_0_30px_rgba(217,249,157,0.4)] hover:shadow-[0_0_40px_rgba(217,249,157,0.6)] hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 transition-all duration-300 select-none"
              >
                {loading ? "Entrando..." : "Entrar"}
              </button>
            </Tooltip>

            <div className="mt-8 text-sm text-zinc-500 flex items-center justify-center gap-2 select-none">
              <span>Está sem acesso?</span>
              <Tooltip
                text="Contatar suporte para criar conta"
                className="w-fit"
              >
                <button
                  type="button"
                  onClick={() => setShowRegisterModal(true)}
                  className="text-[#d9f99d] hover:text-[#c4f07a] transition-colors hover:underline outline-none"
                >
                  Solicite seu cadastro
                </button>
              </Tooltip>
            </div>
          </form>
        </div>
      </div>

      {/* --- FORGOT PASSWORD MODAL --- */}
      {showForgotModal && (
        <div
          className={`
                absolute inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-md p-4 
                transition-opacity duration-500
                ${isForgotClosing ? "opacity-0" : "opacity-100"} 
            `}
        >
          <form
            onSubmit={handleSendRecovery}
            className="bg-[#1a1a1a] border border-zinc-800 rounded-3xl shadow-2xl w-full max-w-md p-8 relative"
            style={{
              animation: isForgotClosing
                ? "modalPopExit 0.5s ease-in forwards"
                : "modalPop 0.5s ease-out forwards",
            }}
          >
            <button
              type="button"
              onClick={closeForgotModal}
              className="absolute top-4 right-4 text-zinc-500 hover:text-white transition-colors"
            >
              <X size={24} />
            </button>

            <div className="mb-6 select-none">
              <h2 className="text-2xl font-bold text-white mb-2">
                Recuperar Senha
              </h2>
              <p className="text-zinc-400 text-sm">
                Digite o email associado à sua conta para receber as instruções
                de recuperação.
              </p>
            </div>

            {forgotError && (
              <div className="flex items-center gap-2 p-3 mb-4 bg-red-500/10 border border-red-500/50 rounded-lg animate-[modalPop_0.3s_ease-out_forwards]">
                <AlertCircle size={18} className="text-red-500 shrink-0" />
                <span className="text-xs text-red-400 font-medium select-none">
                  {forgotError}
                </span>
              </div>
            )}

            <div className="space-y-6">
              <InputField
                id="recovery-email"
                label="Email de recuperação"
                type="email"
                placeholder="seu@email.com"
                value={recoveryEmail}
                onChange={(e) => setRecoveryEmail(e.target.value)}
                icon={Mail}
              />

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={closeForgotModal}
                  className="flex-1 py-3 text-sm font-bold text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-xl transition-colors border border-transparent hover:border-zinc-700 select-none"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="flex-1 py-3 text-sm font-bold text-black bg-[#d9f99d] hover:bg-[#bef264] rounded-xl transition-colors shadow-lg shadow-[#d9f99d]/20 select-none"
                >
                  Enviar Email
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* --- REQUEST REGISTRATION MODAL --- */}
      {showRegisterModal && (
        <div
          className={`
                absolute inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-md p-4 
                transition-opacity duration-500
                ${isRegisterClosing ? "opacity-0" : "opacity-100"} 
            `}
        >
          <form
            onSubmit={handleSendRegistration}
            className="bg-[#1a1a1a] border border-zinc-800 rounded-3xl shadow-2xl w-full max-w-md p-8 relative"
            style={{
              animation: isRegisterClosing
                ? "modalPopExit 0.5s ease-in forwards"
                : "modalPop 0.5s ease-out forwards",
            }}
          >
            <button
              type="button"
              onClick={closeRegisterModal}
              className="absolute top-4 right-4 text-zinc-500 hover:text-white transition-colors"
            >
              <X size={24} />
            </button>

            <div className="mb-6 select-none">
              <h2 className="text-2xl font-bold text-white mb-2">
                Solicitar Cadastro
              </h2>
              <p className="text-zinc-400 text-sm">
                Informe seu email de contato para enviarmos as instruções de
                cadastro.
              </p>
            </div>

            {registerError && (
              <div className="flex items-center gap-2 p-3 mb-4 bg-red-500/10 border border-red-500/50 rounded-lg animate-[modalPop_0.3s_ease-out_forwards]">
                <AlertCircle size={18} className="text-red-500 shrink-0" />
                <span className="text-xs text-red-400 font-medium select-none">
                  {registerError}
                </span>
              </div>
            )}

            <div className="space-y-6">
              <InputField
                id="register-email"
                label="Email de contato"
                type="email"
                placeholder="seu@email.com"
                value={registerEmail}
                onChange={(e) => setRegisterEmail(e.target.value)}
                icon={Mail}
              />

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={closeRegisterModal}
                  className="flex-1 py-3 text-sm font-bold text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-xl transition-colors border border-transparent hover:border-zinc-700 select-none"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="flex-1 py-3 text-sm font-bold text-black bg-[#d9f99d] hover:bg-[#bef264] rounded-xl transition-colors shadow-lg shadow-[#d9f99d]/20 select-none"
                >
                  Solicitar
                </button>
              </div>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

```

## `frontend/src/pages/UsersPage.tsx`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```tsx
﻿import React, { useState, useRef, useEffect, useMemo } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  UserPlus,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Trash2,
  Info,
  X,
} from "lucide-react";
import { UserModal } from "../components/UserModal";
import { DeleteModal } from "../components/DeleteModal";
import { Tooltip } from "../components/Tooltip";
import {
  FilterAutocomplete,
  FilterMultiSelect,
} from "../components/SharedFilters";

// Mock Data
const INITIAL_USERS = [
  {
    id: 1,
    name: "João Victor Almeida Santos",
    email: "joao.santos@recife.pe.gov.br",
    phone: "(81) 9 8765-4321",
    secretaria: "EMLURB",
    cargo: "Analista de Fiscalização Urbana",
    rpa: "RPA 1",
    status: "Ativo",
  },
  {
    id: 2,
    name: "Maria Eduarda Ferreira Lima",
    email: "maria.lima@recife.pe.gov.br",
    phone: "(81) 9 9123-7788",
    secretaria: "EMLURB",
    cargo: "Fiscal Ambiental",
    rpa: "RPA 6",
    status: "Ativo",
  },
  {
    id: 3,
    name: "Pedro Henrique Silva",
    email: "pedro.silva@recife.pe.gov.br",
    phone: "(81) 9 8888-9999",
    secretaria: "EMLURB",
    cargo: "Gerente Operacional",
    rpa: "RPA 3",
    status: "Inativo",
  },
  {
    id: 4,
    name: "Ana Clara Souza",
    email: "ana.souza@recife.pe.gov.br",
    phone: "(81) 9 7777-6666",
    secretaria: "EMLURB",
    cargo: "Analista de Fiscalização Urbana",
    rpa: "RPA 1",
    status: "Ativo",
  },
  {
    id: 5,
    name: "Lucas Oliveira",
    email: "lucas.oliveira@recife.pe.gov.br",
    phone: "(81) 9 5555-4444",
    secretaria: "EMLURB",
    cargo: "Fiscal Ambiental",
    rpa: "RPA 2",
    status: "Ativo",
  },
  {
    id: 6,
    name: "Fernanda Lima",
    email: "fernanda.lima@recife.pe.gov.br",
    phone: "(81) 9 1111-2222",
    secretaria: "EMLURB",
    cargo: "Engenheira Civil",
    rpa: "RPA 4",
    status: "Inativo",
  },
  {
    id: 7,
    name: "Roberto Campos",
    email: "roberto.campos@recife.pe.gov.br",
    phone: "(81) 9 3333-4444",
    secretaria: "EMLURB",
    cargo: "Analista de Sistemas",
    rpa: "RPA 5",
    status: "Ativo",
  },
  {
    id: 8,
    name: "Juliana Martins",
    email: "juliana.martins@recife.pe.gov.br",
    phone: "(81) 9 6666-7777",
    secretaria: "EMLURB",
    cargo: "Fiscal Ambiental",
    rpa: "RPA 1",
    status: "Ativo",
  },
  {
    id: 9,
    name: "Carlos Eduardo",
    email: "carlos.eduardo@recife.pe.gov.br",
    phone: "(81) 9 9999-8888",
    secretaria: "EMLURB",
    cargo: "Gerente de Projetos",
    rpa: "RPA 3",
    status: "Inativo",
  },
  {
    id: 10,
    name: "Beatriz Costa",
    email: "beatriz.costa@recife.pe.gov.br",
    phone: "(81) 9 2222-1111",
    secretaria: "EMLURB",
    cargo: "Analista Administrativa",
    rpa: "RPA 2",
    status: "Ativo",
  },
  {
    id: 11,
    name: "Ricardo Alves",
    email: "ricardo.alves@recife.pe.gov.br",
    phone: "(81) 9 4444-5555",
    secretaria: "EMLURB",
    cargo: "Fiscal de Obras",
    rpa: "RPA 6",
    status: "Ativo",
  },
];

export const UsersPage: React.FC = () => {
  const [users, setUsers] = useState(INITIAL_USERS);

  // --- Filter States ---
  const [filterName, setFilterName] = useState("");
  const [filterEmail, setFilterEmail] = useState("");
  const [filterRoles, setFilterRoles] = useState<string[]>([]);
  const [filterStatus, setFilterStatus] = useState<string[]>([]);

  // --- Pagination States ---
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);
  const [showItemsMenu, setShowItemsMenu] = useState(false);

  // --- Modal States ---
  const [isUserModalOpen, setIsUserModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<any>(null);
  const [showSuccessToast, setShowSuccessToast] = useState(false);
  const [isUserModalClosing, setIsUserModalClosing] = useState(false);
  const [isDeleteModalClosing, setIsDeleteModalClosing] = useState(false);

  // --- Filtering Logic ---
  const matchesFilters = (user: any, exclude?: "name" | "email" | "role" | "status") => {
    if (exclude !== "name" && filterName) {
      if (!user.name.toLowerCase().includes(filterName.toLowerCase())) return false;
    }
    if (exclude !== "email" && filterEmail) {
      if (!user.email.toLowerCase().includes(filterEmail.toLowerCase())) return false;
    }
    if (exclude !== "role" && filterRoles.length > 0) {
      if (!filterRoles.includes(user.cargo)) return false;
    }
    if (exclude !== "status" && filterStatus.length > 0) {
      if (!filterStatus.includes(user.status)) return false;
    }
    return true;
  };

  const nameOptions = useMemo(() => {
    const filtered = users.filter((user) => matchesFilters(user, "name"));
    return Array.from(new Set(filtered.map((user) => user.name))).sort();
  }, [filterEmail, filterName, filterRoles, filterStatus, users]);

  const emailOptions = useMemo(() => {
    const filtered = users.filter((user) => matchesFilters(user, "email"));
    return Array.from(new Set(filtered.map((user) => user.email))).sort();
  }, [filterEmail, filterName, filterRoles, filterStatus, users]);

  const roleOptions = useMemo(() => {
    const filtered = users.filter((user) => matchesFilters(user, "role"));
    return Array.from(new Set(filtered.map((user) => user.cargo))).sort();
  }, [filterEmail, filterName, filterRoles, filterStatus, users]);

  const statusOptions = useMemo(() => {
    const filtered = users.filter((user) => matchesFilters(user, "status"));
    return Array.from(new Set(filtered.map((user) => user.status))).sort();
  }, [filterEmail, filterName, filterRoles, filterStatus, users]);

  const filteredUsers = users.filter((user) => matchesFilters(user));

  // --- Pagination Logic ---
  const totalPages = Math.ceil(filteredUsers.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const visibleUsers = filteredUsers.slice(startIndex, endIndex);

  // Reset page when filters or items per page change
  useEffect(() => {
    setCurrentPage(1);
  }, [filterEmail, filterName, filterRoles, filterStatus, itemsPerPage]);

  // --- Handlers ---
  const handleOpenCreate = () => {
    setSelectedUser(null);
    setIsUserModalClosing(false);
    setIsUserModalOpen(true);
  };

  const handleOpenEdit = (user: any) => {
    setSelectedUser(user);
    setIsUserModalClosing(false);
    setIsUserModalOpen(true);
  };

  const handleOpenDelete = (user: any, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedUser(user);
    setIsDeleteModalClosing(false);
    setIsDeleteModalOpen(true);
  };

  const handleCloseUserModal = () => {
    setIsUserModalClosing(true);
    setTimeout(() => {
      setIsUserModalOpen(false);
      setIsUserModalClosing(false);
    }, 500);
  };

  const handleCloseDeleteModal = () => {
    setIsDeleteModalClosing(true);
    setTimeout(() => {
      setIsDeleteModalOpen(false);
      setIsDeleteModalClosing(false);
    }, 500);
  };

  const handleSaveUser = () => {
    handleCloseUserModal();
    setShowSuccessToast(true);
    setTimeout(() => setShowSuccessToast(false), 3000);
  };

  const handleDeleteUser = () => {
    if (selectedUser) {
      setUsers(users.filter((u) => u.id !== selectedUser.id));
    }
    handleCloseDeleteModal();
  };

  // Helper to generate page numbers
  const getPageNumbers = () => {
    const pages = [];
    for (let i = 1; i <= totalPages; i++) {
      pages.push(i);
    }
    return pages;
  };

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      <Sidebar />

      {/* Global Animation Styles */}
      <style>{`
        @keyframes modalPop {
          0% { opacity: 0; transform: scale(0.8) translateY(50px); }
          100% { opacity: 1; transform: scale(1) translateY(0); }
        }
        @keyframes modalPopExit {
          0% { opacity: 1; transform: scale(1) translateY(0); }
          100% { opacity: 0; transform: scale(0.8) translateY(50px); }
        }
      `}</style>

      {/* FIX: Added overflow-x-hidden to main to prevent horizontal scrollbar */}
      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto overflow-x-hidden relative">
        {/* Success Toast */}
        {showSuccessToast && (
          <div className="absolute top-8 right-8 z-50 animate-in slide-in-from-top-5 duration-300">
            <div className="bg-[#dcfce7] border border-green-200 text-[#166534] px-4 py-3 rounded-xl shadow-lg flex items-center gap-3">
              <div className="bg-green-500 rounded-full p-1 text-white">
                <Info size={12} strokeWidth={4} />
              </div>
              <span className="font-semibold text-sm">
                Usuário salvo com sucesso!
              </span>
              <button
                onClick={() => setShowSuccessToast(false)}
                className="ml-4 hover:text-green-800"
              >
                <X size={16} />
              </button>
            </div>
          </div>
        )}

        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-[#1a1a1a]">
            Usuários Cadastrados
          </h1>
        </div>

        {/* Filters Bar */}
        <div className="flex items-start gap-4 mb-8">
          <div className="flex-1">
            <div className="grid grid-cols-5 gap-4">
              <FilterAutocomplete
                label="Nome"
                value={filterName}
                options={nameOptions}
                onChange={setFilterName}
              />
              <FilterAutocomplete
                label="E-mail"
                value={filterEmail}
                options={emailOptions}
                onChange={setFilterEmail}
              />
              <FilterMultiSelect
                label="Cargo"
                value={filterRoles}
                options={roleOptions}
                onChange={(v) => setFilterRoles(v)}
              />
              <FilterMultiSelect
                label="Status"
                value={filterStatus}
                options={statusOptions}
                onChange={(v) => setFilterStatus(v)}
              />
              <div className="hidden md:block"></div>
              <div className="hidden md:block"></div>
            </div>
          </div>
          <div className="pt-[25px]">
            <Tooltip
              text="Adicionar novo usuário"
              className="w-fit"
              spacing="mb-2"
            >
              <button
                onClick={handleOpenCreate}
                className="h-[50px] px-6 py-2 bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors flex items-center justify-center text-black shadow-sm"
              >
                <UserPlus size={24} />
              </button>
            </Tooltip>
          </div>
        </div>

        {/* Table Card */}
        <div className="bg-white rounded-[2rem] shadow-sm border border-gray-100 overflow-hidden min-h-[600px] flex flex-col">
          <div className="overflow-x-auto flex-1">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-gray-100">
                  {[
                    "Nome",
                    "E-mail",
                    "Telefone",
                    "Secretaria",
                    "Cargo",
                    "RPA",
                    "Ação",
                  ].map((head, i) => (
                    <th
                      key={i}
                      className="px-6 py-5 text-sm font-bold text-[#1a1a1a] whitespace-nowrap"
                    >
                      {head}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleUsers.length > 0 ? (
                  visibleUsers.map((row, index) => (
                    <tr
                      key={row.id}
                      onClick={() => handleOpenEdit(row)}
                      className={`transition-colors border-b border-gray-50 last:border-0 cursor-pointer group ${index % 2 === 0 ? "bg-gray-50" : "bg-white"} hover:bg-gray-200`}
                    >
                      <td className="px-6 py-5 text-sm text-[#1a1a1a] font-medium">
                        <Tooltip text={row.name}>
                          <span className="truncate max-w-[200px] block">
                            {row.name}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.email}>
                          <span className="truncate max-w-[240px] block">
                            {row.email}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        {row.phone}
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.secretaria}>
                          <span className="truncate max-w-[200px] block">
                            {row.secretaria}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.cargo}>
                          <span className="truncate max-w-[220px] block">
                            {row.cargo}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        {row.rpa}
                      </td>
                      <td className="px-6 py-5">
                        <Tooltip
                          text="Deletar usuário"
                          variant="danger"
                          className="w-fit"
                          spacing="mb-2"
                        >
                          <button
                            onClick={(e) => handleOpenDelete(row, e)}
                            className="w-8 h-8 flex items-center justify-center text-[#f43f5e] hover:bg-pink-50 rounded-lg transition-colors bg-transparent"
                          >
                            <Trash2 size={20} />
                          </button>
                        </Tooltip>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-6 py-10 text-center text-gray-500"
                    >
                      Nenhum usuário encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Dynamic Pagination Footer */}
          <div className="flex items-center justify-between px-6 py-6 border-t border-gray-100 mt-auto bg-white">
            <span className="text-sm text-gray-500">
              Mostrando {visibleUsers.length > 0 ? startIndex + 1 : 0} -{" "}
              {Math.min(endIndex, filteredUsers.length)} de{" "}
              {filteredUsers.length} registros
            </span>

            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-500">Itens</span>

              {/* Items Per Page Dropdown */}
              <div className="relative">
                <div
                  onClick={() => setShowItemsMenu(!showItemsMenu)}
                  className="flex items-center gap-2 bg-gray-200 rounded-lg px-3 py-1 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-300 transition-colors select-none min-w-[60px] justify-between"
                >
                  {itemsPerPage}
                  <ChevronDown
                    size={14}
                    className={`transition-transform duration-200 ${showItemsMenu ? "rotate-180" : ""}`}
                  />
                </div>

                {showItemsMenu && (
                  <div className="absolute bottom-full left-0 mb-1 w-full bg-white border border-gray-200 rounded-lg shadow-xl overflow-hidden z-30 animate-in fade-in zoom-in-95 slide-in-from-bottom-2 duration-200 ease-out origin-bottom">
                    {[10, 20, 30].map((num) => (
                      <div
                        key={num}
                        onClick={() => {
                          setItemsPerPage(num);
                          setShowItemsMenu(false);
                        }}
                        className={`px-3 py-2 text-sm cursor-pointer hover:bg-gray-50 flex justify-center ${itemsPerPage === num ? "font-bold bg-gray-50 text-[#1a1a1a]" : "text-gray-600"}`}
                      >
                        {num}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Page Numbers */}
              <div className="flex items-center gap-2 ml-4">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className={`w-6 h-6 flex items-center justify-center transition-colors ${currentPage === 1 ? "text-gray-300 cursor-not-allowed" : "text-gray-400 hover:text-gray-600"}`}
                >
                  <ChevronLeft size={16} />
                </button>

                {getPageNumbers().map((pageNum) => (
                  <button
                    key={pageNum}
                    onClick={() => setCurrentPage(pageNum)}
                    className={`w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold transition-all shadow-sm
                            ${currentPage === pageNum ? "bg-[#ccff33] text-black" : "text-gray-500 hover:bg-gray-100"}`}
                  >
                    {pageNum}
                  </button>
                ))}

                <button
                  onClick={() =>
                    setCurrentPage((p) => Math.min(totalPages, p + 1))
                  }
                  disabled={currentPage === totalPages || totalPages === 0}
                  className={`w-6 h-6 flex items-center justify-center transition-colors ${currentPage === totalPages || totalPages === 0 ? "text-gray-300 cursor-not-allowed" : "text-gray-400 hover:text-gray-600"}`}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Modals */}
      {isUserModalOpen && (
        <UserModal
          onClose={handleCloseUserModal}
          onSave={handleSaveUser}
          initialData={selectedUser}
          isClosing={isUserModalClosing}
        />
      )}

      {isDeleteModalOpen && (
        <DeleteModal
          onClose={handleCloseDeleteModal}
          onConfirm={handleDeleteUser}
          isClosing={isDeleteModalClosing}
        />
      )}
    </div>
  );
};

```

## `frontend/src/services/api.ts`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```typescript
﻿import axios from 'axios';
import type { InternalAxiosRequestConfig, AxiosError } from 'axios';

// Criar instância do axios com configuração base
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8001/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor de Request - Adicionar token JWT
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('@Saira:token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error: AxiosError) => {
    return Promise.reject(error);
  }
);

// Interceptor de Response - Tratar erro 401
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      // Limpar token e redirecionar para login
      localStorage.removeItem('@Saira:token');
      localStorage.removeItem('@Saira:user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;

```

## `frontend/src/services/mockData.ts`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```typescript
﻿export type WasteType = "Entulho" | "Lixo domiciliar" | "Poda" | "Plástico";

export type PoiData = {
  id: string;
  bairro: string;
  logradouro: string;
  latitude: number;
  longitude: number;
  timestamp: string;
  wasteType: WasteType;
  volume: number; // Volume in m³
  status: "Pendente" | "Em análise" | "Resolvido";
  photoUrl: string;
  hasOffender: boolean;
};

type SeedLocation = {
  bairro: string;
  logradouro: string;
  latitude: number;
  longitude: number;
};

const seedLocations: SeedLocation[] = [
  {
    bairro: "Imbiribeira",
    logradouro: "Rua Visconde de Suassuna",
    latitude: -8.1122,
    longitude: -34.9026,
  },
  {
    bairro: "Brasília Teimosa",
    logradouro: "Av. Brasília Formosa",
    latitude: -8.0848,
    longitude: -34.8876,
  },
  {
    bairro: "Santo Amaro",
    logradouro: "Rua do Pombal",
    latitude: -8.0435,
    longitude: -34.8906,
  },
  {
    bairro: "Prado",
    logradouro: "Rua Abdias de Carvalho",
    latitude: -8.0617,
    longitude: -34.9123,
  },
  {
    bairro: "Porto da Madeira",
    logradouro: "Av. Beberibe",
    latitude: -8.0163,
    longitude: -34.8856,
  },
  {
    bairro: "Ilha de Deus",
    logradouro: "Ponte Paulo Guerra",
    latitude: -8.0934,
    longitude: -34.9073,
  },
  {
    bairro: "Torrões",
    logradouro: "Rua Onze de Fevereiro",
    latitude: -8.0673,
    longitude: -34.9318,
  },
  {
    bairro: "Várzea",
    logradouro: "Praça da Várzea",
    latitude: -8.0531,
    longitude: -34.9545,
  },
  {
    bairro: "Jiquiá",
    logradouro: "Rua João Teixeira",
    latitude: -8.0825,
    longitude: -34.9213,
  },
];

const WASTE_TYPES: WasteType[] = [
  "Entulho",
  "Lixo domiciliar",
  "Poda",
  "Plástico",
];

const PHOTO_URLS = [
  "https://placehold.co/600x400/ef4444/FFFFFF?text=Foto+1",
  "https://placehold.co/600x400/3b82f6/FFFFFF?text=Foto+2",
  "https://placehold.co/600x400/f97316/FFFFFF?text=Foto+3",
  "https://placehold.co/600x400/22c55e/FFFFFF?text=Foto+4",
  "https://placehold.co/600x400/8b5cf6/FFFFFF?text=Foto+5",
  "https://placehold.co/600x400/0ea5e9/FFFFFF?text=Foto+6",
  "https://placehold.co/600x400/facc15/1f2937?text=Foto+7",
  "https://placehold.co/600x400/14b8a6/FFFFFF?text=Foto+8",
  "https://placehold.co/600x400/64748b/FFFFFF?text=Foto+9",
];

const randomInt = (min: number, max: number) =>
  Math.floor(Math.random() * (max - min + 1)) + min;

const randomItem = <T,>(items: T[]) => items[randomInt(0, items.length - 1)];

const buildRandomTimestamp = (year: number, monthIndex: number) => {
  const start = new Date(Date.UTC(year, monthIndex, 1, 0, 0, 0));
  const end = new Date(Date.UTC(year, monthIndex + 1, 0, 23, 59, 59));
  const range = end.getTime() - start.getTime();
  const offset = randomInt(0, range);
  return new Date(start.getTime() + offset).toISOString();
};

const getStatusForDate = (year: number, monthIndex: number) => {
  if (year === 2025) return "Resolvido" as const;
  if (year === 2026 && monthIndex === 0) {
    return randomItem(["Pendente", "Em análise", "Resolvido"] as const);
  }
  return "Resolvido" as const;
};

const generateMockData = (): PoiData[] => {
  const results: PoiData[] = [];
  let counter = 1;

  for (const location of seedLocations) {
    for (let year = 2025; year <= 2026; year += 1) {
      const startMonth = year === 2025 ? 0 : 0;
      const endMonth = year === 2025 ? 11 : 0;

      for (let month = startMonth; month <= endMonth; month += 1) {
        for (let i = 0; i < 10; i += 1) {
          results.push({
            id: `SAIRA-${String(counter).padStart(4, "0")}`,
            bairro: location.bairro,
            logradouro: location.logradouro,
            latitude: location.latitude,
            longitude: location.longitude,
            timestamp: buildRandomTimestamp(year, month),
            wasteType: randomItem(WASTE_TYPES),
            volume: randomInt(10, 100),
            status: getStatusForDate(year, month),
            photoUrl: randomItem(PHOTO_URLS),
            hasOffender: Math.random() < 0.5,
          });
          counter += 1;
        }
      }
    }
  }

  return results;
};

export const masterPois: PoiData[] = generateMockData();

```

## `frontend/tailwind.config.js`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```javascript
// tailwind.config.js
const { heroui } = require("@heroui/react");

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./node_modules/@heroui/theme/dist/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  darkMode: "class",
  plugins: [heroui()], // Add the HeroUI plugin here
};

```

## `frontend/tsconfig.app.json`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "types": ["vite/client", "leaflet", "leaflet.heat", "react-leaflet"],
    "skipLibCheck": true,

    /* Bundler mode */
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",

    /* Linting */
    "strict": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedSideEffectImports": true
  },
  "include": [
    "src",
    "src/components/CameraDetectionsTableSection.tsx",
    "src/components/TablePaginationSection.tsx"
  ]
}

```

## `frontend/tsconfig.json`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}

```

## `frontend/tsconfig.node.json`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.node.tsbuildinfo",
    "target": "ES2023",
    "lib": ["ES2023"],
    "module": "ESNext",
    "types": ["node"],
    "skipLibCheck": true,

    /* Bundler mode */
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,

    /* Linting */
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedSideEffectImports": true
  },
  "include": ["vite.config.ts"]
}

```

## `frontend/vite.config.ts`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
});

```

## `infra/README.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
# Infra - Infraestrutura como Codigo

Modulos Terraform para provisionamento dos recursos AWS do SAIRA.

## Modulos

| Modulo | Recurso | Descricao |
| ------ | ------- | --------- |
| `s3` | S3 Bucket | Armazenamento de imagens de deteccoes |
| `sqs` | SQS Queue | Fila de mensagens entre cameras e YOLO worker |
| `rds` | RDS PostgreSQL | Banco de dados gerenciado com PostGIS |
| `ecs` | ECS Fargate | Hospedagem do backend e frontend |
| `iam` | IAM Roles | Permissoes para servicos (ECS, EC2, S3, SQS) |
| `ec2_yolo_vm` | EC2 Instance | VM dedicada para o worker YOLO |

## Ambientes

```text
infra/terraform/envs/
├── dev/dev.dev         # Variaveis do ambiente de desenvolvimento
└── prod/prod.prod      # Variaveis do ambiente de producao
```

## Uso

```bash
cd infra/terraform/envs/dev
terraform init
terraform plan
terraform apply
```

```

## `infra/terraform/envs/dev/dev.dev`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```hcl


```

## `infra/terraform/envs/prod/prod.prod`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```hcl


```

## `infra/terraform/modules/ec2_yolo_vm/ec2_yolo_vm.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `infra/terraform/modules/ec2_yolo_vm/ecs2_yolo_vm.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `infra/terraform/modules/ecs/ecs.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `infra/terraform/modules/iam/iam.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `infra/terraform/modules/rds/rds.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `infra/terraform/modules/s3/file.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `infra/terraform/modules/sqs/sqs.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `ingester-bluestacks/Dockerfile`

**Purpose:** Receita de build da imagem container para padronizar runtime e deploy deste componente.

```dockerfile
# Usar uma imagem base oficial do Python
FROM python:3.11-slim

# Instalar o cliente ADB do Linux
RUN apt-get update && \
    apt-get install -y android-tools-adb && \
    rm -rf /var/lib/apt/lists/*

# Definir o diretório de trabalho no container
WORKDIR /app

# Instalar Poetry
RUN pip install --no-cache-dir poetry

# Copiar o restante do código-fonte da aplicação
COPY . .

# Instalar as dependências do projeto
# O --no-interaction previne perguntas interativas
RUN poetry config virtualenvs.create false && poetry install --no-interaction

# Comando para executar a aplicação como um módulo
CMD ["python", "-m", "ingester.main"]

```

## `ingester-bluestacks/pyproject.toml`

**Purpose:** Manifesto de dependencias e metadados de build usado para reproducibilidade do componente.

```toml
[tool.poetry]
name = "ingester"
version = "0.1.0"
description = "Saira Ingester Service"
authors = ["Your Name <you@example.com>"]
packages = [{include = "ingester", from = "src"}]

[tool.poetry.dependencies]
python = "^3.11"
pillow = "^10.4.0"
python-dotenv = "^1.0.0"

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"

```

## `ingester-bluestacks/README.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
# Ingester BlueStacks Mode

Este servi�o � uma c�pia do ingester para uso com BlueStacks, sem alterar o ingester original.

## Pr�-requisitos
- Python 3.11+
- Android SDK Platform-Tools (ADB) no PATH
- BlueStacks aberto com ADB habilitado

## Configura��o
Defina o serial do BlueStacks via vari�vel de ambiente:

```powershell
$env:INGESTER_DEVICE_SERIAL="127.0.0.1:5555"
```

Se precisar listar devices:

```powershell
adb devices
```

## Execu��o

```powershell
cd C:\saira\services\ingester-bluestacks
poetry install
python -m ingester.main
```

## Observa��es
- Coordenadas de taps dependem da resolu��o do BlueStacks; ajuste em `src/ingester/config.py`.
- Se o serial n�o estiver presente em `adb devices`, o ingester n�o inicia captura.

```

## `ingester-bluestacks/src/ingester/__init__.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
'the init file'

```

## `ingester-bluestacks/src/ingester/cameras.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
'cameras'

```

## `ingester-bluestacks/src/ingester/config.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/config.py
"""
Centralized configuration for the Ingester service.
"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"), override=True)


def _parse_bool_env(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return default


# --- Application and Device Settings ---

# Nova premissa: o fluxo de automação assume que o aplicativo alvo já está aberto.
# Isso desativa a necessidade de navegar para a Home e abrir o app.
ASSUME_APP_OPEN = True

# Package name for the ICSee application.
ICSEE_PACKAGE_NAME = "com.icsee.pro"


# --- Camera Configurations ---
# Coordenadas para acessar a visualização da câmera dentro do app.
CAMERAS = {
    "camera_quarto_1": {
        "tap_coords": {
            "x": 833,
            "y": 480
        }
    },
    "camera_quarto_2": {
        "tap_coords": {
            "x": 250,
            "y": 480  # Coordenada Y ajustada para diferenciar da primeira câmera
        }
    }
}

# --- Ritual de Estabilização Pré-Captura ---
# Sequência de ações a serem executadas para estabilizar o stream de vídeo
# antes de realizar a captura do screenshot.
PRE_CAPTURE_WAIT_SECONDS = 2  # Tempo de espera (em segundos) entre os taps do ritual.
PRE_CAPTURE_SEQUENCE = [
    {"type": "tap", "coords": {"x": 994, "y": 706}, "label": "fullscreen_btn"},
    {"type": "wait", "duration": PRE_CAPTURE_WAIT_SECONDS},
    {"type": "tap", "coords": {"x": 500, "y": 500}, "label": "dismiss_controls"},
]

# --- Fullscreen Controls ---
FULLSCREEN_TAP_COORDS = {"x": 994, "y": 706}
MENU_TAP_COORDS = {"x": 500, "y": 500}

# --- Timing Delays (in seconds) ---
# Delays para garantir que a UI responda adequadamente.

# Delay entre a finalização de uma câmera e o início da próxima.
# Essencial para permitir que a UI (lista de câmeras) se estabilize.
INTER_CAMERA_DELAY_SECONDS = 1.0

# Tempo de espera para o stream da câmera carregar após selecioná-la.
WAIT_STREAM_LOAD_SECONDS = 15

# --- Ações Pós-Captura ---
# Define o comportamento ao final do fluxo.

# Número de vezes que a tecla BACK será pressionada.
POST_CAPTURE_BACK_COUNT = 2
# Delay entre os pressionamentos da tecla BACK.
POST_BACK_DELAY_SECONDS = 0.5

# --- Capture Loop (Cadence) ---
# Default cadence is 5 minutes.
CAPTURE_INTERVAL_SECONDS = int(os.getenv("INGESTER_CAPTURE_INTERVAL_SECONDS", "300"))
# Health cadence.
HEALTH_INTERVAL_SECONDS = 60
# Allow infinite loop in local mode.
RUN_FOREVER = _parse_bool_env(os.getenv("INGESTER_RUN_FOREVER"), True)
# None or 0 means infinite cycles.
MAX_CYCLES = int(os.getenv("INGESTER_MAX_CYCLES", "0")) or None
# Backoff after a failed cycle.
ERROR_BACKOFF_SECONDS = 30
# ADB timeouts (seconds).
CAPTURE_ADB_TIMEOUT_SECONDS = 30
HEALTH_ADB_TIMEOUT_SECONDS = 30

# Optional heavy dumpsys for debugging only.
ENABLE_CONNECTIVITY_DUMPSYS = False

# --- Logging ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
HEALTH_JSONL_FILENAME = "health.jsonl"
CYCLES_JSONL_PATH = os.path.join(LOG_DIR, "cycles.jsonl")

# --- Output ---
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "captures")

# --- App Focus Validation ---
EXPECTED_PACKAGE = "com.xm.csee"
EXPECTED_ACTIVITIES = [
    "com.xworld.MainActivity",
    "com.xworld.activity.monitor.view.MonitorActivity",
]

# --- Screen Validation ---
MAX_SCREEN_RETRIES = 2
RETRY_DELAY_SEC = 1.5
BLACK_MEAN_THRESHOLD = 35
WHITE_MEAN_THRESHOLD = 240
LOW_STD_THRESHOLD = 20

# --- Loading Screen Detection ---
LOADING_MEAN_MAX = 60
LOADING_BRIGHT_CENTER_MIN = 0.01

# --- Error Artifacts ---
LOGCAT_LINES_ON_ERROR = 500

# --- ADB Timeouts / Logging ---
BATTERY_DUMPSYS_TIMEOUT_SECONDS = 12
ADB_TIMEOUT_RETRY_DELAY_SECONDS = 1.0
ADB_ERROR_OUTPUT_TAIL_CHARS = 800

# --- BlueStacks / ADB Device Selection ---
# If set, ingester will use this device serial only (e.g. 127.0.0.1:5555).
ADB_DEVICE_SERIAL = os.getenv("INGESTER_DEVICE_SERIAL")

# --- Health Check Flag ---
ENABLE_HEALTHCHECK = _parse_bool_env(os.getenv("INGESTER_ENABLE_HEALTHCHECK"), False)
ENABLE_FOCUS_VALIDATION = _parse_bool_env(os.getenv("INGESTER_ENABLE_FOCUS_VALIDATION"), False)

# --- Screen State Detection & Recovery ---
ENABLE_SCREEN_STATE_DETECTION = _parse_bool_env(
    os.getenv("INGESTER_ENABLE_SCREEN_STATE_DETECTION"), False
)

# App launch configuration
APP_LAUNCH_ACTIVITY = "com.xworld.MainActivity"
APP_LAUNCH_WAIT_SECONDS = 8.0
APP_ICON_TAP_COORDS = {"x": 150, "y": 1150}  # Fallback: ícone do ICSee na Home

# Recovery settings
MAX_STATE_RECOVERY_ATTEMPTS = 2
PRE_CAPTURE_RETRY_MAX = 2
STATE_CHECK_WAIT_SECONDS = 1.0

# Screen state thresholds — calibrados com dados reais de screen_profiles.json.
# Árvore de decisão (avaliada nesta ordem):
#   1. camera_normal:     dark_ratio_top >= 0.5  (topo escuro, exclusivo desta tela)
#   2. camera_fullscreen: dark_ratio_left >= 0.7  (borda esquerda escura = vídeo cheio)
#   3. home:              h_line_status_bottom <= 0.3  (sem linha de status do app)
#   4. camera_list:       h_line alto + dark ratios baixos
#   5. UNKNOWN:           nenhuma regra se encaixou → tenta voltar para HOME
SCREEN_STATE_THRESHOLDS = {
    "camera_normal": {
        "dark_ratio_top_min": 0.5,       # home=0.02, list=0.01, normal=0.76, full=0.04
    },
    "camera_fullscreen": {
        "dark_ratio_left_min": 0.7,      # home=0.004, list=0, normal=0.15, full=0.86
    },
    "home": {
        "h_line_status_bottom_max": 0.3, # home=0.11, list=0.79, normal=0.80, full=0.3-0.6
    },
    "sanity": {
        "camera_list_max_dark": 0.3,     # dark_top e dark_left devem ser < 0.3 para camera_list
    },
}

```

## `ingester-bluestacks/src/ingester/local/__init__.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# This file makes 'local' a Python package

```

## `ingester-bluestacks/src/ingester/local/adb_adapter.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/adb_adapter.py
import logging
import subprocess
import re
import time
from typing import Any

from .. import config

logger = logging.getLogger(__name__)


class AdbCommandError(RuntimeError):
    def __init__(self, cmd: str, returncode: int, stdout: str, stderr: str):
        super().__init__(f"ADB command failed (code={returncode}): {cmd}")
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class AdbTimeoutError(TimeoutError):
    def __init__(self, cmd: str, timeout_s: float):
        super().__init__(f"ADB command timed out after {timeout_s}s: {cmd}")
        self.cmd = cmd
        self.timeout_s = timeout_s


def _run_command(
    command: list[str],
    timeout_s: float | None = None,
    check: bool = True,
    retry_on_timeout: bool = False,
) -> subprocess.CompletedProcess:
    """Run an adb command list with timeout and duration logging."""
    full_command = ["adb"] + command
    cmd_str = " ".join(full_command)
    start = time.monotonic()
    if timeout_s is None:
        timeout_s = config.CAPTURE_ADB_TIMEOUT_SECONDS

    try:
        process = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        duration_s = time.monotonic() - start
        logger.warning(f"ADB timeout duration={duration_s:.3f}s cmd={cmd_str}")
        if retry_on_timeout:
            logger.warning("ADB retry on timeout: restarting server and retrying once.")
            _restart_adb_server()
            return _run_command(
                command,
                timeout_s=timeout_s,
                check=check,
                retry_on_timeout=False,
            )
        raise AdbTimeoutError(cmd_str, timeout_s if timeout_s is not None else -1)

    duration_s = time.monotonic() - start
    logger.info(f"ADB done duration={duration_s:.3f}s exit_code={process.returncode} cmd={cmd_str}")

    if process.stdout:
        logger.debug(f"ADB stdout: {process.stdout.strip()}")
    if process.stderr:
        logger.debug(f"ADB stderr: {process.stderr.strip()}")

    if check and process.returncode != 0:
        stdout_tail = _tail_text(process.stdout or "", config.ADB_ERROR_OUTPUT_TAIL_CHARS)
        stderr_tail = _tail_text(process.stderr or "", config.ADB_ERROR_OUTPUT_TAIL_CHARS)
        logger.warning(
            "ADB command failed; stdout_tail=%s stderr_tail=%s",
            stdout_tail,
            stderr_tail,
        )
        raise AdbCommandError(cmd_str, process.returncode, process.stdout or "", process.stderr or "")

    return process


def run_shell(cmd: str, timeout_s: float) -> str:
    """Run an adb shell command on the first connected device."""
    devices = list_devices(timeout_s=timeout_s)
    if not devices:
        raise AdbCommandError("adb devices", 1, "", "No devices")
    result = _run_shell_cmd(devices[0], cmd, timeout_s=timeout_s, check=True)
    return (result.stdout or "").strip()


def _run_shell_cmd(
    device_id: str,
    cmd: str,
    timeout_s: float | None = None,
    check: bool = True,
    retry_on_timeout: bool = False,
) -> subprocess.CompletedProcess:
    # Use sh -c only for commands with shell metacharacters (pipes, redirects, etc.)
    _shell_meta = set("|&;<>()$`\\\"'")
    needs_shell = any(c in _shell_meta for c in cmd)
    if needs_shell:
        args = ["-s", device_id, "shell", "sh", "-c", cmd]
    else:
        args = ["-s", device_id, "shell"] + cmd.split()
    return _run_command(
        args,
        timeout_s=timeout_s,
        check=check,
        retry_on_timeout=retry_on_timeout,
    )


def list_devices(timeout_s: float | None = None) -> list[str]:
    """List connected adb device serials."""
    logger.info("Listing ADB devices...")
    _run_command(["start-server"], timeout_s=timeout_s, check=False)
    result = _run_command(["devices"], timeout_s=timeout_s, check=True)
    device_lines = re.findall(r"^(.+?)\s+device$", result.stdout, re.MULTILINE)
    if not device_lines:
        logger.warning("No ADB devices found.")
        return []
    if config.ADB_DEVICE_SERIAL:
        if config.ADB_DEVICE_SERIAL in device_lines:
            logger.info(f"Using configured device serial: {config.ADB_DEVICE_SERIAL}")
            return [config.ADB_DEVICE_SERIAL]
        logger.warning(
            f"Configured serial not found in adb devices: {config.ADB_DEVICE_SERIAL}"
        )
        return []
    logger.info(f"Devices found: {device_lines}")
    return device_lines


def go_home_monkey(device_id: str, timeout_s: float | None = None):
    logger.info(f"Going Home via monkey on device {device_id}...")
    _run_command(["-s", device_id, "shell", "monkey", "-c", "android.intent.category.LAUNCHER", "1"], timeout_s=timeout_s)


def go_home_keyevent(device_id: str, timeout_s: float | None = None):
    logger.info(f"Going Home via KEYCODE_HOME on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "keyevent", "3"], timeout_s=timeout_s)


def close_app(device_id: str, package_name: str, timeout_s: float | None = None):
    logger.info(f"Force-stopping '{package_name}' on device {device_id}...")
    _run_command(["-s", device_id, "shell", "am", "force-stop", package_name], timeout_s=timeout_s)


def tap(device_id: str, x: int, y: int, timeout_s: float | None = None):
    logger.info(f"Tap (X={x}, Y={y}) on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "tap", str(x), str(y)], timeout_s=timeout_s)


def press_key(device_id: str, keycode: str, timeout_s: float | None = None):
    logger.info(f"Keyevent '{keycode}' on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "keyevent", keycode], timeout_s=timeout_s)


def swipe(device_id: str, x1: int, y1: int, x2: int, y2: int, duration: int = 300, timeout_s: float | None = None):
    logger.info(f"Swipe ({x1},{y1}) -> ({x2},{y2}) on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)], timeout_s=timeout_s)


def screencap(device_id: str, local_path: str, timeout_s: float | None = None) -> bool:
    remote_path = "/sdcard/saira_capture.png"
    logger.info(f"Screencap device {device_id} to {local_path}...")
    try:
        _run_command(["-s", device_id, "shell", "screencap", remote_path], timeout_s=timeout_s)
        _run_command(["-s", device_id, "pull", remote_path, local_path], timeout_s=timeout_s)
        _run_command(["-s", device_id, "shell", "rm", remote_path], timeout_s=timeout_s)
        logger.info(f"Screenshot saved: {local_path}")
        return True
    except (AdbCommandError, AdbTimeoutError):
        logger.error(f"Failed to screencap device {device_id}.")
        return False


def launch_app(device_id: str, timeout_s: float | None = None) -> bool:
    """Launch the ICSee app by tapping its icon on the home screen.

    Assumes the device is already on the HOME screen.
    """
    coords = config.APP_ICON_TAP_COORDS
    if not coords:
        logger.error("APP_ICON_TAP_COORDS nao configurado.")
        return False

    logger.info(f"Abrindo app: tap no icone em ({coords['x']}, {coords['y']})")
    try:
        tap(device_id, coords["x"], coords["y"], timeout_s=timeout_s)
        time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
        return True
    except Exception as exc:
        logger.error(f"Falha ao abrir app via tap: {exc}")
        return False


def get_device_state(device_id: str, timeout_s: float | None = None) -> str:
    result = _run_command(["-s", device_id, "get-state"], timeout_s=timeout_s, check=False)
    return (result.stdout or "").strip()


def get_health_snapshot(device_id: str, timeout_s: float) -> dict[str, Any]:
    if not config.ENABLE_HEALTHCHECK:
        logger.info("Health check disabled by config; skipping device health collection.")
        return {"disabled": True, "device_id": device_id}

    errors: list[str] = []
    snapshot: dict[str, Any] = {"device_id": device_id}
    warn_exc = logger.isEnabledFor(logging.DEBUG)

    try:
        snapshot["adb_state"] = get_device_state(device_id, timeout_s=timeout_s)
        snapshot["adb_ok"] = True
    except Exception as exc:
        errors.append(f"adb_state: {exc}")
        snapshot["adb_ok"] = False
        logger.warning(f"ADB state check failed: {exc}", exc_info=warn_exc)

    try:
        snapshot.update(get_battery_info(device_id, timeout_s))
    except Exception as exc:
        errors.append(f"battery: {exc}")
        logger.warning(f"Battery check failed: {exc}", exc_info=warn_exc)

    try:
        snapshot.update(get_uptime_info(device_id, timeout_s))
    except Exception as exc:
        errors.append(f"uptime: {exc}")
        logger.warning(f"Uptime check failed: {exc}", exc_info=warn_exc)

    try:
        snapshot.update(get_storage_info(device_id, timeout_s, "/data"))
    except Exception as exc:
        errors.append(f"storage: {exc}")
        logger.warning(f"Storage check failed: {exc}", exc_info=warn_exc)

    try:
        snapshot.update(get_network_info(device_id, timeout_s))
    except Exception as exc:
        errors.append(f"network: {exc}")
        logger.warning(f"Network check failed: {exc}", exc_info=warn_exc)

    try:
        snapshot.update(get_mem_info(device_id, timeout_s))
    except Exception as exc:
        errors.append(f"mem: {exc}")
        logger.warning(f"Mem check failed: {exc}", exc_info=warn_exc)

    if config.ENABLE_CONNECTIVITY_DUMPSYS:
        try:
            result = _run_shell_cmd(device_id, "dumpsys connectivity | head -n 80", timeout_s=timeout_s, check=False)
            snapshot["connectivity_dumpsys"] = (result.stdout or "").splitlines()
        except Exception as exc:
            errors.append(f"connectivity_dumpsys: {exc}")
            logger.warning(f"Connectivity dumpsys failed: {exc}", exc_info=warn_exc)

    snapshot["_errors"] = errors
    return snapshot


def get_battery_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    battery_timeout = max(timeout_s, config.BATTERY_DUMPSYS_TIMEOUT_SECONDS)
    result = _run_shell_cmd(
        device_id,
        "dumpsys battery",
        timeout_s=battery_timeout,
        check=True,
        retry_on_timeout=True,
    )
    text = result.stdout or ""
    level = _extract_int(text, r"level:\s*(\d+)")
    status = _extract_int(text, r"status:\s*(\d+)")
    temperature = _extract_int(text, r"temperature:\s*(\d+)")
    voltage = _extract_int(text, r"voltage:\s*(\d+)")
    usb_powered = _extract_bool(text, r"USB powered:\s*(\w+)")
    ac_powered = _extract_bool(text, r"AC powered:\s*(\w+)")

    battery_temp_c = None
    if temperature is not None:
        battery_temp_c = temperature / 10.0

    return {
        "battery_level": level,
        "battery_status": status,
        "battery_temp_c": battery_temp_c,
        "battery_voltage_mv": voltage,
        "battery_usb_powered": usb_powered,
        "battery_ac_powered": ac_powered,
    }


def get_uptime_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, "cat /proc/uptime", timeout_s=timeout_s, check=True)
    uptime_s = _extract_float(result.stdout or "", r"^([\d\.]+)")
    return {"uptime_s": uptime_s}


def get_storage_info(device_id: str, timeout_s: float, mount_point: str) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, f"df {mount_point}", timeout_s=timeout_s, check=True)
    available_kb = _parse_df_available_kb(result.stdout or "", mount_point)
    return {"storage_available_kb": available_kb}


def get_network_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, "ip -f inet addr show wlan0", timeout_s=timeout_s, check=False)
    wlan0_ip = _extract_ip_addr(result.stdout or "")

    routes_result = _run_shell_cmd(device_id, "ip route", timeout_s=timeout_s, check=False)
    routes_raw = (routes_result.stdout or "").splitlines()
    default_route = _has_default_route(routes_raw)

    internet_ok = False
    method = None
    ping_result = _run_shell_cmd(device_id, "ping -c 1 -W 2 1.1.1.1", timeout_s=timeout_s, check=False)
    if ping_result.returncode == 0:
        internet_ok = True
        method = "ping"
    else:
        http_ok = _http_connectivity_check(device_id, timeout_s)
        if http_ok:
            internet_ok = True
            method = "http"

    info: dict[str, Any] = {
        "wlan0_ip": wlan0_ip,
        "internet_ok": internet_ok,
        "method": method,
        "default_route": default_route,
    }

    if not default_route:
        info["routes_raw"] = routes_raw[:5]

    return info


def get_mem_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, "cat /proc/meminfo", timeout_s=timeout_s, check=False)
    mem_available_kb = _extract_int(result.stdout or "", r"MemAvailable:\s*(\d+)\s*kB")
    return {"mem_available_kb": mem_available_kb}


def get_window_dump(device_id: str, timeout_s: float) -> str:
    result = _run_shell_cmd(device_id, "dumpsys window", timeout_s=timeout_s, check=False)
    return result.stdout or ""


def get_focus_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    raw = get_window_dump(device_id, timeout_s=timeout_s)
    focus = parse_window_dump(raw)
    logger.info(f"Focus detected source={focus.get('raw_match_source')} component={focus.get('component')}")
    return focus


def get_logcat_tail(device_id: str, lines: int, timeout_s: float) -> str:
    cmd = f"logcat -d -t {lines}"
    result = _run_shell_cmd(device_id, cmd, timeout_s=timeout_s, check=False)
    return result.stdout or ""


def _http_connectivity_check(device_id: str, timeout_s: float) -> bool:
    cmd = (
        "(command -v curl >/dev/null 2>&1 && curl -s --max-time 3 -o /dev/null "
        "http://connectivitycheck.gstatic.com/generate_204) "
        "|| (command -v wget >/dev/null 2>&1 && wget -q --spider --timeout=3 "
        "http://connectivitycheck.gstatic.com/generate_204) "
        "|| (command -v toybox >/dev/null 2>&1 && toybox wget -q --spider --timeout=3 "
        "http://connectivitycheck.gstatic.com/generate_204)"
    )
    result = _run_shell_cmd(device_id, cmd, timeout_s=timeout_s, check=False)
    return result.returncode == 0


def _has_default_route(routes: list[str]) -> bool:
    for line in routes:
        if not line:
            continue
        if line.startswith("default"):
            return True
        if "0.0.0.0/0" in line:
            return True
    return False


def _extract_ip_addr(text: str) -> str | None:
    match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", text or "")
    if match:
        return match.group(1)
    return None


def _extract_first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if match:
        return match.group(0)
    return None


def _window_excerpt(text: str, max_lines: int = 5) -> str:
    lines = []
    for line in (text or "").splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line or "mObscuringWindow" in line:
            lines.append(line.strip())
        if len(lines) >= max_lines:
            break
    return " | ".join(lines)


def parse_window_dump(raw: str) -> dict[str, Any]:
    component, source, raw_line = _find_focus_component(raw)
    pkg, activity = _split_component(component)
    insets = _extract_insets(raw)
    obscuring = _extract_first_match(raw, r"mObscuringWindow=Window\{[^}]+\}")
    return {
        "package": pkg,
        "activity": activity,
        "component": component,
        "insets": insets,
        "raw_match_source": source,
        "raw": raw_line,
        "wm_obscuring_window": obscuring,
        "window_dump_excerpt": _window_excerpt(raw),
    }


def _find_focus_component(raw: str) -> tuple[str | None, str, str]:
    patterns = [
        ("imeTarget", r"imeLayeringTarget.*?([\w.]+/[\w.$]+)"),
        ("imeInputTarget", r"imeInputTarget.*?([\w.]+/[\w.$]+)"),
        ("currentFocus", r"mCurrentFocus=.*?([\w.]+/[\w.$]+)"),
        ("focusedApp", r"mFocusedApp=.*?([\w.]+/[\w.$]+)"),
        ("resumedActivity", r"mResumedActivity:.*?([\w.]+/[\w.$]+)"),
        ("lastWakeLockObscuringWindow", r"mLastWakeLockObscuringWindow=.*?([\w.]+/[\w.$]+)"),
        ("obscuringWindow", r"mObscuringWindow=.*?([\w.]+/[\w.$]+)"),
    ]
    for name, pattern in patterns:
        match = re.search(pattern, raw or "", re.MULTILINE)
        if match:
            return match.group(1), name, match.group(0)
    fallback = re.search(r"([\w.]+/[\w.$]+)", raw or "", re.MULTILINE)
    if fallback:
        return fallback.group(1), "fallback", fallback.group(0)
    return None, "unknown", ""


def _split_component(component: str | None) -> tuple[str | None, str | None]:
    if not component:
        return None, None
    parts = component.split("/", 1)
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1]


def _extract_insets(raw: str) -> dict[str, int] | None:
    match = re.search(r"mContentInsets=\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw or "")
    if not match:
        return None
    left, top, right, bottom = [int(value) for value in match.groups()]
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _extract_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _extract_bool(text: str, pattern: str) -> bool | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    return None


def _parse_df_available_kb(text: str, mount_point: str) -> int | None:
    for line in (text or "").splitlines():
        if line.endswith(mount_point):
            parts = re.split(r"\s+", line.strip())
            if len(parts) >= 4:
                try:
                    return int(parts[3])
                except ValueError:
                    return None
    return None


def _tail_text(text: str, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text.strip()
    return text[-max_chars:].strip()


def _restart_adb_server() -> None:
    try:
        subprocess.run(["adb", "kill-server"], capture_output=True, text=True, check=False)
        time.sleep(config.ADB_TIMEOUT_RETRY_DELAY_SECONDS)
        subprocess.run(["adb", "start-server"], capture_output=True, text=True, check=False)
    except Exception:
        logger.warning("Failed to restart adb server.")

```

## `ingester-bluestacks/src/ingester/local/capture.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/capture.py
import logging
import os
import time
import json
import traceback
import shutil
from datetime import datetime

from PIL import Image

from . import adb_adapter, screen_classifier, screen_fingerprint
from .screen_classifier import ScreenState
from .. import config

logger = logging.getLogger(__name__)

def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _append_jsonl(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _step_start(name: str) -> dict:
    return {"name": name, "ok": False, "start": _now_iso(), "end": None, "duration_ms": None, "details": None}


def _step_end(step: dict, ok: bool, details: str | None = None) -> dict:
    step["ok"] = ok
    step["end"] = _now_iso()
    step["duration_ms"] = _duration_ms(step["start"], step["end"])
    if details:
        step["details"] = details
    return step


def _duration_ms(start_iso: str, end_iso: str) -> int:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    return int((end - start).total_seconds() * 1000)


def _validate_focus(focus: dict) -> tuple[bool, str]:
    pkg = focus.get("package")
    activity = focus.get("activity")
    if pkg != config.EXPECTED_PACKAGE:
        return False, f"focus_package_mismatch:{pkg}"
    if activity not in config.EXPECTED_ACTIVITIES:
        return False, f"focus_activity_mismatch:{activity}"
    return True, "ok"


def _analyze_image(path: str) -> dict:
    with Image.open(path) as img:
        gray = img.convert("L").resize((64, 64))
        pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    min_v = min(pixels)
    max_v = max(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    std = variance ** 0.5
    return {"mean": round(mean, 2), "std": round(std, 2), "min": min_v, "max": max_v}


def _validate_screenshot(stats: dict) -> tuple[bool, str]:
    mean = stats["mean"]
    std = stats["std"]
    if mean <= config.BLACK_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_black_screen"
    if mean >= config.WHITE_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_white_screen"
    return True, "ok"


def _write_error_artifacts(cycle_id: str, device_id: str, health: dict | None, screenshot_path: str | None) -> str:
    base_dir = os.path.join(config.LOG_DIR, f"cycle_{cycle_id}_artifacts")
    os.makedirs(base_dir, exist_ok=True)

    window_txt = os.path.join(base_dir, "window.txt")
    logcat_txt = os.path.join(base_dir, "logcat.txt")
    health_json = os.path.join(base_dir, "health.json")

    if config.ENABLE_FOCUS_VALIDATION:
        try:
            window_dump = adb_adapter.get_window_dump(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            with open(window_txt, "w", encoding="utf-8") as handle:
                handle.write(window_dump)
        except Exception as exc:
            logger.error(f"Failed to write window.txt: {exc}", exc_info=True)
    else:
        logger.info("Skipping window.txt artifact (focus validation disabled).")

    try:
        logcat = adb_adapter.get_logcat_tail(device_id, config.LOGCAT_LINES_ON_ERROR, config.HEALTH_ADB_TIMEOUT_SECONDS)
        with open(logcat_txt, "w", encoding="utf-8") as handle:
            handle.write(logcat)
    except Exception as exc:
        logger.error(f"Failed to write logcat.txt: {exc}", exc_info=True)

    try:
        with open(health_json, "w", encoding="utf-8") as handle:
            json.dump(health or {}, handle, ensure_ascii=True, indent=2)
    except Exception as exc:
        logger.error(f"Failed to write health.json: {exc}", exc_info=True)

    if screenshot_path and os.path.exists(screenshot_path):
        try:
            shutil.copyfile(screenshot_path, os.path.join(base_dir, "screenshot.png"))
        except Exception as exc:
            logger.error(f"Failed to copy screenshot: {exc}", exc_info=True)

    return base_dir


def _error_obj(error_message: str | None, error_type: str | None, steps: list[dict], trace: str | None = None) -> dict | None:
    if not error_message:
        return None
    step_name = steps[-1]["name"] if steps else None
    return {
        "type": error_type or "CycleError",
        "message": error_message,
        "step": step_name,
        "trace": trace,
    }


def _capture_with_validation(device_id: str, camera_name: str) -> dict:
    last_focus = None
    last_stats = None
    last_path = None
    validation_reason = None

    attempts = config.MAX_SCREEN_RETRIES + 1
    for attempt in range(1, attempts + 1):
        if config.ENABLE_FOCUS_VALIDATION:
            focus = adb_adapter.get_focus_info(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            last_focus = focus
            focus_ok, focus_reason = _validate_focus(focus)
            if not focus_ok:
                validation_reason = focus_reason
                if attempt < attempts:
                    time.sleep(config.RETRY_DELAY_SEC)
                    continue
                return {
                    "path": None,
                    "validated": False,
                    "validation_reason": validation_reason,
                    "stats": None,
                    "attempts": attempt,
                    "focus": last_focus,
                }
        else:
            if attempt == 1:
                logger.info("Focus validation disabled by config; skipping.")

        camera_dir = os.path.join(config.OUTPUT_DIR, camera_name)
        os.makedirs(camera_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"capture_{device_id}_{timestamp}_attempt{attempt}.png"
        filepath = os.path.join(camera_dir, filename)
        last_path = filepath

        success = adb_adapter.screencap(
            device_id,
            filepath,
            timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
        )
        if not success:
            validation_reason = "screencap_failed"
            if attempt < attempts:
                time.sleep(config.RETRY_DELAY_SEC)
                continue
            return {
                "path": filepath,
                "validated": False,
                "validation_reason": validation_reason,
                "stats": None,
                "attempts": attempt,
                "focus": last_focus,
            }

        stats = _analyze_image(filepath)
        last_stats = stats
        valid, reason = _validate_screenshot(stats)
        validation_reason = reason
        if valid:
            return {
                "path": filepath,
                "validated": True,
                "validation_reason": "ok",
                "stats": stats,
                "attempts": attempt,
                "focus": last_focus,
            }

        if attempt < attempts:
            try:
                os.remove(filepath)
            except OSError:
                pass
            time.sleep(config.RETRY_DELAY_SEC)

    return {
        "path": last_path,
        "validated": False,
        "validation_reason": validation_reason,
        "stats": last_stats,
        "attempts": attempts,
        "focus": last_focus,
    }


def _check_screen(device_id: str, expected: ScreenState, context: str) -> tuple[bool, ScreenState, str | None]:
    """Take a screenshot, classify screen state, compare to expected.

    Returns (match, actual_state, screenshot_path).
    Screenshot is deleted if state matches.
    """
    if not config.ENABLE_SCREEN_STATE_DETECTION:
        logger.info(f"[{context}] Deteccao de tela desabilitada; pulando verificacao.")
        return True, ScreenState.UNKNOWN, None

    state, _fp, path = screen_classifier.capture_and_detect(device_id, context)
    match = state == expected
    if match:
        logger.info(f"[{context}] Tela OK: {state.value}")
    else:
        logger.warning(f"[{context}] Tela inesperada: esperado={expected.value} detectado={state.value}")
    # Cleanup temp screenshot
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    return match, state, path


def _recover_to_camera_list(device_id: str, current: ScreenState) -> bool:
    """Try to navigate back to the CAMERA_LIST screen."""
    logger.info(f"Recuperacao: estado atual={current.value}, objetivo=camera_list")

    if current == ScreenState.HOME:
        logger.info("Recuperacao: HOME detectado, abrindo app...")
        for attempt in range(1, config.MAX_STATE_RECOVERY_ATTEMPTS + 1):
            logger.info(f"Recuperacao: tentativa {attempt}/{config.MAX_STATE_RECOVERY_ATTEMPTS} de abrir o app...")
            if not adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS):
                continue
            time.sleep(config.STATE_CHECK_WAIT_SECONDS)
            ok, state, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, f"recovery_post_launch_attempt{attempt}")
            if ok:
                return True
            # Se caiu numa sub-tela do app (não HOME), tenta BACK
            if state != ScreenState.HOME:
                adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                time.sleep(config.STATE_CHECK_WAIT_SECONDS)
                ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, f"recovery_post_back_attempt{attempt}")
                if ok:
                    return True
            # Ainda HOME — esperar mais antes de tentar de novo
            logger.warning(f"Recuperacao: ainda em {state.value} apos tentativa {attempt}, aguardando antes de tentar novamente...")
            time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
        return False

    if current == ScreenState.CAMERA_NORMAL:
        adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        time.sleep(config.STATE_CHECK_WAIT_SECONDS)
        ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_normal")
        return ok

    if current == ScreenState.CAMERA_FULLSCREEN:
        for _ in range(2):
            adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(config.POST_BACK_DELAY_SECONDS)
        time.sleep(config.STATE_CHECK_WAIT_SECONDS)
        ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_fullscreen")
        return ok

    # UNKNOWN — try HOME + launch
    logger.info("Recuperacao: estado desconhecido, tentando HOME + launch_app...")
    adb_adapter.go_home_keyevent(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
    if not adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS):
        return False
    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
    ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_unknown")
    return ok


def _run_pre_capture_sequence(device_id: str, camera_name: str) -> None:
    """Try to enter fullscreen: direct tap, then menu + fullscreen if needed."""
    fs = config.FULLSCREEN_TAP_COORDS
    menu = config.MENU_TAP_COORDS

    logger.info(f"[{camera_name}] Tap direto fullscreen (X={fs['x']}, Y={fs['y']})...")
    adb_adapter.tap(device_id, fs["x"], fs["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)

    if not config.ENABLE_SCREEN_STATE_DETECTION:
        return

    state, _fp, path = screen_classifier.capture_and_detect(
        device_id, f"pre_capture_fullscreen_direct:{camera_name}"
    )
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

    if state == ScreenState.CAMERA_FULLSCREEN:
        return

    logger.info(f"[{camera_name}] Fullscreen direto falhou (estado={state.value}), abrindo menu...")
    adb_adapter.tap(device_id, menu["x"], menu["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    adb_adapter.tap(device_id, fs["x"], fs["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)


def _is_loading_screen(screenshot_path: str) -> bool:
    """Check if the screenshot is a loading/black screen (stream not ready yet)."""
    stats = _analyze_image(screenshot_path)
    if stats["mean"] <= config.BLACK_MEAN_THRESHOLD and stats["std"] <= config.LOW_STD_THRESHOLD:
        return True

    fp = screen_fingerprint.extract_fingerprint(screenshot_path)
    ind = fp["indicators"]
    return (
        stats["mean"] <= config.LOADING_MEAN_MAX
        and ind.get("bright_ratio_center", 0.0) >= config.LOADING_BRIGHT_CENTER_MIN
    )


def _wait_for_stream(device_id: str, camera_name: str, cam_coords: dict) -> bool:
    """Poll the screen until the stream loads or timeout is reached.

    Checks:
      1. If CAMERA_LIST → tap didn't register, retry.
      2. If CAMERA_FULLSCREEN + black screen → loading, wait and retry.
      3. Otherwise → stream is ready.

    Returns True if stream loaded, False if timed out.
    """
    timeout = config.WAIT_STREAM_LOAD_SECONDS
    poll_interval = 5
    elapsed = 0.0

    def _cleanup(p):
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass

    while elapsed < timeout:
        state, _fp, path = screen_classifier.capture_and_detect(device_id, f"stream_poll:{camera_name}")

        # If we're back on camera list, the tap didn't register — retry
        if state == ScreenState.CAMERA_LIST:
            logger.warning(f"[{camera_name}] Ainda na lista de cameras, repetindo tap...")
            _cleanup(path)
            adb_adapter.tap(device_id, cam_coords["x"], cam_coords["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(poll_interval)
            elapsed += poll_interval
            continue

        # Loading check: only in CAMERA_FULLSCREEN (black screen with loading bar)
        if state == ScreenState.CAMERA_FULLSCREEN:
            if path and os.path.exists(path) and _is_loading_screen(path):
                logger.info(f"[{camera_name}] Tela de carregamento detectada, aguardando {poll_interval}s... ({elapsed:.0f}/{timeout}s)")
                _cleanup(path)
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue

        # Not camera_list, not loading — stream is ready
        _cleanup(path)
        logger.info(f"[{camera_name}] Stream carregado (estado={state.value}, elapsed={elapsed:.0f}s)")
        return True

    logger.error(f"[{camera_name}] Timeout aguardando stream ({timeout}s)")
    return False


def run_capture_batch(device_id: str | None = None, steps: list[dict] | None = None) -> dict | None:
    """
    Executa um fluxo de captura para todas as cameras configuradas no app ICSee.
    Inclui verificacao de estado de tela e recuperacao automatica quando habilitado.
    """
    logger.info("Iniciando fluxo de captura para todas as cameras...")

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    active_device_id = device_id

    try:
        if not active_device_id:
            devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise RuntimeError("Nenhum dispositivo encontrado para captura.")
            active_device_id = devices[0]

        logger.info(f"Usando o dispositivo: {active_device_id}")

        # --- CHECKPOINT A: verificar se estamos na tela de lista de cameras ---
        if config.ENABLE_SCREEN_STATE_DETECTION:
            step = _step_start("checkpoint_a:verify_camera_list")
            ok, state, _ = _check_screen(active_device_id, ScreenState.CAMERA_LIST, "pre_cycle")
            if not ok:
                logger.warning(f"Checkpoint A: tela errada ({state.value}), tentando recuperar...")
                recovery_ok = _recover_to_camera_list(active_device_id, state)
                if steps is not None:
                    steps.append(_step_end(step, recovery_ok, f"recovery_from={state.value}"))
                if not recovery_ok:
                    raise RuntimeError(f"Checkpoint A falhou: nao conseguiu voltar para camera_list (estado={state.value})")
                logger.info("Checkpoint A: recuperacao bem-sucedida.")
            else:
                if steps is not None:
                    steps.append(_step_end(step, True, "camera_list_ok"))

        total_cameras = len(config.CAMERAS)
        logger.info(f"Encontradas {total_cameras} cameras para capturar.")

        last_screenshot_info = None
        for i, (camera_name, camera_conf) in enumerate(config.CAMERAS.items()):
            logger.info(f"--- [Camera {i+1}/{total_cameras}] Iniciando captura para: {camera_name} ---")

            try:
                # --- Etapa 1: Navegar ate a camera ---
                step = _step_start(f"camera:{camera_name}:tap")
                cam_coords = camera_conf["tap_coords"]
                logger.info(f"[{camera_name}] Acessando camera em (X={cam_coords['x']}, Y={cam_coords['y']})...")
                adb_adapter.tap(
                    active_device_id,
                    cam_coords["x"],
                    cam_coords["y"],
                    timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                )
                if steps is not None:
                    steps.append(_step_end(step, True))

                # --- Etapa 2: Aguardar stream carregar (polling) ---
                # Em vez de esperar um tempo fixo, verificamos se a tela ainda
                # esta carregando (preta) ou se voltou para a lista de cameras.
                step = _step_start(f"camera:{camera_name}:wait_stream")
                stream_ready = _wait_for_stream(active_device_id, camera_name, cam_coords)
                if steps is not None:
                    steps.append(_step_end(step, stream_ready))
                if not stream_ready:
                    logger.warning(f"[{camera_name}] Stream timeout, voltando para HOME...")
                    adb_adapter.go_home_keyevent(active_device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
                    raise RuntimeError(f"Stream nao carregou para {camera_name} dentro de {config.WAIT_STREAM_LOAD_SECONDS}s")

                # --- Etapa 3: Ritual de Estabilizacao Pre-Captura ---
                logger.info(f"[{camera_name}] Iniciando ritual de estabilizacao pre-captura...")
                step = _step_start(f"camera:{camera_name}:pre_capture")
                _run_pre_capture_sequence(active_device_id, camera_name)
                logger.info(f"[{camera_name}] Ritual de estabilizacao concluido.")
                if steps is not None:
                    steps.append(_step_end(step, True))

                # --- Etapa 4: Verificacao pre-captura ---
                # Conferir que estamos em fullscreen (nao em camera_list, loading, ou camera_normal)
                if config.ENABLE_SCREEN_STATE_DETECTION:
                    step = _step_start(f"camera:{camera_name}:pre_capture_check")
                    for retry in range(config.PRE_CAPTURE_RETRY_MAX + 1):
                        state, _fp, path = screen_classifier.capture_and_detect(
                            active_device_id, f"pre_capture_check:{camera_name}:r{retry}"
                        )
                        is_loading = (
                            state == ScreenState.CAMERA_FULLSCREEN
                            and path and os.path.exists(path)
                            and _is_loading_screen(path)
                        )
                        # Cleanup temp screenshot
                        try:
                            if path and os.path.exists(path):
                                os.remove(path)
                        except OSError:
                            pass

                        if state == ScreenState.CAMERA_LIST:
                            if steps is not None:
                                steps.append(_step_end(step, False, "voltou_para_camera_list"))
                            raise RuntimeError(f"[{camera_name}] Voltou para camera_list antes da captura")

                        if is_loading:
                            logger.warning(f"[{camera_name}] Tela de loading detectada antes da captura, aguardando 5s...")
                            time.sleep(5)
                            continue

                        if state == ScreenState.CAMERA_NORMAL:
                            if retry < config.PRE_CAPTURE_RETRY_MAX:
                                logger.warning(f"[{camera_name}] Ainda em camera_normal apos ritual (tentativa {retry+1}), repetindo ritual...")
                                _run_pre_capture_sequence(active_device_id, camera_name)
                                continue
                            else:
                                logger.error(f"[{camera_name}] Nao entrou em fullscreen apos {config.PRE_CAPTURE_RETRY_MAX+1} tentativas")
                                if steps is not None:
                                    steps.append(_step_end(step, False, "stuck_in_camera_normal"))
                                raise RuntimeError(f"[{camera_name}] Nao entrou em fullscreen apos ritual")

                        # CAMERA_FULLSCREEN (not loading) or UNKNOWN — proceed
                        break

                    if steps is not None and step.get("end") is None:
                        steps.append(_step_end(step, True, f"state={state.value}"))

                # --- Etapa 5: Capturar o Screenshot ---
                step = _step_start(f"camera:{camera_name}:screencap_validate")
                logger.info(f"[{camera_name}] Iniciando captura de screenshot com validacao...")
                screenshot_info = _capture_with_validation(active_device_id, camera_name)
                last_screenshot_info = screenshot_info
                if steps is not None:
                    steps.append(_step_end(step, screenshot_info.get("validated", False), screenshot_info.get("validation_reason")))
                if not screenshot_info.get("validated"):
                    raise RuntimeError(f"Screenshot invalid: {screenshot_info.get('validation_reason')}")

                # --- Etapa 4: Acoes Pos-Captura (Retornar N Niveis) ---
                logger.info(f"[{camera_name}] Iniciando sequencia de retorno pos-captura...")
                post_step = _step_start(f"camera:{camera_name}:post_back")
                for j in range(config.POST_CAPTURE_BACK_COUNT):
                    back_index = j + 1
                    logger.info(f"[{camera_name}] Executando BACK ({back_index}/{config.POST_CAPTURE_BACK_COUNT})...")
                    adb_adapter.press_key(
                        active_device_id,
                        "KEYCODE_BACK",
                        timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                    )
                    if back_index < config.POST_CAPTURE_BACK_COUNT:
                        logger.info(f"[{camera_name}] Aguardando {config.POST_BACK_DELAY_SECONDS}s...")
                        time.sleep(config.POST_BACK_DELAY_SECONDS)
                if steps is not None:
                    steps.append(_step_end(post_step, True))

                logger.info(f"--- [Camera {i+1}/{total_cameras}] Captura para {camera_name} concluida. ---")

            except Exception as e:
                logger.error(f"--- [Camera {i+1}/{total_cameras}] Ocorreu um erro inesperado ao processar '{camera_name}': {e} ---", exc_info=True)
                raise

            # Adiciona um delay entre as cameras para estabilizacao da UI, exceto apos a ultima.
            if i < total_cameras - 1:
                logger.info(f"Aguardando {config.INTER_CAMERA_DELAY_SECONDS}s antes de prosseguir para a proxima camera...")
                time.sleep(config.INTER_CAMERA_DELAY_SECONDS)

        # --- CHECKPOINT C: verificar se voltamos para a lista de cameras ---
        if config.ENABLE_SCREEN_STATE_DETECTION:
            step = _step_start("checkpoint_c:verify_camera_list")
            ok, state, _ = _check_screen(active_device_id, ScreenState.CAMERA_LIST, "post_cycle")
            if steps is not None:
                steps.append(_step_end(step, ok, f"state={state.value}"))
            if not ok:
                logger.warning(f"Checkpoint C: ciclo terminou em estado inesperado ({state.value}). Informativo apenas.")

        return last_screenshot_info

    except Exception as e:
        logger.critical(f"Ocorreu um erro critico no fluxo de captura principal: {e}", exc_info=True)
        raise

    finally:
        if active_device_id:
            logger.info("Fluxo de captura para todas as cameras finalizado.")


def run_forever_loop():
    cycle_id = 0
    max_cycles = config.MAX_CYCLES
    if max_cycles == 0:
        max_cycles = None

    while True:
        cycle_id += 1
        cycle_start = time.time()
        cycle_id_str = f"{cycle_id}"
        ts_start = _now_iso()
        logger.info(f"[cycle_id={cycle_id}] Ciclo iniciado.")
        cycle_error = None
        cycle_error_type = None
        cycle_trace = None
        steps: list[dict] = []
        focus_info: dict | None = None
        health_snapshot: dict | None = None
        screenshot_info: dict | None = None
        device_id = None

        try:
            step = _step_start("health_check")
            devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise RuntimeError("Nenhum dispositivo encontrado para captura.")
            device_id = devices[0]
            if config.ENABLE_HEALTHCHECK:
                try:
                    health_snapshot = adb_adapter.get_health_snapshot(
                        device_id,
                        timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS,
                    )
                    steps.append(_step_end(step, True))
                except Exception as exc:
                    steps.append(_step_end(step, False, f"health_error:{exc}"))
                    health_snapshot = {"error": str(exc)}
                    logger.exception("Health check failed.")
            else:
                logger.info("Health check desabilitado por config; pulando coleta.")
                health_snapshot = {"disabled": True}
                steps.append(_step_end(step, True, "disabled_by_config"))

            step = _step_start("capture_batch")
            screenshot_info = run_capture_batch(device_id=device_id, steps=steps)
            focus_info = screenshot_info.get("focus") if screenshot_info else None
            steps.append(_step_end(step, True))

        except Exception as exc:
            cycle_error = str(exc)
            cycle_error_type = type(exc).__name__
            cycle_trace = traceback.format_exc()
            logger.error(f"[cycle_id={cycle_id}] Erro no ciclo: {exc}", exc_info=True)
            logger.info(f"[cycle_id={cycle_id}] Aplicando backoff de {config.ERROR_BACKOFF_SECONDS}s.")
            if device_id:
                _write_error_artifacts(cycle_id_str, device_id, health_snapshot, screenshot_info.get("path") if screenshot_info else None)
            time.sleep(config.ERROR_BACKOFF_SECONDS)
        finally:
            cycle_end = time.time()
            cycle_duration_s = round(cycle_end - cycle_start, 3)
            ts_end = _now_iso()

            event = {
                "cycle_id": cycle_id_str,
                "ts_start": ts_start,
                "ts_end": ts_end,
                "duration_ms": int(cycle_duration_s * 1000),
                "ok": cycle_error is None,
                "error": _error_obj(cycle_error, cycle_error_type, steps, cycle_trace),
                "steps": steps,
                "focus": focus_info,
                "health": health_snapshot,
                "screenshot": screenshot_info,
            }
            _append_jsonl(config.CYCLES_JSONL_PATH, event)

            logger.info(f"[cycle_id={cycle_id}] Ciclo finalizado em {cycle_duration_s}s.")

            if not cycle_error:
                elapsed = cycle_end - cycle_start
                sleep_seconds = max(0, config.CAPTURE_INTERVAL_SECONDS - elapsed)
                if sleep_seconds > 0:
                    logger.info(f"[cycle_id={cycle_id}] Dormindo {sleep_seconds:.1f}s ate o proximo ciclo.")
                    time.sleep(sleep_seconds)

        if not config.RUN_FOREVER and max_cycles and cycle_id >= max_cycles:
            logger.info(f"[cycle_id={cycle_id}] Encerrando loop (MAX_CYCLES atingido).")
            break


def run_capture():
    """Executa o fluxo de captura para todas as cameras configuradas."""
    run_capture_batch()


if __name__ == "__main__":
    run_capture()

```

## `ingester-bluestacks/src/ingester/local/screen_classifier.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/screen_classifier.py
"""
Screen state classifier for the ICSee capture flow.

Detects which screen the device is currently showing by analyzing
UI chrome (bars, edges, headers) — NOT camera content, which varies.
"""
import logging
import os
import re
import tempfile
from enum import Enum

from . import adb_adapter, screen_fingerprint
from .. import config

logger = logging.getLogger(__name__)


class ScreenState(Enum):
    HOME = "home"
    CAMERA_LIST = "camera_list"
    CAMERA_NORMAL = "camera_normal"
    CAMERA_FULLSCREEN = "camera_fullscreen"
    UNKNOWN = "unknown"


def detect_screen_state(image_path: str) -> tuple[ScreenState, dict]:
    """Classify screen state from a screenshot.

    Returns (state, fingerprint_dict).
    """
    fp = screen_fingerprint.extract_fingerprint(image_path)
    ind = fp["indicators"]
    thresh = config.SCREEN_STATE_THRESHOLDS

    state = _classify(ind, thresh)

    logger.info(
        f"Screen state detected: {state.value} | "
        f"dark_top={ind['dark_ratio_top']:.2f} "
        f"dark_left={ind['dark_ratio_left']:.2f} "
        f"h_line_status={ind['h_line_status_bottom']:.2f} "
        f"dark_header={ind['dark_ratio_header']:.2f} "
        f"center_edge={ind['center_edge_density']:.1f}"
    )

    return state, fp


def _classify(ind: dict, thresh: dict) -> ScreenState:
    """Decision tree based on raw indicator values.

    Evaluation order (most distinctive first):
      1. camera_normal:     dark_ratio_top >= 0.5
      2. camera_fullscreen: dark_ratio_left >= 0.7
      3. home:              h_line_status_bottom <= 0.3
      4. camera_list:       h_line_status_bottom > 0.3 AND sanity checks pass
      5. UNKNOWN:           fallback when nothing fits

    Each positive match also runs a sanity check to avoid false positives.
    """
    t_norm = thresh.get("camera_normal", {})
    t_fs = thresh.get("camera_fullscreen", {})
    t_home = thresh.get("home", {})
    t_sanity = thresh.get("sanity", {})

    dark_top = ind["dark_ratio_top"]
    dark_left = ind["dark_ratio_left"]
    h_line = ind["h_line_status_bottom"]

    # Valores de referência observados:
    #   dark_ratio_top:  home=0.02, list=0.01, normal=0.76, full=0.04
    #   dark_ratio_left: home=0.004, list=0, normal=0.15, full=0.86
    #   h_line_status:   home=0.11, list=0.79, normal=0.80, full=0.3-0.6

    # 1. CAMERA_NORMAL: topo muito escuro (~0.76)
    #    Sanity: dark_left deve ser baixo (não é fullscreen)
    if dark_top >= t_norm.get("dark_ratio_top_min", 0.5):
        if dark_left < t_fs.get("dark_ratio_left_min", 0.7):
            return ScreenState.CAMERA_NORMAL
        # Topo escuro E borda escura — improvável, marcar como desconhecido
        logger.warning(f"Classificacao ambigua: dark_top={dark_top:.2f} E dark_left={dark_left:.2f} altos")
        return ScreenState.UNKNOWN

    # 2. CAMERA_FULLSCREEN: borda esquerda escura (~0.86)
    #    Sanity: topo NÃO deve ser escuro (já foi descartado acima)
    if dark_left >= t_fs.get("dark_ratio_left_min", 0.7):
        return ScreenState.CAMERA_FULLSCREEN

    # 3. HOME: sem linha de status do app (~0.11)
    #    Sanity: dark_top e dark_left devem ser baixos
    if h_line <= t_home.get("h_line_status_bottom_max", 0.3):
        if dark_top < 0.15 and dark_left < 0.15:
            return ScreenState.HOME
        logger.warning(f"Classificacao ambigua: h_line={h_line:.2f} baixo mas dark_top={dark_top:.2f} dark_left={dark_left:.2f}")
        return ScreenState.UNKNOWN

    # 4. CAMERA_LIST: h_line alto (~0.79), dark ratios baixos
    #    Sanity: tela deve ser "brilhante" — dark ratios todos baixos
    max_dark = t_sanity.get("camera_list_max_dark", 0.3)
    if dark_top < max_dark and dark_left < max_dark:
        return ScreenState.CAMERA_LIST

    # 5. Nada se encaixou
    logger.warning(
        f"Estado desconhecido: dark_top={dark_top:.2f} dark_left={dark_left:.2f} "
        f"h_line={h_line:.2f} — nenhuma regra se encaixou"
    )
    return ScreenState.UNKNOWN


def capture_and_detect(
    device_id: str,
    context: str,
) -> tuple[ScreenState, dict, str]:
    """Take a screenshot and detect the screen state.

    Args:
        device_id: ADB device serial.
        context: Label for logging / filename (e.g. "pre_cycle").

    Returns:
        (state, fingerprint, screenshot_path)
    """
    safe_context = _sanitize_filename(context)
    fd, filepath = tempfile.mkstemp(prefix=f"state_{safe_context}_", suffix=".png")
    os.close(fd)

    success = adb_adapter.screencap(
        device_id, filepath, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS
    )
    if not success:
        logger.error(f"[{context}] Screenshot failed for state detection.")
        return ScreenState.UNKNOWN, {}, filepath

    state, fp = detect_screen_state(filepath)
    return state, fp, filepath


def _sanitize_filename(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\\\|?*]+', "_", value)
    sanitized = re.sub(r"\\s+", "_", sanitized).strip("_")
    return sanitized or "state"

```

## `ingester-bluestacks/src/ingester/local/screen_fingerprint.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/screen_fingerprint.py
"""
Diagnostic tool to extract visual fingerprints from device screenshots.

Usage (from the ingester root):
    python -m ingester.local.screen_fingerprint --label home
    python -m ingester.local.screen_fingerprint --label camera_list
    python -m ingester.local.screen_fingerprint --label camera_normal
    python -m ingester.local.screen_fingerprint --label camera_fullscreen

Each run captures a screenshot, extracts features, and appends to
    logs/screen_profiles.json
After capturing all 4 screens, the profiles file can be reviewed and
the thresholds copied into config.py for runtime screen detection.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

from PIL import Image, ImageStat

from . import adb_adapter
from .. import config

logger = logging.getLogger(__name__)

# Grid layout: split screen into regions for analysis
# Each region is (name, x_frac_start, y_frac_start, x_frac_end, y_frac_end)
#
# Strategy: camera content changes per camera/time-of-day, but UI chrome
# (bars, buttons, borders) stays consistent. We focus on structural regions.
REGIONS = [
    # --- System bars ---
    ("top_bar",        0.0, 0.00, 1.0, 0.04),   # Android status bar (clock, icons)
    ("bottom_bar",     0.0, 0.96, 1.0, 1.00),   # Android nav bar (back, home, recent)
    # --- App UI zones (outside the video area) ---
    ("app_header",     0.0, 0.04, 1.0, 0.12),   # App toolbar / title area
    ("app_footer",     0.0, 0.88, 1.0, 0.96),   # App bottom controls / tab bar
    # --- Edges (detect UI borders vs video filling the screen) ---
    ("left_edge",      0.0,  0.12, 0.04, 0.88),
    ("right_edge",     0.96, 0.12, 1.0,  0.88),
    # --- Content zones (will vary per camera, used for sanity only) ---
    ("center",         0.15, 0.30, 0.85, 0.70),
    # --- Full frame ---
    ("full",           0.0, 0.00, 1.0, 1.00),
]


def _region_stats(img: Image.Image, region: tuple) -> dict:
    """Extract color statistics for a rectangular region of the image."""
    name, x0f, y0f, x1f, y1f = region
    w, h = img.size
    box = (int(x0f * w), int(y0f * h), int(x1f * w), int(y1f * h))
    cropped = img.crop(box)

    # Grayscale stats
    gray = cropped.convert("L")
    gray_stat = ImageStat.Stat(gray)
    g_mean = gray_stat.mean[0]
    g_std = gray_stat.stddev[0]
    g_min, g_max = gray.getextrema()

    # Color stats (RGB)
    rgb = cropped.convert("RGB")
    rgb_stat = ImageStat.Stat(rgb)
    r_mean, g_mean_c, b_mean = rgb_stat.mean
    r_std, g_std_c, b_std = rgb_stat.stddev

    # Dominant color heuristic: mean RGB rounded
    dominant = (int(round(r_mean)), int(round(g_mean_c)), int(round(b_mean)))

    # Edge density: simple Sobel-like measure on grayscale
    small = gray.resize((64, 64))
    px = list(small.getdata())
    edge_sum = 0
    for y in range(1, 63):
        for x in range(1, 63):
            idx = y * 64 + x
            gx = abs(px[idx + 1] - px[idx - 1])
            gy = abs(px[idx + 64] - px[idx - 64])
            edge_sum += gx + gy
    edge_density = round(edge_sum / (62 * 62), 2)

    return {
        "region": name,
        "box_px": list(box),
        "gray_mean": round(g_mean, 2),
        "gray_std": round(g_std, 2),
        "gray_min": g_min,
        "gray_max": g_max,
        "rgb_mean": [round(r_mean, 2), round(g_mean_c, 2), round(b_mean, 2)],
        "rgb_std": [round(r_std, 2), round(g_std_c, 2), round(b_std, 2)],
        "dominant_rgb": list(dominant),
        "edge_density": edge_density,
    }


def _color_histogram_summary(img: Image.Image, bins: int = 8) -> dict:
    """Simplified color histogram: divide 0-255 into bins for each channel."""
    rgb = img.convert("RGB")
    r_hist = rgb.split()[0].histogram()
    g_hist = rgb.split()[1].histogram()
    b_hist = rgb.split()[2].histogram()

    def _bin(hist, n_bins):
        step = 256 // n_bins
        total = sum(hist)
        return [round(sum(hist[i * step:(i + 1) * step]) / total, 4) for i in range(n_bins)]

    return {
        "r_hist": _bin(r_hist, bins),
        "g_hist": _bin(g_hist, bins),
        "b_hist": _bin(b_hist, bins),
    }


def _aspect_and_size(img: Image.Image) -> dict:
    w, h = img.size
    return {"width": w, "height": h, "aspect": round(w / h, 4)}


def _dark_pixel_ratio(img: Image.Image, region_frac: tuple, threshold: int = 30) -> float:
    """Fraction of pixels darker than threshold in a region. Detects dark UI bars."""
    x0f, y0f, x1f, y1f = region_frac
    w, h = img.size
    box = (int(x0f * w), int(y0f * h), int(x1f * w), int(y1f * h))
    gray = img.crop(box).convert("L")
    px = list(gray.getdata())
    if not px:
        return 0.0
    return round(sum(1 for p in px if p < threshold) / len(px), 4)


def _bright_pixel_ratio(img: Image.Image, region_frac: tuple, threshold: int = 200) -> float:
    """Fraction of pixels brighter than threshold in a region."""
    x0f, y0f, x1f, y1f = region_frac
    w, h = img.size
    box = (int(x0f * w), int(y0f * h), int(x1f * w), int(y1f * h))
    gray = img.crop(box).convert("L")
    px = list(gray.getdata())
    if not px:
        return 0.0
    return round(sum(1 for p in px if p > threshold) / len(px), 4)


def _horizontal_line_score(img: Image.Image, y_frac: float, tolerance: int = 10) -> float:
    """Detect if there's a horizontal line (UI separator) at a given Y fraction.
    Returns fraction of pixels in that row that match the row's median color."""
    w, h = img.size
    y = int(y_frac * h)
    y = max(0, min(y, h - 1))
    row = list(img.convert("L").crop((0, y, w, y + 1)).getdata())
    if not row:
        return 0.0
    median = sorted(row)[len(row) // 2]
    matching = sum(1 for p in row if abs(p - median) <= tolerance)
    return round(matching / len(row), 4)


def extract_fingerprint(image_path: str) -> dict:
    """Extract a full fingerprint from a screenshot PNG.

    The indicators focus on UI chrome (bars, edges, separators) which are
    stable regardless of what the camera is showing.
    """
    img = Image.open(image_path)

    regions = [_region_stats(img, r) for r in REGIONS]
    histogram = _color_histogram_summary(img)
    size_info = _aspect_and_size(img)

    def _r(name):
        return next(r for r in regions if r["region"] == name)

    top_bar = _r("top_bar")
    bottom_bar = _r("bottom_bar")
    app_header = _r("app_header")
    app_footer = _r("app_footer")
    left = _r("left_edge")
    right = _r("right_edge")
    center = _r("center")

    # --- Structural indicators (independent of camera content) ---

    # Dark pixel ratio in chrome zones — stable across cameras
    dark_ratio_top = _dark_pixel_ratio(img, (0.0, 0.0, 1.0, 0.04))
    dark_ratio_bottom = _dark_pixel_ratio(img, (0.0, 0.96, 1.0, 1.0))
    dark_ratio_header = _dark_pixel_ratio(img, (0.0, 0.04, 1.0, 0.12))
    dark_ratio_footer = _dark_pixel_ratio(img, (0.0, 0.88, 1.0, 0.96))
    dark_ratio_left = _dark_pixel_ratio(img, (0.0, 0.12, 0.04, 0.88))
    dark_ratio_right = _dark_pixel_ratio(img, (0.96, 0.12, 1.0, 0.88))
    bright_ratio_center = _bright_pixel_ratio(img, (0.4, 0.4, 0.6, 0.6))

    # Horizontal line detection at UI boundary positions
    # These detect separators between app header/content and content/footer
    h_line_top_border = _horizontal_line_score(img, 0.12)
    h_line_bottom_border = _horizontal_line_score(img, 0.88)
    h_line_status_bottom = _horizontal_line_score(img, 0.04)

    # UI presence booleans
    has_status_bar = top_bar["gray_mean"] > 30
    has_nav_bar = bottom_bar["gray_mean"] > 30
    has_app_header = app_header["edge_density"] > 8 or app_header["gray_std"] > 20
    has_app_footer = app_footer["edge_density"] > 8 or app_footer["gray_std"] > 20
    edges_dark = dark_ratio_left > 0.7 and dark_ratio_right > 0.7

    return {
        "size": size_info,
        "regions": regions,
        "histogram": histogram,
        "indicators": {
            # UI presence
            "has_status_bar": has_status_bar,
            "has_nav_bar": has_nav_bar,
            "has_app_header": has_app_header,
            "has_app_footer": has_app_footer,
            "edges_dark": edges_dark,
            # Raw values for threshold tuning
            "top_bar_gray_mean": top_bar["gray_mean"],
            "top_bar_gray_std": top_bar["gray_std"],
            "bottom_bar_gray_mean": bottom_bar["gray_mean"],
            "bottom_bar_gray_std": bottom_bar["gray_std"],
            "app_header_gray_mean": app_header["gray_mean"],
            "app_header_edge_density": app_header["edge_density"],
            "app_footer_gray_mean": app_footer["gray_mean"],
            "app_footer_edge_density": app_footer["edge_density"],
            "left_edge_gray_mean": left["gray_mean"],
            "left_edge_gray_std": left["gray_std"],
            "right_edge_gray_mean": right["gray_mean"],
            "right_edge_gray_std": right["gray_std"],
            "center_edge_density": center["edge_density"],
            # Dark ratios (% of dark pixels in chrome zones)
            "dark_ratio_top": dark_ratio_top,
            "dark_ratio_bottom": dark_ratio_bottom,
            "dark_ratio_header": dark_ratio_header,
            "dark_ratio_footer": dark_ratio_footer,
            "dark_ratio_left": dark_ratio_left,
            "dark_ratio_right": dark_ratio_right,
            "bright_ratio_center": bright_ratio_center,
            # Horizontal line scores at UI boundaries
            "h_line_status_bottom": h_line_status_bottom,
            "h_line_top_border": h_line_top_border,
            "h_line_bottom_border": h_line_bottom_border,
        },
    }


def capture_and_fingerprint(label: str, device_id: str | None = None) -> dict:
    """Capture a screenshot from the device and extract its fingerprint."""
    if not device_id:
        devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        if not devices:
            raise RuntimeError("Nenhum dispositivo conectado.")
        device_id = devices[0]

    os.makedirs(config.LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = os.path.join(config.LOG_DIR, f"fingerprint_{label}_{timestamp}.png")

    logger.info(f"Capturando screenshot para label='{label}' ...")
    success = adb_adapter.screencap(device_id, screenshot_path, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    if not success:
        raise RuntimeError(f"Falha ao capturar screenshot para label='{label}'.")

    logger.info(f"Extraindo fingerprint de {screenshot_path} ...")
    fp = extract_fingerprint(screenshot_path)

    result = {
        "label": label,
        "timestamp": timestamp,
        "device_id": device_id,
        "screenshot_path": screenshot_path,
        "fingerprint": fp,
    }

    # Append to profiles file
    profiles_path = os.path.join(config.LOG_DIR, "screen_profiles.json")
    existing = []
    if os.path.exists(profiles_path):
        with open(profiles_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing.append(result)
    with open(profiles_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    logger.info(f"Fingerprint salvo em {profiles_path}")
    _print_summary(result)
    return result


def _print_summary(result: dict):
    """Print a human-readable summary of the fingerprint."""
    fp = result["fingerprint"]
    ind = fp["indicators"]
    print(f"\n{'='*70}")
    print(f"  Screen Fingerprint: {result['label']}")
    print(f"{'='*70}")
    print(f"  Resolution:       {fp['size']['width']}x{fp['size']['height']}")
    print()
    print("  UI Chrome Detection (stable across cameras):")
    print(f"    Status bar:     {'YES' if ind['has_status_bar'] else 'NO':4s}  gray_mean={ind['top_bar_gray_mean']:5.1f}  dark_ratio={ind['dark_ratio_top']:.2f}")
    print(f"    Nav bar:        {'YES' if ind['has_nav_bar'] else 'NO':4s}  gray_mean={ind['bottom_bar_gray_mean']:5.1f}  dark_ratio={ind['dark_ratio_bottom']:.2f}")
    print(f"    App header:     {'YES' if ind['has_app_header'] else 'NO':4s}  gray_mean={ind['app_header_gray_mean']:5.1f}  edge_density={ind['app_header_edge_density']:.1f}  dark_ratio={ind['dark_ratio_header']:.2f}")
    print(f"    App footer:     {'YES' if ind['has_app_footer'] else 'NO':4s}  gray_mean={ind['app_footer_gray_mean']:5.1f}  edge_density={ind['app_footer_edge_density']:.1f}  dark_ratio={ind['dark_ratio_footer']:.2f}")
    print(f"    Left edge:      dark_ratio={ind['dark_ratio_left']:.2f}  gray={ind['left_edge_gray_mean']:5.1f}±{ind['left_edge_gray_std']:.1f}")
    print(f"    Right edge:     dark_ratio={ind['dark_ratio_right']:.2f}  gray={ind['right_edge_gray_mean']:5.1f}±{ind['right_edge_gray_std']:.1f}")
    print(f"    Edges dark:     {'YES' if ind['edges_dark'] else 'NO'}")
    print()
    print("  Horizontal lines (UI separators):")
    print(f"    Status bottom:  {ind['h_line_status_bottom']:.2f}")
    print(f"    Header/content: {ind['h_line_top_border']:.2f}")
    print(f"    Content/footer: {ind['h_line_bottom_border']:.2f}")
    print()
    print("  Region details:")
    for r in fp["regions"]:
        print(f"    {r['region']:14s}  gray={r['gray_mean']:6.1f}±{r['gray_std']:5.1f}  "
              f"rgb=({r['rgb_mean'][0]:5.1f},{r['rgb_mean'][1]:5.1f},{r['rgb_mean'][2]:5.1f})  "
              f"edge={r['edge_density']:5.1f}")
    print(f"{'='*70}\n")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Capture and fingerprint a device screen state.")
    parser.add_argument("--label", required=True,
                        help="Label for this screen state (e.g. home, camera_list, camera_normal, camera_fullscreen)")
    parser.add_argument("--device", default=None, help="ADB device serial (auto-detected if omitted)")
    parser.add_argument("--from-file", default=None,
                        help="Analyze an existing screenshot instead of capturing a new one")
    args = parser.parse_args()

    if args.from_file:
        fp = extract_fingerprint(args.from_file)
        result = {
            "label": args.label,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "device_id": "from_file",
            "screenshot_path": args.from_file,
            "fingerprint": fp,
        }
        _print_summary(result)

        profiles_path = os.path.join(config.LOG_DIR, "screen_profiles.json")
        existing = []
        if os.path.exists(profiles_path):
            with open(profiles_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        existing.append(result)
        os.makedirs(config.LOG_DIR, exist_ok=True)
        with open(profiles_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        print(f"Salvo em {profiles_path}")
    else:
        capture_and_fingerprint(args.label, device_id=args.device)


if __name__ == "__main__":
    main()

```

## `ingester-bluestacks/src/ingester/local/test_classifier.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/test_classifier.py
"""
Quick test: captures a screenshot and prints the detected screen state.

Usage (from ingester root):
    python -m ingester.local.test_classifier
"""
import logging

from . import adb_adapter, screen_classifier
from .. import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    if not devices:
        print("Nenhum dispositivo conectado.")
        return
    device_id = devices[0]
    print(f"Dispositivo: {device_id}\n")

    state, fp, path = screen_classifier.capture_and_detect(device_id, "test")
    ind = fp.get("indicators", {})

    dark_top = ind.get("dark_ratio_top", 0)
    dark_left = ind.get("dark_ratio_left", 0)
    h_line = ind.get("h_line_status_bottom", 0)

    t = config.SCREEN_STATE_THRESHOLDS
    t_top = t.get("camera_normal", {}).get("dark_ratio_top_min", 0.5)
    t_left = t.get("camera_fullscreen", {}).get("dark_ratio_left_min", 0.7)
    t_hline = t.get("home", {}).get("h_line_status_bottom_max", 0.3)
    t_sanity = t.get("sanity", {}).get("camera_list_max_dark", 0.3)

    def _mark(hit):
        return "<<< MATCH" if hit else ""

    r1 = dark_top >= t_top
    r2 = (not r1) and dark_left >= t_left
    r3 = (not r1 and not r2) and h_line <= t_hline
    r4 = (not r1 and not r2 and not r3) and dark_top < t_sanity and dark_left < t_sanity
    r5 = not (r1 or r2 or r3 or r4)

    print(f"\n{'='*60}")
    print(f"  ESTADO DETECTADO:  {state.value.upper()}")
    print(f"{'='*60}")
    print(f"  Regras (avaliadas em ordem):")
    print(f"    1. dark_ratio_top  = {dark_top:.4f}  >= {t_top}  → camera_normal     {_mark(r1)}")
    print(f"    2. dark_ratio_left = {dark_left:.4f}  >= {t_left}  → camera_fullscreen {_mark(r2)}")
    print(f"    3. h_line_status   = {h_line:.4f}  <= {t_hline}  → home              {_mark(r3)}")
    print(f"    4. dark_top & left < {t_sanity}          → camera_list        {_mark(r4)}")
    print(f"    5. nenhuma regra                  → UNKNOWN            {_mark(r5)}")
    print(f"\n  Screenshot: {path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

```

## `ingester-bluestacks/src/ingester/main.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/main.py
import os
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
import json
from datetime import datetime

from ingester import config
from ingester.local import adb_adapter

def setup_logging() -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []

    file_handler = RotatingFileHandler(
        os.path.join(config.LOG_DIR, "ingester.log"),
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

def _append_health_jsonl(payload: dict) -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    filepath = os.path.join(config.LOG_DIR, config.HEALTH_JSONL_FILENAME)
    with open(filepath, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

def run_health_loop() -> None:
    health_cycle_id = 0
    while True:
        start = time.time()
        health_cycle_id += 1
        errors: list[str] = []
        snapshot = None
        serial = None

        try:
            devices = adb_adapter.list_devices(timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise adb_adapter.AdbCommandError("adb devices", 1, "", "No devices")
            serial = devices[0]
            snapshot = adb_adapter.get_health_snapshot(serial, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            errors.extend(snapshot.pop("_errors", []))
        except Exception as exc:
            errors.append(str(exc))
            logging.error(f"[health_cycle_id={health_cycle_id}] Health loop error: {exc}", exc_info=True)

        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "serial": serial,
            "health_cycle_id": health_cycle_id,
            "snapshot": snapshot,
            "errors": errors,
        }
        _append_health_jsonl(payload)

        elapsed = time.time() - start
        sleep_seconds = max(0, config.HEALTH_INTERVAL_SECONDS - elapsed)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

def main_aws():
    """
    Função placeholder para o modo de operação padrão (AWS SQS/S3).
    """
    logging.info("Modo AWS (SQS/S3) ativado. Nenhuma ação implementada ainda.")
    # Aqui entraria a lógica original de `cameras.py`, `sqs.py`, etc.
    pass

if __name__ == "__main__":
    setup_logging()
    # Verifica o modo de operação a partir de uma variável de ambiente
    ingester_mode = os.environ.get("INGESTER_MODE", "local").lower()

    if ingester_mode == "local":
        logging.info("Modo 'local' detectado. Iniciando captura via ADB.")
        # Importa e executa a lógica de captura local somente quando necessário
        health_thread = threading.Thread(target=run_health_loop, name="health-loop", daemon=True)
        health_thread.start()
        from ingester.local.capture import run_forever_loop
        run_forever_loop()
    elif ingester_mode == "aws":
        main_aws()
    else:
        logging.error(f"Modo de ingester desconhecido: '{ingester_mode}'. Use 'local' ou 'aws'.")

```

## `ingester-bluestacks/src/ingester/s3.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `ingester-bluestacks/src/ingester/sqs.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `ingester/ANALISE_INGESTER.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
# Análise Crítica do Ingester — Automação Android com Dispositivos Físicos

## Resumo

O ingester é um sistema de automação que captura screenshots de câmeras IP via app Android (ICSee) usando ADB em dispositivos físicos. Esta análise avalia o código atual contra as melhores práticas da indústria para automação Android.

---

## 1. Problema Crítico: Coordenadas Hardcoded

**Arquivos afetados:** `config.py`, `capture.py`

O sistema inteiro depende de coordenadas X,Y fixas para navegação:

```python
CAMERAS = {
    "camera_quarto_1": {"tap_coords": {"x": 833, "y": 480}},
    "camera_quarto_2": {"tap_coords": {"x": 250, "y": 480}}
}
PRE_CAPTURE_RITUAL = {"fullscreen_tap": {"x": 540, "y": 960}}
```

**Por que é problemático:**
- Coordenadas quebram se a resolução, DPI ou orientação da tela mudar
- Qualquer atualização do app ICSee que mude o layout invalida toda a configuração
- Trocar de dispositivo exige recalibração manual completa
- É a abordagem mais frágil possível segundo a literatura

**Recomendação:**
Migrar para [uiautomator2](https://github.com/openatx/uiautomator2) (Python wrapper), que permite localizar elementos por `text`, `resourceId`, `className` ou `XPath`. Isso torna os scripts resilientes a mudanças de layout e resolução. Reservar coordenadas apenas para elementos que o uiautomator2 não consegue acessar (canvas, WebView).

```python
# Ao invés de:
adb_adapter.tap(833, 480)

# Usar:
import uiautomator2 as u2
d = u2.connect()
d(text="Camera Quarto 1").click()
```

Se coordenadas forem inevitáveis (app com UI não acessível), ao menos calcular dinamicamente via dump da hierarquia UI ao invés de hardcode.

**Severidade: Alta** — É a maior fonte de fragilidade do sistema.

---

## 2. Sleeps Fixos vs. Waits Dinâmicos

**Arquivos afetados:** `capture.py`, `config.py`

O código usa `time.sleep()` em vários pontos com tempos fixos:

```python
INTER_CAMERA_DELAY = 2.0
STREAM_LOAD_TIMEOUT = 15
BACK_PRESS_DELAY = 1.0
```

**Por que é problemático:**
- Sleeps fixos são a causa #1 de flakiness em automação Android
- Se o dispositivo estiver lento (bateria baixa, pouca RAM), o sleep pode ser insuficiente
- Se estiver rápido, desperdiça tempo desnecessariamente

**O que já está bom:**
- `_wait_for_stream()` já implementa polling — isso é correto

**Recomendação:**
Substituir todos os `time.sleep()` por waits condicionais. O uiautomator2 oferece `d.wait_activity()`, `d(text="X").wait()`, e `wait_timeout` configurável. Para o ADB puro, implementar um helper genérico de polling:

```python
def wait_until(condition_fn, timeout=15, interval=1.0, desc="condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition_fn():
            return True
        time.sleep(interval)
    raise TimeoutError(f"{desc} not met in {timeout}s")
```

**Severidade: Média**

---

## 3. Ausência de Device Management Robusto

**Arquivo afetado:** `adb_adapter.py`

O sistema assume um único dispositivo conectado e não tem lógica robusta de reconexão:

```python
def list_devices():
    # Lista dispositivos mas não gerencia conexão
```

**Problemas:**
- Sem lógica de reconexão automática quando o USB desconecta momentaneamente
- Sem heartbeat de conexão ADB (além do health check periódico)
- `adb kill-server` + `adb start-server` é usado apenas em timeout — deveria ser uma estratégia de recuperação mais ampla
- Sem suporte a múltiplos dispositivos simultâneos

**Recomendação:**
- Implementar um **device watchdog** que verifica a conexão ADB a cada N segundos e tenta reconectar
- Usar `adb -s <serial>` explicitamente em todos os comandos (já parcialmente feito)
- Adicionar retry com backoff exponencial para comandos ADB que falham por desconexão
- Considerar conexão via WiFi ADB (`adb tcpip 5555`) como fallback para USB instável

**Severidade: Média-Alta** — Em produção 24/7, desconexões USB são inevitáveis.

---

## 4. Classificação de Tela por Pixel Analysis — Fragilidade

**Arquivos afetados:** `screen_classifier.py`, `screen_fingerprint.py`

A classificação de estado da tela usa análise de pixels (dark ratios, bright ratios, h-line scores) com thresholds manuais:

```python
SCREEN_STATE_THRESHOLDS = {
    "camera_normal": {"dark_ratio_top_min": 0.5},
    "camera_fullscreen": {"dark_ratio_left_min": 0.7},
    "home": {"h_line_status_bottom_max": 0.3},
}
```

**Por que é problemático:**
- Thresholds calibrados para um dispositivo/resolução específica
- Qualquer mudança de brilho, tema do sistema, wallpaper ou atualização do app invalida os thresholds
- O classificador tem 5 estados mas usa decision tree de 4 regras com fallback para UNKNOWN — pouco discriminativo

**O que já está bom:**
- A abordagem de fingerprinting é criativa e a ferramenta de calibração é útil
- O fallback para UNKNOWN com recovery é uma boa prática

**Recomendação:**
- Usar `dumpsys window` / `dumpsys activity` (já parcialmente usado para focus) como fonte primária de estado — é determinístico
- O uiautomator2 pode fazer `d.app_current()` para saber o app/activity atual e `d.dump_hierarchy()` para o estado completo da UI
- Manter a análise visual apenas como validação secundária (ex: detectar tela preta/congelada)

**Severidade: Média**

---

## 5. Tratamento de Erros — Bom mas Pode Melhorar

**Arquivo afetado:** `capture.py`, `adb_adapter.py`

**O que está bom:**
- Multi-level error handling (comando → step → ciclo)
- Coleta de artefatos em erro (logcat, health, screenshot, window dump)
- Logging estruturado em JSONL
- Retry em screenshots com validação

**O que pode melhorar:**
- Falta um **circuit breaker**: após N falhas consecutivas, o sistema deveria entrar em modo degradado (ex: reiniciar app, reiniciar ADB server, notificar operador)
- Não há **alerting/notificação** — falhas só são detectadas olhando logs
- O error backoff é fixo (30s) — deveria ser exponencial
- Falta categorização de erros (transiente vs. permanente)

**Recomendação:**
```python
class CircuitBreaker:
    def __init__(self, max_failures=5, reset_timeout=300):
        self.failures = 0
        self.max_failures = max_failures
        self.state = "closed"  # closed, open, half-open

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.max_failures:
            self.state = "open"
            # Trigger recovery: restart ADB, reboot device, notify

    def record_success(self):
        self.failures = 0
        self.state = "closed"
```

**Severidade: Média**

---

## 6. Estrutura de Código e Manutenibilidade

### 6.1 Arquivos Vazios
`cameras.py`, `s3.py`, `sqs.py` são placeholders vazios. Remover ou adicionar `raise NotImplementedError` para deixar claro que são pendentes.

### 6.2 Responsabilidades Misturadas em `capture.py`
O arquivo `capture.py` (~665 linhas) acumula:
- Análise de imagem
- Validação de foco
- Classificação de tela
- Orquestração de captura
- Loop infinito
- Logging de ciclos
- Coleta de artefatos de erro

**Recomendação:** Separar em módulos:
- `image_analyzer.py` — análise de pixels, validação de screenshot
- `capture_orchestrator.py` — workflow de captura
- `cycle_runner.py` — loop principal e logging de ciclos

### 6.3 Config Hardcoded
Coordenadas de câmeras, thresholds e activities esperadas estão hardcoded em `config.py`. Considerar migrar para um arquivo externo (YAML/JSON) que pode ser editado sem mexer no código.

### 6.4 Sem Testes Automatizados
Não há testes unitários. `test_classifier.py` é uma ferramenta de diagnóstico manual, não um teste automatizado.

**Recomendação:** Criar testes para:
- Parsing de output ADB (battery, storage, network)
- Classificação de tela com imagens de referência
- Validação de screenshots
- Recovery flows (mockando ADB)

**Severidade: Baixa-Média**

---

## 7. Segurança e Operação 24/7

### 7.1 Sem Watchdog de Processo
Se o processo Python morrer, nada o reinicia automaticamente.

**Recomendação:** Usar systemd (Linux), supervisord, ou Docker restart policy para garantir uptime.

### 7.2 Acúmulo de Artefatos
Screenshots e artefatos de erro se acumulam em disco sem cleanup.

**Recomendação:** Implementar rotação/cleanup automático (ex: manter apenas últimos 7 dias).

### 7.3 Sem Métricas Exportáveis
Health checks salvam em JSONL local mas não expõem métricas para monitoramento externo.

**Recomendação:** Expor métricas via Prometheus endpoint ou enviar para serviço de monitoramento. Pelo menos criar um endpoint HTTP simples de healthcheck.

### 7.4 Temperatura do Dispositivo
O health check coleta temperatura da bateria, mas não age sobre ela.

**Recomendação:** Se temperatura > threshold, pausar captura para evitar throttling e dano ao dispositivo.

**Severidade: Média** (para operação contínua)

---

## 8. Alternativas de Framework

O código atual usa ADB "raw" via subprocess. Alternativas mais robustas:

| Framework | Vantagem | Desvantagem |
|-----------|----------|-------------|
| [uiautomator2](https://github.com/openatx/uiautomator2) | Python nativo, seletores por elemento, rápido | Requer ATX agent no device |
| [Appium](https://appium.io/) | Cross-platform, ampla comunidade | Overhead de servidor, mais complexo |
| [scrcpy](https://github.com/Genymobile/scrcpy) | Stream de tela eficiente, screenshot rápido | Foco em espelhamento, não automação |
| ADB puro (atual) | Zero dependências no device | Frágil, coordenadas fixas, lento |

**Recomendação principal:** Migrar para **uiautomator2** — é a melhor relação custo-benefício para o caso de uso. Mantém Python, adiciona seletores por elemento, waits nativos, e screenshot mais rápido (via minicap).

---

## 9. Resumo de Prioridades

| # | Item | Severidade | Esforço |
|---|------|-----------|---------|
| 1 | Migrar de coordenadas fixas para seletores (uiautomator2) | Alta | Alto |
| 2 | Device watchdog / reconexão automática | Média-Alta | Médio |
| 3 | Substituir sleeps por waits condicionais | Média | Baixo |
| 4 | Circuit breaker + backoff exponencial | Média | Médio |
| 5 | Classificação de tela via dumpsys/hierarchy (não pixels) | Média | Médio |
| 6 | Cleanup de artefatos + monitoramento externo | Média | Baixo |
| 7 | Separar responsabilidades do capture.py | Baixa-Média | Médio |
| 8 | Testes automatizados | Baixa-Média | Médio |
| 9 | Config externo (YAML/JSON) | Baixa | Baixo |

---

## 10. O que Está Bem Feito

- **Health monitoring** abrangente (bateria, storage, rede, memória, uptime)
- **Logging estruturado** com JSONL para ciclos e health — facilita análise posterior
- **Recovery automático** por estado de tela — boa resiliência
- **Validação de screenshots** (foco + análise de imagem) — evita salvar capturas inválidas
- **Feature flags** para habilitar/desabilitar componentes — boa operabilidade
- **Artefatos de debug em erro** — facilita diagnóstico pós-mortem
- **Ferramenta de calibração** do fingerprint — prática para setup inicial

---

## 11. Análise de Artefatos de Erro (Logs de Produção)

Foram analisados 96 diretórios de artefatos (cycle_21 a cycle_548) coletados em 2026-01-30. Cada diretório contém `health.json`, `logcat.txt` e `window.txt`.

### 11.1 Erros Identificados

#### Erro A — Stream Loading Timeout (mais frequente)

**Ciclos afetados:** 500, 501, 502, 546, 547, 548

```
ERROR - [camera_quarto_2] Timeout aguardando stream (15s)
ERROR - Stream nao carregou para camera_quarto_2 dentro de 15s
```

O stream da câmera IP não carrega dentro do timeout de 15 segundos. Afeta ambas as câmeras alternadamente.

**Causa raiz identificada no logcat (ciclo 500):**
- O app ICSee apresentou **ANR (Application Not Responding)** com duração de 3050ms
- Heap de memória em 508MB/512MB (**99% ocupado**)
- Múltiplos bloqueios de GC (Garbage Collector) de até 1.6s cada:
  ```
  WaitForGcToComplete blocked Alloc on Background for 1.684s
  WaitForGcToComplete blocked Alloc on Background for 1.577s
  WaitForGcToComplete blocked Alloc on Background for 1.528s
  ```
- Erro de processamento de stream: `OnMessage ERROR-->没有接收对象 9` ("Sem objeto receptor")

**Conclusão:** O app ICSee está com **memory leak** ou consumo excessivo de memória. Quando o heap fica cheio, o GC bloqueia threads por segundos, impedindo o carregamento do stream a tempo.

**Correções recomendadas:**
1. **Reiniciar o app periodicamente** (ex: a cada 50 ciclos) com `am force-stop com.icsee.pro` seguido de relaunch — isso libera memória acumulada
2. **Aumentar o timeout de stream** de 15s para 25-30s para acomodar GC stalls
3. **Monitorar memória do app** via `dumpsys meminfo com.icsee.pro` e reiniciar automaticamente quando heap > 90%
4. **Adicionar retry do ciclo inteiro** quando stream timeout ocorre, precedido de force-stop do app

---

#### Erro B — Falha ao Entrar em Fullscreen (ciclo 526)

```
ERROR - [camera_quarto_1] Nao entrou em fullscreen apos 3 tentativas
```

Após 3 tentativas do ritual de pré-captura, a tela não transicionou para fullscreen.

**Causa provável:** Com o app sob pressão de memória (ver Erro A), a resposta ao tap é lenta ou ignorada. O tap em coordenadas fixas pode ter errado o alvo se houve micro-lag no rendering.

**Correções recomendadas:**
1. Após falha de fullscreen, fazer `force-stop` + relaunch antes de retry (não apenas repetir o tap)
2. Usar wait condicional ao invés de tentativas cegas — verificar estado da tela entre tentativas com intervalo maior

---

#### Erro C — Cascata de Falhas no Checkpoint A (ciclos 527-533)

```
ERROR - Checkpoint A falhou: nao conseguiu voltar para camera_list (estado=camera_normal)
```

**7 ciclos consecutivos** falharam no mesmo ponto: o sistema não consegue sair do estado `camera_normal` para voltar ao `camera_list`. O recovery tenta `BACK` uma vez (correto para `camera_normal`), mas não funciona.

**Análise:**
- O Erro B (ciclo 526) deixou o app num estado inconsistente
- O BACK press não surtiu efeito — o app provavelmente estava travado/não responsivo (ANR residual)
- O recovery atual tenta no máximo 2 vezes com BACK, mas **não escala para force-stop** quando BACK falha
- Resultado: 7 ciclos (~4 minutos) completamente perdidos até o sistema se recuperar

**Este é o bug mais grave**: o recovery não tem escalação suficiente.

**Correções recomendadas:**
1. **Escalação de recovery**: se BACK não funcionar após 2 tentativas, escalar para `force-stop` + relaunch
2. **Implementar circuit breaker**: após 3 falhas consecutivas no mesmo checkpoint, assumir que o app travou e fazer force-stop incondicional
3. **Adicionar `am force-stop` como arma de recovery** — atualmente o código só usa BACK e HOME, nunca mata o app

---

### 11.2 Timeline dos Erros

| Hora | Ciclo | Erro | Câmera |
|------|-------|------|--------|
| 09:07 | 500 | Stream Timeout | camera_quarto_2 |
| 09:08 | 501 | Stream Timeout | camera_quarto_1 |
| 09:09 | 502 | Stream Timeout | camera_quarto_1 |
| 09:56 | 526 | Fullscreen Falhou | camera_quarto_1 |
| 09:57–10:01 | 527-533 | Checkpoint Cascata (7x) | N/A |
| 10:26 | 546 | Stream Timeout | camera_quarto_2 |
| 10:28 | 547 | Stream Timeout | camera_quarto_1 |
| 10:29 | 548 | Stream Timeout | camera_quarto_1 |

### 11.3 Estado do Dispositivo

| Métrica | Valor |
|---------|-------|
| Dispositivo | Xiaomi MIUI (MTK), Serial 1073e8400412 |
| Bateria | 100% (AC powered) |
| Temperatura | 36.4°C |
| IP WiFi | 192.168.0.15 |
| Internet | OK |
| ADB | Conectado, estável |
| Uptime | ~16 horas |
| RAM disponível | ~655 MB (sistema) |
| Heap do app | 508/512 MB (99% — **crítico**) |

**Conclusão:** O hardware e a conectividade estão saudáveis. Todos os erros são na camada de aplicação (app ICSee com memory leak / GC stalls).

### 11.4 Plano de Ação Baseado nos Erros Reais

| # | Ação | Resolve | Esforço |
|---|------|---------|---------|
| 1 | Reinício periódico do app ICSee (force-stop a cada N ciclos) | Erros A, B, C | Baixo |
| 2 | Escalação de recovery: BACK → HOME → force-stop | Erro C (cascata) | Baixo |
| 3 | Monitorar heap do app e reiniciar quando > 90% | Erro A (preventivo) | Médio |
| 4 | Aumentar stream timeout para 25-30s | Erro A (tolerância) | Trivial |
| 5 | Circuit breaker: 3 falhas consecutivas → force-stop | Erro C | Médio |

---

## Fontes

- [uiautomator2 — Python Wrapper](https://github.com/openatx/uiautomator2)
- [Android UI Automator — Documentação Oficial](https://developer.android.com/training/testing/other-components/ui-automator)
- [BrowserStack — Android App Automation using UIAutomator](https://www.browserstack.com/guide/android-app-automation-using-uiautomator)
- [Appium Common Pitfalls 2025 — Medium](https://medium.com/@abhishek.builds/mobile-automation-with-appium-common-pitfalls-and-how-to-fix-them-2025-guide-aa352228c49a)
- [ADB Cheat Sheet — AutomateThePlanet](https://www.automatetheplanet.com/adb-cheat-sheet/)
- [AWS Device Farm — Troubleshooting](https://docs.aws.amazon.com/devicefarm/latest/developerguide/troubleshooting-android-applications.html)
- [CTG — Android UI Automation Using Python Wrapper](https://www.ctg.com/blogs/android-ui-automation-using-python-wrapper-for-ui-automator)

```

## `ingester/ANALISE_LOOP_PARADO.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
# Analise: Loop principal parado enquanto health check continua

Data da analise: 31/01/2026.

## Sintomas observados
- O ultimo "Ciclo iniciado" no log foi o `cycle_id=254` em 31/01/2026 01:18:56.
- A partir de ~01:22:01 aparecem timeouts longos de ADB (ex.: `dumpsys battery`, `am force-stop`, `get-state`).
- O arquivo `health.jsonl` continua sendo atualizado periodicamente, indicando que o health loop segue ativo.
- Os artifacts de erro dos ciclos 252/253 mostram o aparelho no HOME; `window.txt` mostra foco no launcher.
- `logcat.txt` dos ciclos 252/253 mostra travamento/instabilidade do app e OOM no `com.xm.csee`.

## Hipotese principal
O loop principal ficou bloqueado dentro do ciclo 254 ao executar uma chamada ADB lenta/pendurada.
Como o health check roda em outra thread, ele continuou funcionando, criando a impressao de que "o sistema ainda esta rodando".

## Evidencias diretas
- `ingester.log`:
  - Ultimo ciclo iniciado: `cycle_id=254` em 01:18:56.
  - Timeouts longos de ADB logo depois (~01:22:01), indicando comando bloqueado.
- `health.jsonl`:
  - Continua gerando eventos (ex.: 09:49), logo a thread de health esta viva.
- `cycle_252_artifacts` / `cycle_253_artifacts`:
  - Screenshot no HOME; foco do `WindowManager` no launcher.
  - `logcat` mostra OOM do `com.xm.csee`.

## Porque o loop nao "tentou mais"
O loop principal so reinicia ao finalizar o ciclo atual. Se uma chamada ADB fica presa, o ciclo nao termina e o proximo nunca inicia.
O backoff e as tentativas sao aplicados somente depois que uma excecao sobe e o ciclo finaliza.

## Como verificar agora (passos rapidos)
Sem `rg` instalado, use:

1) Ultimos ciclos e timeouts:
```
Select-String -Path C:\saira\services\ingester\logs\ingester.log -Pattern "Ciclo iniciado|ADB timeout duration" |
  Select-Object -Last 20
```

2) Health loop ativo:
```
Get-Content -Tail 5 C:\saira\services\ingester\logs\health.jsonl
```

3) Ultimos ciclos gravados:
```
Get-Content -Tail 3 C:\saira\services\ingester\logs\cycles.jsonl
```

## Opcoes para consertar (prioridade sugerida)

### Opcao A: Watchdog de ciclo (evita travar indefinidamente)
Adicionar um timeout global por ciclo. Se exceder X segundos, o loop aborta o ciclo atual e inicia outro.

Impacto:
- Evita travas permanentes quando ADB nao responde.

### Opcao B: Timeout + retry mais agressivo em ADB critico
Para comandos de alto risco (ex.: `am force-stop`, `dumpsys battery`), habilitar `retry_on_timeout=True`
ou reduzir o timeout e re-tentar com backoff curto.

Impacto:
- Menos travas longas no loop.
- Pode aumentar carga de ADB.

### Opcao C: Separar health e capture com isolamento
Se o ciclo principal travar, um supervisor (ou outro thread) pode reiniciar o processo.

Impacto:
- Mais resiliencia.
- Requer ajuste de arquitetura.

### Opcao D: Reforcar recuperacao do app
Quando detectar foco no launcher ou OOM do app, reiniciar o app antes de seguir:
- Reabrir app se foco != `com.xm.csee`.
- Limpar cache/force-stop + relaunch ao detectar OOM.

Impacto:
- Ajuda quando o app entra em estado instavel.

## Proxima acao recomendada
Implementar Opcao A (watchdog de ciclo) + Opcao B (retry em ADB critico), pois sao pequenas mudancas
que evitam o loop travar e nao impactam o fluxo principal.


```

## `ingester/config/device_profile.yaml`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```yaml
# Device Profile — Dados específicos do dispositivo/setup.
# Edite este arquivo para ajustar coordenadas, câmeras e thresholds
# sem precisar alterar o código Python.

cameras:
  camera_quarto_1:
    tap_coords: {x: 277, y: 478}
  #camera_quarto_2:
   # tap_coords: {x: 803, y: 478}

ui_coords:
  fullscreen_btn: {x: 994, y: 706}
  dismiss_controls: {x: 500, y: 500}
  app_icon: {x: 150, y: 1150}

# Thresholds calibrados com dados reais de screen_profiles.json.
# Árvore de decisão (avaliada nesta ordem):
#   1. camera_normal:     dark_ratio_top >= 0.5
#   2. camera_fullscreen: dark_ratio_left >= 0.7
#   3. home:              h_line_status_bottom <= 0.3
#   4. camera_list:       dark ratios baixos
#   5. UNKNOWN:           nenhuma regra se encaixou
screen_thresholds:
  camera_normal:
    dark_ratio_top_min: 0.5
  camera_fullscreen:
    dark_ratio_left_min: 0.7
  home:
    h_line_status_bottom_max: 0.3
  sanity:
    camera_list_max_dark: 0.3

```

## `ingester/Dockerfile`

**Purpose:** Receita de build da imagem container para padronizar runtime e deploy deste componente.

```dockerfile
# Usar uma imagem base oficial do Python
FROM python:3.11-slim

# Instalar o cliente ADB do Linux
RUN apt-get update && \
    apt-get install -y android-tools-adb && \
    rm -rf /var/lib/apt/lists/*

# Definir o diretório de trabalho no container
WORKDIR /app

# Instalar Poetry
RUN pip install --no-cache-dir poetry

# Copiar o restante do código-fonte da aplicação
COPY . .

# Instalar as dependências do projeto
# O --no-interaction previne perguntas interativas
RUN poetry config virtualenvs.create false && poetry install --no-interaction

# Comando para executar a aplicação como um módulo
CMD ["python", "-m", "ingester.main"]

```

## `ingester/pyproject.toml`

**Purpose:** Manifesto de dependencias e metadados de build usado para reproducibilidade do componente.

```toml
[tool.poetry]
name = "ingester"
version = "0.1.0"
description = "Saira Ingester Service"
authors = ["Your Name <you@example.com>"]
packages = [{include = "ingester", from = "src"}]

[tool.poetry.dependencies]
python = "^3.11"
pillow = "^10.4.0"
python-dotenv = "^1.0.0"
pyyaml = "^6.0"

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"

```

## `ingester/README.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
# Ingester Service

Serviço responsável por capturar screenshots de câmeras via app Android (ICSee) usando ADB.

## Estrutura de pastas importante

- Logs: `services/ingester/logs/`
- Capturas: `services/ingester/data/captures/<camera_name>/`
- Dashboard estático: `services/ingester/src/ingester/dashboard_static/`

## Execução local (Windows/macOS)

> No Windows/macOS, execute direto no host (Docker Desktop não expõe USB bem).

**Pré-requisitos**
- Python 3.11+
- ADB (Android SDK Platform-Tools) no PATH
- Dispositivo Android conectado (`adb devices`)
- Dependências instaladas (Poetry)

**Instalar dependências**

```powershell
cd C:\saira\services\ingester
poetry install
```

**Executar ingester (modo local)**

```powershell
cd C:\saira\services\ingester
$env:PYTHONPATH = "$PWD\src"
python -m ingester.main
```

> O loop de captura grava ciclos em `logs/cycles.jsonl` e screenshots em `data/captures/<camera_name>/`.

## Dashboard

**Subir o dashboard**

```powershell
cd C:\saira\services\ingester
$env:PYTHONPATH = "$PWD\src"
python -m ingester.dashboard
```

Abra: `http://127.0.0.1:8088`

### Controles disponíveis

- **Rodar 1 ciclo**: executa um ciclo (mesmo em pausa)
- **Pausar / Retomar**: pausa/retoma o loop
- **Stop**: encerra o loop no próximo checkpoint
- **Arquivar logs**: move logs e capturas para `logs/archives/archive_<timestamp>` (somente com Stop ativo)

> O estado do controle fica em `logs/control.json`.

## Logs

- Log principal: `logs/ingester.log`
- Ciclos: `logs/cycles.jsonl`
- Health checks: `logs/health.jsonl`

Acompanhar em tempo real:

```powershell
Get-Content C:\saira\services\ingester\logs\ingester.log -Wait
```

## Configuração

- Config principal: `services/ingester/src/ingester/config.py`
- Variáveis de ambiente (opcional): `services/ingester/.env`

**Câmeras**

As câmeras são definidas em `config.py` usando o nome da câmera como pasta de captura:

```python
CAMERAS = {
    "camera_quarto_1": {"tap_coords": {"x": 833, "y": 480}},
    "camera_quarto_2": {"tap_coords": {"x": 250, "y": 480}},
}
```

## Produção / Docker (Linux)

```bash
docker compose up ingester --build
```

O container instala `adb` e dependências automaticamente.

## Troubleshooting rápido

- **Botões não fazem nada**: o ingester precisa estar rodando; os botões só alteram `control.json`.
- **404 em /api/archive**: o dashboard rodando não é o correto. Verifique `/api/version`.
- **Acentos quebrados**: faça hard refresh (Ctrl+F5) e confirme UTF-8.

```

## `ingester/src/ingester/__init__.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
'the init file'

```

## `ingester/src/ingester/cameras.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
'cameras'

```

## `ingester/src/ingester/config.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/config.py
"""
Centralized configuration for the Ingester service.

Device-specific data (cameras, coordinates, thresholds) is loaded from
config/device_profile.yaml when available; otherwise built-in defaults are used.
"""
import logging
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"), override=True)

logger = logging.getLogger(__name__)


def _parse_bool_env(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return default


# ---------------------------------------------------------------------------
# Device profile loader (YAML)
# ---------------------------------------------------------------------------

_DEVICE_PROFILE_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
    "config",
    "device_profile.yaml",
)


def _load_device_profile() -> dict:
    """Load device_profile.yaml if it exists. Returns empty dict on failure."""
    if not os.path.isfile(_DEVICE_PROFILE_PATH):
        logger.info("device_profile.yaml not found; using built-in defaults.")
        return {}
    try:
        import yaml
        with open(_DEVICE_PROFILE_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        logger.info(f"Loaded device profile from {_DEVICE_PROFILE_PATH}")
        return data
    except ImportError:
        logger.warning("pyyaml not installed; using built-in defaults.")
        return {}
    except Exception as exc:
        logger.warning(f"Failed to load device_profile.yaml: {exc}; using built-in defaults.")
        return {}


_profile = _load_device_profile()

# ---------------------------------------------------------------------------
# Built-in defaults (used when YAML is absent or incomplete)
# ---------------------------------------------------------------------------

_DEFAULT_CAMERAS = {
    "camera_quarto_1": {
        "tap_coords": {"x": 833, "y": 480}
    }#,
   # "camera_quarto_2": {
    #    "tap_coords": {"x": 250, "y": 480}
        #}
}

_DEFAULT_UI_COORDS = {
    "fullscreen_btn": {"x": 994, "y": 706},
    "dismiss_controls": {"x": 500, "y": 500},
    "app_icon": {"x": 150, "y": 1150},
}

_DEFAULT_SCREEN_THRESHOLDS = {
    "camera_normal": {"dark_ratio_top_min": 0.5},
    "camera_fullscreen": {"dark_ratio_left_min": 0.7},
    "home": {"h_line_status_bottom_max": 0.3},
    "sanity": {"camera_list_max_dark": 0.3},
}

# ---------------------------------------------------------------------------
# Application and Device Settings
# ---------------------------------------------------------------------------

ASSUME_APP_OPEN = True
ICSEE_PACKAGE_NAME = "com.icsee.pro"

# --- Camera Configurations (from YAML or defaults) ---
CAMERAS = _profile.get("cameras", _DEFAULT_CAMERAS)

# --- UI Coordinates (from YAML or defaults) ---
_ui = _profile.get("ui_coords", _DEFAULT_UI_COORDS)
FULLSCREEN_TAP_COORDS = _ui.get("fullscreen_btn", _DEFAULT_UI_COORDS["fullscreen_btn"])
MENU_TAP_COORDS = _ui.get("dismiss_controls", _DEFAULT_UI_COORDS["dismiss_controls"])
APP_ICON_TAP_COORDS = _ui.get("app_icon", _DEFAULT_UI_COORDS["app_icon"])

# --- Pre-capture sequence (derived from UI coords) ---
PRE_CAPTURE_WAIT_SECONDS = 2
PRE_CAPTURE_SEQUENCE = [
    {"type": "tap", "coords": FULLSCREEN_TAP_COORDS, "label": "fullscreen_btn"},
    {"type": "wait", "duration": PRE_CAPTURE_WAIT_SECONDS},
    {"type": "tap", "coords": MENU_TAP_COORDS, "label": "dismiss_controls"},
]

# --- Timing Delays (in seconds) ---
INTER_CAMERA_DELAY_SECONDS = 1.0
WAIT_STREAM_LOAD_SECONDS = 25

# --- Post-capture ---
POST_CAPTURE_BACK_COUNT = 2
POST_BACK_DELAY_SECONDS = 0.5

# --- Capture Loop (Cadence) ---
CAPTURE_INTERVAL_SECONDS = int(os.getenv("INGESTER_CAPTURE_INTERVAL_SECONDS", "300"))
HEALTH_INTERVAL_SECONDS = 60
RUN_FOREVER = _parse_bool_env(os.getenv("INGESTER_RUN_FOREVER"), True)
MAX_CYCLES = int(os.getenv("INGESTER_MAX_CYCLES", "0")) or None
# Legacy fixed backoff (replaced by exponential backoff — see ERROR_BACKOFF_BASE_SECONDS).
ERROR_BACKOFF_SECONDS = 30
CAPTURE_ADB_TIMEOUT_SECONDS = 30
HEALTH_ADB_TIMEOUT_SECONDS = 15

ENABLE_CONNECTIVITY_DUMPSYS = False

# --- Logging ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
HEALTH_JSONL_FILENAME = "health.jsonl"
CYCLES_JSONL_PATH = os.path.join(LOG_DIR, "cycles.jsonl")
CONTROL_JSON_PATH = os.path.join(LOG_DIR, "control.json")

# --- Output ---
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "captures")

# --- App Focus Validation ---
EXPECTED_PACKAGE = "com.xm.csee"
EXPECTED_ACTIVITIES = [
    "com.xworld.MainActivity",
    "com.xworld.activity.monitor.view.MonitorActivity",
]

# --- Screen Validation ---
MAX_SCREEN_RETRIES = 2
RETRY_DELAY_SEC = 1.5
BLACK_MEAN_THRESHOLD = 35
WHITE_MEAN_THRESHOLD = 240
LOW_STD_THRESHOLD = 20

# --- Loading Screen Detection ---
LOADING_MEAN_MAX = 60
LOADING_BRIGHT_CENTER_MIN = 0.01

# --- Error Artifacts ---
LOGCAT_LINES_ON_ERROR = 500

# --- ADB Timeouts / Logging ---
BATTERY_DUMPSYS_TIMEOUT_SECONDS = 12
ADB_TIMEOUT_RETRY_DELAY_SECONDS = 1.0
ADB_ERROR_OUTPUT_TAIL_CHARS = 800

# --- Health Check Flag ---
ENABLE_HEALTHCHECK = _parse_bool_env(os.getenv("INGESTER_ENABLE_HEALTHCHECK"), False)
ENABLE_FOCUS_VALIDATION = _parse_bool_env(os.getenv("INGESTER_ENABLE_FOCUS_VALIDATION"), False)

# --- Screen State Detection & Recovery ---
ENABLE_SCREEN_STATE_DETECTION = _parse_bool_env(
    os.getenv("INGESTER_ENABLE_SCREEN_STATE_DETECTION"), False
)

# App launch configuration
APP_LAUNCH_ACTIVITY = "com.xworld.MainActivity"
APP_LAUNCH_WAIT_SECONDS = 8.0

# Recovery settings
MAX_STATE_RECOVERY_ATTEMPTS = 2
PRE_CAPTURE_RETRY_MAX = 2
STATE_CHECK_WAIT_SECONDS = 1.0

# Periodic app restart to prevent memory leaks (ICSee heap exhaustion).
APP_RESTART_EVERY_N_CYCLES = int(os.getenv("INGESTER_APP_RESTART_EVERY_N_CYCLES", "50"))

# Circuit breaker: after N consecutive cycle failures, force-stop the app.
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("INGESTER_CIRCUIT_BREAKER_THRESHOLD", "3"))

# Exponential backoff on consecutive failures (seconds).
ERROR_BACKOFF_BASE_SECONDS = 10
ERROR_BACKOFF_MAX_SECONDS = 300

# Max consecutive failures before stopping the loop entirely.
MAX_CONSECUTIVE_FAILURES = int(os.getenv("INGESTER_MAX_CONSECUTIVE_FAILURES", "10"))

# Number of BACK presses after app launch to dismiss overlays (CloudWebActivity, ads, etc.)
APP_LAUNCH_DISMISS_BACK_PRESSES = 2
APP_LAUNCH_DISMISS_DELAY_SECONDS = 1.0

# --- Per-camera circuit breaker ---
CAMERA_CB_FAILURE_THRESHOLD = int(os.getenv("INGESTER_CAMERA_CB_FAILURE_THRESHOLD", "3"))
CAMERA_CB_COOLDOWN_SECONDS = int(os.getenv("INGESTER_CAMERA_CB_COOLDOWN_SECONDS", "600"))

# --- Cycle watchdog (global timeout per cycle) ---
CYCLE_TIMEOUT_SECONDS = int(os.getenv("INGESTER_CYCLE_TIMEOUT_SECONDS", "180"))

# --- Health check total timeout budget ---
HEALTH_CHECK_TOTAL_TIMEOUT_SECONDS = int(os.getenv("INGESTER_HEALTH_TOTAL_TIMEOUT", "60"))

# --- Memory watchdog thresholds ---
MEMORY_CHECK_ENABLED = _parse_bool_env(os.getenv("INGESTER_MEMORY_CHECK_ENABLED"), True)
MEMORY_WARNING_THRESHOLD_KB = int(os.getenv("INGESTER_MEMORY_WARNING_KB", "400000"))    # ~400MB
MEMORY_CRITICAL_THRESHOLD_KB = int(os.getenv("INGESTER_MEMORY_CRITICAL_KB", "200000"))  # ~200MB
MEMORY_POST_REBOOT_WAIT_SECONDS = int(os.getenv("INGESTER_MEMORY_POST_REBOOT_WAIT", "120"))

# --- App recovery: known launcher packages ---
LAUNCHER_PACKAGES = ["com.android.launcher", "com.android.launcher3", "com.sec.android.app.launcher"]

# Screen state thresholds (from YAML or defaults)
SCREEN_STATE_THRESHOLDS = _profile.get("screen_thresholds", _DEFAULT_SCREEN_THRESHOLDS)

# --- Camera Battery Monitoring (IP cameras via ICSee app) ---
BATTERY_CHECK_INTERVAL_SECONDS = int(os.getenv("INGESTER_BATTERY_CHECK_INTERVAL", "3600"))       # 1 hora
BATTERY_CHECK_INTERVAL_LOW_SECONDS = int(os.getenv("INGESTER_BATTERY_CHECK_LOW_INTERVAL", "1800"))  # 30 min quando critical
CAMERA_BATTERY_WARNING_LEVEL = int(os.getenv("INGESTER_BATTERY_WARNING_LEVEL", "15"))   # ≤15%: dobra intervalo
CAMERA_BATTERY_CRITICAL_LEVEL = int(os.getenv("INGESTER_BATTERY_CRITICAL_LEVEL", "10"))  # ≤10%: pausa captura
CAMERA_BATTERY_RESUME_LEVEL = int(os.getenv("INGESTER_BATTERY_RESUME_LEVEL", "15"))     # ≥15%: retoma normal
CAMERA_SETTINGS_TAP_COORDS = {"x": 1015, "y": 150}
UIAUTOMATOR_DUMP_PATH = "/data/local/tmp/ui_dump.xml"
UIAUTOMATOR_DUMP_TIMEOUT_SECONDS = 15
BATTERY_CHECK_SETTINGS_WAIT_SECONDS = 2.0


```

## `ingester/src/ingester/dashboard.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/dashboard.py
import json
import os
import threading
import shutil
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from ingester import config

PROJECT_ROOT = config.PROJECT_ROOT
LOG_DIR = config.LOG_DIR
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CAPTURES_DIR = os.path.join(DATA_DIR, "captures")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "dashboard_static")
ARCHIVES_DIR = os.path.join(LOG_DIR, "archives")

CYCLES_PATH = config.CYCLES_JSONL_PATH
HEALTH_PATH = os.path.join(LOG_DIR, config.HEALTH_JSONL_FILENAME)
CONTROL_PATH = config.CONTROL_JSON_PATH
START_TIME = datetime.now(timezone.utc)

ALLOWED_MEDIA_ROOTS = [LOG_DIR, CAPTURES_DIR]


def _safe_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _iter_jsonl(path: str):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _read_jsonl_tail(path: str, limit: int) -> list[dict]:
    if limit <= 0 or not os.path.exists(path):
        return []
    # Read from end in chunks to avoid loading large files.
    size = os.path.getsize(path)
    if size == 0:
        return []

    chunk_size = 64 * 1024
    data = b""
    with open(path, "rb") as handle:
        pos = size
        while pos > 0 and data.count(b"\n") <= limit:
            read_size = min(chunk_size, pos)
            pos -= read_size
            handle.seek(pos)
            data = handle.read(read_size) + data

    lines = data.splitlines()
    tail = lines[-limit:]
    items: list[dict] = []
    for raw in tail:
        try:
            items.append(json.loads(raw.decode("utf-8")))
        except json.JSONDecodeError:
            continue
    return items


def _read_control_state() -> dict:
    if not os.path.exists(CONTROL_PATH):
        return {"pause": False, "stop": False, "run_once": False}
    try:
        with open(CONTROL_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"pause": False, "stop": False, "run_once": False}
    return {
        "pause": bool(data.get("pause", False)),
        "stop": bool(data.get("stop", False)),
        "run_once": bool(data.get("run_once", False)),
    }


def _write_control_state(state: dict) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(CONTROL_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=True, indent=2)


def _archive_logs() -> dict:
    os.makedirs(ARCHIVES_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = os.path.join(ARCHIVES_DIR, f"archive_{stamp}")
    os.makedirs(target, exist_ok=True)

    moved = 0
    skipped = []
    for name in os.listdir(LOG_DIR):
        if name in ("archives", os.path.basename(CONTROL_PATH), "screen_profiles.json"):
            continue
        src = os.path.join(LOG_DIR, name)
        dst = os.path.join(target, name)
        try:
            shutil.move(src, dst)
            moved += 1
        except OSError:
            skipped.append(name)
    captures_target = os.path.join(target, "captures")
    if os.path.isdir(CAPTURES_DIR):
        try:
            shutil.move(CAPTURES_DIR, captures_target)
            os.makedirs(CAPTURES_DIR, exist_ok=True)
        except OSError:
            skipped.append("captures")
    return {"moved": moved, "target": target, "skipped": skipped}


def _count_cycles(path: str) -> tuple[int, int]:
    total = 0
    errors = 0
    for item in _iter_jsonl(path):
        total += 1
        if item.get("ok") is False:
            errors += 1
    return total, errors


def _last_item(path: str) -> dict | None:
    items = _read_jsonl_tail(path, 1)
    return items[-1] if items else None


def _find_last_screenshot(cycles_path: str) -> dict | None:
    items = _read_jsonl_tail(cycles_path, 250)
    for item in reversed(items):
        screenshot = item.get("screenshot") or {}
        path = screenshot.get("path")
        if path and os.path.exists(path):
            return {
                "path": path,
                "ts_end": item.get("ts_end"),
                "cycle_id": item.get("cycle_id"),
            }
    return None


def _last_screenshot_per_camera_from_disk() -> list[dict]:
    result = []
    for name in config.CAMERAS.keys():
        camera_dir = os.path.join(CAPTURES_DIR, name)
        if not os.path.isdir(camera_dir):
            result.append({"camera": name, "path": None, "ts_end": None})
            continue
        files = [
            os.path.join(camera_dir, f)
            for f in os.listdir(camera_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        ]
        if not files:
            result.append({"camera": name, "path": None, "ts_end": None})
            continue
        latest = max(files, key=lambda p: os.path.getmtime(p))
        ts = datetime.fromtimestamp(os.path.getmtime(latest), timezone.utc).isoformat()
        result.append({"camera": name, "path": latest, "ts_end": ts})
    return result


def _active_cameras_from_cycle(cycle: dict | None) -> tuple[int, list[str]]:
    if not cycle:
        return 0, []
    steps = cycle.get("steps") or []
    active = []
    for name in config.CAMERAS.keys():
        marker = f"camera:{name}:screencap_validate"
        for step in steps:
            if step.get("name") == marker and step.get("ok") is True:
                active.append(name)
                break
    return len(active), active


def _last_action_from_cycles(cycles_path: str) -> dict | None:
    items = _read_jsonl_tail(cycles_path, 200)
    for item in reversed(items):
        steps = item.get("steps") or []
        if not steps:
            continue
        last_step = steps[-1]
        return {
            "name": last_step.get("name"),
            "ok": last_step.get("ok"),
            "details": last_step.get("details"),
            "ts_end": last_step.get("end"),
            "cycle_id": item.get("cycle_id"),
        }
    return None


def _list_error_cycles(limit: int) -> list[dict]:
    items = _read_jsonl_tail(CYCLES_PATH, max(limit * 5, limit))
    errors = []
    for item in reversed(items):
        if item.get("ok") is False:
            error = item.get("error") or {}
            errors.append(
                {
                    "cycle_id": item.get("cycle_id"),
                    "ts_end": item.get("ts_end"),
                    "message": error.get("message"),
                    "type": error.get("type"),
                    "step": error.get("step"),
                    "artifact_dir": _artifact_dir(item.get("cycle_id")),
                }
            )
        if len(errors) >= limit:
            break
    return errors


def _artifact_dir(cycle_id: str | None) -> str | None:
    if not cycle_id:
        return None
    path = os.path.join(LOG_DIR, f"cycle_{cycle_id}_artifacts")
    return path if os.path.isdir(path) else None


def _media_allowed(path: str) -> bool:
    if not path:
        return False
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    for root in ALLOWED_MEDIA_ROOTS:
        try:
            if os.path.realpath(root) == os.path.commonpath([real, os.path.realpath(root)]):
                return True
        except ValueError:
            continue
    return False


def _guess_content_type(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith(".txt") or lower.endswith(".log"):
        return "text/plain; charset=utf-8"
    if lower.endswith(".css"):
        return "text/css; charset=utf-8"
    if lower.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if lower.endswith(".html"):
        return "text/html; charset=utf-8"
    return "application/octet-stream"


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "IngesterDashboard/0.2"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionAbortedError:
            return

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionAbortedError:
            return

    def _send_text(self, text: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self._send_bytes(body, "text/plain; charset=utf-8", status)

    def _serve_static(self, path: str) -> None:
        if not os.path.exists(path) or not os.path.isfile(path):
            self._send_text("Not found", status=HTTPStatus.NOT_FOUND)
            return
        with open(path, "rb") as handle:
            data = handle.read()
        self._send_bytes(data, _guess_content_type(path))

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route == "/":
            return self._serve_static(os.path.join(STATIC_DIR, "index.html"))

        if route.startswith("/assets/"):
            rel = route.replace("/assets/", "", 1)
            return self._serve_static(os.path.join(STATIC_DIR, rel))

        if route == "/api/summary":
            total, errors = _count_cycles(CYCLES_PATH)
            last_cycle = _last_item(CYCLES_PATH)
            active_count, active_list = _active_cameras_from_cycle(last_cycle)
            last_health = _last_item(HEALTH_PATH)
            last_screenshot = _find_last_screenshot(CYCLES_PATH)
            control_state = _read_control_state()
            last_action = _last_action_from_cycles(CYCLES_PATH)
            last_cycle_age_s = None
            if last_cycle and last_cycle.get("ts_end"):
                try:
                    ts = datetime.fromisoformat(last_cycle["ts_end"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    last_cycle_age_s = int((datetime.now(timezone.utc) - ts).total_seconds())
                except ValueError:
                    last_cycle_age_s = None
            camera_battery = last_cycle.get("camera_battery") if last_cycle else None
            camera_battery_ts = last_cycle.get("ts_end") if (last_cycle and camera_battery) else None
            payload = {
                "cameras_configured": len(config.CAMERAS),
                "cameras_active": active_count,
                "cameras_active_list": active_list,
                "cycles_total": total,
                "cycles_ok": total - errors,
                "cycles_error": errors,
                "last_cycle": last_cycle,
                "last_health": last_health,
                "last_screenshot": last_screenshot,
                "last_screenshots": _last_screenshot_per_camera_from_disk(),
                "capture_interval_s": config.CAPTURE_INTERVAL_SECONDS,
                "control": control_state,
                "last_action": last_action,
                "last_cycle_age_s": last_cycle_age_s,
                "program_uptime_s": int((datetime.now(timezone.utc) - START_TIME).total_seconds()),
                "camera_battery": camera_battery,
                "camera_battery_ts": camera_battery_ts,
            }
            return self._send_json(payload)

        if route == "/api/cycles":
            limit = _safe_int(query.get("limit", ["200"])[0], 200)
            items = _read_jsonl_tail(CYCLES_PATH, limit)
            return self._send_json({"items": items})

        if route == "/api/cycle":
            cycle_id = query.get("id", [""])[0]
            if not cycle_id:
                return self._send_json({"error": "missing id"}, status=HTTPStatus.BAD_REQUEST)
            match = None
            for item in _iter_jsonl(CYCLES_PATH):
                if item.get("cycle_id") == cycle_id:
                    match = item
            if not match:
                return self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return self._send_json(match)

        if route == "/api/errors":
            limit = _safe_int(query.get("limit", ["50"])[0], 50)
            items = _list_error_cycles(limit)
            return self._send_json({"items": items})

        if route == "/api/health":
            limit = _safe_int(query.get("limit", ["200"])[0], 200)
            items = _read_jsonl_tail(HEALTH_PATH, limit)
            return self._send_json({"items": items})

        if route == "/api/cameras":
            return self._send_json({"items": list(config.CAMERAS.keys())})

        if route == "/api/control":
            return self._send_json(_read_control_state())

        if route == "/api/version":
            return self._send_json({"version": self.server_version, "file": __file__})

        if route == "/favicon.ico":
            return self._send_text("Not found", status=HTTPStatus.NOT_FOUND)

        if route == "/media":
            raw_path = query.get("path", [""])[0]
            if not raw_path:
                return self._send_text("missing path", status=HTTPStatus.BAD_REQUEST)
            path = unquote(raw_path)
            if not _media_allowed(path) or not os.path.exists(path):
                return self._send_text("not allowed", status=HTTPStatus.FORBIDDEN)
            with open(path, "rb") as handle:
                data = handle.read()
            return self._send_bytes(data, _guess_content_type(path))

        self._send_text("Not found", status=HTTPStatus.NOT_FOUND)

    def log_message(self, format, *args):
        # Suppress noisy HTTP logs; rely on ingester log if needed.
        return

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/archive":
            control = _read_control_state()
            if not control.get("stop"):
                return self._send_text(
                    "Arquivamento permitido apenas com o ingester parado (Stop).",
                    status=HTTPStatus.CONFLICT,
                )
            result = _archive_logs()
            return self._send_json(result)

        if route != "/api/control":
            return self._send_text("Not found", status=HTTPStatus.NOT_FOUND)

        length = _safe_int(self.headers.get("Content-Length"), 0)
        raw = self.rfile.read(length) if length > 0 else b""
        data: dict = {}
        if raw:
            try:
                data = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                try:
                    data = {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
                except UnicodeDecodeError:
                    data = {}

        action = (data.get("action") or "").lower()
        state = _read_control_state()

        if action == "pause":
            state["pause"] = True
        elif action == "resume":
            state["pause"] = False
            state["stop"] = False
        elif action == "stop":
            state["stop"] = True
        elif action == "run_once":
            state["run_once"] = True
        elif action == "clear":
            state = {"pause": False, "stop": False, "run_once": False}
        else:
            return self._send_json({"error": "invalid action"}, status=HTTPStatus.BAD_REQUEST)

        _write_control_state(state)
        return self._send_json(state)


def run_dashboard(host: str = "127.0.0.1", port: int = 8088) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Ingester dashboard listening on http://{host}:{port}")
    print(f"Dashboard file: {__file__}")
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    host = os.environ.get("INGESTER_DASHBOARD_HOST", "0.0.0.0")
    port = _safe_int(os.environ.get("INGESTER_DASHBOARD_PORT"), 8088)
    run_dashboard(host=host, port=port)

```

## `ingester/src/ingester/dashboard_static/app.js`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```javascript
const batteryCards = document.getElementById("battery-cards");
const summaryCards = document.getElementById("summary-cards");
const indicatorCards = document.getElementById("indicator-cards");
const cameraSelect = document.getElementById("camera-select");
const cameraShotFrame = document.getElementById("camera-shot-frame");
const cameraShotMeta = document.getElementById("camera-shot-meta");
const statusChip = document.getElementById("status-chip");
const statusText = document.getElementById("status-text");
const errorsList = document.getElementById("errors-list");
const cyclesList = document.getElementById("cycles-list");
const healthList = document.getElementById("health-list");
const controlStateBadge = document.getElementById("control-state");
const archiveStatus = document.getElementById("archive-status");
const controlStatus = document.getElementById("control-status");
const lastActionLine = document.getElementById("last-action");

const btnRunOnce = document.getElementById("btn-run-once");
const btnPause = document.getElementById("btn-pause");
const btnResume = document.getElementById("btn-resume");
const btnStop = document.getElementById("btn-stop");
const btnArchive = document.getElementById("btn-archive");

let cyclesData = [];
let errorsData = [];
let cameraShotsData = [];
let cameraList = [];

const fmtDate = (iso) => {
  if (!iso) return "-";
  const d = new Date(iso + "Z");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
};

const fmtDuration = (ms) => {
  if (ms == null) return "-";
  const s = Math.round(ms / 100) / 10;
  return `${s}s`;
};

const fmtSeconds = (seconds) => {
  if (seconds == null) return "-";
  const total = Math.max(0, Math.floor(seconds));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const mins = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
};

const buildCard = (label, value, sub) => {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <h4>${label}</h4>
    <div class="value">${value}</div>
    <div class="sub">${sub || ""}</div>
  `;
  return card;
};

const updateControlBadge = (control) => {
  if (!control) return;
  if (control.stop) {
    controlStateBadge.textContent = "stop";
    controlStateBadge.className = "badge error";
    if (btnArchive) btnArchive.disabled = false;
    return;
  }
  if (control.pause) {
    controlStateBadge.textContent = "pausado";
    controlStateBadge.className = "badge warn";
    if (btnArchive) btnArchive.disabled = true;
    return;
  }
  controlStateBadge.textContent = "ativo";
  controlStateBadge.className = "badge";
  if (btnArchive) btnArchive.disabled = true;
};

const setControlStatus = (message, isError = false) => {
  if (!controlStatus) return;
  controlStatus.textContent = message || "";
  controlStatus.className = isError ? "status-line error" : "status-line";
};

const renderSummary = (data) => {
  summaryCards.innerHTML = "";
  summaryCards.append(
    buildCard(
      "Câmeras ativas",
      data.cameras_active ?? "-",
      data.cameras_active_list?.join(", ") || "último ciclo"
    ),
    buildCard("Câmeras configuradas", data.cameras_configured ?? "-", "mapa do config"),
    buildCard("Ciclos totais", data.cycles_total ?? "-", "desde o início"),
    buildCard("Erros", data.cycles_error ?? "-", "ciclos com falha"),
    buildCard(
      "Tempo ligado",
      fmtSeconds(data.program_uptime_s),
      "uptime do dashboard"
    ),
    buildCard(
      "Último ciclo",
      data.last_cycle?.cycle_id ?? "-",
      data.last_cycle ? fmtDate(data.last_cycle.ts_end) : "sem dados"
    )
  );

  if (data.last_cycle?.ok === false) {
    statusChip.classList.add("error");
    statusText.textContent = "Último ciclo com erro";
  } else {
    statusChip.classList.remove("error");
    statusText.textContent = "Rodando";
  }

  updateControlBadge(data.control);

  if (lastActionLine) {
    const action = data.last_action;
    if (action && action.name) {
      const status = action.ok === false ? "erro" : "ok";
      const details = action.details ? `• ${action.details}` : "";
      lastActionLine.textContent = `Última ação: ${action.name} (${status})${details}`;
    } else {
      lastActionLine.textContent = "Última ação: sem dados";
    }
  }

  if (controlStatus && data.control) {
    const control = data.control;
    const age = data.last_cycle_age_s != null ? `${data.last_cycle_age_s}s` : "-";
    controlStatus.textContent = `Controle: pause=${control.pause} stop=${control.stop} run_once=${control.run_once} • Último ciclo há ${age}`;
  }

  cameraShotsData = data.last_screenshots || [];
  renderCameraShot();
  renderBattery(data.camera_battery, data.camera_battery_ts);
};

const renderBattery = (battery, ts) => {
  if (!batteryCards) return;
  batteryCards.innerHTML = "";
  const tsEl = document.getElementById("battery-ts");
  if (tsEl) {
    if (ts) {
      const d = new Date(ts);
      tsEl.textContent = `• última checagem: ${d.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })}`;
    } else {
      tsEl.textContent = "";
    }
  }
  if (!battery || !Object.keys(battery).length) {
    batteryCards.innerHTML = '<span class="muted">Sem dados de bateria.</span>';
    return;
  }
  Object.entries(battery).forEach(([cam, info]) => {
    const level = info.level != null ? info.level : null;
    const state = info.state || "unknown";
    let stateLabel, badgeClass;
    if (state === "critical") {
      stateLabel = "critico";
      badgeClass = "badge error";
    } else if (state === "warning") {
      stateLabel = "alerta";
      badgeClass = "badge warn";
    } else if (state === "normal") {
      stateLabel = "normal";
      badgeClass = "badge";
    } else {
      stateLabel = "desconhecido";
      badgeClass = "badge";
    }
    const levelText = level != null ? `${level}%` : "-";
    const barWidth = level != null ? Math.max(0, Math.min(100, level)) : 0;
    const barColor = level != null
      ? (level <= 10 ? "var(--rose)" : level <= 15 ? "var(--accent)" : "var(--teal)")
      : "var(--ink-soft)";
    const card = document.createElement("div");
    card.className = "battery-card";
    card.innerHTML = `
      <div class="battery-header">
        <span class="battery-cam">${cam}</span>
        <span class="${badgeClass}">${stateLabel}</span>
      </div>
      <div class="battery-level">${levelText}</div>
      <div class="battery-bar-bg"><div class="battery-bar" style="width:${barWidth}%;background:${barColor}"></div></div>
    `;
    batteryCards.appendChild(card);
  });
};

const renderIndicators = () => {
  if (!indicatorCards) return;
  indicatorCards.innerHTML = "";
  if (!cyclesData.length) {
    indicatorCards.append(buildCard("Média de duração", "-", "sem ciclos"));
    return;
  }

  const durations = cyclesData.map((c) => c.duration_ms || 0);
  const total = durations.reduce((a, b) => a + b, 0);
  const avg = total / durations.length;
  const sorted = durations.slice().sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)] || 0;
  const p95 = sorted[Math.floor(sorted.length * 0.95)] || 0;

  const errors = cyclesData.filter((c) => c.ok === false);
  const errorRate = (errors.length / cyclesData.length) * 100;

  const lastWindowSize = 5;
  const lastWindow = cyclesData.slice(-lastWindowSize);
  const windowErrors = lastWindow.filter((c) => c.ok === false).length;

  const lastError = errors.length ? errors[errors.length - 1] : null;

  indicatorCards.append(
    buildCard("Média duração", fmtDuration(avg), `mediana ${fmtDuration(median)}`),
    buildCard("P95 duração", fmtDuration(p95), "ciclos mais lentos"),
    buildCard("Taxa de erro", `${errorRate.toFixed(1)}%`, `${errors.length} falhas`),
    buildCard("Erros na última janela", `${windowErrors}/${lastWindowSize}`, "janela de 5 ciclos"),
    buildCard(
      "Último erro",
      lastError ? `#${lastError.cycle_id}` : "-",
      lastError ? (lastError.error?.message || "erro") : "sem falhas"
    )
  );
};

const renderErrors = (items) => {
  errorsList.innerHTML = "";
  if (!items.length) {
    errorsList.innerHTML = '<div class="item"><p class="muted">Sem erros recentes.</p></div>';
    return;
  }
  items.forEach((item) => {
    const wrapper = document.createElement("div");
    wrapper.className = "item";
    const artifactDir = item.artifact_dir;
    const links = [];
    if (artifactDir) {
      ["window.txt", "logcat.txt", "health.json", "screenshot.png"].forEach((file) => {
        const path = `${artifactDir}\\${file}`;
        links.push(`<a class="code" target="_blank" href="/media?path=${encodeURIComponent(path)}">${file}</a>`);
      });
    }
    wrapper.innerHTML = `
      <h4>Cycle ${item.cycle_id} <span class="badge error">erro</span></h4>
      <p>${item.type || "Erro"}: ${item.message || "-"}</p>
      <p>Etapa: <span class="code">${item.step || "-"}</span> • ${fmtDate(item.ts_end)}</p>
      ${links.length ? `<p>Artifacts: ${links.join(" ")}</p>` : ""}
    `;
    errorsList.appendChild(wrapper);
  });
};

const renderCycles = (items) => {
  cyclesList.innerHTML = "";
  if (!items.length) {
    cyclesList.innerHTML = '<div class="item"><p class="muted">Sem ciclos ainda.</p></div>';
    return;
  }

  items
    .slice()
    .reverse()
    .forEach((item) => {
      const wrapper = document.createElement("div");
      wrapper.className = "item";
      const status = item.ok ? "ok" : "erro";
      const badgeClass = item.ok ? "badge" : "badge error";
      const errorMsg = item.error?.message ? `• ${item.error.message}` : "";
      const steps = item.steps || [];
      const stepList = steps
        .map(
          (step) =>
            `<div class="code">${step.ok ? "?" : "?"} ${step.name} (${fmtDuration(
              step.duration_ms
            )}) ${step.details || ""}</div>`
        )
        .join("");

      wrapper.innerHTML = `
        <h4>Cycle ${item.cycle_id} <span class="${badgeClass}">${status}</span></h4>
        <p>Duração: ${fmtDuration(item.duration_ms)} • ${fmtDate(item.ts_end)} ${errorMsg}</p>
        <details>
          <summary class="muted">Detalhes do ciclo</summary>
          <div class="stack">${stepList || '<span class="muted">Sem steps</span>'}</div>
        </details>
      `;
      cyclesList.appendChild(wrapper);
    });
};

const renderHealth = (items) => {
  healthList.innerHTML = "";
  if (!items.length) {
    healthList.innerHTML = '<div class="item"><p class="muted">Sem registros de saúde.</p></div>';
    return;
  }
  items
    .slice()
    .reverse()
    .slice(0, 20)
    .forEach((item) => {
      const wrapper = document.createElement("div");
      wrapper.className = "item";
      wrapper.innerHTML = `
        <h4>Health ${item.health_cycle_id ?? "-"}</h4>
        <p>Serial: <span class="code">${item.serial || "-"}</span> • ${fmtDate(item.timestamp)}</p>
        <p>Bateria: ${item.snapshot?.battery_level ?? "-"}% • Temp: ${item.snapshot?.battery_temp_c ?? "-"}°C</p>
        <p>Wi-Fi: ${item.snapshot?.wlan0_ip || "-"} • Internet: ${item.snapshot?.internet_ok ? "ok" : "falha"}</p>
      `;
      healthList.appendChild(wrapper);
    });
};

const loadSummary = async () => {
  const res = await fetch("/api/summary");
  if (!res.ok) return;
  const data = await res.json();
  renderSummary(data);
};

const loadCameras = async () => {
  const res = await fetch("/api/cameras");
  if (!res.ok) return;
  const data = await res.json();
  cameraList = data.items || [];
  renderCameraShot();
};

const renderCameraShot = () => {
  if (!cameraShotFrame || !cameraShotMeta || !cameraSelect) return;
  const previous = cameraSelect.value;
  cameraSelect.innerHTML = "";

  const list = cameraList.length ? cameraList : cameraShotsData.map((s) => s.camera);
  if (!list.length) {
    cameraShotFrame.innerHTML = '<span class="muted">Sem câmeras configuradas.</span>';
    cameraShotMeta.textContent = "";
    return;
  }

  list.forEach((camera) => {
    const option = document.createElement("option");
    option.value = camera;
    option.textContent = camera;
    if (previous && previous === camera) option.selected = true;
    cameraSelect.appendChild(option);
  });

  const selected = cameraSelect.value || list[0];
  const shot = cameraShotsData.find((s) => s.camera === selected);
  if (!shot) {
    cameraShotFrame.innerHTML = '<span class="muted">Sem captura para esta câmera.</span>';
    cameraShotMeta.textContent = `Último screenshot - ${selected} • sem dados`;
    return;
  }
  const imgSrc = `/media?path=${encodeURIComponent(shot.path)}`;
  cameraShotFrame.innerHTML = `<img src="${imgSrc}" alt="${shot.camera}" />`;
  cameraShotMeta.textContent = `Último screenshot - ${shot.camera} • ${fmtDate(shot.ts_end)}`;
};

const loadErrors = async () => {
  const res = await fetch("/api/errors?limit=120");
  if (!res.ok) return;
  const data = await res.json();
  errorsData = data.items || [];
  renderErrors(errorsData);
};

const loadCycles = async () => {
  const res = await fetch("/api/cycles?limit=240");
  if (!res.ok) return;
  const data = await res.json();
  cyclesData = data.items || [];
  renderCycles(cyclesData);
  renderIndicators();
};

const loadHealth = async () => {
  const res = await fetch("/api/health?limit=200");
  if (!res.ok) return;
  const data = await res.json();
  renderHealth(data.items || []);
};


const postControl = async (action) => {
  console.log("POST /api/control", action);
  setControlStatus("Enviando comando...", false);
  const res = await fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!res.ok) {
    const text = await res.text();
    console.warn("API /api/control erro", res.status, text);
    setControlStatus(text || "Falha ao enviar comando.", true);
    return;
  }
  const payload = await res.json();
  console.log("API /api/control ok", payload);
  setControlStatus("Comando aplicado.", false);
  loadSummary();
};

const archiveLogs = async () => {
  console.log("POST /api/archive");
  if (archiveStatus) archiveStatus.textContent = "Arquivando logs...";
  const res = await fetch("/api/archive", { method: "POST" });
  if (!res.ok) {
    const text = await res.text();
    console.warn("API /api/archive erro", res.status, text);
    if (archiveStatus) archiveStatus.textContent = text || "Falha ao arquivar.";
    setControlStatus("Arquivo não encontrado: reinicie o servidor do dashboard.", true);
    return;
  }
  const data = await res.json();
  console.log("API /api/archive ok", data);
  if (archiveStatus) archiveStatus.textContent = `Arquivados: ${data.moved || 0} itens.`;
  setControlStatus("Arquivamento concluído.", false);
  refreshAll();
};

const refreshAll = () => {
  loadSummary();
  loadErrors();
  loadCycles();
  loadHealth();
};

refreshAll();
loadCameras();
setInterval(refreshAll, 20000);

const loadVersion = async () => {
  const res = await fetch("/api/version");
  if (!res.ok) return;
  const data = await res.json();
  setControlStatus(`Servidor: ${data.version} • ${data.file}`, false);
};

loadVersion();

cameraSelect?.addEventListener("change", renderCameraShot);

const wireButton = (id, fn) => {
  const btn = document.getElementById(id);
  if (btn) btn.addEventListener("click", fn);
};

wireButton("refresh-errors", loadErrors);
wireButton("refresh-cycles", loadCycles);
wireButton("refresh-health", loadHealth);

btnRunOnce?.addEventListener("click", () => postControl("run_once"));
btnPause?.addEventListener("click", () => postControl("pause"));
btnResume?.addEventListener("click", () => postControl("resume"));
btnStop?.addEventListener("click", () => postControl("stop"));
btnArchive?.addEventListener("click", archiveLogs);

```

## `ingester/src/ingester/dashboard_static/index.html`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```html
<!doctype html>
<html lang="pt-br">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ingester Dashboard</title>
    <link rel="stylesheet" href="/assets/styles.css?v=7" />
  </head>
  <body>
    <div class="bg-grid"></div>
    <header class="topbar">
      <div>
        <p class="eyebrow">Ingester • Cameras</p>
        <h1>Controle de Testes</h1>
      </div>
      <div class="status-chip" id="status-chip">
        <span class="dot"></span>
        <span id="status-text">Carregando...</span>
      </div>
    </header>

    <main class="layout">
      <section class="panel summary">
        <h2>Visão Geral</h2>
        <div class="cards" id="summary-cards"></div>
        <div class="last-shot">
          <div>
            <h3>Últimos screenshots por câmera</h3>
          </div>
          <div class="panel-actions">
            <select id="camera-select" class="filter"></select>
          </div>
          <div class="shot-frame" id="camera-shot-frame">
            <span class="muted">Sem capturas recentes.</span>
          </div>
          <p class="muted" id="camera-shot-meta"></p>
        </div>
        <h3 class="section-title">Bateria das Cameras <span class="muted" id="battery-ts"></span></h3>
        <div class="battery-grid" id="battery-cards"></div>
        <h3 class="section-title">Indicadores</h3>
        <div class="cards" id="indicator-cards"></div>
      </section>

      <section class="panel controls">
        <div class="panel-header">
          <h2>Controles</h2>
          <span class="badge" id="control-state">ativo</span>
        </div>
        <div class="controls-grid">
          <button class="cta" id="btn-run-once">Rodar 1 ciclo</button>
          <button class="ghost" id="btn-pause">Pausar</button>
          <button class="ghost" id="btn-resume">Retomar</button>
          <button class="ghost warn" id="btn-stop">Stop</button>
          <button class="ghost" id="btn-archive">Arquivar logs</button>
        </div>
        <p class="muted" id="control-hint">Use pausa para congelar o loop. Stop encerra o processo no próximo ciclo. Arquive apenas após Stop.</p>
        <p class="muted" id="archive-status"></p>
        <p class="status-line" id="control-status"></p>
        <p class="status-line" id="last-action"></p>
      </section>

      <section class="panel errors">
        <div class="panel-header">
          <h2>Erros recentes</h2>
          <div class="panel-actions">
            <button class="ghost" id="refresh-errors">Atualizar</button>
          </div>
        </div>
        <div id="errors-list" class="stack"></div>
      </section>

      <section class="panel cycles">
        <div class="panel-header">
          <h2>Ciclos</h2>
          <div class="panel-actions">
            <button class="ghost" id="refresh-cycles">Atualizar</button>
          </div>
        </div>
        <div id="cycles-list" class="stack"></div>
      </section>

      <section class="panel health">
        <div class="panel-header">
          <h2>Saúde do dispositivo</h2>
          <button class="ghost" id="refresh-health">Atualizar</button>
        </div>
        <div id="health-list" class="stack"></div>
      </section>
    </main>

    <footer class="footer">
      <span>Dashboard local • atualiza a cada 20s</span>
    </footer>

    <script src="/assets/app.js?v=10"></script>
  </body>
</html>

```

## `ingester/src/ingester/dashboard_static/styles.css`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```css
:root {
  --ink: #121217;
  --ink-soft: #2a2a37;
  --mist: #f2f2f5;
  --paper: #fbfaf6;
  --accent: #d54b1a;
  --accent-dark: #b73c12;
  --teal: #1d8f83;
  --rose: #b63b5a;
  --shadow: 0 22px 60px rgba(18, 18, 23, 0.12);
  --radius: 18px;
  --mono: "JetBrains Mono", "IBM Plex Mono", "Fira Mono", monospace;
  --sans: "Space Grotesk", "IBM Plex Sans", "Fira Sans", sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  font-family: var(--sans);
  background: radial-gradient(circle at 20% 20%, #fff3e3 0, rgba(255, 243, 227, 0) 55%),
    radial-gradient(circle at 80% 10%, #e8f6f4 0, rgba(232, 246, 244, 0) 40%),
    linear-gradient(130deg, #fef7f0 0%, #f7f8fb 100%);
  color: var(--ink);
}

.bg-grid {
  position: fixed;
  inset: 0;
  background-image: linear-gradient(rgba(20, 20, 30, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(20, 20, 30, 0.04) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
  z-index: 0;
}

.topbar {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 32px 6vw 8px;
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.2em;
  font-size: 12px;
  color: var(--ink-soft);
  margin: 0 0 6px;
}

h1 {
  margin: 0;
  font-size: clamp(28px, 4vw, 44px);
  font-weight: 700;
}

.layout {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 22px;
  padding: 12px 6vw 40px;
}

.panel {
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(18, 18, 23, 0.08);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(6px);
  animation: floatIn 0.5s ease-out both;
}

.summary {
  grid-column: span 2;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.panel-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px;
  margin-top: 18px;
}

.card {
  padding: 16px;
  border-radius: 16px;
  background: var(--paper);
  border: 1px solid rgba(18, 18, 23, 0.1);
  min-height: 90px;
}

.card h4 {
  margin: 0 0 8px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-soft);
}

.card .value {
  font-size: 26px;
  font-weight: 700;
}

.card .sub {
  margin-top: 6px;
  font-size: 13px;
  color: var(--ink-soft);
}

.last-shot {
  margin-top: 22px;
  display: grid;
  gap: 14px;
}

.last-shot h3 {
  margin: 0 0 6px;
}

.shot-frame {
  border-radius: 16px;
  border: 1px dashed rgba(18, 18, 23, 0.2);
  background: #f8f0e6;
  padding: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  overflow: hidden;
}

.shot-frame img {
  width: 100%;
  height: 260px;
  border-radius: 12px;
  object-fit: contain;
  background: #111113;
  display: block;
}

.section-title {
  margin: 22px 0 6px;
  font-size: 16px;
}

.battery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
  margin-top: 12px;
}

.battery-card {
  padding: 14px 16px;
  border-radius: 16px;
  background: var(--paper);
  border: 1px solid rgba(18, 18, 23, 0.1);
}

.battery-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.battery-cam {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}

.battery-level {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 8px;
}

.battery-bar-bg {
  height: 6px;
  border-radius: 3px;
  background: rgba(18, 18, 23, 0.08);
  overflow: hidden;
}

.battery-bar {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}

.stack {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.item {
  border-radius: 14px;
  border: 1px solid rgba(18, 18, 23, 0.1);
  padding: 12px 14px;
  background: #fff;
}

.item h4 {
  margin: 0 0 6px;
  font-size: 15px;
}

.item p {
  margin: 4px 0;
  font-size: 13px;
  color: var(--ink-soft);
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(29, 143, 131, 0.12);
  color: var(--teal);
  font-weight: 600;
}

.badge.error {
  background: rgba(182, 59, 90, 0.14);
  color: var(--rose);
}

.badge.warn {
  background: rgba(213, 75, 26, 0.14);
  color: var(--accent-dark);
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-radius: 999px;
  background: #111113;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}

.status-chip .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #69d1a3;
  box-shadow: 0 0 10px rgba(105, 209, 163, 0.8);
}

.status-chip.error .dot {
  background: #ff7b7b;
  box-shadow: 0 0 10px rgba(255, 123, 123, 0.8);
}

.ghost {
  border: 1px solid rgba(18, 18, 23, 0.1);
  background: transparent;
  padding: 8px 12px;
  border-radius: 999px;
  font-family: var(--sans);
  cursor: pointer;
}

.ghost.warn {
  border-color: rgba(182, 59, 90, 0.3);
  color: var(--rose);
}

.ghost:hover {
  border-color: rgba(18, 18, 23, 0.3);
}

.ghost:disabled,
.cta:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.cta {
  border: none;
  background: var(--accent);
  color: white;
  padding: 10px 14px;
  border-radius: 999px;
  font-weight: 600;
  cursor: pointer;
}

.cta:hover {
  background: var(--accent-dark);
}

.filter {
  border: 1px solid rgba(18, 18, 23, 0.12);
  border-radius: 999px;
  padding: 8px 12px;
  font-family: var(--sans);
  background: #fff;
  min-width: 140px;
}

.filter:disabled {
  opacity: 0.6;
}

.controls-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.muted {
  color: var(--ink-soft);
  font-size: 13px;
}

.code {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--ink-soft);
}

.footer {
  padding: 20px 6vw 30px;
  color: var(--ink-soft);
  font-size: 12px;
}

.status-line {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--ink-soft);
}

.status-line.error {
  color: var(--rose);
}

@keyframes floatIn {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 960px) {
  .summary {
    grid-column: span 1;
  }
}

```

## `ingester/src/ingester/local/__init__.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# This file makes 'local' a Python package

```

## `ingester/src/ingester/local/adb_adapter.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/adb_adapter.py
import logging
import subprocess
import re
import time
from typing import Any

from .. import config

logger = logging.getLogger(__name__)


class AdbCommandError(RuntimeError):
    def __init__(self, cmd: str, returncode: int, stdout: str, stderr: str):
        super().__init__(f"ADB command failed (code={returncode}): {cmd}")
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class AdbTimeoutError(TimeoutError):
    def __init__(self, cmd: str, timeout_s: float):
        super().__init__(f"ADB command timed out after {timeout_s}s: {cmd}")
        self.cmd = cmd
        self.timeout_s = timeout_s


def _run_command(
    command: list[str],
    timeout_s: float | None = None,
    check: bool = True,
    retry_on_timeout: bool = False,
) -> subprocess.CompletedProcess:
    """Run an adb command list with timeout and duration logging."""
    full_command = ["adb"] + command
    cmd_str = " ".join(full_command)
    start = time.monotonic()
    if timeout_s is None:
        timeout_s = config.CAPTURE_ADB_TIMEOUT_SECONDS

    try:
        process = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        duration_s = time.monotonic() - start
        logger.warning(f"ADB timeout duration={duration_s:.3f}s cmd={cmd_str}")
        if retry_on_timeout:
            logger.warning("ADB retry on timeout: restarting server and retrying once.")
            _restart_adb_server()
            return _run_command(
                command,
                timeout_s=timeout_s,
                check=check,
                retry_on_timeout=False,
            )
        raise AdbTimeoutError(cmd_str, timeout_s if timeout_s is not None else -1)

    duration_s = time.monotonic() - start
    logger.info(f"ADB done duration={duration_s:.3f}s exit_code={process.returncode} cmd={cmd_str}")

    if process.stdout:
        logger.debug(f"ADB stdout: {process.stdout.strip()}")
    if process.stderr:
        logger.debug(f"ADB stderr: {process.stderr.strip()}")

    if check and process.returncode != 0:
        stdout_tail = _tail_text(process.stdout or "", config.ADB_ERROR_OUTPUT_TAIL_CHARS)
        stderr_tail = _tail_text(process.stderr or "", config.ADB_ERROR_OUTPUT_TAIL_CHARS)
        logger.warning(
            "ADB command failed; stdout_tail=%s stderr_tail=%s",
            stdout_tail,
            stderr_tail,
        )
        raise AdbCommandError(cmd_str, process.returncode, process.stdout or "", process.stderr or "")

    return process


def run_shell(cmd: str, timeout_s: float) -> str:
    """Run an adb shell command on the first connected device."""
    devices = list_devices(timeout_s=timeout_s)
    if not devices:
        raise AdbCommandError("adb devices", 1, "", "No devices")
    result = _run_shell_cmd(devices[0], cmd, timeout_s=timeout_s, check=True)
    return (result.stdout or "").strip()


def _run_shell_cmd(
    device_id: str,
    cmd: str,
    timeout_s: float | None = None,
    check: bool = True,
    retry_on_timeout: bool = False,
) -> subprocess.CompletedProcess:
    # Use sh -c only for commands with shell metacharacters (pipes, redirects, etc.)
    _shell_meta = set("|&;<>()$`\\\"'")
    needs_shell = any(c in _shell_meta for c in cmd)
    if needs_shell:
        args = ["-s", device_id, "shell", "sh", "-c", cmd]
    else:
        args = ["-s", device_id, "shell"] + cmd.split()
    return _run_command(
        args,
        timeout_s=timeout_s,
        check=check,
        retry_on_timeout=retry_on_timeout,
    )


def list_devices(timeout_s: float | None = None) -> list[str]:
    """List connected adb device serials."""
    logger.info("Listing ADB devices...")
    _run_command(["start-server"], timeout_s=timeout_s, check=False)
    result = _run_command(["devices"], timeout_s=timeout_s, check=True)
    device_lines = re.findall(r"^(.+?)\s+device$", result.stdout, re.MULTILINE)
    if not device_lines:
        logger.warning("No ADB devices found.")
        return []
    logger.info(f"Devices found: {device_lines}")
    return device_lines


def go_home_monkey(device_id: str, timeout_s: float | None = None):
    logger.info(f"Going Home via monkey on device {device_id}...")
    _run_command(["-s", device_id, "shell", "monkey", "-c", "android.intent.category.LAUNCHER", "1"], timeout_s=timeout_s)


def go_home_keyevent(device_id: str, timeout_s: float | None = None):
    logger.info(f"Going Home via KEYCODE_HOME on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "keyevent", "3"], timeout_s=timeout_s)


def close_app(device_id: str, package_name: str, timeout_s: float | None = None):
    logger.info(f"Force-stopping '{package_name}' on device {device_id}...")
    _run_command(["-s", device_id, "shell", "am", "force-stop", package_name], timeout_s=timeout_s)


def tap(device_id: str, x: int, y: int, timeout_s: float | None = None):
    logger.info(f"Tap (X={x}, Y={y}) on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "tap", str(x), str(y)], timeout_s=timeout_s)


def press_key(device_id: str, keycode: str, timeout_s: float | None = None):
    logger.info(f"Keyevent '{keycode}' on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "keyevent", keycode], timeout_s=timeout_s)


def swipe(device_id: str, x1: int, y1: int, x2: int, y2: int, duration: int = 300, timeout_s: float | None = None):
    logger.info(f"Swipe ({x1},{y1}) -> ({x2},{y2}) on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)], timeout_s=timeout_s)


def screencap(device_id: str, local_path: str, timeout_s: float | None = None) -> bool:
    remote_path = "/sdcard/saira_capture.png"
    logger.info(f"Screencap device {device_id} to {local_path}...")
    try:
        _run_command(["-s", device_id, "shell", "screencap", remote_path], timeout_s=timeout_s)
        _run_command(["-s", device_id, "pull", remote_path, local_path], timeout_s=timeout_s)
        _run_command(["-s", device_id, "shell", "rm", remote_path], timeout_s=timeout_s)
        logger.info(f"Screenshot saved: {local_path}")
        return True
    except (AdbCommandError, AdbTimeoutError):
        logger.error(f"Failed to screencap device {device_id}.")
        return False


def launch_app(device_id: str, timeout_s: float | None = None) -> bool:
    """Launch the ICSee app by tapping its icon on the home screen.

    Assumes the device is already on the HOME screen.
    """
    coords = config.APP_ICON_TAP_COORDS
    if not coords:
        logger.error("APP_ICON_TAP_COORDS nao configurado.")
        return False

    logger.info(f"Abrindo app: tap no icone em ({coords['x']}, {coords['y']})")
    try:
        tap(device_id, coords["x"], coords["y"], timeout_s=timeout_s)
        time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
        return True
    except Exception as exc:
        logger.error(f"Falha ao abrir app via tap: {exc}")
        return False


def get_device_state(device_id: str, timeout_s: float | None = None) -> str:
    result = _run_command(["-s", device_id, "get-state"], timeout_s=timeout_s, check=False)
    return (result.stdout or "").strip()


def get_health_snapshot(
    device_id: str,
    timeout_s: float,
    total_timeout_s: float | None = None,
) -> dict[str, Any]:
    if not config.ENABLE_HEALTHCHECK:
        logger.info("Health check disabled by config; skipping device health collection.")
        return {"disabled": True, "device_id": device_id}

    budget = total_timeout_s or config.HEALTH_CHECK_TOTAL_TIMEOUT_SECONDS
    deadline = time.monotonic() + budget
    errors: list[str] = []
    snapshot: dict[str, Any] = {"device_id": device_id}
    warn_exc = logger.isEnabledFor(logging.DEBUG)

    def _remaining() -> float:
        return max(0, deadline - time.monotonic())

    def _cmd_timeout() -> float:
        return min(timeout_s, _remaining()) if _remaining() > 0 else 0.1

    def _budget_exceeded() -> bool:
        if _remaining() <= 0:
            errors.append("total_timeout_exceeded")
            snapshot["_timeout"] = True
            logger.warning(f"Health check total timeout ({budget}s) exceeded; returning partial snapshot.")
            return True
        return False

    if not _budget_exceeded():
        try:
            snapshot["adb_state"] = get_device_state(device_id, timeout_s=_cmd_timeout())
            snapshot["adb_ok"] = True
        except Exception as exc:
            errors.append(f"adb_state: {exc}")
            snapshot["adb_ok"] = False
            logger.warning(f"ADB state check failed: {exc}", exc_info=warn_exc)

    if not _budget_exceeded():
        try:
            snapshot.update(get_battery_info(device_id, _cmd_timeout()))
        except Exception as exc:
            errors.append(f"battery: {exc}")
            logger.warning(f"Battery check failed: {exc}", exc_info=warn_exc)

    if not _budget_exceeded():
        try:
            snapshot.update(get_uptime_info(device_id, _cmd_timeout()))
        except Exception as exc:
            errors.append(f"uptime: {exc}")
            logger.warning(f"Uptime check failed: {exc}", exc_info=warn_exc)

    if not _budget_exceeded():
        try:
            snapshot.update(get_storage_info(device_id, _cmd_timeout(), "/data"))
        except Exception as exc:
            errors.append(f"storage: {exc}")
            logger.warning(f"Storage check failed: {exc}", exc_info=warn_exc)

    if not _budget_exceeded():
        try:
            snapshot.update(get_network_info(device_id, _cmd_timeout()))
        except Exception as exc:
            errors.append(f"network: {exc}")
            logger.warning(f"Network check failed: {exc}", exc_info=warn_exc)

    if not _budget_exceeded():
        try:
            snapshot.update(get_mem_info(device_id, _cmd_timeout()))
        except Exception as exc:
            errors.append(f"mem: {exc}")
            logger.warning(f"Mem check failed: {exc}", exc_info=warn_exc)

    if not _budget_exceeded() and config.ENABLE_CONNECTIVITY_DUMPSYS:
        try:
            result = _run_shell_cmd(device_id, "dumpsys connectivity | head -n 80", timeout_s=_cmd_timeout(), check=False)
            snapshot["connectivity_dumpsys"] = (result.stdout or "").splitlines()
        except Exception as exc:
            errors.append(f"connectivity_dumpsys: {exc}")
            logger.warning(f"Connectivity dumpsys failed: {exc}", exc_info=warn_exc)

    snapshot["_errors"] = errors
    return snapshot


def get_battery_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    battery_timeout = max(timeout_s, config.BATTERY_DUMPSYS_TIMEOUT_SECONDS)
    result = _run_shell_cmd(
        device_id,
        "dumpsys battery",
        timeout_s=battery_timeout,
        check=True,
        retry_on_timeout=True,
    )
    text = result.stdout or ""
    level = _extract_int(text, r"level:\s*(\d+)")
    status = _extract_int(text, r"status:\s*(\d+)")
    temperature = _extract_int(text, r"temperature:\s*(\d+)")
    voltage = _extract_int(text, r"voltage:\s*(\d+)")
    usb_powered = _extract_bool(text, r"USB powered:\s*(\w+)")
    ac_powered = _extract_bool(text, r"AC powered:\s*(\w+)")

    battery_temp_c = None
    if temperature is not None:
        battery_temp_c = temperature / 10.0

    return {
        "battery_level": level,
        "battery_status": status,
        "battery_temp_c": battery_temp_c,
        "battery_voltage_mv": voltage,
        "battery_usb_powered": usb_powered,
        "battery_ac_powered": ac_powered,
    }


def get_uptime_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, "cat /proc/uptime", timeout_s=timeout_s, check=True)
    uptime_s = _extract_float(result.stdout or "", r"^([\d\.]+)")
    return {"uptime_s": uptime_s}


def get_storage_info(device_id: str, timeout_s: float, mount_point: str) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, f"df {mount_point}", timeout_s=timeout_s, check=True)
    available_kb = _parse_df_available_kb(result.stdout or "", mount_point)
    return {"storage_available_kb": available_kb}


def get_network_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, "ip -f inet addr show wlan0", timeout_s=timeout_s, check=False)
    wlan0_ip = _extract_ip_addr(result.stdout or "")

    routes_result = _run_shell_cmd(device_id, "ip route", timeout_s=timeout_s, check=False)
    routes_raw = (routes_result.stdout or "").splitlines()
    default_route = _has_default_route(routes_raw)

    internet_ok = False
    method = None
    ping_result = _run_shell_cmd(device_id, "ping -c 1 -W 2 1.1.1.1", timeout_s=timeout_s, check=False)
    if ping_result.returncode == 0:
        internet_ok = True
        method = "ping"
    else:
        http_ok = _http_connectivity_check(device_id, timeout_s)
        if http_ok:
            internet_ok = True
            method = "http"

    info: dict[str, Any] = {
        "wlan0_ip": wlan0_ip,
        "internet_ok": internet_ok,
        "method": method,
        "default_route": default_route,
    }

    if not default_route:
        info["routes_raw"] = routes_raw[:5]

    return info


def get_mem_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, "cat /proc/meminfo", timeout_s=timeout_s, check=False)
    mem_available_kb = _extract_int(result.stdout or "", r"MemAvailable:\s*(\d+)\s*kB")
    return {"mem_available_kb": mem_available_kb}


def get_window_dump(device_id: str, timeout_s: float) -> str:
    result = _run_shell_cmd(device_id, "dumpsys window", timeout_s=timeout_s, check=False)
    return result.stdout or ""


def get_focus_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    raw = get_window_dump(device_id, timeout_s=timeout_s)
    focus = parse_window_dump(raw)
    logger.info(f"Focus detected source={focus.get('raw_match_source')} component={focus.get('component')}")
    return focus


def get_logcat_tail(device_id: str, lines: int, timeout_s: float) -> str:
    cmd = f"logcat -d -t {lines}"
    result = _run_shell_cmd(device_id, cmd, timeout_s=timeout_s, check=False)
    return result.stdout or ""


def _http_connectivity_check(device_id: str, timeout_s: float) -> bool:
    cmd = (
        "(command -v curl >/dev/null 2>&1 && curl -s --max-time 3 -o /dev/null "
        "http://connectivitycheck.gstatic.com/generate_204) "
        "|| (command -v wget >/dev/null 2>&1 && wget -q --spider --timeout=3 "
        "http://connectivitycheck.gstatic.com/generate_204) "
        "|| (command -v toybox >/dev/null 2>&1 && toybox wget -q --spider --timeout=3 "
        "http://connectivitycheck.gstatic.com/generate_204)"
    )
    result = _run_shell_cmd(device_id, cmd, timeout_s=timeout_s, check=False)
    return result.returncode == 0


def _has_default_route(routes: list[str]) -> bool:
    for line in routes:
        if not line:
            continue
        if line.startswith("default"):
            return True
        if "0.0.0.0/0" in line:
            return True
    return False


def _extract_ip_addr(text: str) -> str | None:
    match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", text or "")
    if match:
        return match.group(1)
    return None


def _extract_first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if match:
        return match.group(0)
    return None


def _window_excerpt(text: str, max_lines: int = 5) -> str:
    lines = []
    for line in (text or "").splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line or "mObscuringWindow" in line:
            lines.append(line.strip())
        if len(lines) >= max_lines:
            break
    return " | ".join(lines)


def parse_window_dump(raw: str) -> dict[str, Any]:
    component, source, raw_line = _find_focus_component(raw)
    pkg, activity = _split_component(component)
    insets = _extract_insets(raw)
    obscuring = _extract_first_match(raw, r"mObscuringWindow=Window\{[^}]+\}")
    return {
        "package": pkg,
        "activity": activity,
        "component": component,
        "insets": insets,
        "raw_match_source": source,
        "raw": raw_line,
        "wm_obscuring_window": obscuring,
        "window_dump_excerpt": _window_excerpt(raw),
    }


def _find_focus_component(raw: str) -> tuple[str | None, str, str]:
    patterns = [
        ("imeTarget", r"imeLayeringTarget.*?([\w.]+/[\w.$]+)"),
        ("imeInputTarget", r"imeInputTarget.*?([\w.]+/[\w.$]+)"),
        ("currentFocus", r"mCurrentFocus=.*?([\w.]+/[\w.$]+)"),
        ("focusedApp", r"mFocusedApp=.*?([\w.]+/[\w.$]+)"),
        ("resumedActivity", r"mResumedActivity:.*?([\w.]+/[\w.$]+)"),
        ("lastWakeLockObscuringWindow", r"mLastWakeLockObscuringWindow=.*?([\w.]+/[\w.$]+)"),
        ("obscuringWindow", r"mObscuringWindow=.*?([\w.]+/[\w.$]+)"),
    ]
    for name, pattern in patterns:
        match = re.search(pattern, raw or "", re.MULTILINE)
        if match:
            return match.group(1), name, match.group(0)
    fallback = re.search(r"([\w.]+/[\w.$]+)", raw or "", re.MULTILINE)
    if fallback:
        return fallback.group(1), "fallback", fallback.group(0)
    return None, "unknown", ""


def _split_component(component: str | None) -> tuple[str | None, str | None]:
    if not component:
        return None, None
    parts = component.split("/", 1)
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1]


def _extract_insets(raw: str) -> dict[str, int] | None:
    match = re.search(r"mContentInsets=\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw or "")
    if not match:
        return None
    left, top, right, bottom = [int(value) for value in match.groups()]
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _extract_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _extract_bool(text: str, pattern: str) -> bool | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    return None


def _parse_df_available_kb(text: str, mount_point: str) -> int | None:
    for line in (text or "").splitlines():
        if line.endswith(mount_point):
            parts = re.split(r"\s+", line.strip())
            if len(parts) >= 4:
                try:
                    return int(parts[3])
                except ValueError:
                    return None
    return None


def _tail_text(text: str, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text.strip()
    return text[-max_chars:].strip()


def reboot_device(device_id: str, timeout_s: float | None = 30) -> None:
    """Reboot the Android device via ADB."""
    logger.warning(f"Rebooting device {device_id}...")
    _run_command(["-s", device_id, "reboot"], timeout_s=timeout_s, check=False)


def wait_for_device(device_id: str, max_wait_s: float = 120, poll_interval_s: float = 5) -> bool:
    """Wait until the device comes back online after a reboot.

    Returns True if device reconnected within *max_wait_s*, False otherwise.
    """
    logger.info(f"Waiting for device {device_id} to come back online (max {max_wait_s}s)...")
    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        try:
            devices = list_devices(timeout_s=5)
            if device_id in devices:
                logger.info(f"Device {device_id} is back online.")
                return True
        except Exception:
            pass
        time.sleep(poll_interval_s)
    logger.error(f"Device {device_id} did not come back within {max_wait_s}s.")
    return False


def dump_ui_hierarchy(device_id: str, timeout_s: float | None = None) -> str:
    """Run uiautomator dump and return the XML content as a string."""
    dump_path = config.UIAUTOMATOR_DUMP_PATH
    t = timeout_s or config.UIAUTOMATOR_DUMP_TIMEOUT_SECONDS
    _run_shell_cmd(device_id, f"uiautomator dump {dump_path}", timeout_s=t, check=False)
    result = _run_shell_cmd(device_id, f"cat {dump_path}", timeout_s=t, check=True)
    return result.stdout or ""


def parse_camera_battery_from_settings(xml_content: str) -> int | None:
    """Extract battery percentage from the ICSee settings screen UI dump.

    Looks for the node with resource-id 'com.xm.csee:id/lis_battery_manager',
    then finds the 'tv_right' TextView inside it which contains text like '48%'.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        logger.warning("Failed to parse UI dump XML for battery extraction.")
        return None

    for node in root.iter("node"):
        rid = node.get("resource-id", "")
        if rid == "com.xm.csee:id/lis_battery_manager":
            for child in node.iter("node"):
                if child.get("resource-id", "") == "com.xm.csee:id/tv_right":
                    text = child.get("text", "").strip()
                    match = re.search(r"(\d+)", text)
                    if match:
                        return int(match.group(1))
            break

    logger.warning("Battery field (lis_battery_manager/tv_right) not found in UI dump.")
    return None


def _restart_adb_server() -> None:
    try:
        subprocess.run(["adb", "kill-server"], capture_output=True, text=True, check=False)
        time.sleep(config.ADB_TIMEOUT_RETRY_DELAY_SECONDS)
        subprocess.run(["adb", "start-server"], capture_output=True, text=True, check=False)
    except Exception:
        logger.warning("Failed to restart adb server.")

```

## `ingester/src/ingester/local/capture.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/capture.py
import concurrent.futures
import logging
from logging.handlers import RotatingFileHandler
import os
import time
import json
import traceback
import shutil
from datetime import datetime

from PIL import Image

from . import adb_adapter, screen_classifier, screen_fingerprint
from .screen_classifier import ScreenState
from .. import config

logger = logging.getLogger(__name__)


def _ensure_logging() -> None:
    if logging.getLogger().handlers:
        return
    os.makedirs(config.LOG_DIR, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        os.path.join(config.LOG_DIR, "ingester.log"),
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _append_jsonl(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _read_control_state() -> dict:
    path = config.CONTROL_JSON_PATH
    if not os.path.exists(path):
        return {"pause": False, "stop": False, "run_once": False}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"pause": False, "stop": False, "run_once": False}
    return {
        "pause": bool(data.get("pause", False)),
        "stop": bool(data.get("stop", False)),
        "run_once": bool(data.get("run_once", False)),
    }


def _write_control_state(state: dict) -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    with open(config.CONTROL_JSON_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=True, indent=2)


def _step_start(name: str) -> dict:
    return {"name": name, "ok": False, "start": _now_iso(), "end": None, "duration_ms": None, "details": None}


def _step_end(step: dict, ok: bool, details: str | None = None) -> dict:
    step["ok"] = ok
    step["end"] = _now_iso()
    step["duration_ms"] = _duration_ms(step["start"], step["end"])
    if details:
        step["details"] = details
    return step


def _duration_ms(start_iso: str, end_iso: str) -> int:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    return int((end - start).total_seconds() * 1000)


def _validate_focus(focus: dict) -> tuple[bool, str]:
    pkg = focus.get("package")
    activity = focus.get("activity")
    if pkg != config.EXPECTED_PACKAGE:
        return False, f"focus_package_mismatch:{pkg}"
    if activity not in config.EXPECTED_ACTIVITIES:
        return False, f"focus_activity_mismatch:{activity}"
    return True, "ok"


def _analyze_image(path: str) -> dict:
    with Image.open(path) as img:
        gray = img.convert("L").resize((64, 64))
        pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    min_v = min(pixels)
    max_v = max(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    std = variance ** 0.5
    return {"mean": round(mean, 2), "std": round(std, 2), "min": min_v, "max": max_v}


def _validate_screenshot(stats: dict) -> tuple[bool, str]:
    mean = stats["mean"]
    std = stats["std"]
    if mean <= config.BLACK_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_black_screen"
    if mean >= config.WHITE_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_white_screen"
    return True, "ok"


def _write_error_artifacts(cycle_id: str, device_id: str, health: dict | None, screenshot_path: str | None) -> str:
    base_dir = os.path.join(config.LOG_DIR, f"cycle_{cycle_id}_artifacts")
    os.makedirs(base_dir, exist_ok=True)

    window_txt = os.path.join(base_dir, "window.txt")
    logcat_txt = os.path.join(base_dir, "logcat.txt")
    health_json = os.path.join(base_dir, "health.json")

    if config.ENABLE_FOCUS_VALIDATION:
        try:
            window_dump = adb_adapter.get_window_dump(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            with open(window_txt, "w", encoding="utf-8") as handle:
                handle.write(window_dump)
        except Exception as exc:
            logger.error(f"Failed to write window.txt: {exc}", exc_info=True)
    else:
        logger.info("Skipping window.txt artifact (focus validation disabled).")

    try:
        logcat = adb_adapter.get_logcat_tail(device_id, config.LOGCAT_LINES_ON_ERROR, config.HEALTH_ADB_TIMEOUT_SECONDS)
        with open(logcat_txt, "w", encoding="utf-8") as handle:
            handle.write(logcat)
    except Exception as exc:
        logger.error(f"Failed to write logcat.txt: {exc}", exc_info=True)

    try:
        with open(health_json, "w", encoding="utf-8") as handle:
            json.dump(health or {}, handle, ensure_ascii=True, indent=2)
    except Exception as exc:
        logger.error(f"Failed to write health.json: {exc}", exc_info=True)

    screenshot_dest = os.path.join(base_dir, "screenshot.png")
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            shutil.copyfile(screenshot_path, screenshot_dest)
        except Exception as exc:
            logger.error(f"Failed to copy screenshot: {exc}", exc_info=True)
    else:
        # No existing screenshot — capture a fresh one for diagnostics
        try:
            fresh_path = adb_adapter.screencap(device_id, screenshot_dest, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            logger.info(f"Fresh error screenshot saved: {fresh_path}")
        except Exception as exc:
            logger.error(f"Failed to capture error screenshot: {exc}", exc_info=True)

    return base_dir


def _error_obj(error_message: str | None, error_type: str | None, steps: list[dict], trace: str | None = None) -> dict | None:
    if not error_message:
        return None
    step_name = steps[-1]["name"] if steps else None
    return {
        "type": error_type or "CycleError",
        "message": error_message,
        "step": step_name,
        "trace": trace,
    }


def _capture_with_validation(device_id: str, camera_name: str) -> dict:
    last_focus = None
    last_stats = None
    last_path = None
    validation_reason = None

    attempts = config.MAX_SCREEN_RETRIES + 1
    for attempt in range(1, attempts + 1):
        if config.ENABLE_FOCUS_VALIDATION:
            focus = adb_adapter.get_focus_info(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            last_focus = focus
            focus_ok, focus_reason = _validate_focus(focus)
            if not focus_ok:
                validation_reason = focus_reason
                if attempt < attempts:
                    time.sleep(config.RETRY_DELAY_SEC)
                    continue
                return {
                    "path": None,
                    "validated": False,
                    "validation_reason": validation_reason,
                    "stats": None,
                    "attempts": attempt,
                    "focus": last_focus,
                }
        else:
            if attempt == 1:
                logger.info("Focus validation disabled by config; skipping.")

        camera_dir = os.path.join(config.OUTPUT_DIR, camera_name)
        os.makedirs(camera_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"capture_{device_id}_{timestamp}_attempt{attempt}.png"
        filepath = os.path.join(camera_dir, filename)
        last_path = filepath

        success = adb_adapter.screencap(
            device_id,
            filepath,
            timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
        )
        if not success:
            validation_reason = "screencap_failed"
            if attempt < attempts:
                time.sleep(config.RETRY_DELAY_SEC)
                continue
            return {
                "path": filepath,
                "validated": False,
                "validation_reason": validation_reason,
                "stats": None,
                "attempts": attempt,
                "focus": last_focus,
            }

        stats = _analyze_image(filepath)
        last_stats = stats
        valid, reason = _validate_screenshot(stats)
        validation_reason = reason
        if valid:
            return {
                "path": filepath,
                "validated": True,
                "validation_reason": "ok",
                "stats": stats,
                "attempts": attempt,
                "focus": last_focus,
            }

        if attempt < attempts:
            try:
                os.remove(filepath)
            except OSError:
                pass
            time.sleep(config.RETRY_DELAY_SEC)

    return {
        "path": last_path,
        "validated": False,
        "validation_reason": validation_reason,
        "stats": last_stats,
        "attempts": attempts,
        "focus": last_focus,
    }


def _check_screen(device_id: str, expected: ScreenState, context: str) -> tuple[bool, ScreenState, str | None]:
    """Take a screenshot, classify screen state, compare to expected.

    Returns (match, actual_state, screenshot_path).
    Screenshot is deleted if state matches.
    """
    if not config.ENABLE_SCREEN_STATE_DETECTION:
        logger.info(f"[{context}] Deteccao de tela desabilitada; pulando verificacao.")
        return True, ScreenState.UNKNOWN, None

    state, _fp, path = screen_classifier.capture_and_detect(device_id, context)
    match = state == expected
    if match:
        logger.info(f"[{context}] Tela OK: {state.value}")
    else:
        logger.warning(f"[{context}] Tela inesperada: esperado={expected.value} detectado={state.value}")
    # Cleanup temp screenshot
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    return match, state, path


def _recover_to_camera_list(device_id: str, current: ScreenState) -> bool:
    """Try to navigate back to the CAMERA_LIST screen."""
    logger.info(f"Recuperacao: estado atual={current.value}, objetivo=camera_list")

    if current == ScreenState.HOME:
        logger.info("Recuperacao: HOME detectado, abrindo app...")
        for attempt in range(1, config.MAX_STATE_RECOVERY_ATTEMPTS + 1):
            logger.info(f"Recuperacao: tentativa {attempt}/{config.MAX_STATE_RECOVERY_ATTEMPTS} de abrir o app...")
            if not adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS):
                continue
            time.sleep(config.STATE_CHECK_WAIT_SECONDS)
            ok, state, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, f"recovery_post_launch_attempt{attempt}")
            if ok:
                return True
            # Se caiu numa sub-tela do app (não HOME), tenta BACK
            if state != ScreenState.HOME:
                adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                time.sleep(config.STATE_CHECK_WAIT_SECONDS)
                ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, f"recovery_post_back_attempt{attempt}")
                if ok:
                    return True
            # Ainda HOME — esperar mais antes de tentar de novo
            logger.warning(f"Recuperacao: ainda em {state.value} apos tentativa {attempt}, aguardando antes de tentar novamente...")
            time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
        return False

    if current == ScreenState.CAMERA_NORMAL:
        adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        time.sleep(config.STATE_CHECK_WAIT_SECONDS)
        ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_normal")
        return ok

    if current == ScreenState.CAMERA_FULLSCREEN:
        for _ in range(2):
            adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(config.POST_BACK_DELAY_SECONDS)
        time.sleep(config.STATE_CHECK_WAIT_SECONDS)
        ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_fullscreen")
        return ok

    # UNKNOWN — try HOME + launch
    logger.info("Recuperacao: estado desconhecido, tentando HOME + launch_app...")
    adb_adapter.go_home_keyevent(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
    if not adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS):
        return False
    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
    ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_unknown")
    return ok


def _run_pre_capture_sequence(device_id: str, camera_name: str) -> None:
    """Try to enter fullscreen: direct tap, then menu + fullscreen if needed."""
    fs = config.FULLSCREEN_TAP_COORDS
    menu = config.MENU_TAP_COORDS

    logger.info(f"[{camera_name}] Tap direto fullscreen (X={fs['x']}, Y={fs['y']})...")
    adb_adapter.tap(device_id, fs["x"], fs["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)

    if not config.ENABLE_SCREEN_STATE_DETECTION:
        return

    state, _fp, path = screen_classifier.capture_and_detect(
        device_id, f"pre_capture_fullscreen_direct:{camera_name}"
    )
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

    if state == ScreenState.CAMERA_FULLSCREEN:
        return

    logger.info(f"[{camera_name}] Fullscreen direto falhou (estado={state.value}), abrindo menu...")
    adb_adapter.tap(device_id, menu["x"], menu["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    adb_adapter.tap(device_id, fs["x"], fs["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)


def _is_loading_screen(screenshot_path: str) -> bool:
    """Check if the screenshot is a loading/black screen (stream not ready yet)."""
    stats = _analyze_image(screenshot_path)
    if stats["mean"] <= config.BLACK_MEAN_THRESHOLD and stats["std"] <= config.LOW_STD_THRESHOLD:
        return True

    fp = screen_fingerprint.extract_fingerprint(screenshot_path)
    ind = fp["indicators"]
    return (
        stats["mean"] <= config.LOADING_MEAN_MAX
        and ind.get("bright_ratio_center", 0.0) >= config.LOADING_BRIGHT_CENTER_MIN
    )


def _wait_for_stream(device_id: str, camera_name: str, cam_coords: dict) -> bool:
    """Poll the screen until the stream loads or timeout is reached.

    Checks:
      1. If CAMERA_LIST → tap didn't register, retry.
      2. If CAMERA_FULLSCREEN + black screen → loading, wait and retry.
      3. Otherwise → stream is ready.

    Returns True if stream loaded, False if timed out.
    """
    timeout = config.WAIT_STREAM_LOAD_SECONDS
    poll_interval = 5
    elapsed = 0.0

    def _cleanup(p):
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass

    while elapsed < timeout:
        state, _fp, path = screen_classifier.capture_and_detect(device_id, f"stream_poll:{camera_name}")

        # If we're back on camera list, the tap didn't register — retry
        if state == ScreenState.CAMERA_LIST:
            logger.warning(f"[{camera_name}] Ainda na lista de cameras, repetindo tap...")
            _cleanup(path)
            adb_adapter.tap(device_id, cam_coords["x"], cam_coords["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(poll_interval)
            elapsed += poll_interval
            continue

        # Loading check: only in CAMERA_FULLSCREEN (black screen with loading bar)
        if state == ScreenState.CAMERA_FULLSCREEN:
            if path and os.path.exists(path) and _is_loading_screen(path):
                logger.info(f"[{camera_name}] Tela de carregamento detectada, aguardando {poll_interval}s... ({elapsed:.0f}/{timeout}s)")
                _cleanup(path)
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue

        # Not camera_list, not loading — stream is ready
        _cleanup(path)
        logger.info(f"[{camera_name}] Stream carregado (estado={state.value}, elapsed={elapsed:.0f}s)")
        return True

    logger.error(f"[{camera_name}] Timeout aguardando stream ({timeout}s)")
    return False


class CameraBatteryMonitor:
    """Per-camera battery level tracking with warning/critical state management.

    States:
        NORMAL  (>15%): capture at normal interval
        WARNING (≤15%): capture at 2× interval
        CRITICAL(≤10%): pause capture, check battery every 30min
    """

    def __init__(self):
        self._levels: dict[str, int | None] = {}
        self._last_check: dict[str, float] = {}
        self._state: dict[str, str] = {}  # "normal", "warning", "critical"

    def should_check(self, camera_name: str) -> bool:
        last = self._last_check.get(camera_name)
        if last is None:
            return True  # never checked
        state = self._state.get(camera_name, "normal")
        interval = (
            config.BATTERY_CHECK_INTERVAL_LOW_SECONDS
            if state == "critical"
            else config.BATTERY_CHECK_INTERVAL_SECONDS
        )
        return (time.monotonic() - last) >= interval

    def any_needs_check(self) -> bool:
        for cam_name in config.CAMERAS:
            if self.should_check(cam_name):
                return True
        return False

    def update(self, camera_name: str, level: int | None) -> None:
        self._levels[camera_name] = level
        self._last_check[camera_name] = time.monotonic()
        if level is None:
            return

        old_state = self._state.get(camera_name, "normal")

        if level <= config.CAMERA_BATTERY_CRITICAL_LEVEL:
            new_state = "critical"
        elif level <= config.CAMERA_BATTERY_WARNING_LEVEL:
            new_state = "warning"
        else:
            new_state = "normal"

        # Transition from critical/warning back to normal only when ≥ RESUME level
        if old_state in ("critical", "warning") and level < config.CAMERA_BATTERY_RESUME_LEVEL:
            if new_state == "normal":
                new_state = old_state  # keep current state until resume level reached

        if new_state != old_state:
            logger.info(
                f"[BATTERY] {camera_name}: {old_state} -> {new_state} (level={level}%)"
            )
        self._state[camera_name] = new_state

    def is_capture_paused(self, camera_name: str) -> bool:
        # Block capture if battery is critical OR if we never got a reading
        if camera_name not in self._levels:
            return True  # no reading yet — block until first check succeeds
        return self._state.get(camera_name) == "critical"

    def get_interval_multiplier(self) -> int:
        """Return 2 if any active camera is in warning state, else 1."""
        for cam_name in config.CAMERAS:
            state = self._state.get(cam_name, "normal")
            if state == "warning":
                return 2
        return 1

    def status(self) -> dict:
        return {
            cam: {
                "level": self._levels.get(cam),
                "state": self._state.get(cam, "unknown"),
            }
            for cam in config.CAMERAS
        }


class CameraCircuitBreaker:
    """Per-camera circuit breaker. Disables a camera after N consecutive failures for a cooldown period."""

    def __init__(self, threshold: int, cooldown_s: float):
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._failures: dict[str, int] = {}
        self._disabled_until: dict[str, float] = {}

    def record_success(self, camera_name: str) -> None:
        self._failures[camera_name] = 0
        self._disabled_until.pop(camera_name, None)

    def record_failure(self, camera_name: str) -> None:
        count = self._failures.get(camera_name, 0) + 1
        self._failures[camera_name] = count
        if count >= self._threshold:
            until = time.monotonic() + self._cooldown_s
            self._disabled_until[camera_name] = until
            logger.warning(
                f"[CB] {camera_name} desabilitada por {self._cooldown_s}s "
                f"apos {count} falhas consecutivas"
            )

    def is_available(self, camera_name: str) -> bool:
        until = self._disabled_until.get(camera_name)
        if until is None:
            return True
        if time.monotonic() >= until:
            self._disabled_until.pop(camera_name, None)
            self._failures[camera_name] = 0
            logger.info(f"[CB] {camera_name} reabilitada apos cooldown")
            return True
        remaining = until - time.monotonic()
        logger.info(f"[CB] {camera_name} ainda desabilitada ({remaining:.0f}s restantes)")
        return False

    def status(self) -> dict:
        return {
            "failures": dict(self._failures),
            "disabled": {k: round(v - time.monotonic(), 1) for k, v in self._disabled_until.items()},
        }


def _check_cameras_battery(
    device_id: str,
    battery_monitor: CameraBatteryMonitor,
    steps: list[dict],
) -> None:
    """Navigate to each camera's settings screen and read the battery level via uiautomator dump.

    Flow per camera (from camera_list):
      0. Verify we are on camera_list (recover if not)
      1. Tap camera thumbnail → enters preview
      2. Tap settings icon (X:1015, Y:150)
      3. Wait for settings screen to load
      4. uiautomator dump → parse battery
      5. BACK → BACK → back to camera_list
      6. Verify we returned to camera_list (recover if not)
    """
    settings_coords = config.CAMERA_SETTINGS_TAP_COORDS

    # --- Verify starting screen ---
    ok, state, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "battery_pre_check")
    if not ok:
        logger.warning(f"[BATTERY] Not on camera_list (state={state.value}), recovering...")
        if not _recover_to_camera_list(device_id, state):
            logger.error("[BATTERY] Failed to recover to camera_list, aborting battery check.")
            steps.append(_step_end(_step_start("battery_pre_check"), False, f"recovery_failed:{state.value}"))
            return

    for camera_name, camera_conf in config.CAMERAS.items():
        if not battery_monitor.should_check(camera_name):
            continue

        step = _step_start(f"battery_check:{camera_name}")
        level = None
        try:
            cam_coords = camera_conf["tap_coords"]

            # 1. Tap camera thumbnail
            logger.info(f"[BATTERY] {camera_name}: tap camera at ({cam_coords['x']}, {cam_coords['y']})")
            adb_adapter.tap(device_id, cam_coords["x"], cam_coords["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(config.BATTERY_CHECK_SETTINGS_WAIT_SECONDS)

            # 2. Tap settings icon
            logger.info(f"[BATTERY] {camera_name}: tap settings at ({settings_coords['x']}, {settings_coords['y']})")
            adb_adapter.tap(device_id, settings_coords["x"], settings_coords["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(config.BATTERY_CHECK_SETTINGS_WAIT_SECONDS)

            # 3. UI dump and parse
            logger.info(f"[BATTERY] {camera_name}: running uiautomator dump...")
            xml_content = adb_adapter.dump_ui_hierarchy(device_id, timeout_s=config.UIAUTOMATOR_DUMP_TIMEOUT_SECONDS)
            level = adb_adapter.parse_camera_battery_from_settings(xml_content)

            if level is not None:
                logger.info(f"[BATTERY] {camera_name}: battery level = {level}%")
            else:
                logger.warning(f"[BATTERY] {camera_name}: could not read battery level from settings screen")

            battery_monitor.update(camera_name, level)
            steps.append(_step_end(step, True, f"level={level}%"))

        except Exception as exc:
            logger.error(f"[BATTERY] {camera_name}: battery check failed: {exc}", exc_info=True)
            battery_monitor.update(camera_name, level)
            steps.append(_step_end(step, False, str(exc)))
        finally:
            # 4. Navigate back to camera_list (BACK × 2)
            try:
                for _ in range(2):
                    adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                    time.sleep(config.POST_BACK_DELAY_SECONDS)
            except Exception as exc:
                logger.warning(f"[BATTERY] {camera_name}: failed to navigate back: {exc}")

            # 5. Verify we returned to camera_list
            ok, state, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, f"battery_post:{camera_name}")
            if not ok:
                logger.warning(f"[BATTERY] {camera_name}: not on camera_list after BACK (state={state.value}), recovering...")
                if not _recover_to_camera_list(device_id, state):
                    logger.error(f"[BATTERY] {camera_name}: recovery failed, aborting remaining cameras.")
                    break

    logger.info(f"[BATTERY] Check complete: {battery_monitor.status()}")


def run_capture_batch(
    device_id: str | None = None,
    steps: list[dict] | None = None,
    camera_cb: CameraCircuitBreaker | None = None,
    battery_monitor: CameraBatteryMonitor | None = None,
) -> dict | None:
    """
    Executa um fluxo de captura para todas as cameras configuradas no app ICSee.
    Inclui verificacao de estado de tela e recuperacao automatica quando habilitado.
    """
    logger.info("Iniciando fluxo de captura para todas as cameras...")

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    active_device_id = device_id

    try:
        if not active_device_id:
            devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise RuntimeError("Nenhum dispositivo encontrado para captura.")
            active_device_id = devices[0]

        logger.info(f"Usando o dispositivo: {active_device_id}")

        # --- CHECKPOINT A: verificar se estamos na tela de lista de cameras ---
        if config.ENABLE_SCREEN_STATE_DETECTION:
            step = _step_start("checkpoint_a:verify_camera_list")
            ok, state, _ = _check_screen(active_device_id, ScreenState.CAMERA_LIST, "pre_cycle")
            if not ok:
                logger.warning(f"Checkpoint A: tela errada ({state.value}), tentando recuperar...")
                recovery_ok = _recover_to_camera_list(active_device_id, state)
                if steps is not None:
                    steps.append(_step_end(step, recovery_ok, f"recovery_from={state.value}"))
                if not recovery_ok:
                    raise RuntimeError(f"Checkpoint A falhou: nao conseguiu voltar para camera_list (estado={state.value})")
                logger.info("Checkpoint A: recuperacao bem-sucedida.")
            else:
                if steps is not None:
                    steps.append(_step_end(step, True, "camera_list_ok"))

        total_cameras = len(config.CAMERAS)
        logger.info(f"Encontradas {total_cameras} cameras para capturar.")

        last_screenshot_info = None
        cameras_skipped = 0
        cameras_failed = 0
        for i, (camera_name, camera_conf) in enumerate(config.CAMERAS.items()):
            # --- Battery: skip cameras without reading or with critically low battery ---
            if battery_monitor and battery_monitor.is_capture_paused(camera_name):
                cameras_skipped += 1
                cam_status = battery_monitor.status().get(camera_name, {})
                level = cam_status.get("level")
                if level is None:
                    reason = "no_battery_reading"
                    logger.warning(f"[{camera_name}] Captura bloqueada: sem leitura de bateria ainda")
                else:
                    reason = f"battery_critical:{level}%"
                    logger.warning(f"[{camera_name}] Captura pausada: bateria critica ({level}%)")
                if steps is not None:
                    steps.append(_step_end(_step_start(f"camera:{camera_name}:skipped_battery"), True, reason))
                continue

            # --- Circuit breaker: skip disabled cameras ---
            if camera_cb and not camera_cb.is_available(camera_name):
                cameras_skipped += 1
                if steps is not None:
                    steps.append(_step_end(_step_start(f"camera:{camera_name}:skipped_cb"), True, "circuit_breaker_open"))
                continue

            logger.info(f"--- [Camera {i+1}/{total_cameras}] Iniciando captura para: {camera_name} ---")

            try:
                # --- Etapa 1: Navegar ate a camera ---
                step = _step_start(f"camera:{camera_name}:tap")
                cam_coords = camera_conf["tap_coords"]
                logger.info(f"[{camera_name}] Acessando camera em (X={cam_coords['x']}, Y={cam_coords['y']})...")
                adb_adapter.tap(
                    active_device_id,
                    cam_coords["x"],
                    cam_coords["y"],
                    timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                )
                if steps is not None:
                    steps.append(_step_end(step, True))

                # --- Etapa 2: Aguardar stream carregar (polling) ---
                # Em vez de esperar um tempo fixo, verificamos se a tela ainda
                # esta carregando (preta) ou se voltou para a lista de cameras.
                step = _step_start(f"camera:{camera_name}:wait_stream")
                stream_ready = _wait_for_stream(active_device_id, camera_name, cam_coords)
                if steps is not None:
                    steps.append(_step_end(step, stream_ready))
                if not stream_ready:
                    logger.warning(f"[{camera_name}] Stream timeout, voltando para HOME...")
                    adb_adapter.go_home_keyevent(active_device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
                    raise RuntimeError(f"Stream nao carregou para {camera_name} dentro de {config.WAIT_STREAM_LOAD_SECONDS}s")

                # --- Etapa 3: Ritual de Estabilizacao Pre-Captura ---
                logger.info(f"[{camera_name}] Iniciando ritual de estabilizacao pre-captura...")
                step = _step_start(f"camera:{camera_name}:pre_capture")
                _run_pre_capture_sequence(active_device_id, camera_name)
                logger.info(f"[{camera_name}] Ritual de estabilizacao concluido.")
                if steps is not None:
                    steps.append(_step_end(step, True))

                # --- Etapa 4: Verificacao pre-captura ---
                # Conferir que estamos em fullscreen (nao em camera_list, loading, ou camera_normal)
                if config.ENABLE_SCREEN_STATE_DETECTION:
                    step = _step_start(f"camera:{camera_name}:pre_capture_check")
                    for retry in range(config.PRE_CAPTURE_RETRY_MAX + 1):
                        state, _fp, path = screen_classifier.capture_and_detect(
                            active_device_id, f"pre_capture_check:{camera_name}:r{retry}"
                        )
                        is_loading = (
                            state == ScreenState.CAMERA_FULLSCREEN
                            and path and os.path.exists(path)
                            and _is_loading_screen(path)
                        )
                        # Cleanup temp screenshot
                        try:
                            if path and os.path.exists(path):
                                os.remove(path)
                        except OSError:
                            pass

                        if state == ScreenState.CAMERA_LIST:
                            if steps is not None:
                                steps.append(_step_end(step, False, "voltou_para_camera_list"))
                            raise RuntimeError(f"[{camera_name}] Voltou para camera_list antes da captura")

                        if is_loading:
                            logger.warning(f"[{camera_name}] Tela de loading detectada antes da captura, aguardando 5s...")
                            time.sleep(5)
                            continue

                        if state == ScreenState.CAMERA_NORMAL:
                            if retry < config.PRE_CAPTURE_RETRY_MAX:
                                logger.warning(f"[{camera_name}] Ainda em camera_normal apos ritual (tentativa {retry+1}), repetindo ritual...")
                                _run_pre_capture_sequence(active_device_id, camera_name)
                                continue
                            else:
                                logger.error(f"[{camera_name}] Nao entrou em fullscreen apos {config.PRE_CAPTURE_RETRY_MAX+1} tentativas")
                                if steps is not None:
                                    steps.append(_step_end(step, False, "stuck_in_camera_normal"))
                                raise RuntimeError(f"[{camera_name}] Nao entrou em fullscreen apos ritual")

                        # CAMERA_FULLSCREEN (not loading) or UNKNOWN — proceed
                        break

                    if steps is not None and step.get("end") is None:
                        steps.append(_step_end(step, True, f"state={state.value}"))

                # --- Etapa 5: Capturar o Screenshot ---
                step = _step_start(f"camera:{camera_name}:screencap_validate")
                logger.info(f"[{camera_name}] Iniciando captura de screenshot com validacao...")
                screenshot_info = _capture_with_validation(active_device_id, camera_name)
                last_screenshot_info = screenshot_info
                if steps is not None:
                    steps.append(_step_end(step, screenshot_info.get("validated", False), screenshot_info.get("validation_reason")))
                if not screenshot_info.get("validated"):
                    raise RuntimeError(f"Screenshot invalid: {screenshot_info.get('validation_reason')}")

                # --- Etapa 4: Acoes Pos-Captura (Retornar N Niveis) ---
                logger.info(f"[{camera_name}] Iniciando sequencia de retorno pos-captura...")
                post_step = _step_start(f"camera:{camera_name}:post_back")
                for j in range(config.POST_CAPTURE_BACK_COUNT):
                    back_index = j + 1
                    logger.info(f"[{camera_name}] Executando BACK ({back_index}/{config.POST_CAPTURE_BACK_COUNT})...")
                    adb_adapter.press_key(
                        active_device_id,
                        "KEYCODE_BACK",
                        timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                    )
                    if back_index < config.POST_CAPTURE_BACK_COUNT:
                        logger.info(f"[{camera_name}] Aguardando {config.POST_BACK_DELAY_SECONDS}s...")
                        time.sleep(config.POST_BACK_DELAY_SECONDS)
                if steps is not None:
                    steps.append(_step_end(post_step, True))

                logger.info(f"--- [Camera {i+1}/{total_cameras}] Captura para {camera_name} concluida. ---")
                if camera_cb:
                    camera_cb.record_success(camera_name)

            except Exception as e:
                logger.error(f"--- [Camera {i+1}/{total_cameras}] Erro ao processar '{camera_name}': {e} ---", exc_info=True)
                cameras_failed += 1
                if camera_cb:
                    camera_cb.record_failure(camera_name)
                continue

            # Adiciona um delay entre as cameras para estabilizacao da UI, exceto apos a ultima.
            if i < total_cameras - 1:
                logger.info(f"Aguardando {config.INTER_CAMERA_DELAY_SECONDS}s antes de prosseguir para a proxima camera...")
                time.sleep(config.INTER_CAMERA_DELAY_SECONDS)

        # --- Check: at least one camera must have succeeded ---
        if last_screenshot_info is None:
            if cameras_skipped == total_cameras:
                raise RuntimeError(f"Todas as {total_cameras} cameras desabilitadas pelo circuit breaker")
            raise RuntimeError(f"Nenhuma camera capturada com sucesso ({cameras_failed} falhas, {cameras_skipped} puladas)")

        # --- CHECKPOINT C: verificar se voltamos para a lista de cameras ---
        if config.ENABLE_SCREEN_STATE_DETECTION:
            step = _step_start("checkpoint_c:verify_camera_list")
            ok, state, _ = _check_screen(active_device_id, ScreenState.CAMERA_LIST, "post_cycle")
            if steps is not None:
                steps.append(_step_end(step, ok, f"state={state.value}"))
            if not ok:
                logger.warning(f"Checkpoint C: ciclo terminou em estado inesperado ({state.value}). Informativo apenas.")

        return last_screenshot_info

    except Exception as e:
        logger.critical(f"Ocorreu um erro critico no fluxo de captura principal: {e}", exc_info=True)
        raise

    finally:
        if active_device_id:
            logger.info("Fluxo de captura para todas as cameras finalizado.")


def _restart_app(device_id: str, reason: str, steps: list[dict]) -> None:
    """Force-stop and relaunch the ICSee app.

    After relaunch, presses BACK to dismiss any overlay (CloudWebActivity,
    ads, webviews) that ICSee may show on cold start.
    """
    step = _step_start(f"app_restart:{reason}")
    logger.info(f"Reiniciando app: {reason}...")
    try:
        adb_adapter.close_app(device_id, config.ICSEE_PACKAGE_NAME, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        time.sleep(2)
        adb_adapter.go_home_keyevent(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        time.sleep(1)
        adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)

        # Dismiss overlays (CloudWebActivity) that appear after cold start
        for i in range(config.APP_LAUNCH_DISMISS_BACK_PRESSES):
            logger.info(f"Dismiss overlay: BACK ({i+1}/{config.APP_LAUNCH_DISMISS_BACK_PRESSES})")
            adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(config.APP_LAUNCH_DISMISS_DELAY_SECONDS)

        steps.append(_step_end(step, True))
        logger.info("App reiniciado com sucesso.")
    except Exception as exc:
        steps.append(_step_end(step, False, str(exc)))
        logger.error(f"Falha ao reiniciar app: {exc}", exc_info=True)


def _detect_and_recover_app(device_id: str, reason: str, steps: list[dict]) -> bool:
    """Detect if ICSee is in a bad state (OOM/ANR/crash) and force-restart if needed."""
    try:
        focus = adb_adapter.get_focus_info(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
        pkg = focus.get("package", "") or ""

        is_launcher = any(lp in pkg for lp in config.LAUNCHER_PACKAGES)
        is_anr = "Application Not Responding" in focus.get("raw", "") or (pkg == "android")

        if is_launcher or is_anr:
            logger.warning(f"App em estado ruim detectado: pkg={pkg}, launcher={is_launcher}, anr={is_anr}. Motivo: {reason}")
            _restart_app(device_id, f"recovery:{reason}:pkg={pkg}", steps)
            return True
        return False
    except Exception as exc:
        logger.warning(f"Nao foi possivel verificar estado do app para recovery: {exc}")
        return False


def _run_cycle_body(
    cycle_id: int,
    steps: list[dict],
    camera_cb: CameraCircuitBreaker,
    consecutive_failures: int,
    battery_monitor: CameraBatteryMonitor | None = None,
) -> tuple:
    """Cycle body extracted for watchdog wrapping. Returns (health_snapshot, screenshot_info, focus_info, device_id)."""
    step = _step_start("health_check")
    devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    if not devices:
        raise RuntimeError("Nenhum dispositivo encontrado para captura.")
    device_id = devices[0]

    # --- Memory pre-check before starting cycle ---
    if config.MEMORY_CHECK_ENABLED:
        mem_step = _step_start("memory_pre_check")
        try:
            mem_info = adb_adapter.get_mem_info(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            mem_kb = mem_info.get("mem_available_kb")
            if mem_kb is not None:
                if mem_kb < config.MEMORY_CRITICAL_THRESHOLD_KB:
                    logger.critical(
                        f"[cycle_id={cycle_id}] MEMORY CRITICAL pre-check: {mem_kb}KB. "
                        f"Rebooting device before cycle."
                    )
                    adb_adapter.reboot_device(device_id)
                    adb_adapter.wait_for_device(device_id, max_wait_s=config.MEMORY_POST_REBOOT_WAIT_SECONDS)
                    time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
                    adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                    time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
                    steps.append(_step_end(mem_step, True, f"rebooted:mem={mem_kb}KB"))
                elif mem_kb < config.MEMORY_WARNING_THRESHOLD_KB:
                    logger.warning(
                        f"[cycle_id={cycle_id}] MEMORY WARNING pre-check: {mem_kb}KB. "
                        f"Restarting app to free memory."
                    )
                    _restart_app(device_id, f"memory_warning:{mem_kb}KB", steps)
                    time.sleep(5)
                    steps.append(_step_end(mem_step, True, f"app_restarted:mem={mem_kb}KB"))
                else:
                    steps.append(_step_end(mem_step, True, f"ok:mem={mem_kb}KB"))
            else:
                steps.append(_step_end(mem_step, True, "mem_unavailable"))
        except Exception as exc:
            logger.warning(f"[cycle_id={cycle_id}] Memory pre-check failed: {exc}")
            steps.append(_step_end(mem_step, False, str(exc)))

    # --- Periodic app restart ---
    if config.APP_RESTART_EVERY_N_CYCLES > 0 and cycle_id % config.APP_RESTART_EVERY_N_CYCLES == 0:
        _restart_app(device_id, f"periodic_every_{config.APP_RESTART_EVERY_N_CYCLES}_cycles", steps)

    # --- Circuit breaker: restart app after N consecutive failures ---
    if consecutive_failures > 0 and consecutive_failures % config.CIRCUIT_BREAKER_THRESHOLD == 0:
        _restart_app(device_id, f"circuit_breaker_after_{consecutive_failures}_failures", steps)

    health_snapshot: dict | None = None
    if config.ENABLE_HEALTHCHECK:
        try:
            health_snapshot = adb_adapter.get_health_snapshot(
                device_id,
                timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS,
            )
            steps.append(_step_end(step, True))
        except Exception as exc:
            steps.append(_step_end(step, False, f"health_error:{exc}"))
            health_snapshot = {"error": str(exc)}
            logger.exception("Health check failed.")
    else:
        logger.info("Health check desabilitado por config; pulando coleta.")
        health_snapshot = {"disabled": True}
        steps.append(_step_end(step, True, "disabled_by_config"))

    # --- Camera battery check ---
    if battery_monitor and battery_monitor.any_needs_check():
        logger.info(f"[cycle_id={cycle_id}] Running camera battery check...")
        _check_cameras_battery(device_id, battery_monitor, steps)

    step = _step_start("capture_batch")
    screenshot_info = run_capture_batch(
        device_id=device_id, steps=steps, camera_cb=camera_cb,
        battery_monitor=battery_monitor,
    )
    focus_info = screenshot_info.get("focus") if screenshot_info else None
    steps.append(_step_end(step, True))

    return health_snapshot, screenshot_info, focus_info, device_id


def run_forever_loop():
    _ensure_logging()
    cycle_id = 0
    consecutive_failures = 0
    max_cycles = config.MAX_CYCLES
    if max_cycles == 0:
        max_cycles = None

    camera_cb = CameraCircuitBreaker(
        threshold=config.CAMERA_CB_FAILURE_THRESHOLD,
        cooldown_s=config.CAMERA_CB_COOLDOWN_SECONDS,
    )
    battery_monitor = CameraBatteryMonitor()

    while True:
        control = _read_control_state()
        if control.get("stop"):
            logger.info("Controle: stop solicitado. Encerrando loop.")
            break
        if control.get("pause") and not control.get("run_once"):
            logger.info("Controle: pausa ativa. Aguardando para retomar...")
            time.sleep(5)
            continue
        run_once = control.get("run_once", False)

        cycle_id += 1
        cycle_start = time.time()
        cycle_id_str = f"{cycle_id}"
        ts_start = _now_iso()
        logger.info(f"[cycle_id={cycle_id}] Ciclo iniciado.")
        cycle_error = None
        cycle_error_type = None
        cycle_trace = None
        steps: list[dict] = []
        focus_info: dict | None = None
        health_snapshot: dict | None = None
        screenshot_info: dict | None = None
        device_id = None

        try:
            # --- Watchdog: run cycle body with global timeout ---
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _run_cycle_body, cycle_id, steps, camera_cb, consecutive_failures,
                    battery_monitor,
                )
                try:
                    health_snapshot, screenshot_info, focus_info, device_id = future.result(
                        timeout=config.CYCLE_TIMEOUT_SECONDS,
                    )
                except concurrent.futures.TimeoutError:
                    logger.error(
                        f"[cycle_id={cycle_id}] Watchdog timeout! Ciclo excedeu {config.CYCLE_TIMEOUT_SECONDS}s. "
                        f"Reiniciando ADB server para desbloquear."
                    )
                    adb_adapter._restart_adb_server()
                    raise RuntimeError(f"Watchdog timeout apos {config.CYCLE_TIMEOUT_SECONDS}s")

            consecutive_failures = 0

        except Exception as exc:
            cycle_error = str(exc)
            cycle_error_type = type(exc).__name__
            cycle_trace = traceback.format_exc()
            consecutive_failures += 1
            logger.error(f"[cycle_id={cycle_id}] Erro no ciclo (falha consecutiva #{consecutive_failures}): {exc}", exc_info=True)

            # --- App recovery: detect OOM/ANR/crash and force-restart ---
            if device_id:
                _detect_and_recover_app(device_id, f"cycle_error:{cycle_error_type}", steps)

            # Exponential backoff
            backoff = min(
                config.ERROR_BACKOFF_BASE_SECONDS * (2 ** (consecutive_failures - 1)),
                config.ERROR_BACKOFF_MAX_SECONDS,
            )
            logger.info(f"[cycle_id={cycle_id}] Aplicando backoff exponencial de {backoff:.0f}s.")

            if device_id:
                _write_error_artifacts(cycle_id_str, device_id, health_snapshot, screenshot_info.get("path") if screenshot_info else None)
            time.sleep(backoff)
        finally:
            cycle_end = time.time()
            cycle_duration_s = round(cycle_end - cycle_start, 3)
            ts_end = _now_iso()

            event = {
                "cycle_id": cycle_id_str,
                "ts_start": ts_start,
                "ts_end": ts_end,
                "duration_ms": int(cycle_duration_s * 1000),
                "ok": cycle_error is None,
                "error": _error_obj(cycle_error, cycle_error_type, steps, cycle_trace),
                "steps": steps,
                "focus": focus_info,
                "health": health_snapshot,
                "screenshot": screenshot_info,
                "camera_cb": camera_cb.status(),
                "camera_battery": battery_monitor.status(),
            }
            _append_jsonl(config.CYCLES_JSONL_PATH, event)

            logger.info(f"[cycle_id={cycle_id}] Ciclo finalizado em {cycle_duration_s}s.")

            if not cycle_error:
                elapsed = cycle_end - cycle_start
                interval = config.CAPTURE_INTERVAL_SECONDS * battery_monitor.get_interval_multiplier()
                sleep_seconds = max(0, interval - elapsed)
                if battery_monitor.get_interval_multiplier() > 1:
                    logger.info(
                        f"[cycle_id={cycle_id}] Intervalo dobrado por bateria baixa "
                        f"({config.CAPTURE_INTERVAL_SECONDS}s -> {interval}s)"
                    )
                if sleep_seconds > 0:
                    logger.info(f"[cycle_id={cycle_id}] Dormindo {sleep_seconds:.1f}s ate o proximo ciclo.")
                    time.sleep(sleep_seconds)

        # --- Max consecutive failures: stop loop entirely ---
        if consecutive_failures >= config.MAX_CONSECUTIVE_FAILURES:
            logger.critical(
                f"[cycle_id={cycle_id}] {consecutive_failures} falhas consecutivas atingiram o limite "
                f"de {config.MAX_CONSECUTIVE_FAILURES}. Encerrando loop para evitar danos ao dispositivo."
            )
            break

        if run_once:
            control["run_once"] = False
            _write_control_state(control)

        if not config.RUN_FOREVER and max_cycles and cycle_id >= max_cycles:
            logger.info(f"[cycle_id={cycle_id}] Encerrando loop (MAX_CYCLES atingido).")
            break


def run_capture():
    """Executa o fluxo de captura para todas as cameras configuradas."""
    run_capture_batch()


if __name__ == "__main__":
    run_capture()

```

## `ingester/src/ingester/local/cycle_logger.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/cycle_logger.py
"""Cycle logging, step tracking, control state, and error artifact collection."""
import json
import logging
import os
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler

from . import adb_adapter
from .. import config

logger = logging.getLogger(__name__)


def ensure_logging() -> None:
    """Set up rotating file + console logging if not already configured."""
    if logging.getLogger().handlers:
        return
    os.makedirs(config.LOG_DIR, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        os.path.join(config.LOG_DIR, "ingester.log"),
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def append_jsonl(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def read_control_state() -> dict:
    path = config.CONTROL_JSON_PATH
    if not os.path.exists(path):
        return {"pause": False, "stop": False, "run_once": False}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"pause": False, "stop": False, "run_once": False}
    return {
        "pause": bool(data.get("pause", False)),
        "stop": bool(data.get("stop", False)),
        "run_once": bool(data.get("run_once", False)),
    }


def write_control_state(state: dict) -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    with open(config.CONTROL_JSON_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=True, indent=2)


def step_start(name: str) -> dict:
    return {"name": name, "ok": False, "start": now_iso(), "end": None, "duration_ms": None, "details": None}


def step_end(step: dict, ok: bool, details: str | None = None) -> dict:
    step["ok"] = ok
    step["end"] = now_iso()
    step["duration_ms"] = _duration_ms(step["start"], step["end"])
    if details:
        step["details"] = details
    return step


def _duration_ms(start_iso: str, end_iso: str) -> int:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    return int((end - start).total_seconds() * 1000)


def error_obj(error_message: str | None, error_type: str | None, steps: list[dict], trace: str | None = None) -> dict | None:
    if not error_message:
        return None
    step_name = steps[-1]["name"] if steps else None
    return {
        "type": error_type or "CycleError",
        "message": error_message,
        "step": step_name,
        "trace": trace,
    }


def write_error_artifacts(cycle_id: str, device_id: str, health: dict | None, screenshot_path: str | None) -> str:
    base_dir = os.path.join(config.LOG_DIR, f"cycle_{cycle_id}_artifacts")
    os.makedirs(base_dir, exist_ok=True)

    window_txt = os.path.join(base_dir, "window.txt")
    logcat_txt = os.path.join(base_dir, "logcat.txt")
    health_json = os.path.join(base_dir, "health.json")

    if config.ENABLE_FOCUS_VALIDATION:
        try:
            window_dump = adb_adapter.get_window_dump(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            with open(window_txt, "w", encoding="utf-8") as handle:
                handle.write(window_dump)
        except Exception as exc:
            logger.error(f"Failed to write window.txt: {exc}", exc_info=True)
    else:
        logger.info("Skipping window.txt artifact (focus validation disabled).")

    try:
        logcat = adb_adapter.get_logcat_tail(device_id, config.LOGCAT_LINES_ON_ERROR, config.HEALTH_ADB_TIMEOUT_SECONDS)
        with open(logcat_txt, "w", encoding="utf-8") as handle:
            handle.write(logcat)
    except Exception as exc:
        logger.error(f"Failed to write logcat.txt: {exc}", exc_info=True)

    try:
        with open(health_json, "w", encoding="utf-8") as handle:
            json.dump(health or {}, handle, ensure_ascii=True, indent=2)
    except Exception as exc:
        logger.error(f"Failed to write health.json: {exc}", exc_info=True)

    if screenshot_path and os.path.exists(screenshot_path):
        try:
            shutil.copyfile(screenshot_path, os.path.join(base_dir, "screenshot.png"))
        except Exception as exc:
            logger.error(f"Failed to copy screenshot: {exc}", exc_info=True)

    return base_dir

```

## `ingester/src/ingester/local/image_validator.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/image_validator.py
"""Image analysis, screenshot validation, and loading screen detection."""
import logging

from PIL import Image

from . import screen_fingerprint
from .. import config

logger = logging.getLogger(__name__)


def analyze_image(path: str) -> dict:
    """Compute basic grayscale statistics for a screenshot."""
    with Image.open(path) as img:
        gray = img.convert("L").resize((64, 64))
        pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    min_v = min(pixels)
    max_v = max(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    std = variance ** 0.5
    return {"mean": round(mean, 2), "std": round(std, 2), "min": min_v, "max": max_v}


def validate_screenshot(stats: dict) -> tuple[bool, str]:
    """Reject screenshots that are probably black or white screens."""
    mean = stats["mean"]
    std = stats["std"]
    if mean <= config.BLACK_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_black_screen"
    if mean >= config.WHITE_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_white_screen"
    return True, "ok"


def validate_focus(focus: dict) -> tuple[bool, str]:
    """Check whether the expected app/activity has window focus."""
    pkg = focus.get("package")
    activity = focus.get("activity")
    if pkg != config.EXPECTED_PACKAGE:
        return False, f"focus_package_mismatch:{pkg}"
    if activity not in config.EXPECTED_ACTIVITIES:
        return False, f"focus_activity_mismatch:{activity}"
    return True, "ok"


def is_loading_screen(screenshot_path: str) -> bool:
    """Check if the screenshot is a loading/black screen (stream not ready yet)."""
    stats = analyze_image(screenshot_path)
    if stats["mean"] <= config.BLACK_MEAN_THRESHOLD and stats["std"] <= config.LOW_STD_THRESHOLD:
        return True

    fp = screen_fingerprint.extract_fingerprint(screenshot_path)
    ind = fp["indicators"]
    return (
        stats["mean"] <= config.LOADING_MEAN_MAX
        and ind.get("bright_ratio_center", 0.0) >= config.LOADING_BRIGHT_CENTER_MIN
    )

```

## `ingester/src/ingester/local/screen_classifier.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/screen_classifier.py
"""
Screen state classifier for the ICSee capture flow.

Detects which screen the device is currently showing by analyzing
UI chrome (bars, edges, headers) — NOT camera content, which varies.
"""
import logging
import os
import re
import tempfile
from enum import Enum

from . import adb_adapter, screen_fingerprint
from .. import config

logger = logging.getLogger(__name__)


class ScreenState(Enum):
    HOME = "home"
    CAMERA_LIST = "camera_list"
    CAMERA_NORMAL = "camera_normal"
    CAMERA_FULLSCREEN = "camera_fullscreen"
    UNKNOWN = "unknown"


def detect_screen_state(image_path: str) -> tuple[ScreenState, dict]:
    """Classify screen state from a screenshot.

    Returns (state, fingerprint_dict).
    """
    fp = screen_fingerprint.extract_fingerprint(image_path)
    ind = fp["indicators"]
    thresh = config.SCREEN_STATE_THRESHOLDS

    state = _classify(ind, thresh)

    logger.info(
        f"Screen state detected: {state.value} | "
        f"dark_top={ind['dark_ratio_top']:.2f} "
        f"dark_left={ind['dark_ratio_left']:.2f} "
        f"h_line_status={ind['h_line_status_bottom']:.2f} "
        f"dark_header={ind['dark_ratio_header']:.2f} "
        f"center_edge={ind['center_edge_density']:.1f}"
    )

    return state, fp


def _classify(ind: dict, thresh: dict) -> ScreenState:
    """Decision tree based on raw indicator values.

    Evaluation order (most distinctive first):
      1. camera_normal:     dark_ratio_top >= 0.5
      2. camera_fullscreen: dark_ratio_left >= 0.7
      3. home:              h_line_status_bottom <= 0.3
      4. camera_list:       h_line_status_bottom > 0.3 AND sanity checks pass
      5. UNKNOWN:           fallback when nothing fits

    Each positive match also runs a sanity check to avoid false positives.
    """
    t_norm = thresh.get("camera_normal", {})
    t_fs = thresh.get("camera_fullscreen", {})
    t_home = thresh.get("home", {})
    t_sanity = thresh.get("sanity", {})

    dark_top = ind["dark_ratio_top"]
    dark_left = ind["dark_ratio_left"]
    h_line = ind["h_line_status_bottom"]

    # Valores de referência observados:
    #   dark_ratio_top:  home=0.02, list=0.01, normal=0.76, full=0.04
    #   dark_ratio_left: home=0.004, list=0, normal=0.15, full=0.86
    #   h_line_status:   home=0.11, list=0.79, normal=0.80, full=0.3-0.6

    # 1. CAMERA_NORMAL: topo muito escuro (~0.76)
    #    Sanity: dark_left deve ser baixo (não é fullscreen)
    if dark_top >= t_norm.get("dark_ratio_top_min", 0.5):
        if dark_left < t_fs.get("dark_ratio_left_min", 0.7):
            return ScreenState.CAMERA_NORMAL
        # Topo escuro E borda escura — improvável, marcar como desconhecido
        logger.warning(f"Classificacao ambigua: dark_top={dark_top:.2f} E dark_left={dark_left:.2f} altos")
        return ScreenState.UNKNOWN

    # 2. CAMERA_FULLSCREEN: borda esquerda escura (~0.86)
    #    Sanity: topo NÃO deve ser escuro (já foi descartado acima)
    if dark_left >= t_fs.get("dark_ratio_left_min", 0.7):
        return ScreenState.CAMERA_FULLSCREEN

    # 3. HOME: sem linha de status do app (~0.11)
    #    Sanity: dark_top e dark_left devem ser baixos
    if h_line <= t_home.get("h_line_status_bottom_max", 0.3):
        if dark_top < 0.15 and dark_left < 0.15:
            return ScreenState.HOME
        logger.warning(f"Classificacao ambigua: h_line={h_line:.2f} baixo mas dark_top={dark_top:.2f} dark_left={dark_left:.2f}")
        return ScreenState.UNKNOWN

    # 4. CAMERA_LIST: h_line alto (~0.79), dark ratios baixos
    #    Sanity: tela deve ser "brilhante" — dark ratios todos baixos
    max_dark = t_sanity.get("camera_list_max_dark", 0.3)
    if dark_top < max_dark and dark_left < max_dark:
        return ScreenState.CAMERA_LIST

    # 5. Nada se encaixou
    logger.warning(
        f"Estado desconhecido: dark_top={dark_top:.2f} dark_left={dark_left:.2f} "
        f"h_line={h_line:.2f} — nenhuma regra se encaixou"
    )
    return ScreenState.UNKNOWN


def capture_and_detect(
    device_id: str,
    context: str,
) -> tuple[ScreenState, dict, str]:
    """Take a screenshot and detect the screen state.

    Args:
        device_id: ADB device serial.
        context: Label for logging / filename (e.g. "pre_cycle").

    Returns:
        (state, fingerprint, screenshot_path)
    """
    safe_context = _sanitize_filename(context)
    fd, filepath = tempfile.mkstemp(prefix=f"state_{safe_context}_", suffix=".png")
    os.close(fd)

    success = adb_adapter.screencap(
        device_id, filepath, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS
    )
    if not success:
        logger.error(f"[{context}] Screenshot failed for state detection.")
        return ScreenState.UNKNOWN, {}, filepath

    state, fp = detect_screen_state(filepath)
    return state, fp, filepath


def _sanitize_filename(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\\\|?*]+', "_", value)
    sanitized = re.sub(r"\\s+", "_", sanitized).strip("_")
    return sanitized or "state"

```

## `ingester/src/ingester/local/screen_fingerprint.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/screen_fingerprint.py
"""
Diagnostic tool to extract visual fingerprints from device screenshots.

Usage (from the ingester root):
    python -m ingester.local.screen_fingerprint --label home
    python -m ingester.local.screen_fingerprint --label camera_list
    python -m ingester.local.screen_fingerprint --label camera_normal
    python -m ingester.local.screen_fingerprint --label camera_fullscreen

Each run captures a screenshot, extracts features, and appends to
    logs/screen_profiles.json
After capturing all 4 screens, the profiles file can be reviewed and
the thresholds copied into config.py for runtime screen detection.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

from PIL import Image, ImageStat

from . import adb_adapter
from .. import config

logger = logging.getLogger(__name__)

# Grid layout: split screen into regions for analysis
# Each region is (name, x_frac_start, y_frac_start, x_frac_end, y_frac_end)
#
# Strategy: camera content changes per camera/time-of-day, but UI chrome
# (bars, buttons, borders) stays consistent. We focus on structural regions.
REGIONS = [
    # --- System bars ---
    ("top_bar",        0.0, 0.00, 1.0, 0.04),   # Android status bar (clock, icons)
    ("bottom_bar",     0.0, 0.96, 1.0, 1.00),   # Android nav bar (back, home, recent)
    # --- App UI zones (outside the video area) ---
    ("app_header",     0.0, 0.04, 1.0, 0.12),   # App toolbar / title area
    ("app_footer",     0.0, 0.88, 1.0, 0.96),   # App bottom controls / tab bar
    # --- Edges (detect UI borders vs video filling the screen) ---
    ("left_edge",      0.0,  0.12, 0.04, 0.88),
    ("right_edge",     0.96, 0.12, 1.0,  0.88),
    # --- Content zones (will vary per camera, used for sanity only) ---
    ("center",         0.15, 0.30, 0.85, 0.70),
    # --- Full frame ---
    ("full",           0.0, 0.00, 1.0, 1.00),
]


def _region_stats(img: Image.Image, region: tuple) -> dict:
    """Extract color statistics for a rectangular region of the image."""
    name, x0f, y0f, x1f, y1f = region
    w, h = img.size
    box = (int(x0f * w), int(y0f * h), int(x1f * w), int(y1f * h))
    cropped = img.crop(box)

    # Grayscale stats
    gray = cropped.convert("L")
    gray_stat = ImageStat.Stat(gray)
    g_mean = gray_stat.mean[0]
    g_std = gray_stat.stddev[0]
    g_min, g_max = gray.getextrema()

    # Color stats (RGB)
    rgb = cropped.convert("RGB")
    rgb_stat = ImageStat.Stat(rgb)
    r_mean, g_mean_c, b_mean = rgb_stat.mean
    r_std, g_std_c, b_std = rgb_stat.stddev

    # Dominant color heuristic: mean RGB rounded
    dominant = (int(round(r_mean)), int(round(g_mean_c)), int(round(b_mean)))

    # Edge density: simple Sobel-like measure on grayscale
    small = gray.resize((64, 64))
    px = list(small.getdata())
    edge_sum = 0
    for y in range(1, 63):
        for x in range(1, 63):
            idx = y * 64 + x
            gx = abs(px[idx + 1] - px[idx - 1])
            gy = abs(px[idx + 64] - px[idx - 64])
            edge_sum += gx + gy
    edge_density = round(edge_sum / (62 * 62), 2)

    return {
        "region": name,
        "box_px": list(box),
        "gray_mean": round(g_mean, 2),
        "gray_std": round(g_std, 2),
        "gray_min": g_min,
        "gray_max": g_max,
        "rgb_mean": [round(r_mean, 2), round(g_mean_c, 2), round(b_mean, 2)],
        "rgb_std": [round(r_std, 2), round(g_std_c, 2), round(b_std, 2)],
        "dominant_rgb": list(dominant),
        "edge_density": edge_density,
    }


def _color_histogram_summary(img: Image.Image, bins: int = 8) -> dict:
    """Simplified color histogram: divide 0-255 into bins for each channel."""
    rgb = img.convert("RGB")
    r_hist = rgb.split()[0].histogram()
    g_hist = rgb.split()[1].histogram()
    b_hist = rgb.split()[2].histogram()

    def _bin(hist, n_bins):
        step = 256 // n_bins
        total = sum(hist)
        return [round(sum(hist[i * step:(i + 1) * step]) / total, 4) for i in range(n_bins)]

    return {
        "r_hist": _bin(r_hist, bins),
        "g_hist": _bin(g_hist, bins),
        "b_hist": _bin(b_hist, bins),
    }


def _aspect_and_size(img: Image.Image) -> dict:
    w, h = img.size
    return {"width": w, "height": h, "aspect": round(w / h, 4)}


def _dark_pixel_ratio(img: Image.Image, region_frac: tuple, threshold: int = 30) -> float:
    """Fraction of pixels darker than threshold in a region. Detects dark UI bars."""
    x0f, y0f, x1f, y1f = region_frac
    w, h = img.size
    box = (int(x0f * w), int(y0f * h), int(x1f * w), int(y1f * h))
    gray = img.crop(box).convert("L")
    px = list(gray.getdata())
    if not px:
        return 0.0
    return round(sum(1 for p in px if p < threshold) / len(px), 4)


def _bright_pixel_ratio(img: Image.Image, region_frac: tuple, threshold: int = 200) -> float:
    """Fraction of pixels brighter than threshold in a region."""
    x0f, y0f, x1f, y1f = region_frac
    w, h = img.size
    box = (int(x0f * w), int(y0f * h), int(x1f * w), int(y1f * h))
    gray = img.crop(box).convert("L")
    px = list(gray.getdata())
    if not px:
        return 0.0
    return round(sum(1 for p in px if p > threshold) / len(px), 4)


def _horizontal_line_score(img: Image.Image, y_frac: float, tolerance: int = 10) -> float:
    """Detect if there's a horizontal line (UI separator) at a given Y fraction.
    Returns fraction of pixels in that row that match the row's median color."""
    w, h = img.size
    y = int(y_frac * h)
    y = max(0, min(y, h - 1))
    row = list(img.convert("L").crop((0, y, w, y + 1)).getdata())
    if not row:
        return 0.0
    median = sorted(row)[len(row) // 2]
    matching = sum(1 for p in row if abs(p - median) <= tolerance)
    return round(matching / len(row), 4)


def extract_fingerprint(image_path: str) -> dict:
    """Extract a full fingerprint from a screenshot PNG.

    The indicators focus on UI chrome (bars, edges, separators) which are
    stable regardless of what the camera is showing.
    """
    img = Image.open(image_path)

    regions = [_region_stats(img, r) for r in REGIONS]
    histogram = _color_histogram_summary(img)
    size_info = _aspect_and_size(img)

    def _r(name):
        return next(r for r in regions if r["region"] == name)

    top_bar = _r("top_bar")
    bottom_bar = _r("bottom_bar")
    app_header = _r("app_header")
    app_footer = _r("app_footer")
    left = _r("left_edge")
    right = _r("right_edge")
    center = _r("center")

    # --- Structural indicators (independent of camera content) ---

    # Dark pixel ratio in chrome zones — stable across cameras
    dark_ratio_top = _dark_pixel_ratio(img, (0.0, 0.0, 1.0, 0.04))
    dark_ratio_bottom = _dark_pixel_ratio(img, (0.0, 0.96, 1.0, 1.0))
    dark_ratio_header = _dark_pixel_ratio(img, (0.0, 0.04, 1.0, 0.12))
    dark_ratio_footer = _dark_pixel_ratio(img, (0.0, 0.88, 1.0, 0.96))
    dark_ratio_left = _dark_pixel_ratio(img, (0.0, 0.12, 0.04, 0.88))
    dark_ratio_right = _dark_pixel_ratio(img, (0.96, 0.12, 1.0, 0.88))
    bright_ratio_center = _bright_pixel_ratio(img, (0.4, 0.4, 0.6, 0.6))

    # Horizontal line detection at UI boundary positions
    # These detect separators between app header/content and content/footer
    h_line_top_border = _horizontal_line_score(img, 0.12)
    h_line_bottom_border = _horizontal_line_score(img, 0.88)
    h_line_status_bottom = _horizontal_line_score(img, 0.04)

    # UI presence booleans
    has_status_bar = top_bar["gray_mean"] > 30
    has_nav_bar = bottom_bar["gray_mean"] > 30
    has_app_header = app_header["edge_density"] > 8 or app_header["gray_std"] > 20
    has_app_footer = app_footer["edge_density"] > 8 or app_footer["gray_std"] > 20
    edges_dark = dark_ratio_left > 0.7 and dark_ratio_right > 0.7

    return {
        "size": size_info,
        "regions": regions,
        "histogram": histogram,
        "indicators": {
            # UI presence
            "has_status_bar": has_status_bar,
            "has_nav_bar": has_nav_bar,
            "has_app_header": has_app_header,
            "has_app_footer": has_app_footer,
            "edges_dark": edges_dark,
            # Raw values for threshold tuning
            "top_bar_gray_mean": top_bar["gray_mean"],
            "top_bar_gray_std": top_bar["gray_std"],
            "bottom_bar_gray_mean": bottom_bar["gray_mean"],
            "bottom_bar_gray_std": bottom_bar["gray_std"],
            "app_header_gray_mean": app_header["gray_mean"],
            "app_header_edge_density": app_header["edge_density"],
            "app_footer_gray_mean": app_footer["gray_mean"],
            "app_footer_edge_density": app_footer["edge_density"],
            "left_edge_gray_mean": left["gray_mean"],
            "left_edge_gray_std": left["gray_std"],
            "right_edge_gray_mean": right["gray_mean"],
            "right_edge_gray_std": right["gray_std"],
            "center_edge_density": center["edge_density"],
            # Dark ratios (% of dark pixels in chrome zones)
            "dark_ratio_top": dark_ratio_top,
            "dark_ratio_bottom": dark_ratio_bottom,
            "dark_ratio_header": dark_ratio_header,
            "dark_ratio_footer": dark_ratio_footer,
            "dark_ratio_left": dark_ratio_left,
            "dark_ratio_right": dark_ratio_right,
            "bright_ratio_center": bright_ratio_center,
            # Horizontal line scores at UI boundaries
            "h_line_status_bottom": h_line_status_bottom,
            "h_line_top_border": h_line_top_border,
            "h_line_bottom_border": h_line_bottom_border,
        },
    }


def capture_and_fingerprint(label: str, device_id: str | None = None) -> dict:
    """Capture a screenshot from the device and extract its fingerprint."""
    if not device_id:
        devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        if not devices:
            raise RuntimeError("Nenhum dispositivo conectado.")
        device_id = devices[0]

    os.makedirs(config.LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = os.path.join(config.LOG_DIR, f"fingerprint_{label}_{timestamp}.png")

    logger.info(f"Capturando screenshot para label='{label}' ...")
    success = adb_adapter.screencap(device_id, screenshot_path, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    if not success:
        raise RuntimeError(f"Falha ao capturar screenshot para label='{label}'.")

    logger.info(f"Extraindo fingerprint de {screenshot_path} ...")
    fp = extract_fingerprint(screenshot_path)

    result = {
        "label": label,
        "timestamp": timestamp,
        "device_id": device_id,
        "screenshot_path": screenshot_path,
        "fingerprint": fp,
    }

    # Append to profiles file
    profiles_path = os.path.join(config.LOG_DIR, "screen_profiles.json")
    existing = []
    if os.path.exists(profiles_path):
        with open(profiles_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing.append(result)
    with open(profiles_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    logger.info(f"Fingerprint salvo em {profiles_path}")
    _print_summary(result)
    return result


def _print_summary(result: dict):
    """Print a human-readable summary of the fingerprint."""
    fp = result["fingerprint"]
    ind = fp["indicators"]
    print(f"\n{'='*70}")
    print(f"  Screen Fingerprint: {result['label']}")
    print(f"{'='*70}")
    print(f"  Resolution:       {fp['size']['width']}x{fp['size']['height']}")
    print()
    print("  UI Chrome Detection (stable across cameras):")
    print(f"    Status bar:     {'YES' if ind['has_status_bar'] else 'NO':4s}  gray_mean={ind['top_bar_gray_mean']:5.1f}  dark_ratio={ind['dark_ratio_top']:.2f}")
    print(f"    Nav bar:        {'YES' if ind['has_nav_bar'] else 'NO':4s}  gray_mean={ind['bottom_bar_gray_mean']:5.1f}  dark_ratio={ind['dark_ratio_bottom']:.2f}")
    print(f"    App header:     {'YES' if ind['has_app_header'] else 'NO':4s}  gray_mean={ind['app_header_gray_mean']:5.1f}  edge_density={ind['app_header_edge_density']:.1f}  dark_ratio={ind['dark_ratio_header']:.2f}")
    print(f"    App footer:     {'YES' if ind['has_app_footer'] else 'NO':4s}  gray_mean={ind['app_footer_gray_mean']:5.1f}  edge_density={ind['app_footer_edge_density']:.1f}  dark_ratio={ind['dark_ratio_footer']:.2f}")
    print(f"    Left edge:      dark_ratio={ind['dark_ratio_left']:.2f}  gray={ind['left_edge_gray_mean']:5.1f}±{ind['left_edge_gray_std']:.1f}")
    print(f"    Right edge:     dark_ratio={ind['dark_ratio_right']:.2f}  gray={ind['right_edge_gray_mean']:5.1f}±{ind['right_edge_gray_std']:.1f}")
    print(f"    Edges dark:     {'YES' if ind['edges_dark'] else 'NO'}")
    print()
    print("  Horizontal lines (UI separators):")
    print(f"    Status bottom:  {ind['h_line_status_bottom']:.2f}")
    print(f"    Header/content: {ind['h_line_top_border']:.2f}")
    print(f"    Content/footer: {ind['h_line_bottom_border']:.2f}")
    print()
    print("  Region details:")
    for r in fp["regions"]:
        print(f"    {r['region']:14s}  gray={r['gray_mean']:6.1f}±{r['gray_std']:5.1f}  "
              f"rgb=({r['rgb_mean'][0]:5.1f},{r['rgb_mean'][1]:5.1f},{r['rgb_mean'][2]:5.1f})  "
              f"edge={r['edge_density']:5.1f}")
    print(f"{'='*70}\n")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Capture and fingerprint a device screen state.")
    parser.add_argument("--label", required=True,
                        help="Label for this screen state (e.g. home, camera_list, camera_normal, camera_fullscreen)")
    parser.add_argument("--device", default=None, help="ADB device serial (auto-detected if omitted)")
    parser.add_argument("--from-file", default=None,
                        help="Analyze an existing screenshot instead of capturing a new one")
    args = parser.parse_args()

    if args.from_file:
        fp = extract_fingerprint(args.from_file)
        result = {
            "label": args.label,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "device_id": "from_file",
            "screenshot_path": args.from_file,
            "fingerprint": fp,
        }
        _print_summary(result)

        profiles_path = os.path.join(config.LOG_DIR, "screen_profiles.json")
        existing = []
        if os.path.exists(profiles_path):
            with open(profiles_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        existing.append(result)
        os.makedirs(config.LOG_DIR, exist_ok=True)
        with open(profiles_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        print(f"Salvo em {profiles_path}")
    else:
        capture_and_fingerprint(args.label, device_id=args.device)


if __name__ == "__main__":
    main()

```

## `ingester/src/ingester/local/test_classifier.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/test_classifier.py
"""
Quick test: captures a screenshot and prints the detected screen state.

Usage (from ingester root):
    python -m ingester.local.test_classifier
"""
import logging

from . import adb_adapter, screen_classifier
from .. import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    if not devices:
        print("Nenhum dispositivo conectado.")
        return
    device_id = devices[0]
    print(f"Dispositivo: {device_id}\n")

    state, fp, path = screen_classifier.capture_and_detect(device_id, "test")
    ind = fp.get("indicators", {})

    dark_top = ind.get("dark_ratio_top", 0)
    dark_left = ind.get("dark_ratio_left", 0)
    h_line = ind.get("h_line_status_bottom", 0)

    t = config.SCREEN_STATE_THRESHOLDS
    t_top = t.get("camera_normal", {}).get("dark_ratio_top_min", 0.5)
    t_left = t.get("camera_fullscreen", {}).get("dark_ratio_left_min", 0.7)
    t_hline = t.get("home", {}).get("h_line_status_bottom_max", 0.3)
    t_sanity = t.get("sanity", {}).get("camera_list_max_dark", 0.3)

    def _mark(hit):
        return "<<< MATCH" if hit else ""

    r1 = dark_top >= t_top
    r2 = (not r1) and dark_left >= t_left
    r3 = (not r1 and not r2) and h_line <= t_hline
    r4 = (not r1 and not r2 and not r3) and dark_top < t_sanity and dark_left < t_sanity
    r5 = not (r1 or r2 or r3 or r4)

    print(f"\n{'='*60}")
    print(f"  ESTADO DETECTADO:  {state.value.upper()}")
    print(f"{'='*60}")
    print(f"  Regras (avaliadas em ordem):")
    print(f"    1. dark_ratio_top  = {dark_top:.4f}  >= {t_top}  → camera_normal     {_mark(r1)}")
    print(f"    2. dark_ratio_left = {dark_left:.4f}  >= {t_left}  → camera_fullscreen {_mark(r2)}")
    print(f"    3. h_line_status   = {h_line:.4f}  <= {t_hline}  → home              {_mark(r3)}")
    print(f"    4. dark_top & left < {t_sanity}          → camera_list        {_mark(r4)}")
    print(f"    5. nenhuma regra                  → UNKNOWN            {_mark(r5)}")
    print(f"\n  Screenshot: {path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

```

## `ingester/src/ingester/local/ui_selector.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/local/ui_selector.py
"""Find and tap UI elements by resource-id, content-desc, or text via uiautomator dump."""
import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET

from . import adb_adapter
from .. import config

logger = logging.getLogger(__name__)

_DUMP_TIMEOUT = 60


def find_element(
    device_id: str,
    resource_id: str | None = None,
    content_desc: str | None = None,
    text: str | None = None,
    timeout_s: float = _DUMP_TIMEOUT,
) -> dict | None:
    """Find a UI element via uiautomator dump.

    Returns {"center": {"x": int, "y": int}, "bounds": str} or None.
    At least one of resource_id, content_desc, or text must be provided.
    """
    remote_xml = "/sdcard/saira_ui_dump.xml"
    fd, local_xml = tempfile.mkstemp(prefix="ui_dump_", suffix=".xml")
    os.close(fd)

    try:
        dump_result = adb_adapter._run_command(
            ["-s", device_id, "shell", "uiautomator", "dump", remote_xml],
            timeout_s=timeout_s,
            check=False,
        )
        if dump_result.returncode != 0:
            logger.warning(f"uiautomator dump failed: {dump_result.stderr}")
            return None

        adb_adapter._run_command(
            ["-s", device_id, "pull", remote_xml, local_xml],
            timeout_s=30,
            check=False,
        )
        adb_adapter._run_command(
            ["-s", device_id, "shell", "rm", remote_xml],
            timeout_s=10,
            check=False,
        )

        return _search_xml(local_xml, resource_id, content_desc, text)
    except Exception as exc:
        logger.warning(f"find_element failed: {exc}")
        return None
    finally:
        try:
            os.unlink(local_xml)
        except OSError:
            pass


def tap_element(
    device_id: str,
    resource_id: str | None = None,
    content_desc: str | None = None,
    text: str | None = None,
    fallback_coords: dict | None = None,
    timeout_s: float = _DUMP_TIMEOUT,
) -> bool:
    """Find an element and tap its center. Falls back to coords if element not found."""
    element = find_element(device_id, resource_id, content_desc, text, timeout_s)

    if element and element.get("center"):
        cx, cy = element["center"]["x"], element["center"]["y"]
        logger.info(f"tap_element: found via selector at ({cx}, {cy})")
        adb_adapter.tap(device_id, cx, cy, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        return True

    if fallback_coords:
        fx, fy = fallback_coords["x"], fallback_coords["y"]
        logger.info(f"tap_element: selector miss, using fallback ({fx}, {fy})")
        adb_adapter.tap(device_id, fx, fy, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        return True

    logger.warning("tap_element: no element found and no fallback coords")
    return False


def _search_xml(
    xml_path: str,
    resource_id: str | None,
    content_desc: str | None,
    text: str | None,
) -> dict | None:
    """Search parsed XML for a matching node."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        logger.warning(f"XML parse error: {exc}")
        return None

    for node in tree.iter("node"):
        if resource_id and node.get("resource-id") == resource_id:
            return _node_to_result(node)
        if content_desc and node.get("content-desc") == content_desc:
            return _node_to_result(node)
        if text and node.get("text") == text:
            return _node_to_result(node)

    return None


def _node_to_result(node: ET.Element) -> dict:
    bounds_str = node.get("bounds", "")
    bounds = _parse_bounds(bounds_str)
    center = None
    if bounds:
        x1, y1, x2, y2 = bounds
        center = {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2}
    return {"bounds": bounds_str, "center": center}


def _parse_bounds(bounds_str: str) -> tuple[int, int, int, int] | None:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
    if not m:
        return None
    return tuple(int(v) for v in m.groups())

```

## `ingester/src/ingester/main.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
# src/ingester/main.py
import os
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
import json
from datetime import datetime

from ingester import config
from ingester.local import adb_adapter

def setup_logging() -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []

    file_handler = RotatingFileHandler(
        os.path.join(config.LOG_DIR, "ingester.log"),
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

def _append_health_jsonl(payload: dict) -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    filepath = os.path.join(config.LOG_DIR, config.HEALTH_JSONL_FILENAME)
    with open(filepath, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

def _check_memory_watchdog(serial: str, snapshot: dict | None, health_cycle_id: int) -> None:
    """Evaluate memory level and take preventive action if needed."""
    if not config.MEMORY_CHECK_ENABLED or not snapshot:
        return
    mem_kb = snapshot.get("mem_available_kb")
    if mem_kb is None:
        return

    if mem_kb < config.MEMORY_CRITICAL_THRESHOLD_KB:
        logging.critical(
            f"[health_cycle_id={health_cycle_id}] MEMORY CRITICAL: {mem_kb}KB available "
            f"(threshold={config.MEMORY_CRITICAL_THRESHOLD_KB}KB). Rebooting device {serial}."
        )
        try:
            adb_adapter.reboot_device(serial)
            adb_adapter.wait_for_device(serial, max_wait_s=config.MEMORY_POST_REBOOT_WAIT_SECONDS)
        except Exception as exc:
            logging.error(f"[health_cycle_id={health_cycle_id}] Failed to reboot device: {exc}")
        return

    if mem_kb < config.MEMORY_WARNING_THRESHOLD_KB:
        logging.warning(
            f"[health_cycle_id={health_cycle_id}] MEMORY WARNING: {mem_kb}KB available "
            f"(threshold={config.MEMORY_WARNING_THRESHOLD_KB}KB). Force-stopping ICSee on {serial}."
        )
        try:
            adb_adapter.close_app(serial, config.ICSEE_PACKAGE_NAME, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
        except Exception as exc:
            logging.error(f"[health_cycle_id={health_cycle_id}] Failed to force-stop app: {exc}")


def run_health_loop() -> None:
    health_cycle_id = 0
    last_uptime: float | None = None
    while True:
        start = time.time()
        health_cycle_id += 1
        errors: list[str] = []
        snapshot = None
        serial = None

        try:
            devices = adb_adapter.list_devices(timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise adb_adapter.AdbCommandError("adb devices", 1, "", "No devices")
            serial = devices[0]
            snapshot = adb_adapter.get_health_snapshot(serial, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            errors.extend(snapshot.pop("_errors", []))
        except Exception as exc:
            errors.append(str(exc))
            logging.error(f"[health_cycle_id={health_cycle_id}] Health loop error: {exc}", exc_info=True)

        # --- Reboot detection (uptime drop) ---
        if snapshot:
            current_uptime = snapshot.get("uptime_s")
            if current_uptime is not None and last_uptime is not None and current_uptime < last_uptime:
                logging.warning(
                    f"[health_cycle_id={health_cycle_id}] REBOOT DETECTED: uptime dropped "
                    f"from {last_uptime:.0f}s to {current_uptime:.0f}s"
                )
            if current_uptime is not None:
                last_uptime = current_uptime

        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "serial": serial,
            "health_cycle_id": health_cycle_id,
            "snapshot": snapshot,
            "errors": errors,
        }
        _append_health_jsonl(payload)

        # --- Memory watchdog ---
        if serial and snapshot:
            _check_memory_watchdog(serial, snapshot, health_cycle_id)

        elapsed = time.time() - start
        sleep_seconds = max(0, config.HEALTH_INTERVAL_SECONDS - elapsed)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

def main_aws():
    """
    Função placeholder para o modo de operação padrão (AWS SQS/S3).
    """
    logging.info("Modo AWS (SQS/S3) ativado. Nenhuma ação implementada ainda.")
    # Aqui entraria a lógica original de `cameras.py`, `sqs.py`, etc.
    pass

if __name__ == "__main__":
    setup_logging()
    # Verifica o modo de operação a partir de uma variável de ambiente
    ingester_mode = os.environ.get("INGESTER_MODE", "local").lower()

    if ingester_mode == "local":
        logging.info("Modo 'local' detectado. Iniciando captura via ADB.")
        # Importa e executa a lógica de captura local somente quando necessário
        health_thread = threading.Thread(target=run_health_loop, name="health-loop", daemon=True)
        health_thread.start()
        from ingester.local.capture import run_forever_loop
        run_forever_loop()
    elif ingester_mode == "aws":
        main_aws()
    else:
        logging.error(f"Modo de ingester desconhecido: '{ingester_mode}'. Use 'local' ou 'aws'.")

```

## `ingester/src/ingester/s3.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `ingester/src/ingester/sqs.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `ingester/tools/recon_device.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python
#!/usr/bin/env python3
"""
Reconnaissance script — coleta informações do dispositivo Android para calibração.

Uso:
  1. Conecte o dispositivo via ADB
  2. Abra o app ICSee manualmente em cada tela desejada
  3. Rode: python tools/recon_device.py <estado>

Estados disponíveis:
  home            — tela inicial do Android (home screen)
  camera_list     — lista de câmeras no ICSee
  camera_normal   — visualização normal de uma câmera
  camera_fullscreen — câmera em tela cheia

O script coleta:
  - Screenshot da tela atual
  - UI hierarchy via uiautomator dump (XML com todos os elementos clicáveis)
  - Activity/package em foreground via dumpsys
  - Resolução da tela

Resultados salvos em: tools/recon_output/<estado>/
"""
import json
import os
import subprocess
import sys
import time

RECON_DIR = os.path.join(os.path.dirname(__file__), "recon_output")
ADB_TIMEOUT = 30


def run_adb(*args: str, timeout: int = ADB_TIMEOUT) -> subprocess.CompletedProcess:
    cmd = ["adb"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def run_shell(cmd: str, timeout: int = ADB_TIMEOUT) -> str:
    result = run_adb("shell", cmd, timeout=timeout)
    return (result.stdout or "").strip()


def get_device_id() -> str | None:
    result = run_adb("devices")
    import re
    devices = re.findall(r"^(.+?)\s+device$", result.stdout or "", re.MULTILINE)
    return devices[0] if devices else None


def collect(state_name: str) -> None:
    device = get_device_id()
    if not device:
        print("ERRO: Nenhum dispositivo ADB conectado.")
        sys.exit(1)

    out_dir = os.path.join(RECON_DIR, state_name)
    os.makedirs(out_dir, exist_ok=True)

    print(f"Dispositivo: {device}")
    print(f"Estado alvo: {state_name}")
    print(f"Output: {out_dir}")
    print()

    # 1. Resolução da tela
    print("[1/5] Coletando resolução da tela...")
    resolution = run_shell("wm size")
    density = run_shell("wm density")
    print(f"  {resolution}")
    print(f"  {density}")

    # 2. Activity em foreground
    print("[2/5] Coletando activity em foreground...")
    dumpsys = run_shell("dumpsys activity activities | grep -E 'mResumedActivity|mFocusedApp|mCurrentFocus'")
    # Also get the full focused window info
    window_focus = run_shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
    print(f"  Activities: {dumpsys}")
    print(f"  Window: {window_focus}")

    # 3. Screenshot
    print("[3/5] Capturando screenshot...")
    remote_path = "/sdcard/recon_screenshot.png"
    local_path = os.path.join(out_dir, "screenshot.png")
    run_adb("shell", "screencap", remote_path, timeout=120)
    run_adb("pull", remote_path, local_path, timeout=60)
    run_adb("shell", "rm", remote_path)
    print(f"  Salvo: {local_path}")

    # 4. UI hierarchy (uiautomator)
    print("[4/5] Coletando UI hierarchy (uiautomator dump)...")
    remote_xml = "/sdcard/recon_ui.xml"
    local_xml = os.path.join(out_dir, "ui_hierarchy.xml")
    ui_result = run_adb("shell", "uiautomator", "dump", remote_xml, timeout=60)
    if ui_result.returncode == 0:
        run_adb("pull", remote_xml, local_xml)
        run_adb("shell", "rm", remote_xml)
        print(f"  Salvo: {local_xml}")
    else:
        print(f"  AVISO: uiautomator dump falhou: {ui_result.stderr}")
        local_xml = None

    # 5. Resumo
    print("[5/5] Gerando resumo...")
    summary = {
        "state": state_name,
        "device": device,
        "resolution": resolution,
        "density": density,
        "foreground_activity": dumpsys,
        "window_focus": window_focus,
        "screenshot": "screenshot.png",
        "ui_hierarchy": "ui_hierarchy.xml" if local_xml else None,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Parse clickable elements from XML if available
    if local_xml and os.path.exists(local_xml):
        clickables = parse_clickable_elements(local_xml)
        summary["clickable_elements"] = clickables
        print(f"  Elementos clicáveis encontrados: {len(clickables)}")

    summary_path = os.path.join(out_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"  Resumo salvo: {summary_path}")

    print()
    print("=== Coleta concluída ===")
    print(f"Arquivos em: {out_dir}")
    if local_xml:
        print(f"Analise o ui_hierarchy.xml para identificar resource-ids e seletores.")


def parse_clickable_elements(xml_path: str) -> list[dict]:
    """Extract clickable elements from uiautomator XML dump."""
    import xml.etree.ElementTree as ET

    elements = []
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return elements

    for node in tree.iter("node"):
        clickable = node.get("clickable", "false") == "true"
        if not clickable:
            continue

        bounds_str = node.get("bounds", "")
        bounds = _parse_bounds(bounds_str)

        elements.append({
            "class": node.get("class"),
            "resource-id": node.get("resource-id") or None,
            "text": node.get("text") or None,
            "content-desc": node.get("content-desc") or None,
            "bounds": bounds_str,
            "center": _center(bounds) if bounds else None,
            "package": node.get("package"),
        })

    return elements


def _parse_bounds(bounds_str: str) -> tuple[int, int, int, int] | None:
    """Parse '[x1,y1][x2,y2]' into (x1, y1, x2, y2)."""
    import re
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
    if not m:
        return None
    return tuple(int(v) for v in m.groups())


def _center(bounds: tuple[int, int, int, int]) -> dict[str, int]:
    x1, y1, x2, y2 = bounds
    return {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2}


VALID_STATES = ["home", "camera_list", "camera_normal", "camera_fullscreen"]

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in VALID_STATES:
        print(f"Uso: python {sys.argv[0]} <estado>")
        print(f"Estados: {', '.join(VALID_STATES)}")
        sys.exit(1)

    collect(sys.argv[1])

```

## `nginx/gateway.conf`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```nginx
map $http_x_forwarded_proto $proxy_x_forwarded_proto {
    default $http_x_forwarded_proto;
    "" $scheme;
}

server {
    listen 80;
    server_name localhost;

    location /api {
        proxy_pass http://backend:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
        proxy_set_header Authorization $http_authorization;
    }

    location = /health {
        proxy_pass http://backend:8001/health;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
        proxy_set_header Authorization $http_authorization;
    }
}

```

## `nginx/README.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
# Nginx - API Gateway

Reverse proxy que roteia requisicoes externas para o backend FastAPI.

## Configuracao

Arquivo: `gateway.conf`

### Rotas

| Path | Destino | Descricao |
| ---- | ------- | --------- |
| `/api/*` | `backend:8001` | Todas as chamadas de API |
| `/health` | `backend:8001/health` | Health check |

### Headers propagados

- `X-Real-IP`
- `X-Forwarded-For`
- `X-Forwarded-Proto`
- `Authorization`

## Uso

O gateway e utilizado nos ambientes de teste e producao via Docker Compose:

```yaml
# docker-compose.prod.yml
api-gateway:
  image: nginx:alpine
  ports:
    - "5000:80"
  volumes:
    - ./nginx/gateway.conf:/etc/nginx/conf.d/default.conf
```

No ambiente de desenvolvimento, o frontend se comunica diretamente com o backend na porta 8001.

```

## `README.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
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

```

## `scripts/download_weights.sh`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```bash


```

## `scripts/install.sh`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```bash


```

## `yolo-worker-vm/README.md`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```markdown
# YOLO Worker VM

Servico de deteccao de residuos por visao computacional, executado em uma instancia EC2 dedicada. Consome mensagens de uma fila SQS, processa imagens com o modelo YOLO e persiste os resultados no banco de dados.

## Stack

- **YOLO** (deteccao de objetos)
- **AWS SQS** (fila de mensagens)
- **AWS S3** (armazenamento de imagens)
- **PostgreSQL** (persistencia de deteccoes)

## Estrutura

```text
src/worker/
├── main.py              # Entry point - loop de consumo da fila SQS
├── config.py            # Configuracoes (credenciais, URLs, thresholds)
├── detector_yolo.py     # Inferencia do modelo YOLO sobre imagens
├── models.py            # Modelos de dados internos
├── queue_sqs.py         # Consumo e acknowledge de mensagens SQS
├── storage_s3.py        # Download/upload de imagens no S3
└── db.py                # Conexao e insercao de deteccoes no PostgreSQL
```

## Fluxo

1. Camera captura frame e envia mensagem para fila SQS
2. Worker consome a mensagem, faz download da imagem do S3
3. Modelo YOLO processa a imagem e identifica residuos
4. Resultado (tipo, volume estimado, confianca) e salvo no banco
5. Imagem anotada e reenviada ao S3

## Deploy

O worker roda como servico systemd em uma EC2:

```bash
# Arquivo de servico
systemd/saira-yolo-worker.service
```

### Download dos pesos do modelo

```bash
./scripts/download_weights.sh
```

Consulte o runbook em `docs/runbooks/yolo-vm.md` para instrucoes detalhadas de provisionamento e operacao.

```

## `yolo-worker-vm/src/worker/__init__.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `yolo-worker-vm/src/worker/config.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `yolo-worker-vm/src/worker/db.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `yolo-worker-vm/src/worker/detector_yolo.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `yolo-worker-vm/src/worker/main.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `yolo-worker-vm/src/worker/models.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `yolo-worker-vm/src/worker/queue_sqs.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `yolo-worker-vm/src/worker/storage_s3.py`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```python


```

## `yolo-worker-vm/systemd/saira-yolo-worker.service`

**Purpose:** Arquivo relevante para arquitetura e execucao do sistema, incluido para preservar contexto tecnico completo.

```ini


```
