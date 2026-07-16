"""add Caminhao to offendertype enum

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-07-15

Adiciona o valor 'Caminhao' ao ENUM `offendertype` (usado por
`offenders.type` e `detection_offenders.offender_type`).

Caminhão/caçamba é uma categoria relevante para fiscalização e hoje se
perde dentro de 'Carro' (o worker mapeia caminhao/truck → Carro). Com o
novo valor, o worker passa a mapear caminhao/truck → Caminhao e a tela de
rotulagem oferece a opção.

Por que 'Caminhao' e não 'CAMINHAO': o modelo usa `values_callable`
(offender.py), então os labels do ENUM no Postgres são os *valores* do
enum Python ('Carroca', 'Carro', ...), capitalizados e sem acento.

PG15 aceita ADD VALUE dentro de transação desde que o novo valor não seja
usado na mesma transação — esta migration só adiciona o label.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "s0t1u2v3w4x5"
down_revision: Union[str, None] = "r9s0t1u2v3w4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE offendertype ADD VALUE IF NOT EXISTS 'Caminhao'")


def downgrade() -> None:
    # Postgres não remove valores de ENUM; rollback exigiria recriar o tipo
    # e reescrever as duas colunas que o usam. Intencionalmente não automatizado.
    pass
