"""add agent1/2 request_id + agent1_confidence columns to detections

Revision ID: l3m4n5o6p7q8
Revises: k2f3a4b5c6d7
Create Date: 2026-05-23

URGENT FIX: worker `db.py:insert_detection` already issues an INSERT
referencing agent1_request_id / agent2_request_id / agent1_confidence
(deployed via earlier commits — worker code-side feature was already
shipped, but the matching migration never made it into git). All
detections that should have been saved with these columns have been
failing in prod with `psycopg2.errors.UndefinedColumn`.

Today (2026-05-23) we observed at least 1 lost TP at 13:11 BRT in
esp32_002 (a person with a wheelbarrow disposing waste — Agent 2
confidence high). Manually re-registered as detection
3c840ac4-b0f7-4fec-b696-dd7e68725b49 with full justification.

This migration adds ONLY the worker-required columns. The fuller
detection_feedback table (defined in i0d1e2f3a4b5_*.py) requires
matching backend code changes still pending and is deferred.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, None] = "k2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    detection_cols = {c["name"] for c in inspector.get_columns("detections")}

    if "agent1_request_id" not in detection_cols:
        op.add_column(
            "detections",
            sa.Column("agent1_request_id", sa.String(64), nullable=True),
        )
    if "agent2_request_id" not in detection_cols:
        op.add_column(
            "detections",
            sa.Column("agent2_request_id", sa.String(64), nullable=True),
        )
    if "agent1_confidence" not in detection_cols:
        op.add_column(
            "detections",
            sa.Column("agent1_confidence", sa.SmallInteger(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    detection_cols = {c["name"] for c in inspector.get_columns("detections")}
    for col_name in ("agent1_confidence", "agent2_request_id", "agent1_request_id"):
        if col_name in detection_cols:
            op.drop_column("detections", col_name)
