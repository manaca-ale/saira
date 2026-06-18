from sqlalchemy import (
    Column, BigInteger, Integer, SmallInteger, String, Boolean, DateTime, Date,
    ForeignKey, Computed, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class CascadeDecision(Base):
    """Registro de cada avaliação do Agent-2 (análise detalhada) na cascata.

    O worker insere uma linha sempre que o Agent-2 roda numa janela (após o
    Agent-1 disparar). Diferente da tabela `detections`, isto persiste também os
    eventos REJEITADOS pelo modelo (disposal=false), que antes só viviam no
    arquivo `gemini_cascade_audit/*.jsonl` do worker.

    Alimenta:
    - I4a (Assertividade do modelo): confirmadas / (confirmadas + rejeitadas)
      = count(agent2_disposal) / count(agent2_success), com agent2_disposal
      ∈ {true, false} entre as avaliações bem-sucedidas.
    - I3 (Qualidade da identificação): entre as confirmadas com infrator
      presente no frame (offender_present), fração que teve crop extraído
      (offender_crop_extracted).
    """

    __tablename__ = "cascade_decisions"
    __table_args__ = (
        Index("ix_cascade_decisions_date_camera", "decided_date_brt", "camera_id"),
        Index("ix_cascade_decisions_evaluated_at", "evaluated_at"),
        Index("ix_cascade_decisions_detection_id", "detection_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=False)
    camera_id = Column(
        Integer,
        ForeignKey("cameras.id", ondelete="SET NULL"),
        nullable=True,
    )
    device_id = Column(String(64), nullable=True)
    agent1_confidence = Column(SmallInteger, nullable=True)
    # True quando o Agent-2 respondeu sem erro (avaliação válida).
    agent2_success = Column(Boolean, nullable=False, default=True)
    # Decisão final do Agent-2: descarte real (confirmado) vs falso alarme.
    # NULL apenas quando agent2_success=false.
    agent2_disposal = Column(Boolean, nullable=True)
    # Agent-2 detectou pessoa/veículo presente no frame.
    offender_present = Column(Boolean, nullable=True)
    # Agent-2 conseguiu extrair o recorte (bbox) do infrator.
    offender_crop_extracted = Column(Boolean, nullable=True)
    # Detecção persistida (apenas quando confirmado). NULL em rejeições.
    detection_id = Column(UUID(as_uuid=True), nullable=True)
    decided_date_brt = Column(
        Date,
        Computed(
            "(evaluated_at AT TIME ZONE 'America/Sao_Paulo')::date",
            persisted=True,
        ),
        nullable=False,
    )
