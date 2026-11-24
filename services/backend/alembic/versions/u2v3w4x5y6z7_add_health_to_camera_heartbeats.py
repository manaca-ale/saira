"""add health payload snapshot to camera_heartbeats

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-09-09

Guarda, por ciclo do offline_monitor, o .health.json que o dispositivo reportou
(camera_ok, rtsp_buffer_ok, throttled, disk_low, cpu_temp_c, uptime_s…). Só os
event-driven (Pi relay) reportam; nas demais câmeras a coluna fica NULL, assim
como nos ciclos em que a câmera está offline (o arquivo estaria velho e gravá-lo
repetido só produziria ruído).

Motivação (queda 08→09/09/2026 na pi-cam-001): o esp32-server sobrescreve o
.health.json a cada keepalive, então a investigação dispôs de UMA amostra —
throttled=0x70000, um bitmask "desde o boot" que não distingue um pico de
inrush no religamento de subtensão recorrente. Sem série temporal não há como
dizer se um sintoma estava piorando, que era exatamente a pergunta.

Nullable, sem backfill: ciclos anteriores simplesmente não têm o dado.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "u2v3w4x5y6z7"
down_revision: Union[str, None] = "t1u2v3w4x5y6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "camera_heartbeats",
        sa.Column("health", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("camera_heartbeats", "health")
