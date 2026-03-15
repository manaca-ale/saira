from pydantic import BaseModel
from typing import Optional, List


class GeocodingResultSchema(BaseModel):
    display_name: str
    latitude: float
    longitude: float
    logradouro: Optional[str] = None
    bairro: Optional[str] = None


class GeocodingResponseSchema(BaseModel):
    results: List[GeocodingResultSchema]
