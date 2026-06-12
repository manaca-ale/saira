"""add detection event_ref + video request fields

Revision ID: o6p7q8r9s0t1
Revises: n5o6p7q8r9s0
Create Date: 2026-06-12

Suporte ao fluxo de vídeo sob demanda dos dispositivos event-driven
(Raspberry Pi relay):

- event_ref: chave do evento de movimento gerado no dispositivo
  (evt-YYYYmmdd_HHMMSS). Correlaciona a detecção ao clipe de 2min guardado
  na Pi; o worker preenche ao inserir a detecção. Detecções coalescidas
  mantêm o ref do PRIMEIRO evento.
- video_status / video_requested_at: estado da requisição de vídeo feita
  pela plataforma (requested -> available | unavailable).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o6p7q8r9s0t1"
down_revision: Union[str, None] = "n5o6p7q8r9s0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("detections", sa.Column("event_ref", sa.String(64), nullable=True))
    op.add_column("detections", sa.Column("video_status", sa.String(16), nullable=True))
    op.add_column(
        "detections",
        sa.Column("video_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_detections_event_ref", "detections", ["event_ref"])


def downgrade() -> None:
    op.drop_index("ix_detections_event_ref", table_name="detections")
    op.drop_column("detections", "video_requested_at")
    op.drop_column("detections", "video_status")
    op.drop_column("detections", "event_ref")
