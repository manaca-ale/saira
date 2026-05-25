"""add per-camera BGSUB tuning fields to cameras

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-05-25

Per-camera overrides for BGSUB filter parameters. All NULL = fall back to
env-global defaults (BGSUB_LR_FAST, BGSUB_PERSISTENCE_THRESHOLD, etc).

Motivation: esp32_001 (zona grande, tráfego constante) e esp32_002 (zona
pequena, baixo tráfego) precisam tunings diferentes. Hoje (25/05) o
deploy mpf=0.4 global deixou esp32_001 com 0% filter rate. Per-camera
config permite calibrar cada câmera sem deploy de worker.

Os campos são lidos por bgsub_filter._resolved_config() — quando NULL,
caem para os env globais (zero risco de regressão para câmeras já em prod).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m4n5o6p7q8r9"
down_revision: Union[str, None] = "l3m4n5o6p7q8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS = [
    ("bgsub_lr_fast", sa.Float()),
    ("bgsub_lr_slow", sa.Float()),
    ("bgsub_mog2_history_fast", sa.Integer()),
    ("bgsub_mog2_history_slow", sa.Integer()),
    ("bgsub_persistence_threshold", sa.Integer()),
    ("bgsub_min_persistence_frames", sa.Float()),
    ("bgsub_min_px_active", sa.Integer()),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("cameras")}
    for name, kind in _NEW_COLUMNS:
        if name not in existing:
            op.add_column("cameras", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("cameras")}
    for name, _ in reversed(_NEW_COLUMNS):
        if name in existing:
            op.drop_column("cameras", name)
