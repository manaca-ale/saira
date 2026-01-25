from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID
from app.models.detection import Detection
from app.models.camera import Camera


async def get_detections_near_point(
    db: AsyncSession,
    latitude: float,
    longitude: float,
    radius_meters: float = 1000
) -> List[Detection]:
    """
    Busca detecções dentro de um raio em metros de um ponto específico

    Args:
        db: Sessão do banco de dados
        latitude: Latitude do ponto central
        longitude: Longitude do ponto central
        radius_meters: Raio de busca em metros (padrão: 1000m)

    Returns:
        Lista de detecções dentro do raio especificado
    """
    # Criar ponto PostGIS com SRID 4326 (WGS84)
    point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)

    # Converter metros para graus (aproximação)
    # 1 grau ≈ 111km no equador
    radius_degrees = radius_meters / 111000

    # Query com ST_DWithin para encontrar pontos próximos
    query = select(Detection).where(
        ST_DWithin(
            Detection.geom,
            point,
            radius_degrees
        )
    )

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_cameras_near_detection(
    db: AsyncSession,
    detection_id: UUID,
    radius_meters: float = 500
) -> List[Camera]:
    """
    Busca câmeras próximas a uma detecção específica

    Args:
        db: Sessão do banco de dados
        detection_id: ID da detecção
        radius_meters: Raio de busca em metros (padrão: 500m)

    Returns:
        Lista de câmeras próximas à detecção
    """
    # Buscar a detecção
    detection_result = await db.execute(
        select(Detection).where(Detection.id == detection_id)
    )
    detection = detection_result.scalar_one_or_none()

    if not detection:
        return []

    # Converter metros para graus
    radius_degrees = radius_meters / 111000

    # Query para encontrar câmeras próximas
    query = select(Camera).where(
        ST_DWithin(
            Camera.geom,
            detection.geom,
            radius_degrees
        )
    )

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_cameras_near_point(
    db: AsyncSession,
    latitude: float,
    longitude: float,
    radius_meters: float = 500
) -> List[Camera]:
    """
    Busca câmeras próximas a um ponto específico

    Args:
        db: Sessão do banco de dados
        latitude: Latitude do ponto central
        longitude: Longitude do ponto central
        radius_meters: Raio de busca em metros (padrão: 500m)

    Returns:
        Lista de câmeras dentro do raio especificado
    """
    # Criar ponto PostGIS
    point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)

    # Converter metros para graus
    radius_degrees = radius_meters / 111000

    # Query
    query = select(Camera).where(
        ST_DWithin(
            Camera.geom,
            point,
            radius_degrees
        )
    ).where(Camera.is_active == True)

    result = await db.execute(query)
    return list(result.scalars().all())


async def calculate_distance_between_points(
    db: AsyncSession,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float
) -> float:
    """
    Calcula a distância em metros entre dois pontos geográficos

    Args:
        db: Sessão do banco de dados
        lat1, lon1: Coordenadas do primeiro ponto
        lat2, lon2: Coordenadas do segundo ponto

    Returns:
        Distância em graus (para converter em metros, multiplicar por ~111000)
    """
    point1 = ST_SetSRID(ST_MakePoint(lon1, lat1), 4326)
    point2 = ST_SetSRID(ST_MakePoint(lon2, lat2), 4326)

    result = await db.execute(
        select(ST_Distance(point1, point2))
    )

    distance_degrees = result.scalar_one()
    return distance_degrees * 111000  # Converter para metros aproximadamente
