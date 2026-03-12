"""Pydantic contract for Gemini structured output."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


_NULL_LIKE = {
    "",
    "none",
    "null",
    "n/a",
    "na",
    "nao identificado",
    "nao visivel",
    "desconhecido",
    "unknown",
}


class GeminiInfractionReport(BaseModel):
    """Structured response returned by Gemini for one temporal sequence."""

    infraction_confirmed: bool = Field(
        description="True only when disposal action is visually confirmed in sequence context."
    )
    confidence_0_100: int = Field(
        ge=0,
        le=100,
        description="Model confidence score from 0 to 100.",
    )
    evidence_summary: str = Field(
        min_length=1,
        max_length=600,
        description="Short factual summary of visual evidence.",
    )

    waste_type: Optional[str] = Field(default=None, max_length=100)
    material_type: Optional[str] = Field(default=None, max_length=100)
    volume_m3: Optional[float] = Field(default=None, ge=0, le=500)

    offender_detected: bool = Field(
        description="True if the model can identify any agent related to disposal action."
    )
    offender_types: Optional[list[str]] = Field(default=None, description="List of offender agent categories.")

    vehicle_plate: Optional[str] = Field(default=None, max_length=20)
    vehicle_color: Optional[str] = Field(default=None, max_length=50)
    vehicle_model: Optional[str] = Field(default=None, max_length=100)
    plate_pattern: Optional[str] = Field(default=None, max_length=20)

    raw_reason_codes: Optional[list[str]] = Field(default=None, description="Internal machine-readable reason codes.")
    event_frame_name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Filename of the frame that best shows the disposal action.",
    )
    offender_frame_name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Filename of the frame that best identifies the offender/vehicle.",
    )

    @field_validator(
        "waste_type",
        "material_type",
        "vehicle_plate",
        "vehicle_color",
        "vehicle_model",
        "plate_pattern",
        "event_frame_name",
        "offender_frame_name",
        mode="before",
    )
    @classmethod
    def _normalize_nullables(cls, value: object) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if text.lower() in _NULL_LIKE:
            return None
        return text

    @field_validator("offender_types", "raw_reason_codes", mode="before")
    @classmethod
    def _normalize_optional_lists(cls, value: object) -> Optional[list[str]]:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            return [cleaned]
        if isinstance(value, list):
            result = [str(item).strip() for item in value if str(item).strip()]
            return result or None
        return None


class GeminiNewLitterReport(BaseModel):
    """Structured response for stage-1 gate: compare first vs last frame of a time window."""

    new_litter_detected: bool = Field(
        description="True only if new solid waste appears or increases between first and last frame."
    )
    confidence_0_100: int = Field(
        ge=0,
        le=100,
        description="Model confidence score from 0 to 100.",
    )
    evidence_summary: str = Field(
        min_length=1,
        max_length=400,
        description="Short factual summary of visual comparison.",
    )
    first_frame_has_litter: bool = False
    last_frame_has_litter: bool = False
    waste_type: Optional[str] = Field(default=None, max_length=100)
    raw_reason_codes: Optional[list[str]] = Field(default=None)

    @field_validator("waste_type", mode="before")
    @classmethod
    def _normalize_nullable_waste(cls, value: object) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if text.lower() in _NULL_LIKE:
            return None
        return text

    @field_validator("raw_reason_codes", mode="before")
    @classmethod
    def _normalize_reason_codes(cls, value: object) -> Optional[list[str]]:
        if value is None:
            return None
        if isinstance(value, list):
            result = [str(item).strip() for item in value if str(item).strip()]
            return result or None
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else None
        return None
