"""replace workflow status (Pendente/Em analise/Resolvido) with validity status

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-05-26

Substitui o status de workflow (Pendente -> Em analise -> Resolvido) por um
status de validade da ocorrência (Pendente -> Confirmado | Rejeitado |
Indeterminado), onde "Pendente" passa a significar "ainda não classificado
pelo usuário".

Decisão de migração (validada com o usuário em 2026-05-26):
- Todo histórico de detecções vira "Pendente" — o usuário vai re-avaliar
  cada uma para decidir Confirmado / Rejeitado / Indeterminado.
- Colunas resolved_at / resolved_by são renomeadas para classified_at /
  classified_by (semântica nova: quem/quando classificou a validade).
- Coluna validity_comment (TEXT, nullable) é adicionada para registrar
  justificativa profissional opcional.
- Colunas removidas (não fazem mais sentido no modelo de validade):
  resolution_justification, forwarded_to_sector,
  analysis_started_at, analysis_started_by.

Forward-only: downgrade lança NotImplementedError. Restaurar de backup
se precisar reverter.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n5o6p7q8r9s0"
down_revision: Union[str, None] = "m4n5o6p7q8r9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Postgres ENUM stores the Python enum *names* (uppercase), to match the
# convention set by the initial migration (`9820af489db3`). The Python enum
# values ("Pendente", "Confirmado", ...) are what API consumers see in JSON.
_NEW_ENUM_VALUES = ("PENDENTE", "CONFIRMADO", "REJEITADO", "INDETERMINADO")
_REMOVED_COLUMNS = (
    "resolution_justification",
    "forwarded_to_sector",
    "analysis_started_at",
    "analysis_started_by",
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Swap o ENUM detectionstatus para o novo conjunto de valores.
    #    Mapeia todos os valores antigos -> 'Pendente' (decisão do usuário:
    #    todo histórico precisa ser re-avaliado).
    op.execute("ALTER TABLE detections ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE detectionstatus RENAME TO detectionstatus_old")
    new_enum = sa.Enum(*_NEW_ENUM_VALUES, name="detectionstatus")
    new_enum.create(bind, checkfirst=False)
    op.execute(
        "ALTER TABLE detections "
        "ALTER COLUMN status TYPE detectionstatus "
        "USING 'PENDENTE'::detectionstatus"
    )
    op.execute("ALTER TABLE detections ALTER COLUMN status SET DEFAULT 'PENDENTE'")
    op.execute("DROP TYPE detectionstatus_old")

    # 2) Adiciona validity_comment.
    inspector = sa.inspect(bind)
    detection_cols = {c["name"] for c in inspector.get_columns("detections")}
    if "validity_comment" not in detection_cols:
        op.add_column(
            "detections",
            sa.Column("validity_comment", sa.Text(), nullable=True),
        )

    # 3) Renomeia resolved_at -> classified_at e resolved_by -> classified_by.
    if "resolved_at" in detection_cols and "classified_at" not in detection_cols:
        op.alter_column("detections", "resolved_at", new_column_name="classified_at")
    if "resolved_by" in detection_cols and "classified_by" not in detection_cols:
        op.alter_column("detections", "resolved_by", new_column_name="classified_by")

    # 4) Remove colunas de workflow que perderam significado.
    detection_cols = {c["name"] for c in sa.inspect(bind).get_columns("detections")}
    for col_name in _REMOVED_COLUMNS:
        if col_name in detection_cols:
            op.drop_column("detections", col_name)


def downgrade() -> None:
    raise NotImplementedError(
        "Destructive migration (drops workflow columns and rewrites status). "
        "Restore from backup to revert."
    )
