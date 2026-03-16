"""Unify all timestamp columns to TIMESTAMPTZ (America/Sao_Paulo)

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-03-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# All tables and their datetime columns to migrate
_COLUMNS = [
    ("detections", ["timestamp", "created_at", "updated_at", "resolved_at", "analysis_started_at"]),
    ("cameras", ["last_capture_at", "created_at", "updated_at"]),
    ("users", ["last_login_at", "created_at", "updated_at"]),
    ("notifications", ["created_at"]),
    ("offenders", ["created_at", "updated_at"]),
    ("detection_offenders", ["created_at"]),
]


def upgrade() -> None:
    # CRITICAL: Set session timezone so existing naive values (which represent
    # Brasília local time) are correctly interpreted during the type conversion.
    # Without this, PostgreSQL would treat them as UTC, shifting all values by +3h.
    op.execute("SET timezone = 'America/Sao_Paulo'")

    for table, columns in _COLUMNS:
        for col in columns:
            op.alter_column(
                table,
                col,
                type_=sa.DateTime(timezone=True),
                existing_type=sa.DateTime(),
                existing_nullable=True,
            )


def downgrade() -> None:
    # Set timezone so that converting back from TIMESTAMPTZ to TIMESTAMP
    # keeps the Brasília local time (strips the offset correctly).
    op.execute("SET timezone = 'America/Sao_Paulo'")

    for table, columns in _COLUMNS:
        for col in columns:
            op.alter_column(
                table,
                col,
                type_=sa.DateTime(),
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=True,
            )
