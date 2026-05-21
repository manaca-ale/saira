"""add image_exports table

Revision ID: j1e2f3a4b5c6
Revises: i0d1e2f3a4b5
Create Date: 2026-05-21

Tracks async camera image export jobs. Each row represents a request from a user
to download all images (occurrences + non-occurrences) captured by a given camera
within a date/time range, packaged into a single ZIP uploaded to S3.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "j1e2f3a4b5c6"
down_revision: Union[str, None] = "g8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if "image_exports" not in existing_tables:
        op.create_table(
            "image_exports",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "camera_id",
                sa.Integer,
                sa.ForeignKey("cameras.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "include_occurrences",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "include_non_occurrences",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column(
                "progress",
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("total_images", sa.Integer, nullable=True),
            sa.Column("s3_key", sa.String(512), nullable=True),
            sa.Column("download_url", sa.String(2048), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
        )
        op.create_index(
            "ix_image_exports_user_id",
            "image_exports",
            ["user_id"],
        )
        op.create_index(
            "ix_image_exports_camera_id",
            "image_exports",
            ["camera_id"],
        )
        op.create_index(
            "ix_image_exports_status",
            "image_exports",
            ["status"],
        )
        op.create_index(
            "ix_image_exports_user_created",
            "image_exports",
            ["user_id", sa.text("created_at DESC")],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if "image_exports" in existing_tables:
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("image_exports")}
        for idx_name in (
            "ix_image_exports_user_created",
            "ix_image_exports_status",
            "ix_image_exports_camera_id",
            "ix_image_exports_user_id",
        ):
            if idx_name in existing_indexes:
                op.drop_index(idx_name, table_name="image_exports")
        op.drop_table("image_exports")
