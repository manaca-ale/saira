"""add motion-gate stats to detections (fg_px / delta_px / config_version)

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-07-18

Registra, por detecção, os valores do gate de movimento no dispositivo
(Raspberry Pi relay) no momento em que o evento abriu, mais a versão da config
vigente. Permite auditar depois "com que margem / sob qual threshold esta
detecção disparou" — hoje esses valores só viviam ~10h no log da Pi.

- gate_fg_px: pixels de foreground (MOG2) na zona no disparo.
- gate_delta_px: pixels de movimento (frame-delta) na zona no disparo.
- gate_config_version: version=YYYY-MM-DD_HH-MM-SS da config aplicada na Pi
  (de onde se derivam os thresholds motion_min_px_active / motion_delta_start_px).

Todas nullable: detecções legadas, câmeras não-event-driven e eventos de
warm-up simplesmente ficam NULL.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t1u2v3w4x5y6"
down_revision: Union[str, None] = "s0t1u2v3w4x5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("detections", sa.Column("gate_fg_px", sa.Integer(), nullable=True))
    op.add_column("detections", sa.Column("gate_delta_px", sa.Integer(), nullable=True))
    op.add_column(
        "detections",
        sa.Column("gate_config_version", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("detections", "gate_config_version")
    op.drop_column("detections", "gate_delta_px")
    op.drop_column("detections", "gate_fg_px")
