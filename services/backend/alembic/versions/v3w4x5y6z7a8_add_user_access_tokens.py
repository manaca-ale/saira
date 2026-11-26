"""convite, recuperação de senha e troca obrigatória

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
Create Date: 2026-11-25

- Tabela user_action_tokens: links de uso único (convite e "esqueci minha
  senha"), só com o SHA-256 do token.
- users.password_hash aceita NULL (convite pendente).
- users.must_change_password: senha definida pelo administrador é provisória.
- users.token_version: vai no JWT como "ver"; somar 1 derruba as sessões.
- users.password_changed_at: auditoria.

Sem backfill: usuários atuais ficam com must_change_password=false e
token_version=0, e os JWT já emitidos continuam valendo.
Ver docs/specs/acesso-usuarios.md.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v3w4x5y6z7a8"
down_revision: Union[str, None] = "u2v3w4x5y6z7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=True)
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "user_action_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("request_ip", sa.String(length=45), nullable=True),
    )
    op.create_index("ix_user_action_tokens_user_id", "user_action_tokens", ["user_id"])
    op.create_index("ix_user_action_tokens_token_hash", "user_action_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_action_tokens_token_hash", table_name="user_action_tokens")
    op.drop_index("ix_user_action_tokens_user_id", table_name="user_action_tokens")
    op.drop_table("user_action_tokens")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "token_version")
    op.drop_column("users", "must_change_password")
    # Usuário com convite pendente não tem senha; o downgrade põe um hash
    # inválido para voltar ao NOT NULL (ninguém entra com ele).
    op.execute("UPDATE users SET password_hash = '!convite-pendente' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)
