"""
Simula uma ocorrencia no banco e dispara notificacoes.

Uso basico:
  python simulate_occurrence.py

Exemplo customizado:
  python simulate_occurrence.py --rpa "RPA 1" --waste-type Entulho --volume 45
"""

import argparse
import asyncio
import random
from datetime import datetime

import redis.asyncio as aioredis
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.camera import Camera
from app.models.detection import Detection, DetectionStatus
from app.services import notification_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Insere uma ocorrencia simulada e envia notificacoes."
    )
    parser.add_argument("--camera-id", type=int, help="ID da camera a ser usada.")
    parser.add_argument("--rpa", type=str, help='Filtra camera por RPA (ex: "RPA 1").')
    parser.add_argument(
        "--waste-type",
        type=str,
        default="Entulho",
        help="Tipo de residuo da ocorrencia.",
    )
    parser.add_argument(
        "--material-type",
        type=str,
        default="Misto",
        help="Tipo de material da ocorrencia.",
    )
    parser.add_argument(
        "--volume",
        type=float,
        default=28.0,
        help="Volume em m3.",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.93,
        help="Confianca da deteccao (0.0 a 1.0).",
    )
    parser.add_argument(
        "--offender",
        type=str,
        default="",
        help="Nome do infrator (opcional).",
    )
    parser.add_argument(
        "--image-url",
        type=str,
        default="https://placehold.co/600x400/ef4444/FFFFFF?text=Ocorrencia+Simulada",
        help="URL da imagem da ocorrencia.",
    )
    return parser


async def pick_camera(camera_id: int | None, rpa: str | None) -> Camera:
    async with AsyncSessionLocal() as db:
        if camera_id is not None:
            result = await db.execute(
                select(Camera).where(Camera.id == camera_id, Camera.is_active == True)
            )
            camera = result.scalar_one_or_none()
            if camera is None:
                raise RuntimeError(f"Camera id={camera_id} nao encontrada/ativa.")
            return camera

        query = select(Camera).where(Camera.is_active == True)
        if rpa:
            query = query.where(Camera.rpa == rpa)
        cameras = (await db.execute(query)).scalars().all()
        if not cameras:
            if rpa:
                raise RuntimeError(f"Nenhuma camera ativa encontrada para RPA '{rpa}'.")
            raise RuntimeError("Nenhuma camera ativa encontrada no banco.")
        return random.choice(cameras)


async def simulate(args: argparse.Namespace) -> None:
    camera = await pick_camera(args.camera_id, args.rpa)

    redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    try:
        async with AsyncSessionLocal() as db:
            # Recarrega a camera na mesma sessao para evitar objetos detached.
            db_camera = await db.get(Camera, camera.id)
            if db_camera is None:
                raise RuntimeError(f"Camera id={camera.id} nao encontrada na sessao.")

            latitude = float(db_camera.latitude)
            longitude = float(db_camera.longitude)
            point = Point(longitude, latitude)

            detection = Detection(
                camera_id=db_camera.id,
                timestamp=datetime.utcnow(),
                logradouro=db_camera.logradouro or "Logradouro nao informado",
                bairro=db_camera.bairro or "Bairro nao informado",
                rpa=db_camera.rpa or "RPA ?",
                latitude=latitude,
                longitude=longitude,
                geom=from_shape(point, srid=4326),
                waste_type=args.waste_type,
                material_type=args.material_type,
                volume_m3=args.volume,
                offenders=args.offender.strip() or None,
                status=DetectionStatus.PENDENTE,
                image_url=args.image_url,
                confidence_score=args.confidence,
            )

            db.add(detection)
            await db.flush()

            await notification_service.on_new_detection(detection, db, redis)
            await db.commit()

            print("[simulate] Ocorrencia criada com sucesso.")
            print(f"[simulate] detection_id: {detection.id}")
            print(f"[simulate] camera_id: {db_camera.id} ({db_camera.name})")
            print(f"[simulate] rpa: {detection.rpa}")
            print(f"[simulate] bairro/logradouro: {detection.bairro} / {detection.logradouro}")
            print("[simulate] Notificacoes criadas e publicadas via Redis.")
    finally:
        await redis.aclose()


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(simulate(args))
