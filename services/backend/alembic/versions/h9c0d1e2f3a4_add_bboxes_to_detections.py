"""add waste_bbox to detections and offender_bbox to detection_offenders

Revision ID: h9c0d1e2f3a4
Revises: f7a8b9c0d1e2
Create Date: 2026-05-17

Adds JSONB columns to persist Gemini-extracted bounding boxes:
- detections.waste_bbox        — [y_min, x_min, y_max, x_max] (0-1000 normalized)
- detection_offenders.offender_bbox — same shape, for the person/vehicle

Required by I3 (Qualidade da identificação) of the daily KPI report.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "h9c0d1e2f3a4"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    detection_cols = {c["name"] for c in inspector.get_columns("detections")}
    if "waste_bbox" not in detection_cols:
        op.add_column(
            "detections",
            sa.Column("waste_bbox", JSONB(), nullable=True),
        )

    offender_cols = {c["name"] for c in inspector.get_columns("detection_offenders")}
    if "offender_bbox" not in offender_cols:
        op.add_column(
            "detection_offenders",
            sa.Column("offender_bbox", JSONB(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    offender_cols = {c["name"] for c in inspector.get_columns("detection_offenders")}
    if "offender_bbox" in offender_cols:
        op.drop_column("detection_offenders", "offender_bbox")

    detection_cols = {c["name"] for c in inspector.get_columns("detections")}
    if "waste_bbox" in detection_cols:
        op.drop_column("detections", "waste_bbox")
