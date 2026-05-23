"""add pile_zone_polygon and bgsub_calibrated_at to cameras

Revision ID: k2f3a4b5c6d7
Revises: j1e2f3a4b5c6
Create Date: 2026-05-23

Adds 2 nullable columns to `cameras` used by the BGSUB pre-filter:

- `pile_zone_polygon` (JSONB): list of polygons, each a list of [x, y] points
  defining the pile zone within the camera frame. Frame reference is 1280×720.
  Worker uses this to build a binary mask of where to measure foreground
  persistence. NULL means no pre-filter for this camera (fail-open).

- `bgsub_calibrated_at` (TIMESTAMP): when the MOG2 background model was last
  trained for this camera (informative; the model itself lives at
  STATE_DIR/bgsub_models/{device_id}.xml on the worker host).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "k2f3a4b5c6d7"
down_revision: Union[str, None] = "j1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("cameras")}

    if "pile_zone_polygon" not in existing_columns:
        op.add_column(
            "cameras",
            sa.Column("pile_zone_polygon", JSONB, nullable=True),
        )
    if "bgsub_calibrated_at" not in existing_columns:
        op.add_column(
            "cameras",
            sa.Column("bgsub_calibrated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("cameras")}

    if "bgsub_calibrated_at" in existing_columns:
        op.drop_column("cameras", "bgsub_calibrated_at")
    if "pile_zone_polygon" in existing_columns:
        op.drop_column("cameras", "pile_zone_polygon")
