from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.config import settings


class ImageExportCreate(BaseModel):
    camera_id: int = Field(..., ge=1)
    start_at: datetime
    end_at: datetime
    include_occurrences: bool = True
    include_non_occurrences: bool = True

    @model_validator(mode="after")
    def _validate_range(self) -> "ImageExportCreate":
        if self.end_at <= self.start_at:
            raise ValueError("end_at deve ser posterior a start_at")

        max_span = timedelta(days=settings.EXPORT_MAX_DAYS)
        if (self.end_at - self.start_at) > max_span:
            raise ValueError(
                f"Intervalo máximo de {settings.EXPORT_MAX_DAYS} dias por exportação"
            )

        if not (self.include_occurrences or self.include_non_occurrences):
            raise ValueError(
                "Selecione pelo menos um tipo de imagem (ocorrência ou sem ocorrência)"
            )
        return self


class ImageExportResponse(BaseModel):
    id: UUID
    user_id: int
    camera_id: int
    camera_name: Optional[str] = None
    camera_device_id: Optional[str] = None
    start_at: datetime
    end_at: datetime
    include_occurrences: bool
    include_non_occurrences: bool
    status: str
    progress: int
    total_images: Optional[int] = None
    download_url: Optional[str] = None
    expires_at: Optional[datetime] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
