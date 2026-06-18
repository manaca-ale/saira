"""add cascade_decisions table (I4a model accuracy, I3 identification)

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-06-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "q8r9s0t1u2v3"
down_revision: Union[str, None] = "p7q8r9s0t1u2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("cascade_decisions"):
        op.create_table(
            "cascade_decisions",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "camera_id",
                sa.Integer(),
                sa.ForeignKey("cameras.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("device_id", sa.String(64), nullable=True),
            sa.Column("agent1_confidence", sa.SmallInteger(), nullable=True),
            sa.Column(
                "agent2_success",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("agent2_disposal", sa.Boolean(), nullable=True),
            sa.Column("offender_present", sa.Boolean(), nullable=True),
            sa.Column("offender_crop_extracted", sa.Boolean(), nullable=True),
            sa.Column("detection_id", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "decided_date_brt",
                sa.Date(),
                sa.Computed(
                    "(evaluated_at AT TIME ZONE 'America/Sao_Paulo')::date",
                    persisted=True,
                ),
                nullable=False,
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cascade_decisions_date_camera "
        "ON cascade_decisions (decided_date_brt, camera_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cascade_decisions_evaluated_at "
        "ON cascade_decisions (evaluated_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cascade_decisions_detection_id "
        "ON cascade_decisions (detection_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cascade_decisions_detection_id")
    op.execute("DROP INDEX IF EXISTS ix_cascade_decisions_evaluated_at")
    op.execute("DROP INDEX IF EXISTS ix_cascade_decisions_date_camera")
    op.drop_table("cascade_decisions")
