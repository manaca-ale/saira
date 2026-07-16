import asyncio
import logging
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, or_, exists
from app.api.deps import get_db, get_current_user
from app.core.database import AsyncSessionLocal
from app.core.redis import get_redis
from app.models.user import User
from app.models.camera import Camera
from app.models.detection import Detection, DetectionStatus
from app.models.offender import DetectionOffender, OffenderSource
from app.schemas.detection import (
    DetectionCreate, DetectionUpdate, DetectionResponse,
    DetectionClassify, DetectionListResponse, DetectionSearchItem,
    DetectionAnalyzedFramesResponse, DetectionVideoResponse,
    DetectionFilterOptionsResponse,
)
from app.services import s3 as s3_service
from app.schemas.detection import DetectionStatus as DetectionStatusSchema
from app.services import notification_service
from app.core.timezone import now_brazil

logger = logging.getLogger(__name__)

router = APIRouter()
WORKER_STATE_DIR = Path(os.getenv("WORKER_STATE_DIR", "/app/yolo_state"))
DETECTION_FRAMES_DIR = WORKER_STATE_DIR / "detection_frames"

# Vídeo sob demanda (dispositivos event-driven / Pi relay).
ESP32_SERVER_URL = os.getenv("ESP32_SERVER_URL", "").rstrip("/")
CAMERA_UPLOADS_DIR = Path(os.getenv("CAMERA_UPLOADS_DIR", "/app/uploads"))
VIDEO_PUBLIC_BASE_URL = os.getenv("CAMERA_UPLOAD_PUBLIC_BASE_URL", "").rstrip("/")
VIDEO_REQUEST_TIMEOUT_S = int(os.getenv("VIDEO_REQUEST_TIMEOUT_S", "600"))

# --- Sorting whitelist (previne SQL injection via campo inválido) ---
DETECTION_SORTABLE_FIELDS: dict[str, Any] = {
    "timestamp":   Detection.timestamp,
    "created_at":  Detection.created_at,
    "volume_m3":   Detection.volume_m3,
    "bairro":      Detection.bairro,
    "logradouro":  Detection.logradouro,
    "status":      Detection.status,
    "rpa":         Detection.rpa,
    "waste_type":  Detection.waste_type,
}
DEFAULT_SORT_FIELD = "timestamp"


def _parse_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_status_filter(value: str) -> Optional[DetectionStatus]:
    normalized = value.strip().lower()
    if normalized == "pendente":
        return DetectionStatus.PENDENTE
    if normalized == "confirmado":
        return DetectionStatus.CONFIRMADO
    if normalized == "rejeitado":
        return DetectionStatus.REJEITADO
    if normalized == "indeterminado":
        return DetectionStatus.INDETERMINADO
    return None


async def _effective_offender_types(
    db: AsyncSession, detection_ids: List[UUID]
) -> dict:
    """Tipos de infrator efetivos por detecção (batch, 1 query).

    Manual vence IA: se a detecção tem rótulo humano, só ele conta; senão
    valem os tipos da IA. Dedupe preservando ordem de criação. Mesma regra
    dos dashboards de infratores (_effective_sighting_condition).
    """
    if not detection_ids:
        return {}

    result = await db.execute(
        select(
            DetectionOffender.detection_id,
            DetectionOffender.offender_type,
            DetectionOffender.source,
        )
        .where(DetectionOffender.detection_id.in_(detection_ids))
        .order_by(DetectionOffender.created_at)
    )

    ai_types: dict = {}
    manual_types: dict = {}
    for det_id, offender_type, source in result.all():
        bucket = manual_types if source == OffenderSource.MANUAL else ai_types
        types = bucket.setdefault(det_id, [])
        if offender_type.value not in types:
            types.append(offender_type.value)

    return {
        det_id: manual_types.get(det_id) or ai_types.get(det_id, [])
        for det_id in set(ai_types) | set(manual_types)
    }


def _expand_waste_type_aliases(values: List[str]) -> List[str]:
    aliases = {
        "entulho": {"entulho"},
        "lixo domiciliar": {"lixo domiciliar", "household waste"},
        "poda": {"poda", "pruning"},
        "plástico": {"plástico", "plastico", "plastic"},
        "plastico": {"plástico", "plastico", "plastic"},
    }
    expanded = set()
    for value in values:
        key = value.strip().lower()
        expanded.update(aliases.get(key, {key}))
    return list(expanded)


@router.get("/", response_model=List[DetectionResponse])
async def get_detections(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    camera_id: Optional[int] = Query(None, ge=1),
    rpa: Optional[str] = None,
    status_filter: Optional[DetectionStatusSchema] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    bairro: Optional[str] = None,
    sort_by: Optional[str] = Query(None, description="Campo para ordenação"),
    sort_order: Optional[str] = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista detecções com filtros e paginação"""
    query = select(Detection)

    filters = []
    if camera_id is not None:
        filters.append(Detection.camera_id == camera_id)
    if rpa:
        filters.append(Detection.rpa == rpa)
    if status_filter:
        filters.append(Detection.status == status_filter)
    if start_date:
        filters.append(Detection.timestamp >= start_date)
    if end_date:
        filters.append(Detection.timestamp <= end_date)
    if bairro:
        filters.append(Detection.bairro == bairro)

    if filters:
        query = query.where(and_(*filters))

    col = DETECTION_SORTABLE_FIELDS.get(sort_by or DEFAULT_SORT_FIELD, Detection.timestamp)
    order = col.asc() if sort_order == "asc" else col.desc()
    query = query.offset(skip).limit(limit).order_by(order)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/search", response_model=DetectionListResponse)
async def search_detections(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    rpa: Optional[str] = None,
    status_filter: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    bairro: Optional[str] = None,
    logradouro: Optional[str] = None,
    waste_type: Optional[str] = None,
    has_offender: Optional[bool] = None,
    has_manual_offender: Optional[bool] = None,
    camera_id: Optional[int] = Query(None, ge=1),
    volume_min: Optional[float] = Query(None, ge=0),
    volume_max: Optional[float] = Query(None, ge=0),
    sort_by: Optional[str] = Query(None, description="Campo para ordenação"),
    sort_order: Optional[str] = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista deteções paginadas com total e filtros para o frontend."""
    if volume_min is not None and volume_max is not None and volume_min > volume_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="volume_min cannot be greater than volume_max",
        )

    filters = []

    rpa_values = _parse_csv(rpa)
    if rpa_values:
        filters.append(Detection.rpa.in_(rpa_values))

    raw_status_values = _parse_csv(status_filter)
    status_values = [
        parsed
        for parsed in (_normalize_status_filter(value) for value in raw_status_values)
        if parsed is not None
    ]
    if raw_status_values and not status_values:
        return DetectionListResponse(items=[], total=0, skip=skip, limit=limit)
    if status_values:
        filters.append(Detection.status.in_(status_values))

    if start_date:
        filters.append(Detection.timestamp >= start_date)
    if end_date:
        filters.append(Detection.timestamp <= end_date)

    if bairro and bairro.strip():
        filters.append(Detection.bairro.ilike(f"%{bairro.strip()}%"))
    if logradouro and logradouro.strip():
        filters.append(Detection.logradouro.ilike(f"%{logradouro.strip()}%"))

    waste_type_values = _expand_waste_type_aliases(_parse_csv(waste_type))
    if waste_type_values:
        filters.append(func.lower(Detection.waste_type).in_(waste_type_values))

    if has_offender is True:
        filters.append(
            and_(
                Detection.offenders.is_not(None),
                func.length(func.trim(Detection.offenders)) > 0,
            )
        )
    elif has_offender is False:
        filters.append(
            or_(
                Detection.offenders.is_(None),
                func.length(func.trim(Detection.offenders)) == 0,
            )
        )

    if has_manual_offender is not None:
        # Rótulo humano de infrator (fila da rotulagem usa =false).
        manual_exists = exists().where(
            DetectionOffender.detection_id == Detection.id,
            DetectionOffender.source == OffenderSource.MANUAL,
        )
        filters.append(manual_exists if has_manual_offender else ~manual_exists)

    if camera_id is not None:
        filters.append(Detection.camera_id == camera_id)

    if volume_min is not None:
        filters.append(Detection.volume_m3 >= volume_min)
    if volume_max is not None:
        filters.append(Detection.volume_m3 <= volume_max)

    filter_expression = and_(*filters) if filters else None

    count_query = select(func.count(Detection.id))
    if filter_expression is not None:
        count_query = count_query.where(filter_expression)
    total = (await db.execute(count_query)).scalar_one()

    query = select(Detection, Camera.name, Camera.device_id).outerjoin(
        Camera, Detection.camera_id == Camera.id
    )
    if filter_expression is not None:
        query = query.where(filter_expression)
    col = DETECTION_SORTABLE_FIELDS.get(sort_by or DEFAULT_SORT_FIELD, Detection.timestamp)
    order = col.asc() if sort_order == "asc" else col.desc()
    query = query.order_by(order).offset(skip).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    offender_types_map = await _effective_offender_types(
        db, [det.id for det, _, _ in rows]
    )

    items = []
    for det, camera_name, camera_device_id in rows:
        item = DetectionSearchItem.model_validate(det)
        item.camera_name = camera_name
        item.camera_device_id = camera_device_id
        item.offender_types = offender_types_map.get(det.id, [])
        items.append(item)

    return DetectionListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/filter-options", response_model=DetectionFilterOptionsResponse)
async def get_filter_options(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Valores distintos (domínio completo) para os filtros do frontend.

    Retorna todos os bairros e logradouros já registrados no banco, ignorando
    paginação e demais filtros — para que os autocompletes não fiquem limitados
    ao subconjunto carregado na tela.
    """

    async def _distinct(column) -> List[str]:
        query = (
            select(column)
            .where(column.is_not(None), func.length(func.trim(column)) > 0)
            .distinct()
            .order_by(column.asc())
        )
        rows = (await db.execute(query)).scalars().all()
        return [value.strip() for value in rows]

    bairros = await _distinct(Detection.bairro)
    logradouros = await _distinct(Detection.logradouro)
    return DetectionFilterOptionsResponse(bairros=bairros, logradouros=logradouros)


@router.get("/{detection_id}", response_model=DetectionResponse)
async def get_detection(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Busca uma detecção por ID"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found"
        )

    return detection


@router.get("/{detection_id}/analyzed-frames", response_model=DetectionAnalyzedFramesResponse)
async def get_detection_analyzed_frames(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return frame options analyzed by Gemini agent-2 for this detection."""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()
    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found",
        )

    fallback_frame_name = ""
    if detection.image_url:
        fallback_frame_name = str(detection.image_url).rstrip("/").split("/")[-1]

    index_file = DETECTION_FRAMES_DIR / f"{detection_id}.json"
    if not index_file.exists():
        frames = []
        if detection.image_url:
            frames = [
                {
                    "frame_name": fallback_frame_name or "selected_frame.jpg",
                    "image_url": str(detection.image_url),
                    "is_default": True,
                }
            ]
        return DetectionAnalyzedFramesResponse(
            detection_id=detection_id,
            selected_frame_name=fallback_frame_name or None,
            frames=frames,
        )

    try:
        payload = json.loads(index_file.read_text(encoding="utf-8"))
    except Exception:
        payload = {}

    raw_frames = payload.get("frames") or []
    frames = []
    for frame in raw_frames:
        frame_name = str(frame.get("frame_name") or "").strip()
        image_url = str(frame.get("image_url") or "").strip()
        if not frame_name or not image_url:
            continue
        frames.append(
            {
                "frame_name": frame_name,
                "image_url": image_url,
                "is_default": bool(frame.get("is_default")),
            }
        )

    if not frames and detection.image_url:
        frames = [
            {
                "frame_name": fallback_frame_name or "selected_frame.jpg",
                "image_url": str(detection.image_url),
                "is_default": True,
            }
        ]

    selected_name = str(payload.get("selected_frame_name") or "").strip() or None
    persisted_image_url = str(detection.image_url or "").strip()

    resolved_selected_frame = None
    if persisted_image_url:
        resolved_selected_frame = next(
            (frame for frame in frames if frame["image_url"] == persisted_image_url),
            None,
        )
    if resolved_selected_frame is None and selected_name:
        resolved_selected_frame = next(
            (frame for frame in frames if frame["frame_name"] == selected_name),
            None,
        )
    if resolved_selected_frame is None:
        resolved_selected_frame = next((frame for frame in frames if frame["is_default"]), None)
    if resolved_selected_frame is None and frames:
        resolved_selected_frame = frames[0]

    if resolved_selected_frame:
        selected_name = resolved_selected_frame["frame_name"]
        for frame in frames:
            frame["is_default"] = frame["frame_name"] == selected_name

    return DetectionAnalyzedFramesResponse(
        detection_id=detection_id,
        selected_frame_name=selected_name,
        frames=frames,
    )


# Os frames de uma detecção são nomeados YYYY-MM-DD_HH-MM-SS.jpg (BRT) e vivem
# no S3 sob ocorrencias/{device}/{data-UTC}/. A partição é por DATA UTC (BRT+3h).
_FRAME_TS_FORMATS = ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%d_%H-%M-%S-%f")
_CONTEXT_FRAMES_CAP = 60


def _parse_frame_ts(frame_name: str) -> Optional[datetime]:
    stem = frame_name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    for fmt in _FRAME_TS_FORMATS:
        try:
            return datetime.strptime(stem, fmt)
        except ValueError:
            continue
    return None


def _occurrence_key_from_url(image_url: str) -> Optional[str]:
    """Extrai a chave S3 `ocorrencias/{device}/YYYY/MM/DD/frame.jpg` de uma
    image_url (aceita https S3, /s3-images/... ou caminho cru). None se a
    detecção não tem frame de ocorrência no S3 (ex.: uploads locais)."""
    if not image_url:
        return None
    idx = image_url.find("ocorrencias/")
    if idx == -1:
        return None
    return image_url[idx:]


@router.get("/{detection_id}/context-frames", response_model=DetectionAnalyzedFramesResponse)
async def get_detection_context_frames(
    detection_id: UUID,
    window_seconds: int = Query(60, ge=5, le=600),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Frames vizinhos da MESMA câmera numa janela de ±window_seconds em torno
    do frame da detecção — dá contexto temporal para a rotulagem julgar o tipo
    de descarte (o analyzed-frames só traz o que a IA analisou, e as detecções
    antigas caem em 1 frame). Ancora no timestamp do frame selecionado (BRT) e
    lista o S3. Cai no analyzed-frames quando não há frame de ocorrência no S3."""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()
    if not detection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")

    key = _occurrence_key_from_url(str(detection.image_url or ""))
    center = _parse_frame_ts(key.rsplit("/", 1)[-1]) if key else None
    if not key or center is None or not s3_service.s3_enabled():
        return await get_detection_analyzed_frames(detection_id, db, current_user)

    selected_name = key.rsplit("/", 1)[-1]
    device_id = key.split("/")[1]
    lo = center - timedelta(seconds=window_seconds)
    hi = center + timedelta(seconds=window_seconds)

    # Partições a varrer: a do frame + as das bordas da janela (BRT->UTC = +3h),
    # cobrindo o caso raro de a janela cruzar a meia-noite UTC (21h BRT).
    prefixes = {key.rsplit("/", 1)[0] + "/"}
    for edge in (lo, hi):
        utc_day = (edge + timedelta(hours=3)).date()
        prefixes.add(s3_service.occurrence_prefix(device_id, utc_day))

    frames: list[dict] = []
    seen: set[str] = set()
    try:
        client = s3_service.get_s3_client()
        for prefix in prefixes:
            for obj_key in s3_service.list_keys(client, prefix):
                name = obj_key.rsplit("/", 1)[-1]
                if name in seen or not name.lower().endswith(".jpg"):
                    continue
                ts = _parse_frame_ts(name)
                if ts is None or ts < lo or ts > hi:
                    continue
                seen.add(name)
                frames.append(
                    {
                        "frame_name": name,
                        "image_url": f"/s3-images/{obj_key}",
                        "is_default": name == selected_name,
                    }
                )
    except Exception:
        logger.exception("context-frames: falha ao listar S3 (%s)", detection_id)
        return await get_detection_analyzed_frames(detection_id, db, current_user)

    if not frames:
        return await get_detection_analyzed_frames(detection_id, db, current_user)

    frames.sort(key=lambda f: f["frame_name"])
    if len(frames) > _CONTEXT_FRAMES_CAP:
        # Mantém a janela centrada no frame selecionado se estourar o teto.
        pivot = next((i for i, f in enumerate(frames) if f["is_default"]), len(frames) // 2)
        half = _CONTEXT_FRAMES_CAP // 2
        start = max(0, min(pivot - half, len(frames) - _CONTEXT_FRAMES_CAP))
        frames = frames[start:start + _CONTEXT_FRAMES_CAP]
    if not any(f["is_default"] for f in frames) and frames:
        frames[0]["is_default"] = True

    return DetectionAnalyzedFramesResponse(
        detection_id=detection_id,
        selected_frame_name=selected_name,
        frames=frames,
    )


@router.post("/", response_model=DetectionResponse, status_code=status.HTTP_201_CREATED)
async def create_detection(
    detection_in: DetectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria uma nova detecção"""
    db_detection = Detection(
        camera_id=detection_in.camera_id,
        timestamp=detection_in.timestamp,
        logradouro=detection_in.logradouro,
        bairro=detection_in.bairro,
        rpa=detection_in.rpa,
        latitude=detection_in.latitude,
        longitude=detection_in.longitude,
        waste_type=detection_in.waste_type,
        material_type=detection_in.material_type,
        volume_m3=detection_in.volume_m3,
        offenders=detection_in.offenders,
        status=detection_in.status,
        image_url=detection_in.image_url,
        confidence_score=detection_in.confidence_score
    )

    # O trigger no banco irá criar automaticamente o campo geom

    db.add(db_detection)
    await db.commit()
    await db.refresh(db_detection)

    # Disparar notificações em background (nova sessão para não conflitar)
    detection_id = db_detection.id
    detection_snapshot = db_detection

    async def _notify():
        try:
            async with AsyncSessionLocal() as bg_db:
                redis = get_redis()
                await notification_service.on_new_detection(detection_snapshot, bg_db, redis)
                await bg_db.commit()
        except Exception:
            logger.exception("Failed to create notifications for detection %s", detection_id)

    asyncio.create_task(_notify())

    return db_detection


@router.patch("/{detection_id}", response_model=DetectionResponse)
async def update_detection(
    detection_id: UUID,
    detection_update: DetectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza uma detecção (status, infratores, etc)"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found"
        )

    # Atualizar campos
    update_data = detection_update.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(detection, key, value)

    await db.commit()
    await db.refresh(detection)

    return detection


@router.delete("/{detection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_detection(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deleta uma detecção"""
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found"
        )

    await db.delete(detection)
    await db.commit()

    return None


@router.post("/{detection_id}/classify", response_model=DetectionResponse)
async def classify_detection(
    detection_id: UUID,
    classify_data: DetectionClassify,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Classifica a validade de uma detecção (Confirmado/Rejeitado/Indeterminado).

    Permite re-classificar — o usuário pode corrigir uma decisão anterior.
    Voltar para Pendente não é permitido aqui (use PATCH para edição admin).
    """
    result = await db.execute(select(Detection).where(Detection.id == detection_id))
    detection = result.scalar_one_or_none()

    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found",
        )

    detection.status = DetectionStatus(classify_data.status.value)
    detection.classified_at = now_brazil()
    detection.classified_by = current_user.id
    detection.validity_comment = classify_data.validity_comment

    await db.commit()
    await db.refresh(detection)
    return detection


# ==========================================
# Vídeo sob demanda (dispositivos event-driven / Pi relay)
# ==========================================

def _video_rel_path(device_id: str, event_ref: str) -> str:
    return f"videos/{device_id}/{event_ref}.mp4"


def _video_public_url(rel_path: str) -> str:
    if VIDEO_PUBLIC_BASE_URL:
        return f"{VIDEO_PUBLIC_BASE_URL}/uploads/{rel_path}"
    return f"/uploads/{rel_path}"


async def _detection_with_device(db: AsyncSession, detection_id: UUID):
    result = await db.execute(
        select(Detection, Camera.device_id)
        .join(Camera, Detection.camera_id == Camera.id, isouter=True)
        .where(Detection.id == detection_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found",
        )
    return row[0], row[1]


@router.post(
    "/{detection_id}/request-video",
    response_model=DetectionVideoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_detection_video(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Solicita ao dispositivo o clipe de 2min do evento desta detecção.

    O dispositivo (Raspberry Pi) guarda o clipe localmente e só faz o upload
    quando recebe este comando (CMD_VIDEO_CLIP:<event_ref> via esp32-server).
    O mp4 chega de forma assíncrona — acompanhe via GET /{id}/video.
    """
    detection, device_id = await _detection_with_device(db, detection_id)

    if not detection.event_ref or not device_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Detecção sem vídeo disponível (dispositivo não event-driven)",
        )
    if not ESP32_SERVER_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ESP32_SERVER_URL não configurado no backend",
        )

    import httpx

    trigger_url = f"{ESP32_SERVER_URL}/device/{device_id}/trigger"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                trigger_url, json={"cmd": f"CMD_VIDEO_CLIP:{detection.event_ref}"}
            )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("request-video trigger failed (%s): %s", trigger_url, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Falha ao enviar comando ao servidor de dispositivos",
        )

    detection.video_status = "requested"
    detection.video_requested_at = now_brazil()
    await db.commit()

    return DetectionVideoResponse(
        detection_id=detection_id,
        event_ref=detection.event_ref,
        status="requested",
        requested_at=detection.video_requested_at,
    )


@router.get("/{detection_id}/video", response_model=DetectionVideoResponse)
async def get_detection_video(
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Estado do clipe de vídeo da detecção (none/requested/available/unavailable).

    'available' é detectado pela existência do mp4 no volume de uploads
    (o esp32-server salva em videos/<device>/<event_ref>.mp4 — URL
    determinística, sem callback). Pedido sem upload após
    VIDEO_REQUEST_TIMEOUT_S vira 'unavailable' (re-requisitável; se a Pi
    reconectar e entregar depois, volta a 'available').
    """
    detection, device_id = await _detection_with_device(db, detection_id)

    if not detection.event_ref or not device_id:
        return DetectionVideoResponse(detection_id=detection_id, status="none")

    rel_path = _video_rel_path(device_id, detection.event_ref)
    if (CAMERA_UPLOADS_DIR / rel_path).is_file():
        if detection.video_status != "available":
            detection.video_status = "available"
            await db.commit()
        return DetectionVideoResponse(
            detection_id=detection_id,
            event_ref=detection.event_ref,
            status="available",
            video_url=_video_public_url(rel_path),
            requested_at=detection.video_requested_at,
        )

    video_status = detection.video_status or "none"
    if video_status == "available":
        # mp4 sumiu do volume (retenção/limpeza) — refletir a realidade.
        video_status = "unavailable"
    elif video_status == "requested" and detection.video_requested_at is not None:
        if now_brazil() - detection.video_requested_at > timedelta(
            seconds=VIDEO_REQUEST_TIMEOUT_S
        ):
            video_status = "unavailable"

    return DetectionVideoResponse(
        detection_id=detection_id,
        event_ref=detection.event_ref,
        status=video_status,
        requested_at=detection.video_requested_at,
    )
