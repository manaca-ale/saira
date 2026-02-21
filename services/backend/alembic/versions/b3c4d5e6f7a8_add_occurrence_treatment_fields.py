"""add occurrence treatment fields

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-02-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('detections', sa.Column('resolved_at', sa.DateTime(), nullable=True))
    op.add_column('detections', sa.Column('resolved_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    op.add_column('detections', sa.Column('resolution_justification', sa.Text(), nullable=True))
    op.add_column('detections', sa.Column('forwarded_to_sector', sa.String(length=100), nullable=True))
    op.add_column('detections', sa.Column('analysis_started_at', sa.DateTime(), nullable=True))
    op.add_column('detections', sa.Column('analysis_started_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))


def downgrade() -> None:
    op.drop_column('detections', 'analysis_started_by')
    op.drop_column('detections', 'analysis_started_at')
    op.drop_column('detections', 'forwarded_to_sector')
    op.drop_column('detections', 'resolution_justification')
    op.drop_column('detections', 'resolved_by')
    op.drop_column('detections', 'resolved_at')
