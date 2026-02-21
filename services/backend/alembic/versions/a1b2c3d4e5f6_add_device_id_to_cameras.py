"""add device_id to cameras

Revision ID: a1b2c3d4e5f6
Revises: 9820af489db3
Create Date: 2026-02-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9820af489db3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cameras', sa.Column('device_id', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_cameras_device_id'), 'cameras', ['device_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_cameras_device_id'), table_name='cameras')
    op.drop_column('cameras', 'device_id')
