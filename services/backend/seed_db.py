"""
Script para popular o banco com os mesmos dados-base usados no frontend
(services/frontend/src/services/mockData.ts).
Uso: python seed_db.py
"""

import asyncio
import calendar
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal

from faker import Faker
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.core.timezone import now_brazil
from app.models.camera import Camera
from app.models.detection import Detection, DetectionStatus
from app.models.offender import (
    DetectionOffender,
    Offender,
    OffenderSource,
    OffenderType,
)
from app.models.user import User

fake = Faker("pt_BR")

SEED_LOCATIONS = [
    {
        "bairro": "Imbiribeira",
        "logradouro": "Rua Visconde de Suassuna",
        "latitude": -8.1122,
        "longitude": -34.9026,
    },
    {
        "bairro": "Brasília Teimosa",
        "logradouro": "Av. Brasília Formosa",
        "latitude": -8.0848,
        "longitude": -34.8876,
    },
    {
        "bairro": "Santo Amaro",
        "logradouro": "Rua do Pombal",
        "latitude": -8.0435,
        "longitude": -34.8906,
    },
    {
        "bairro": "Prado",
        "logradouro": "Rua Abdias de Carvalho",
        "latitude": -8.0617,
        "longitude": -34.9123,
    },
    {
        "bairro": "Porto da Madeira",
        "logradouro": "Av. Beberibe",
        "latitude": -8.0163,
        "longitude": -34.8856,
    },
    {
        "bairro": "Ilha de Deus",
        "logradouro": "Ponte Paulo Guerra",
        "latitude": -8.0934,
        "longitude": -34.9073,
    },
    {
        "bairro": "Torrões",
        "logradouro": "Rua Onze de Fevereiro",
        "latitude": -8.0673,
        "longitude": -34.9318,
    },
    {
        "bairro": "Várzea",
        "logradouro": "Praça da Várzea",
        "latitude": -8.0531,
        "longitude": -34.9545,
    },
    {
        "bairro": "Jiquiá",
        "logradouro": "Rua João Teixeira",
        "latitude": -8.0825,
        "longitude": -34.9213,
    },
]

WASTE_TYPES = ["Entulho", "Lixo domiciliar", "Poda", "Plástico"]
PHOTO_URLS = [
    "https://placehold.co/600x400/ef4444/FFFFFF?text=Foto+1",
    "https://placehold.co/600x400/3b82f6/FFFFFF?text=Foto+2",
    "https://placehold.co/600x400/f97316/FFFFFF?text=Foto+3",
    "https://placehold.co/600x400/22c55e/FFFFFF?text=Foto+4",
    "https://placehold.co/600x400/8b5cf6/FFFFFF?text=Foto+5",
    "https://placehold.co/600x400/0ea5e9/FFFFFF?text=Foto+6",
    "https://placehold.co/600x400/facc15/1f2937?text=Foto+7",
    "https://placehold.co/600x400/14b8a6/FFFFFF?text=Foto+8",
    "https://placehold.co/600x400/64748b/FFFFFF?text=Foto+9",
]

OFFENDER_COLOR_CHOICES = [
    "Branco",
    "Preto",
    "Prata",
    "Cinza",
    "Vermelho",
    "Azul",
]

OFFENDER_PROFILE_SEED = [
    {
        "name": "Jose da Silva",
        "type": OffenderType.CARRO,
        "plate": "QWE2A34",
        "vehicle_color": "Branco",
        "description": "Sedan branco recorrente em descarte irregular",
    },
    {
        "name": "Maria Pereira",
        "type": OffenderType.CARRO,
        "plate": "MNO9B10",
        "vehicle_color": "Prata",
        "description": "Hatch prata visto em varios bairros",
    },
    {
        "name": "Carlos Souza",
        "type": OffenderType.MOTO,
        "plate": "KLM7C65",
        "vehicle_color": "Preto",
        "description": "Moto preta com transporte de sacos de lixo",
    },
    {
        "name": "Equipe carroceiros local",
        "type": OffenderType.CARROCA,
        "plate": None,
        "vehicle_color": None,
        "description": "Carroca de tracao animal usada para descarte",
    },
    {
        "name": "Nao identificado",
        "type": OffenderType.PESSOA,
        "plate": None,
        "vehicle_color": None,
        "description": "Pessoa realizando descarte manual",
    },
]


def _random_month_timestamp(year: int, month_index: int) -> datetime:
    month = month_index + 1
    last_day = calendar.monthrange(year, month)[1]
    tz = ZoneInfo("America/Sao_Paulo")
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=tz)
    delta_seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, delta_seconds))


def _status_for_date(year: int, month_index: int) -> DetectionStatus:
    if year == 2025:
        return DetectionStatus.CONFIRMADO
    if year == 2026 and month_index == 0:
        return random.choice(
            [
                DetectionStatus.PENDENTE,
                DetectionStatus.CONFIRMADO,
                DetectionStatus.REJEITADO,
                DetectionStatus.INDETERMINADO,
            ]
        )
    return DetectionStatus.CONFIRMADO


def _compute_rpa(bairro: str, logradouro: str) -> str:
    key = f"{bairro}-{logradouro}"
    hash_value = 0
    for char in key:
        hash_value = (hash_value * 31 + ord(char)) & 0xFFFFFFFF
        if hash_value >= 0x80000000:
            hash_value -= 0x100000000
    index = abs(hash_value) % 6
    return f"RPA {index + 1}"


def _random_plate() -> str:
    letters = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=3))
    numbers = "".join(random.choices("0123456789", k=1))
    letter = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    numbers_2 = "".join(random.choices("0123456789", k=2))
    return f"{letters}{numbers}{letter}{numbers_2}"


async def seed() -> None:
    random.seed(42)

    async with AsyncSessionLocal() as db:
        print("[seed] Iniciando seeding...")

        # Admin padrao
        result = await db.execute(select(User).where(User.email == "admin@saira.com"))
        admin = result.scalar_one_or_none()

        if admin is None:
            admin = User(
                name="Administrador",
                email="admin@saira.com",
                phone="(81) 99999-9999",
                secretaria="EMLURB",
                cargo="Administrador",
                rpa="RPA-6",
                password_hash=get_password_hash("admin123"),
                is_active=True,
            )
            db.add(admin)
            print("[seed] Usuario admin criado")
        else:
            print("[seed] Usuario admin ja existe")

        # Recria cameras/detections para manter o dataset alinhado ao mockData.ts
        await db.execute(delete(DetectionOffender))
        await db.execute(delete(Offender))
        await db.execute(delete(Detection))
        await db.execute(delete(Camera))
        await db.commit()
        print("[seed] Cameras, deteccoes e infratores antigos removidos")

        offenders_catalog: list[Offender] = []
        for profile in OFFENDER_PROFILE_SEED:
            offender = Offender(
                name=profile["name"],
                type=profile["type"],
                plate=profile["plate"],
                vehicle_color=profile["vehicle_color"],
                description=profile["description"],
                is_active=True,
                created_by=admin.id if admin else None,
            )
            db.add(offender)
            offenders_catalog.append(offender)
        await db.flush()

        camera_by_key: dict[tuple[str, str], Camera] = {}

        for idx, loc in enumerate(SEED_LOCATIONS, start=1):
            point = Point(loc["longitude"], loc["latitude"])
            rpa = _compute_rpa(loc["bairro"], loc["logradouro"])

            camera = Camera(
                name=f"Camera {idx:02d} - {loc['bairro']}",
                logradouro=loc["logradouro"],
                bairro=loc["bairro"],
                rpa=rpa,
                latitude=loc["latitude"],
                longitude=loc["longitude"],
                geom=from_shape(point, srid=4326),
                rtsp_url=f"rtsp://example.com/camera/{idx:02d}",
                capture_interval_seconds=30,
                is_active=True,
                last_capture_at=now_brazil(),
            )
            db.add(camera)
            await db.flush()
            camera_by_key[(loc["bairro"], loc["logradouro"])] = camera

        total = 0
        total_detection_offenders = 0
        for loc in SEED_LOCATIONS:
            camera = camera_by_key[(loc["bairro"], loc["logradouro"])]
            rpa = _compute_rpa(loc["bairro"], loc["logradouro"])

            for year in (2025, 2026):
                start_month = 0
                end_month = 11 if year == 2025 else 0

                for month in range(start_month, end_month + 1):
                    for _ in range(10):
                        has_offender = random.random() < 0.5
                        det_point = Point(loc["longitude"], loc["latitude"])

                        detection = Detection(
                            camera_id=camera.id,
                            timestamp=_random_month_timestamp(year, month),
                            logradouro=loc["logradouro"],
                            bairro=loc["bairro"],
                            rpa=rpa,
                            latitude=loc["latitude"],
                            longitude=loc["longitude"],
                            geom=from_shape(det_point, srid=4326),
                            waste_type=random.choice(WASTE_TYPES),
                            material_type="Misto",
                            volume_m3=random.randint(10, 100),
                            offenders=None,
                            status=_status_for_date(year, month),
                            image_url=random.choice(PHOTO_URLS),
                            confidence_score=round(random.uniform(0.75, 0.99), 2),
                        )
                        db.add(detection)
                        await db.flush()

                        if has_offender:
                            sighting_count = 1 if random.random() < 0.8 else 2
                            offender_labels: list[str] = []

                            for _sighting in range(sighting_count):
                                link_existing_profile = random.random() < 0.7
                                linked_offender = (
                                    random.choice(offenders_catalog)
                                    if link_existing_profile and offenders_catalog
                                    else None
                                )

                                if linked_offender is not None:
                                    offender_type = linked_offender.type
                                    plate = linked_offender.plate
                                    vehicle_color = linked_offender.vehicle_color
                                    offender_name = linked_offender.name
                                else:
                                    offender_type = random.choice(list(OffenderType))
                                    plate = (
                                        _random_plate()
                                        if offender_type in {
                                            OffenderType.CARRO,
                                            OffenderType.MOTO,
                                        }
                                        else None
                                    )
                                    vehicle_color = (
                                        random.choice(OFFENDER_COLOR_CHOICES)
                                        if offender_type in {
                                            OffenderType.CARRO,
                                            OffenderType.MOTO,
                                        }
                                        else None
                                    )
                                    offender_name = (
                                        fake.name()
                                        if offender_type == OffenderType.PESSOA
                                        else offender_type.value
                                    )

                                detection_offender = DetectionOffender(
                                    detection_id=detection.id,
                                    offender_id=(
                                        linked_offender.id if linked_offender else None
                                    ),
                                    offender_type=offender_type,
                                    plate=plate,
                                    vehicle_color=vehicle_color,
                                    waste_type=detection.waste_type,
                                    estimated_volume_m3=Decimal(str(detection.volume_m3)),
                                    source=OffenderSource.AI,
                                    confidence_score=round(
                                        random.uniform(0.75, 0.99), 2
                                    ),
                                    created_by=admin.id if admin else None,
                                    notes="Gerado automaticamente no seed",
                                )
                                db.add(detection_offender)
                                total_detection_offenders += 1

                                if plate:
                                    offender_labels.append(plate)
                                elif offender_name:
                                    offender_labels.append(offender_name)

                            detection.offenders = ", ".join(offender_labels[:3]) or "Nao identificado"

                        total += 1

        await db.commit()

        print(f"[seed] {len(SEED_LOCATIONS)} cameras criadas")
        print(f"[seed] {total} deteccoes criadas")
        print(f"[seed] {len(offenders_catalog)} perfis de infratores criados")
        print(f"[seed] {total_detection_offenders} vinculos detection_offenders criados")
        print("[seed] Concluido")
        print("[seed] Login admin: admin@saira.com / admin123")


if __name__ == "__main__":
    asyncio.run(seed())
