"""REST endpoints for asynchronous camera image exports.

Flow:
    1. POST /api/v1/exports — validates the date range, persists a ``pending``
       row, dispatches the runner via asyncio and returns the row.
    2. GET  /api/v1/exports — lists the current user's exports (newest first).
    3. GET  /api/v1/exports/{id} — single export; refreshes the presigned URL
       when it's about to expire so the browser can resume the download.
    4. DELETE /api/v1/exports/{id} — removes the S3 object and marks the row
       expired (best-effort cleanup, swallows S3 errors).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.timezone import now_brazil
from app.models.camera import Camera
from app.models.image_export import ImageExport
from app.models.user import User
from app.schemas.image_export import ImageExportCreate, ImageExportResponse
from app.services import image_export_runner, s3 as s3_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _serialize(export: ImageExport) -> ImageExportResponse:
    camera = export.camera
    return ImageExportResponse(
        id=export.id,
        user_id=export.user_id,
        camera_id=export.camera_id,
        camera_name=camera.name if camera else None,
        camera_device_id=camera.device_id if camera else None,
        start_at=export.start_at,
        end_at=export.end_at,
        include_occurrences=export.include_occurrences,
        include_non_occurrences=export.include_non_occurrences,
        status=export.status,
        progress=export.progress,
        total_images=export.total_images,
        download_url=export.download_url,
        expires_at=export.expires_at,
        error_message=export.error_message,
        started_at=export.started_at,
        completed_at=export.completed_at,
        created_at=export.created_at,
        updated_at=export.updated_at,
    )


async def _maybe_refresh_url(db: AsyncSession, export: ImageExport) -> ImageExport:
    """If presigned URL is about to expire (<1h left), regenerate it."""
    if export.status != "ready" or not export.s3_key:
        return export
    if not export.expires_at:
        return export
    remaining = export.expires_at - now_brazil()
    if remaining > timedelta(hours=1):
        return export
    if not s3_service.s3_enabled():
        return export
    try:
        client = s3_service.get_s3_client()
        export.download_url = s3_service.generate_presigned_url(client, export.s3_key)
        export.expires_at = now_brazil() + timedelta(
            seconds=settings.EXPORT_PRESIGNED_TTL_SECONDS
        )
        await db.commit()
        await db.refresh(export)
    except Exception:
        logger.exception("Failed to refresh presigned URL for export %s", export.id)
    return export


@router.post(
    "/",
    response_model=ImageExportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_export(
    payload: ImageExportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImageExportResponse:
    # Camera must exist + have a device_id
    cam = await db.get(Camera, payload.camera_id)
    if cam is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Câmera não encontrada",
        )
    if not cam.device_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Câmera sem device_id — não é possível localizar imagens",
        )

    export = ImageExport(
        user_id=current_user.id,
        camera_id=payload.camera_id,
        start_at=payload.start_at,
        end_at=payload.end_at,
        include_occurrences=payload.include_occurrences,
        include_non_occurrences=payload.include_non_occurrences,
        status="pending",
        progress=0,
    )
    db.add(export)
    await db.commit()
    await db.refresh(export)
    # Reload with camera relationship eager so the response is complete
    stmt = (
        select(ImageExport)
        .where(ImageExport.id == export.id)
        .options(selectinload(ImageExport.camera))
    )
    export = (await db.execute(stmt)).scalar_one()

    image_export_runner.schedule_export(export.id)
    return _serialize(export)


@router.get("/", response_model=List[ImageExportResponse])
async def list_exports(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[ImageExportResponse]:
    limit = max(1, min(limit, 100))
    stmt = (
        select(ImageExport)
        .where(ImageExport.user_id == current_user.id)
        .options(selectinload(ImageExport.camera))
        .order_by(ImageExport.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


@router.get("/{export_id}", response_model=ImageExportResponse)
async def get_export(
    export_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImageExportResponse:
    stmt = (
        select(ImageExport)
        .where(ImageExport.id == export_id)
        .options(selectinload(ImageExport.camera))
    )
    export = (await db.execute(stmt)).scalar_one_or_none()
    if export is None or export.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exportação não encontrada",
        )
    export = await _maybe_refresh_url(db, export)
    return _serialize(export)


@router.delete("/{export_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_export(
    export_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(ImageExport).where(ImageExport.id == export_id)
    export = (await db.execute(stmt)).scalar_one_or_none()
    if export is None or export.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exportação não encontrada",
        )
    if export.s3_key and s3_service.s3_enabled():
        try:
            client = s3_service.get_s3_client()
            s3_service.delete_object(client, export.s3_key)
        except Exception:
            logger.exception("Failed to delete S3 object for export %s", export.id)
    export.status = "expired"
    export.download_url = None
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
