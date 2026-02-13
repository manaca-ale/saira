"""add notifications system

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-02-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Enum type for notification type. Use create_type=False on column to avoid
    # duplicate CREATE TYPE attempts in partially applied environments.
    notification_type_enum = ENUM(
        "nova_ocorrencia",
        "lote_ocorrencias",
        name="notificationtype",
        create_type=False,
    )
    notification_type_enum.create(bind, checkfirst=True)

    # Create notifications table if it does not exist.
    if not inspector.has_table("notifications"):
        op.create_table(
            "notifications",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("detection_id", UUID(as_uuid=True), sa.ForeignKey("detections.id", ondelete="SET NULL"), nullable=True),
            sa.Column("type", notification_type_enum, nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("is_read", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )

    # Indexes (idempotent for partially applied environments).
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_is_read ON notifications (is_read)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_read_created "
        "ON notifications (user_id, is_read, created_at)"
    )

    # Add last_login_at to users if missing.
    user_columns = {col["name"] for col in inspector.get_columns("users")}
    if "last_login_at" not in user_columns:
        op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'last_login_at')
    op.drop_table('notifications')
    sa.Enum(name='notificationtype').drop(op.get_bind(), checkfirst=True)
