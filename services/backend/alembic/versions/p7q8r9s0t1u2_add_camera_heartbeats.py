"""add camera_heartbeats table (I1 surveillance reliability)

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1
Create Date: 2026-06-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "p7q8r9s0t1u2"
down_revision: Union[str, None] = "o6p7q8r9s0t1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("camera_heartbeats"):
        op.create_table(
            "camera_heartbeats",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "camera_id",
                sa.Integer(),
                sa.ForeignKey("cameras.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("device_id", sa.String(64), nullable=True),
            sa.Column("is_online", sa.Boolean(), nullable=False),
            sa.Column(
                "check_date_brt",
                sa.Date(),
                sa.Computed(
                    "(checked_at AT TIME ZONE 'America/Sao_Paulo')::date",
                    persisted=True,
                ),
                nullable=False,
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_camera_heartbeats_camera_checked "
        "ON camera_heartbeats (camera_id, checked_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_camera_heartbeats_date "
        "ON camera_heartbeats (check_date_brt)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_camera_heartbeats_date")
    op.execute("DROP INDEX IF EXISTS ix_camera_heartbeats_camera_checked")
    op.drop_table("camera_heartbeats")
