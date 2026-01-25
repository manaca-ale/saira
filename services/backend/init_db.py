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
