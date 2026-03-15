"""Seed real cameras into the database.

Usage:
    python seed_cameras.py

Reads CAMERAS list below and upserts into the cameras table.
Idempotent: safe to run multiple times.
"""
import asyncio
import os
import sys

# Add parent directory so we can import app modules
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select, text
from app.core.database import engine, AsyncSessionLocal
from app.models.camera import Camera


# ---- CONFIGURE YOUR CAMERAS HERE ----
CAMERAS = [
    {
        "name": "Camera 01 - Coque",
        "device_id": "cam_01_coque",
        "logradouro": "Rua Imperial, 200",
        "bairro": "Sao Jose",
        "rpa": "RPA 1",
        "latitude": -8.063170,
        "longitude": -34.871140,
    },
    # Add more cameras as needed:
    # {
    #     "name": "Camera 02 - Boa Viagem",
    #     "device_id": "cam_02_boaviagem",
    #     "logradouro": "Av. Boa Viagem, 1000",
    #     "bairro": "Boa Viagem",
    #     "rpa": "RPA 6",
    #     "latitude": -8.119740,
    #     "longitude": -34.896920,
    # },
]


async def seed():
    async with AsyncSessionLocal() as session:
        for cam_data in CAMERAS:
            result = await session.execute(
                select(Camera).where(Camera.device_id == cam_data["device_id"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                print(f"  Camera '{cam_data['device_id']}' already exists (id={existing.id}), skipping.")
                continue

            camera = Camera(**cam_data)
            session.add(camera)
            await session.commit()
            await session.refresh(camera)
            print(f"  Created camera '{cam_data['device_id']}' (id={camera.id})")

    print("Done.")


if __name__ == "__main__":
    print("Seeding cameras...")
    asyncio.run(seed())
