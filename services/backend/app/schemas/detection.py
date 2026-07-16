from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from decimal import Decimal
from uuid import UUID
from enum import Enum


class DetectionStatus(str, Enum):
    PENDENTE = "Pendente"
    CONFIRMADO = "Confirmado"
    REJEITADO = "Rejeitado"
    INDETERMINADO = "Indeterminado"


class ClassifyAction(str, Enum):
    """Statuses a user can assign via POST /detections/{id}/classify.

    PENDENTE é o estado inicial implícito — não é uma ação do usuário.
    """

    CONFIRMADO = "Confirmado"
    REJEITADO = "Rejeitado"
    INDETERMINADO = "Indeterminado"


class DetectionBase(BaseModel):
    camera_id: Optional[int] = None
    timestamp: datetime
    logradouro: Optional[str] = Field(None, max_length=255)
    bairro: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    latitude: Decimal
    longitude: Decimal
    waste_type: Optional[str] = Field(None, max_length=100)
    material_type: Optional[str] = Field(None, max_length=100)
    volume_m3: Optional[Decimal] = None
    offenders: Optional[str] = Field(None, max_length=255)
    status: DetectionStatus = DetectionStatus.PENDENTE
    image_url: Optional[str] = Field(None, max_length=512)
    confidence_score: Optional[Decimal] = Field(None, ge=0, le=1)


class DetectionCreate(DetectionBase):
    pass


class DetectionUpdate(BaseModel):
    status: Optional[DetectionStatus] = None
    offenders: Optional[str] = Field(None, max_length=255)
    waste_type: Optional[str] = Field(None, max_length=100)
    material_type: Optional[str] = Field(None, max_length=100)
    volume_m3: Optional[Decimal] = None
    image_url: Optional[str] = Field(None, max_length=512)


class DetectionClassify(BaseModel):
    """Payload para POST /detections/{id}/classify.

    Permite ao usuário classificar a validade de uma ocorrência detectada.
    """

    status: ClassifyAction
    validity_comment: Optional[str] = Field(None, max_length=400)


class DetectionResponse(DetectionBase):
    id: UUID
    classified_at: Optional[datetime] = None
    classified_by: Optional[int] = None
    validity_comment: Optional[str] = None
    event_ref: Optional[str] = None
    video_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DetectionVideoResponse(BaseModel):
    """Estado do clipe de vídeo de 2min da detecção (dispositivos event-driven).

    status:
      none        — detecção sem event_ref (dispositivo não event-driven)
      requested   — comando enviado ao dispositivo, aguardando upload
      available   — mp4 disponível em video_url
      unavailable — pedido expirou sem upload (Pi offline / clipe perdido);
                    pode ser re-requisitado
    """

    detection_id: UUID
    event_ref: Optional[str] = None
    status: str
    video_url: Optional[str] = None
    requested_at: Optional[datetime] = None


class DetectionSearchItem(DetectionResponse):
    """Item de /detections/search enriquecido para a listagem do frontend.

    offender_types traz o tipo EFETIVO por detecção: rótulos manuais vencem
    os da IA quando ambos existem (mesma regra dos dashboards de infratores).
    """

    camera_name: Optional[str] = None
    camera_device_id: Optional[str] = None
    offender_types: List[str] = []


class DetectionListResponse(BaseModel):
    items: List[DetectionSearchItem]
    total: int
    skip: int
    limit: int


class DetectionFilterOptionsResponse(BaseModel):
    """Valores distintos do banco para popular os filtros do frontend.

    Retorna o domínio completo (todos os bairros/logradouros já registrados),
    independente de paginação ou de outros filtros ativos na tela.
    """

    bairros: List[str]
    logradouros: List[str]


class DetectionAnalyzedFrame(BaseModel):
    frame_name: str
    image_url: str
    is_default: bool = False


class DetectionAnalyzedFramesResponse(BaseModel):
    detection_id: UUID
    selected_frame_name: Optional[str] = None
    frames: List[DetectionAnalyzedFrame]
