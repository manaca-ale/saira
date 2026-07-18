import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from fastapi import APIRouter, Body, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from geoalchemy2.functions import ST_SetSRID, ST_MakePoint
from app.api.deps import get_db, get_current_user
from app.core.redis import get_redis, init_redis
from app.models.user import User
from app.models.camera import Camera
from app.utils.uploads import (
    UPLOADS_ROOT,
    IMAGE_EXTENSIONS,
    find_latest_image_for_device,
    find_health_for_device,
)
from app.schemas.camera import (
    CameraBgsubConfigUpdate,
    CameraCreate,
    CameraLatestImageResponse,
    CameraLiveSessionResponse,
    CameraPolygonResponse,
    CameraPolygonUpdate,
    CameraResponse,
    CameraUpdate,
    CameraZoomResponse,
)

router = APIRouter()

CAMERA_SORTABLE_FIELDS: dict[str, Any] = {
    "name":        Camera.name,
    "device_id":   Camera.device_id,
    "camera_type": Camera.camera_type,
    "bairro":      Camera.bairro,
    "rpa":         Camera.rpa,
    "is_active":   Camera.is_active,
    "created_at":  Camera.created_at,
}
CAMERA_DEFAULT_SORT = "created_at"

UPLOAD_PUBLIC_BASE_URL = os.getenv("CAMERA_UPLOAD_PUBLIC_BASE_URL", "").rstrip("/")
# esp32-server base URL — usado para enfileirar CMD_SNAPSHOT (imagem sob demanda)
# no poll do dispositivo (Pi event-driven, que não manda mais heartbeat-imagem).
ESP32_SERVER_URL = os.getenv("ESP32_SERVER_URL", "http://esp32-server:5000").rstrip("/")
# Token admin para o esp32-server /device/<id>/config (push do polígono ao vivo).
# Vazio nesta implantação (o esp32-server só exige o header se ele mesmo tiver um
# token configurado — ver server.py set_device_config).
ESP32_ADMIN_TOKEN = os.getenv("ESP32_ADMIN_TOKEN", "")
# Frame de referência em que a zona de interesse (pile_zone_polygon) é desenhada
# (igual ao worker BGSUB e ao motion_gate do Pi). Coordenadas em pixels absolutos.
POLYGON_REF_W = 1280
POLYGON_REF_H = 720

# ----- modo ao vivo (instalação em campo) --------------------------------------
# Teto DURO da sessão, ancorado no start e nunca renovado.
LIVE_SESSION_MAX_S = int(os.getenv("LIVE_SESSION_MAX_S", "600"))
# Lease curto no dispositivo (dead-man's switch): se o browser/backend/rede
# morrerem, a Pi para de subir frames sozinha em <= LIVE_LEASE_S. É a única
# camada do guard de 4G que não depende de nada mais estar vivo.
LIVE_LEASE_S = int(os.getenv("LIVE_LEASE_S", "60"))
LIVE_SESSION_KEY_PREFIX = "saira:camera:live:"


async def get_redis_client():
    try:
        return get_redis()
    except RuntimeError:
        return await init_redis()


def _camera_supports_live(camera: Camera) -> bool:
    """Fonte da verdade do modo ao vivo: só câmeras tipadas explicitamente como
    'pi'. FAIL-CLOSED de propósito — camera_type NULL (tipo desconhecido) não
    ganha live. Errar para o lado aberto seria um botão que não funciona e 4G
    do dispositivo torrado à toa."""
    return (camera.camera_type or "").strip().lower() == "pi"


def _live_session_key(camera_id: int) -> str:
    return f"{LIVE_SESSION_KEY_PREFIX}{camera_id}"

# Backwards-compatible alias kept for existing call sites in this module.
# Upload-tree scanning now lives in app.utils.uploads (shared with the offline monitor).
_find_latest_image_for_device = find_latest_image_for_device


def _build_upload_image_url(relative_path: str) -> str:
    normalized = relative_path.lstrip("/").replace("\\", "/")
    if UPLOAD_PUBLIC_BASE_URL:
        return f"{UPLOAD_PUBLIC_BASE_URL}/uploads/{normalized}"
    return f"/uploads/{normalized}"


@router.get("/", response_model=List[CameraResponse])
async def get_cameras(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    rpa: Optional[str] = None,
    is_active: Optional[bool] = None,
    sort_by: Optional[str] = Query(None, description="Campo para ordenação"),
    sort_order: Optional[str] = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista câmeras com filtros e paginação"""
    query = select(Camera)

    filters = []
    if rpa:
        filters.append(Camera.rpa == rpa)
    if is_active is not None:
        filters.append(Camera.is_active == is_active)

    if filters:
        query = query.where(and_(*filters))

    col = CAMERA_SORTABLE_FIELDS.get(sort_by or CAMERA_DEFAULT_SORT, Camera.created_at)
    order = col.asc() if sort_order == "asc" else col.desc()
    query = query.offset(skip).limit(limit).order_by(order)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Busca uma câmera por ID"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found"
        )

    return camera


@router.get("/{camera_id}/latest-image", response_model=CameraLatestImageResponse)
async def get_camera_latest_image(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna a imagem mais recente na pasta da câmera (uploads/<device_id>)."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found",
        )

    device_id = (camera.device_id or "").strip() or None
    if not device_id:
        return CameraLatestImageResponse(camera_id=camera_id, device_id=None)

    latest = _find_latest_image_for_device(device_id)
    if not latest:
        return CameraLatestImageResponse(camera_id=camera_id, device_id=device_id)

    latest_path, latest_mtime = latest
    try:
        relative = latest_path.relative_to(UPLOADS_ROOT).as_posix()
    except ValueError:
        relative = f"{device_id}/{latest_path.name}"

    captured_at = datetime.fromtimestamp(latest_mtime, tz=timezone.utc)
    return CameraLatestImageResponse(
        camera_id=camera_id,
        device_id=device_id,
        image_url=_build_upload_image_url(relative),
        captured_at=captured_at,
        file_path=relative,
    )


@router.post("/{camera_id}/request-snapshot")
async def request_camera_snapshot(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pede um frame atual sob demanda (abrir painel / "atualizar agora").

    Enfileira CMD_SNAPSHOT no poll do dispositivo via esp32-server /trigger; o
    dispositivo sobe 1 frame e o frontend o lê em seguida via /latest-image.
    Best-effort: dispositivos que não tratam o comando (ex.: esp32, que já
    mandam imagem no timer) simplesmente o ignoram.
    """
    import httpx

    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    device_id = (camera.device_id or "").strip() or None
    if not device_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera has no device_id")

    url = f"{ESP32_SERVER_URL}/device/{device_id}/trigger"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json={"cmd": "CMD_SNAPSHOT"})
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"esp32-server indisponível: {exc}",
        )
    return {"status": "requested", "camera_id": camera_id, "device_id": device_id}


async def _enqueue_device_cmd(camera_id: int, db: AsyncSession, cmd: str) -> str:
    """Resolve o device_id da câmera e enfileira um comando no poll do
    dispositivo via esp32-server /trigger. Retorna o device_id."""
    import httpx

    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    device_id = (camera.device_id or "").strip() or None
    if not device_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera has no device_id")

    url = f"{ESP32_SERVER_URL}/device/{device_id}/trigger"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json={"cmd": cmd})
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"esp32-server indisponível: {exc}",
        )
    return device_id


@router.post("/{camera_id}/zoom")
async def set_camera_zoom(
    camera_id: int,
    zoom: float = Body(..., embed=True, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ajusta o zoom óptico (0 = aberto, 1 = aproximado) — só dispositivos com
    lente motorizada (Pi/Intelbras) reagem. Enfileira CMD_ZOOM:<valor>; a câmera
    aplica em ~2-4s e sobe um frame novo (visível via /latest-image)."""
    device_id = await _enqueue_device_cmd(camera_id, db, f"CMD_ZOOM:{zoom:.4f}")
    return {"status": "requested", "camera_id": camera_id, "device_id": device_id, "zoom": zoom}


@router.post("/{camera_id}/autofocus")
async def camera_autofocus(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dispara o autofoco da lente motorizada (best-effort)."""
    device_id = await _enqueue_device_cmd(camera_id, db, "CMD_AUTOFOCUS")
    return {"status": "requested", "camera_id": camera_id, "device_id": device_id}


@router.get("/{camera_id}/zoom", response_model=CameraZoomResponse)
async def get_camera_zoom(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Zoom óptico ATUAL da lente, lido da telemetria de saúde que o Pi reporta
    (`.health.json` no volume compartilhado — não chama a câmera). `zoom` é None
    quando o dispositivo ainda não reportou ou não tem lente motorizada."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    device_id = (camera.device_id or "").strip() or None
    zoom = None
    camera_ok = None
    reported_at = None
    if device_id:
        health = find_health_for_device(device_id)
        if health:
            raw = health.get("zoom")
            if raw is not None:
                try:
                    zoom = float(raw)
                except (TypeError, ValueError):
                    zoom = None
            camera_ok = health.get("camera_ok")
            reported_at = health.get("received_at") or health.get("ts")
    return CameraZoomResponse(
        camera_id=camera_id,
        device_id=device_id,
        zoom=zoom,
        camera_ok=camera_ok,
        reported_at=reported_at,
    )


def _camera_is_remote_lens(camera: Camera) -> bool:
    """Espelha o cameraSupportsRemoteControl do frontend: True para câmeras com
    lente/agente remoto (Pi/Intelbras). Decide se empurramos o polígono pro
    esp32-server (hot-reload no Pi); câmeras esp32 aplicam via worker (DB)."""
    t = (camera.camera_type or "").strip().lower()
    if t:
        return t != "esp32"
    d = (camera.device_id or "").strip().lower()
    return bool(d) and not d.startswith("esp32")


def _validate_polygon(polygon: Any) -> Optional[str]:
    """Valida a zona de interesse (pile_zone_polygon). Retorna a mensagem de erro
    ou None. Espelha o motion_gate do Pi: aninhamento triplo, cada polígono com
    >= 3 pontos [x, y] dentro do frame de referência. Lista vazia = limpar."""
    if not isinstance(polygon, list):
        return "polygon deve ser uma lista de polígonos"
    for poly in polygon:
        if not isinstance(poly, list) or len(poly) < 3:
            return "cada polígono precisa de pelo menos 3 pontos [x, y]"
        for pt in poly:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                return "cada ponto deve ser [x, y]"
            x, y = pt
            if not (0 <= x <= POLYGON_REF_W and 0 <= y <= POLYGON_REF_H):
                return (
                    f"ponto fora do frame de referência "
                    f"{POLYGON_REF_W}x{POLYGON_REF_H}: {pt}"
                )
    return None


async def _push_polygon_to_device(device_id: str, polygon: list) -> tuple[bool, Optional[str]]:
    """Empurra o pile_zone_polygon pro esp32-server (POST /device/<id>/config) para
    o Pi recarregar por poll (~60s). Best-effort: retorna (ok, detail). Polígono
    vazio => value vazio, que o esp32-server interpreta como remover a chave."""
    import httpx

    url = f"{ESP32_SERVER_URL}/device/{device_id}/config"
    headers = {}
    if ESP32_ADMIN_TOKEN:
        headers["X-Admin-Token"] = ESP32_ADMIN_TOKEN
    value = json.dumps(polygon, separators=(",", ":")) if polygon else ""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json={"pile_zone_polygon": value}, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        return False, f"esp32-server indisponível: {exc}"
    return True, None


@router.post("/{camera_id}/polygon", response_model=CameraPolygonResponse)
async def set_camera_polygon(
    camera_id: int,
    payload: CameraPolygonUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Grava a zona de interesse (pile_zone_polygon) no banco e a aplica AO VIVO:
    empurra pro esp32-server para o Pi recarregar por poll; câmeras esp32 aplicam
    pelo worker BGSUB (relê a máscara por assinatura, sem restart). Ref 1280x720."""
    polygon = payload.polygon
    err = _validate_polygon(polygon)
    if err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err)

    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    camera.pile_zone_polygon = polygon or None
    await db.commit()

    device_id = (camera.device_id or "").strip() or None
    pushed = False
    if device_id and _camera_is_remote_lens(camera):
        pushed, push_err = await _push_polygon_to_device(device_id, polygon)
        detail = "aplicado no dispositivo (recarrega em ~60s)" if pushed else push_err
    else:
        detail = "salvo — o worker de detecção aplica na próxima detecção"
    return CameraPolygonResponse(
        camera_id=camera_id,
        device_id=device_id,
        saved=True,
        pushed_to_device=pushed,
        detail=detail,
    )


# ----- modo ao vivo -----------------------------------------------------------
# O dispositivo SEMPRE recebe o mesmo `CMD_LIVE:{LIVE_LEASE_S}`, nunca o tempo
# restante. Isso é deliberado: o esp32-server deduplica comandos PENDENTES
# (_push_sse_cmd), então uma string estável colapsa renovações repetidas numa só
# enquanto o device estiver offline. Com string variável (ex.: o remaining
# decrescendo) cada comando seria distinto, a fila encheria até COMMAND_QUEUE_DEPTH
# e o servidor passaria a DESCARTAR EM SILÊNCIO todo o resto (CMD_SNAPSHOT,
# CMD_ZOOM, CMD_RESTART_AGENT). O teto real da sessão é do backend; o dispositivo
# só precisa conhecer o lease.
async def _live_cmd(camera_id: int, db: AsyncSession, seconds: int) -> str:
    return await _enqueue_device_cmd(camera_id, db, f"CMD_LIVE:{seconds}")


def _live_response(
    camera_id: int, device_id: str, session: dict, now: float
) -> CameraLiveSessionResponse:
    return CameraLiveSessionResponse(
        camera_id=camera_id,
        device_id=device_id,
        status="live",
        expires_at=datetime.fromtimestamp(session["expires_at"], tz=timezone.utc),
        hard_deadline=datetime.fromtimestamp(session["hard_deadline"], tz=timezone.utc),
        remaining_s=max(0, int(session["hard_deadline"] - now)),
        lease_s=LIVE_LEASE_S,
        # O frontend renova nesse ritmo — 1/3 do lease dá 3 tentativas de folga
        # antes do dispositivo se apagar, absorvendo jitter de entrega do comando.
        renew_after_s=max(5, LIVE_LEASE_S // 3),
    )


@router.post("/{camera_id}/live/start", response_model=CameraLiveSessionResponse)
async def start_camera_live(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis_client),
):
    """Abre uma sessão de modo ao vivo (~1 fps) para instalação em campo.

    O dispositivo sobe frames SEM event_id (não dispara worker/Gemini) enquanto o
    lease estiver válido. A sessão morre por três caminhos independentes: o
    operador fecha (stop), o teto duro de LIVE_SESSION_MAX_S estoura (renew → 409),
    ou o lease do dispositivo expira sozinho se tudo mais morrer.
    """
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    if not _camera_supports_live(camera):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Câmera não suporta modo ao vivo (camera_type != 'pi')",
        )

    now = time.time()
    hard_deadline = now + LIVE_SESSION_MAX_S
    session = {
        "started_at": now,
        "expires_at": min(now + LIVE_LEASE_S, hard_deadline),
        "hard_deadline": hard_deadline,
        "user_id": current_user.id,
    }
    device_id = await _live_cmd(camera_id, db, LIVE_LEASE_S)
    session["device_id"] = device_id
    await redis.setex(
        _live_session_key(camera_id),
        max(1, math.ceil(hard_deadline - now)),
        json.dumps(session),
    )
    return _live_response(camera_id, device_id, session, now)


@router.post("/{camera_id}/live/renew", response_model=CameraLiveSessionResponse)
async def renew_camera_live(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis_client),
):
    """Renova o lease do dispositivo enquanto o operador estiver presente.

    409 quando o teto duro estoura — `hard_deadline` é ancorado no start e nunca
    se move, então a sessão não vira uma janela deslizante infinita. Reabrir exige
    um /live/start novo (ação deliberada do operador).
    """
    key = _live_session_key(camera_id)
    raw = await redis.get(key)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sessão ao vivo não encontrada"
        )
    session = json.loads(raw)

    now = time.time()
    if now >= session["hard_deadline"]:
        await redis.delete(key)
        try:
            await _live_cmd(camera_id, db, 0)  # para o dispositivo já, sem esperar o lease
        except HTTPException:
            pass  # o lease expira sozinho; o teto não pode falhar por causa do device
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sessão ao vivo atingiu o tempo máximo",
        )

    session["expires_at"] = min(now + LIVE_LEASE_S, session["hard_deadline"])
    device_id = await _live_cmd(camera_id, db, LIVE_LEASE_S)
    session["device_id"] = device_id
    await redis.setex(
        key, max(1, math.ceil(session["hard_deadline"] - now)), json.dumps(session)
    )
    return _live_response(camera_id, device_id, session, now)


@router.post("/{camera_id}/live/stop")
async def stop_camera_live(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis_client),
):
    """Encerra a sessão. Idempotente: 200 mesmo sem sessão aberta.

    Nunca falha por causa do esp32-server — se o comando de parada não sair, o
    lease do dispositivo o apaga em <= LIVE_LEASE_S de qualquer forma. Um stop que
    dá erro deixaria o frontend achando que ainda está ao vivo.
    """
    await redis.delete(_live_session_key(camera_id))
    try:
        device_id = await _live_cmd(camera_id, db, 0)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_502_BAD_GATEWAY:
            return {
                "status": "stopped",
                "camera_id": camera_id,
                "device_id": None,
                "detail": "esp32-server indisponível; o lease do dispositivo expira sozinho",
            }
        raise
    return {"status": "stopped", "camera_id": camera_id, "device_id": device_id}


@router.post("/", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def create_camera(
    camera_in: CameraCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria uma nova câmera"""
    # Criar geometria PostGIS
    db_camera = Camera(
        name=camera_in.name,
        device_id=camera_in.device_id,
        camera_type=camera_in.camera_type,
        logradouro=camera_in.logradouro,
        bairro=camera_in.bairro,
        rpa=camera_in.rpa,
        latitude=camera_in.latitude,
        longitude=camera_in.longitude,
        rtsp_url=camera_in.rtsp_url,
        capture_interval_seconds=camera_in.capture_interval_seconds,
        is_active=camera_in.is_active
    )

    # O trigger no banco irá criar automaticamente o campo geom

    db.add(db_camera)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        detail = str(getattr(exc, "orig", exc)).lower()
        if "device_id" in detail and "unique" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="device_id already registered"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="could not create camera"
        )
    await db.refresh(db_camera)

    return db_camera


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: int,
    camera_update: CameraUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza uma câmera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found"
        )

    # Atualizar campos
    update_data = camera_update.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(camera, key, value)

    # O trigger no banco irá atualizar automaticamente o campo geom se lat/lon mudarem

    await db.commit()
    await db.refresh(camera)

    return camera


@router.patch("/{camera_id}/bgsub_config", response_model=CameraResponse)
async def update_camera_bgsub_config(
    camera_id: int,
    payload: CameraBgsubConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atualiza só os campos BGSUB de tuning (lr_fast/slow, threshold, etc).

    Todos NULL = câmera cai pros env globais (BGSUB_LR_FAST etc).
    Endpoint dedicado pra simplicar uso (admin via curl/CLI) e isolar
    auditabilidade da config do filtro.
    """
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(camera, key, value)

    await db.commit()
    await db.refresh(camera)
    return camera


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deleta uma câmera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found"
        )

    await db.delete(camera)
    await db.commit()

    return None
