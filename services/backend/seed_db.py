"""
Script para popular o banco de dados com dados fictícios para desenvolvimento.
Uso: python seed_db.py
"""
import asyncio
from faker import Faker
from datetime import datetime, timedelta
import random
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.camera import Camera
from app.models.detection import Detection, DetectionStatus
from app.core.security import get_password_hash
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

fake = Faker('pt_BR')


async def seed():
    """Função principal para popular o banco de dados"""
    async with AsyncSessionLocal() as db:
        print("🌱 Iniciando seeding do banco de dados...")

        # Verificar se já existe o admin
        result = await db.execute(select(User).where(User.email == "admin@saira.com"))
        admin_exists = result.scalar_one_or_none()

        if not admin_exists:
            print("👤 Criando usuário Admin...")
            admin = User(
                name="Administrador",
                email="admin@saira.com",
                phone="(81) 99999-9999",
                secretaria="EMLURB",
                cargo="Administrador",
                rpa="RPA-6",
                password_hash=get_password_hash("admin123"),
                is_active=True
            )
            db.add(admin)
        else:
            print("✓ Usuário Admin já existe")

        # Criar usuários aleatórios
        print("👥 Criando usuários aleatórios...")
        secretarias = ["EMLURB", "CTTU", "URB", "Secretaria de Meio Ambiente", "Secretaria de Infraestrutura"]
        cargos = ["Fiscal", "Coordenador", "Analista", "Supervisor", "Técnico"]
        rpas = ["RPA-1", "RPA-2", "RPA-3", "RPA-4", "RPA-5", "RPA-6"]

        for i in range(5):
            user = User(
                name=fake.name(),
                email=fake.email(),
                phone=fake.phone_number(),
                secretaria=random.choice(secretarias),
                cargo=random.choice(cargos),
                rpa=random.choice(rpas),
                password_hash=get_password_hash("senha123"),
                is_active=random.choice([True, True, True, False])  # 75% ativos
            )
            db.add(user)

        await db.commit()
        print("✓ Usuários criados com sucesso")

        # Criar câmeras com coordenadas reais de Recife
        print("📷 Criando câmeras...")
        cameras_data = [
            {
                "name": "Câmera Boa Viagem",
                "logradouro": "Av. Boa Viagem",
                "bairro": "Boa Viagem",
                "rpa": "RPA-6",
                "latitude": -8.1287,
                "longitude": -34.8988,
            },
            {
                "name": "Câmera Derby",
                "logradouro": "Av. Agamenon Magalhães",
                "bairro": "Derby",
                "rpa": "RPA-1",
                "latitude": -8.0592,
                "longitude": -34.8843,
            },
            {
                "name": "Câmera Casa Forte",
                "logradouro": "Praça de Casa Forte",
                "bairro": "Casa Forte",
                "rpa": "RPA-3",
                "latitude": -8.0223,
                "longitude": -34.9287,
            },
            {
                "name": "Câmera Recife Antigo",
                "logradouro": "Rua do Bom Jesus",
                "bairro": "Recife",
                "rpa": "RPA-1",
                "latitude": -8.0631,
                "longitude": -34.8711,
            },
            {
                "name": "Câmera Piedade",
                "logradouro": "Av. Caxangá",
                "bairro": "Piedade",
                "rpa": "RPA-4",
                "latitude": -8.0478,
                "longitude": -34.9194,
            },
        ]

        created_cameras = []
        for cam_data in cameras_data:
            point = Point(cam_data["longitude"], cam_data["latitude"])
            camera = Camera(
                name=cam_data["name"],
                logradouro=cam_data["logradouro"],
                bairro=cam_data["bairro"],
                rpa=cam_data["rpa"],
                latitude=cam_data["latitude"],
                longitude=cam_data["longitude"],
                geom=from_shape(point, srid=4326),
                rtsp_url=f"rtsp://example.com/stream/{fake.uuid4()}",
                capture_interval_seconds=random.choice([30, 60, 120]),
                is_active=True,
                last_capture_at=datetime.utcnow() - timedelta(minutes=random.randint(1, 60))
            )
            db.add(camera)
            created_cameras.append(camera)

        await db.commit()
        print("✓ Câmeras criadas com sucesso")

        # Criar detecções
        print("🔍 Criando detecções...")
        waste_types = ["Entulho", "Móveis", "Lixo doméstico", "Resíduos de construção", "Eletrônicos"]
        material_types = ["Concreto", "Madeira", "Plástico", "Metal", "Misto"]
        statuses = [DetectionStatus.PENDENTE, DetectionStatus.EM_ANALISE, DetectionStatus.RESOLVIDO]

        for i in range(25):
            camera = random.choice(created_cameras)
            # Adicionar pequena variação nas coordenadas da câmera
            lat_offset = random.uniform(-0.002, 0.002)
            lng_offset = random.uniform(-0.002, 0.002)
            det_lat = float(camera.latitude) + lat_offset
            det_lng = float(camera.longitude) + lng_offset

            point = Point(det_lng, det_lat)

            detection = Detection(
                camera_id=camera.id,
                timestamp=datetime.utcnow() - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23)),
                logradouro=camera.logradouro,
                bairro=camera.bairro,
                rpa=camera.rpa,
                latitude=det_lat,
                longitude=det_lng,
                geom=from_shape(point, srid=4326),
                waste_type=random.choice(waste_types),
                material_type=random.choice(material_types),
                volume_m3=round(random.uniform(0.5, 15.0), 2),
                offenders=fake.name() if random.random() > 0.5 else None,
                status=random.choice(statuses),
                image_url=f"https://picsum.photos/seed/{fake.uuid4()}/800/600",
                confidence_score=round(random.uniform(0.75, 0.99), 2)
            )
            db.add(detection)

        await db.commit()
        print("✓ Detecções criadas com sucesso")

        print("\n✅ Seeding concluído com sucesso!")
        print("\n📝 Credenciais de acesso:")
        print("   Email: admin@saira.com")
        print("   Senha: admin123")


if __name__ == "__main__":
    asyncio.run(seed())
