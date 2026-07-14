"""add camera_type to cameras

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
Create Date: 2026-07-14

Adds 1 nullable column to `cameras`:

- `camera_type` (VARCHAR(32)): família do hardware — hoje 'esp32' | 'pi' | 'unknown'.
  Fonte da verdade das CAPACIDADES da câmera, que até aqui eram inferidas de uma
  heurística de string no frontend (`!device_id.startsWith("esp32")`).

Por que VARCHAR e não um ENUM do Postgres: adicionar valor a um ENUM exige
migration; com VARCHAR + `Literal` no Pydantic a validação fica na borda e a
frota evolui só com mudança de código.

Semântica do NULL — os dois consumidores têm fallbacks OPOSTOS de propósito:

- `supports_remote_control` (snapshot/zoom, já existente): NULL = fail-OPEN, cai
  na heurística de prefixo legada. Preserva o comportamento atual, zero regressão.
- `supports_live` (modo ao vivo, novo): NULL = fail-CLOSED, sem live. Feature nova
  não tem legado a preservar, e errar para o lado aberto custa 4G do dispositivo.

O backfill reproduz a heurística que vigorava no frontend (tudo que não é esp32*
era tratado como remote-capable), então nenhuma câmera muda de comportamento:
`esp32*` -> 'esp32', qualquer outro device_id -> 'pi'. Câmeras sem device_id
(seed de localização) ficam NULL — não há hardware para tipar.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r9s0t1u2v3w4"
down_revision: Union[str, None] = "q8r9s0t1u2v3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("cameras")}

    if "camera_type" not in existing_columns:
        op.add_column(
            "cameras",
            sa.Column("camera_type", sa.String(32), nullable=True),
        )
        # Backfill idempotente: só preenche o que ainda está NULL, então rodar de
        # novo nunca sobrescreve um tipo já corrigido à mão pelo operador.
        op.execute(
            """
            UPDATE cameras
               SET camera_type = 'esp32'
             WHERE camera_type IS NULL
               AND device_id IS NOT NULL
               AND lower(device_id) LIKE 'esp32%'
            """
        )
        op.execute(
            """
            UPDATE cameras
               SET camera_type = 'pi'
             WHERE camera_type IS NULL
               AND device_id IS NOT NULL
               AND lower(device_id) NOT LIKE 'esp32%'
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("cameras")}

    if "camera_type" in existing_columns:
        op.drop_column("cameras", "camera_type")
