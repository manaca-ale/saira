"""add conecta identity fields on users

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-02-18 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {col["name"] for col in inspector.get_columns("users")}

    if "auth_provider" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "auth_provider",
                sa.String(length=50),
                nullable=False,
                server_default="local",
            ),
        )
        op.alter_column("users", "auth_provider", server_default=None)

    if "external_subject" not in user_columns:
        op.add_column("users", sa.Column("external_subject", sa.String(length=255), nullable=True))

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_external_subject ON users (external_subject)"
    )

    # PostgreSQL UNIQUE INDEX allows multiple NULL values; this works for optional subject.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_external_subject ON users (external_subject)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_external_subject")
    op.execute("DROP INDEX IF EXISTS ix_users_external_subject")

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {col["name"] for col in inspector.get_columns("users")}

    if "external_subject" in user_columns:
        op.drop_column("users", "external_subject")
    if "auth_provider" in user_columns:
        op.drop_column("users", "auth_provider")
