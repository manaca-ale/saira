"""add gemini_call_log table

Revision ID: g8b9c0d1e2f3
Revises: h9c0d1e2f3a4
Create Date: 2026-05-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "g8b9c0d1e2f3"
down_revision: Union[str, None] = "h9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("gemini_call_log"):
        op.create_table(
            "gemini_call_log",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "called_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "camera_id",
                sa.Integer(),
                sa.ForeignKey("cameras.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("device_id", sa.String(64), nullable=True),
            sa.Column("agent", sa.String(16), nullable=False),
            sa.Column("model", sa.String(64), nullable=False),
            sa.Column("request_id", sa.String(64), nullable=True),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "estimated_cost_usd",
                sa.Numeric(12, 8),
                nullable=False,
                server_default="0",
            ),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column(
                "success",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "call_date_brt",
                sa.Date(),
                sa.Computed(
                    "(called_at AT TIME ZONE 'America/Sao_Paulo')::date",
                    persisted=True,
                ),
                nullable=False,
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_gemini_call_log_date_camera "
        "ON gemini_call_log (call_date_brt, camera_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_gemini_call_log_date_agent "
        "ON gemini_call_log (call_date_brt, agent)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_gemini_call_log_called_at "
        "ON gemini_call_log (called_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_gemini_call_log_request_id "
        "ON gemini_call_log (request_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_gemini_call_log_request_id")
    op.execute("DROP INDEX IF EXISTS ix_gemini_call_log_called_at")
    op.execute("DROP INDEX IF EXISTS ix_gemini_call_log_date_agent")
    op.execute("DROP INDEX IF EXISTS ix_gemini_call_log_date_camera")
    op.drop_table("gemini_call_log")
