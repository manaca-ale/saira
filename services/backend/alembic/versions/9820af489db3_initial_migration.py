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
