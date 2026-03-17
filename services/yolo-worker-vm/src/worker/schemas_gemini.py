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

    # Chain-of-Verification: baseline BEFORE decision (forces model to anchor on normal state).
    baseline_description: str = Field(
        default="",
        max_length=400,
        description="List up to 5 fixed/permanent objects visible in the first frame.",
    )

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

    # Visual grounding — bounding boxes force spatial accountability (anti-hallucination).
    waste_bbox: Optional[list[int]] = Field(
        default=None,
        description="Bounding box [y_min, x_min, y_max, x_max] of detected waste, normalized 0-1000.",
    )
    offender_bbox: Optional[list[int]] = Field(
        default=None,
        description="Bounding box [y_min, x_min, y_max, x_max] of offender/vehicle, normalized 0-1000.",
    )

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

    # Scene classification FIRST — forces model to categorize before deciding.
    scene_type: str = Field(
        description=(
            "Classify the scene: EMPTY (no vehicles/people), "
            "TRAFFIC (vehicles/people moving through), "
            "PARKED (vehicles parked, no material handling), "
            "DUMPING (vehicle stopped + person depositing material on ground)."
        ),
    )

    # Independent boolean conditions — evaluated separately by the model,
    # combined deterministically by Python (AND gate). This prevents Flash-Lite
    # from failing compound Boolean logic internally.
    vehicle_stopped: bool = Field(
        default=False,
        description="Is a vehicle stationary (same position) in 2+ frames?",
    )
    person_handling_material: bool = Field(
        default=False,
        description="Is a person carrying, unloading, or depositing material near a vehicle?",
    )
    new_ground_material: bool = Field(
        default=False,
        description="Is there new material on the ground in the last frame that was absent in the first?",
    )

    # Decision fields — only meaningful when scene_type=DUMPING.
    new_litter_detected: bool = Field(
        description="True only when active dumping behavior is visible — vehicle stopped AND person depositing material."
    )
    confidence_0_100: int = Field(
        ge=0,
        le=100,
        description="Model confidence score from 0 to 100.",
    )
    evidence_summary: str = Field(
        min_length=1,
        max_length=500,
        description="Short factual summary of visual comparison (1-2 sentences).",
    )
    first_frame_has_litter: bool = False
    last_frame_has_litter: bool = False
    waste_type: Optional[str] = Field(default=None, max_length=100)
    raw_reason_codes: Optional[list[str]] = Field(default=None)
    # Reasoning field LAST — can be truncated without losing the decision.
    scene_delta_analysis: str = Field(
        default="",
        max_length=500,
        description=(
            "Concise reasoning: (1) up to 5 fixed objects in first frame, "
            "(2) up to 5 fixed objects in last frame, "
            "(3) differences classified as SHADOW|LIGHTING|MOVING_OBJECT|DUMPING_BEHAVIOR."
        ),
    )

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
