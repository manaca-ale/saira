"""add offenders and detection_offenders tables

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-02-13 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ENUM


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Create enum types idempotently.
    offender_type_enum = ENUM(
        "Carroca", "Carro", "Moto", "Pessoa", "Outro",
        name="offendertype",
        create_type=False,
    )
    offender_type_enum.create(bind, checkfirst=True)

    offender_source_enum = ENUM(
        "ai", "manual",
        name="offendersource",
        create_type=False,
    )
    offender_source_enum.create(bind, checkfirst=True)

    # Create offenders table.
    if not inspector.has_table("offenders"):
        op.create_table(
            "offenders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("type", offender_type_enum, nullable=False),
            sa.Column("plate", sa.String(20), nullable=True),
            sa.Column("vehicle_color", sa.String(50), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_offenders_type ON offenders (type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_offenders_plate ON offenders (plate)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_offenders_created_by ON offenders (created_by)")

    # Create detection_offenders table.
    if not inspector.has_table("detection_offenders"):
        op.create_table(
            "detection_offenders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("detection_id", UUID(as_uuid=True), sa.ForeignKey("detections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("offender_id", UUID(as_uuid=True), sa.ForeignKey("offenders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("offender_type", offender_type_enum, nullable=False),
            sa.Column("plate", sa.String(20), nullable=True),
            sa.Column("vehicle_color", sa.String(50), nullable=True),
            sa.Column("waste_type", sa.String(100), nullable=True),
            sa.Column("estimated_volume_m3", sa.Numeric(10, 2), nullable=True),
            sa.Column("source", offender_source_enum, nullable=False),
            sa.Column("confidence_score", sa.Numeric(3, 2), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_detection_offenders_detection_id ON detection_offenders (detection_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_detection_offenders_offender_id ON detection_offenders (offender_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_detection_offenders_plate ON detection_offenders (plate)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_detection_offenders_offender_type ON detection_offenders (offender_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_detection_offenders_source ON detection_offenders (source)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_detection_offenders_plate_detection "
        "ON detection_offenders (plate, detection_id)"
    )


def downgrade() -> None:
    op.drop_table("detection_offenders")
    op.drop_table("offenders")
    sa.Enum(name="offendersource").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="offendertype").drop(op.get_bind(), checkfirst=True)
