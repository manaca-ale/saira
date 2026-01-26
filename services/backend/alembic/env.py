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
