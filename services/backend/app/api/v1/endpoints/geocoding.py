from fastapi import APIRouter, Query, HTTPException, Depends
from typing import List
import httpx

from app.core.config import settings
from app.schemas.geocoding import GeocodingResultSchema
from app.api.deps import get_current_user

router = APIRouter()


def _parse_nominatim_result(item: dict) -> GeocodingResultSchema:
    address = item.get("address", {})
    logradouro = (
        address.get("road")
        or address.get("pedestrian")
        or address.get("footway")
    )
    bairro = (
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("quarter")
        or address.get("city_district")
    )
    return GeocodingResultSchema(
        display_name=item.get("display_name", ""),
        latitude=float(item["lat"]),
        longitude=float(item["lon"]),
        logradouro=logradouro,
        bairro=bairro,
    )


@router.get("/search", response_model=List[GeocodingResultSchema])
async def geocoding_search(
    q: str = Query(..., min_length=3, description="Texto do endereço"),
    limit: int = Query(default=5, ge=1, le=10),
    _current_user=Depends(get_current_user),
):
    """Proxy para o serviço Nominatim (OpenStreetMap). Requer autenticação JWT."""
    params = {
        "q": q,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": limit,
        "countrycodes": settings.GEOCODING_COUNTRYCODES,
        "viewbox": settings.GEOCODING_VIEWBOX,
        "bounded": 0,  # soft bounds: prioriza a região, não restringe
    }
    headers = {"User-Agent": settings.NOMINATIM_USER_AGENT}

    try:
        async with httpx.AsyncClient(timeout=settings.GEOCODING_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{settings.NOMINATIM_BASE_URL}/search",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Timeout ao contatar serviço de geocodificação.",
        )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Serviço de geocodificação indisponível. Insira as coordenadas manualmente.",
        )

    data = response.json()
    return [_parse_nominatim_result(item) for item in data]
