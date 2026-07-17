"""APScheduler job that emails an alert when an active camera stops uploading.

Incident 2026-06-09: esp32_001/002 ficaram ~24h sem enviar (crédito 4G pré-pago
acabou) e só foi percebido por inspeção manual. Este monitor fecha esse buraco de
visibilidade: a cada CAMERA_OFFLINE_CHECK_INTERVAL_MINUTES varre as câmeras ativas,
acha o upload mais recente no volume de uploads (montado RO do esp32-server) e, se
passar de CAMERA_OFFLINE_THRESHOLD_SECONDS sem imagem nova, dispara um e-mail (Resend).

Multi-worker safe: um tick-lock no Redis garante um único runner por ciclo entre os
processos uvicorn; o estado de episódio (active/cooldown) também vive no Redis, então o
alerta não é re-enviado a cada ciclo nem duplicado entre workers. Manda 1 alerta ao
entrar em offline, re-alerta no máx. a cada CAMERA_OFFLINE_REALERT_SECONDS enquanto
permanecer, e um e-mail de recuperação quando volta. Erros são logados, nunca propagam.

Reaproveita o mesmo canal/credenciais do billing (email_service / Resend), mas é um
alerta operacional separado (OFFLINE_ALERT_RECIPIENTS, fallback BILLING_REPORT_RECIPIENTS).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.redis import get_redis
from app.core.timezone import now_brazil
from app.models.camera import Camera
from app.models.camera_heartbeat import CameraHeartbeat
from app.services.email_service import parse_recipients, send_email
from app.utils.uploads import (
    find_health_for_device,
    find_latest_image_for_device,
    find_last_keepalive_for_device,
)

logger = logging.getLogger(__name__)
BRT = ZoneInfo("America/Sao_Paulo")

_scheduler: AsyncIOScheduler | None = None

_TICK_LOCK_KEY = "saira:camera_offline:tick_lock"
_ACTIVE_KEY = "saira:camera_offline:active:{device_id}"      # set enquanto em episódio offline
_COOLDOWN_KEY = "saira:camera_offline:cooldown:{device_id}"  # rate-limit do (re)alerta

# Alerta de saúde DEGRADADA — episódio POR (device, condição).
_HEALTH_ACTIVE_KEY = "saira:camera_health:active:{device_id}:{cond}"
_HEALTH_COOLDOWN_KEY = "saira:camera_health:cooldown:{device_id}:{cond}"
_HEALTH_SEEN_KEY = "saira:camera_health:seen:{device_id}:{cond}"  # debounce 1º avistamento
_HEALTH_ACTIVE_TTL = 7 * 24 * 3600  # hygiene: expira se o episódio ficar preso

# Título (emoji, rótulo) e causa provável por condição. Iterado também na
# varredura de recuperação, então lista TODAS as condições possíveis.
_DEGRADED_TITLES: dict[str, tuple[str, str]] = {
    "camera_sem_imagem": ("📷", "câmera sem gerar imagem"),
    "rtsp_travado": ("🎥", "stream RTSP travado"),
    "subtensao": ("🔌", "subtensão / brown-out"),
    "disco_baixo": ("💾", "disco quase cheio"),
    "sem_eventos": ("🕳️", "sem eventos no período esperado"),
}
_DEGRADED_CAUSE: dict[str, str] = {
    "camera_sem_imagem": (
        "A câmera está online (o dispositivo responde) mas parou de entregar "
        "frames. Verifique energia e o cabo/rede da câmera; pode ter havido "
        "brown-out (subtensão) — considere um power-cycle físico do local."
    ),
    "rtsp_travado": (
        "O buffer RTSP congelou (a última imagem fica presa numa cena velha). "
        "Reiniciar o buffer costuma resolver (comando CMD_RESTART_BUFFER)."
    ),
    "subtensao": (
        "A alimentação está entregando tensão insuficiente (subtensão). Troque "
        "a fonte/cabo — o brown-out pode travar a captura e a escrita de "
        "configuração na câmera até um power-cycle físico."
    ),
    "disco_baixo": (
        "O espaço em disco do dispositivo está no piso. A poda de emergência já "
        "roda automaticamente, mas convém verificar o cartão SD."
    ),
    "sem_eventos": (
        "A câmera está online mas não registra ocorrências há mais que o período "
        "esperado. Verifique o enquadramento/zona e se a cena está obstruída."
    ),
}


def _recipients() -> list[str]:
    raw = settings.OFFLINE_ALERT_RECIPIENTS or settings.BILLING_REPORT_RECIPIENTS
    return parse_recipients(raw)


def _format_age(seconds: float | None) -> str:
    if seconds is None:
        return "sem nenhum upload registrado"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours and minutes:
        return f"{hours}h {minutes}min"
    if hours:
        return f"{hours}h"
    return f"{minutes}min"


def _cam_label(cam: Camera) -> str:
    bits = [cam.name or "(sem nome)"]
    where = " / ".join(p for p in (cam.bairro, cam.rpa and f"RPA {cam.rpa}") if p)
    if where:
        bits.append(where)
    return " — ".join(bits)


def _send_offline_email(recipients: list[str], cam: Camera, age: float | None, last_iso: str | None) -> None:
    age_txt = _format_age(age)
    last_txt = last_iso or "—"
    subject = f"⚠️ SAIRA: câmera {cam.name} ({cam.device_id}) sem upload há {age_txt}"
    html = (
        f"<h2>⚠️ Câmera offline</h2>"
        f"<p>A câmera <strong>{cam.name}</strong> (<code>{cam.device_id}</code>) está "
        f"<strong>sem enviar imagens há {age_txt}</strong>.</p>"
        f"<ul>"
        f"<li><strong>Câmera:</strong> {_cam_label(cam)}</li>"
        f"<li><strong>device_id:</strong> {cam.device_id}</li>"
        f"<li><strong>Último upload:</strong> {last_txt}</li>"
        f"<li><strong>Threshold:</strong> {settings.CAMERA_OFFLINE_THRESHOLD_SECONDS}s</li>"
        f"</ul>"
        f"<p>Causa mais provável em câmera 4G: crédito/franquia de dados pré-pago esgotado. "
        f"Verifique também energia/roteador no local.</p>"
    )
    text = (
        f"SAIRA: câmera {cam.name} ({cam.device_id}) sem upload há {age_txt}.\n"
        f"Último upload: {last_txt}. Threshold: {settings.CAMERA_OFFLINE_THRESHOLD_SECONDS}s.\n"
        f"Causa provável (4G pré-pago): crédito de dados esgotado."
    )
    ok = send_email(to_addrs=recipients, subject=subject, html_body=html, text_body=text)
    logger.warning(
        "offline_monitor: ALERT offline device=%s age=%s last=%s sent=%s recipients=%d",
        cam.device_id, age_txt, last_txt, ok, len(recipients),
    )


def _send_recovery_email(recipients: list[str], cam: Camera, last_iso: str | None) -> None:
    subject = f"✅ SAIRA: câmera {cam.name} ({cam.device_id}) voltou a enviar"
    html = (
        f"<h2>✅ Câmera recuperada</h2>"
        f"<p>A câmera <strong>{cam.name}</strong> (<code>{cam.device_id}</code>) "
        f"voltou a enviar imagens.</p>"
        f"<ul><li><strong>Câmera:</strong> {_cam_label(cam)}</li>"
        f"<li><strong>Último upload:</strong> {last_iso or '—'}</li></ul>"
    )
    text = f"SAIRA: câmera {cam.name} ({cam.device_id}) voltou a enviar. Último upload: {last_iso or '—'}."
    ok = send_email(to_addrs=recipients, subject=subject, html_body=html, text_body=text)
    logger.info(
        "offline_monitor: RECOVERY device=%s last=%s sent=%s", cam.device_id, last_iso, ok,
    )


def _has_undervoltage(throttled) -> bool:
    """True se o bit de subtensão ATUAL (0x1) estiver setado no vcgencmd
    get_throttled (ex.: '0x50005'). O bit 16 (0x10000)='ocorreu desde o boot' é
    persistente e NÃO dispara alerta — viraria ruído para sempre após um único
    pico. Aceita '0x..', decimal ou None; entrada inválida => False."""
    if not throttled:
        return False
    try:
        val = int(str(throttled).strip(), 0)
    except (ValueError, TypeError):
        return False
    return bool(val & 0x1)


def evaluate_degraded(health: dict) -> dict[str, str]:
    """Condições de saúde DEGRADADA a partir do .health.json do dispositivo.
    Devolve {condição: detalhe pt-BR} só das ACIONÁVEIS e com histerese natural
    (idade/limiar), evitando flaps. Função pura (testável sem I/O)."""
    out: dict[str, str] = {}
    if not isinstance(health, dict):
        return out

    # Sem gerar imagem: idade da última captura acima do limiar (histerese
    # embutida). SÓ vale nos modos on/shadow (captura contínua): em off com
    # intervalo longo (ex.: 30min) a idade oscila até o intervalo e um limiar
    # de 15min viraria falso positivo. Fallback camera_ok=false só quando o
    # device NUNCA capturou (idade ausente) — aí é ruim em qualquer modo.
    cap_age = health.get("last_capture_age_s")
    motion_mode = health.get("motion_mode")
    stale_s = settings.CAMERA_HEALTH_STALE_CAPTURE_SECONDS
    if (
        motion_mode in ("on", "shadow")
        and isinstance(cap_age, (int, float))
        and cap_age > stale_s
    ):
        out["camera_sem_imagem"] = f"sem capturar frame novo há {_format_age(cap_age)}"
    elif cap_age is None and health.get("camera_ok") is False:
        out["camera_sem_imagem"] = "a câmera não responde (camera_ok=false)"

    if health.get("rtsp_buffer_ok") is False:
        out["rtsp_travado"] = "buffer RTSP parado (imagem congelada numa cena velha)"

    if _has_undervoltage(health.get("throttled")):
        out["subtensao"] = f"com subtensão detectada (throttled={health.get('throttled')})"

    if health.get("disk_low") is True:
        free = health.get("disk_free_mb")
        out["disco_baixo"] = (
            f"com disco baixo ({free} MB livres)" if free is not None else "com disco baixo"
        )

    # Opt-in: sem eventos por período esperado (default off).
    no_ev_h = settings.CAMERA_HEALTH_NO_EVENTS_HOURS
    if no_ev_h > 0:
        evt_age = health.get("last_event_age_s")
        if isinstance(evt_age, (int, float)) and evt_age > no_ev_h * 3600:
            out["sem_eventos"] = f"sem registrar ocorrência há {_format_age(evt_age)}"

    return out


def _send_degraded_email(recipients: list[str], cam: Camera, cond: str, detail: str) -> None:
    emoji, titulo = _DEGRADED_TITLES.get(cond, ("⚠️", cond))
    causa = _DEGRADED_CAUSE.get(cond, "")
    subject = f"{emoji} SAIRA: câmera {cam.name} ({cam.device_id}) — {titulo}"
    html = (
        f"<h2>{emoji} Câmera degradada — {titulo}</h2>"
        f"<p>A câmera <strong>{cam.name}</strong> (<code>{cam.device_id}</code>) está "
        f"<strong>{detail}</strong>.</p>"
        f"<ul>"
        f"<li><strong>Câmera:</strong> {_cam_label(cam)}</li>"
        f"<li><strong>device_id:</strong> {cam.device_id}</li>"
        f"<li><strong>Condição:</strong> {titulo}</li>"
        f"</ul>"
        + (f"<p>{causa}</p>" if causa else "")
    )
    text = f"SAIRA: câmera {cam.name} ({cam.device_id}) {detail}.\n{causa}"
    ok = send_email(to_addrs=recipients, subject=subject, html_body=html, text_body=text)
    logger.warning(
        "health_monitor: DEGRADED device=%s cond=%s detail=%s sent=%s recipients=%d",
        cam.device_id, cond, detail, ok, len(recipients),
    )


def _send_degraded_recovery_email(recipients: list[str], cam: Camera, cond: str) -> None:
    _emoji, titulo = _DEGRADED_TITLES.get(cond, ("✅", cond))
    subject = f"✅ SAIRA: câmera {cam.name} ({cam.device_id}) — {titulo} normalizado"
    html = (
        f"<h2>✅ Câmera normalizada</h2>"
        f"<p>A condição <strong>{titulo}</strong> da câmera "
        f"<strong>{cam.name}</strong> (<code>{cam.device_id}</code>) foi resolvida.</p>"
        f"<ul><li><strong>Câmera:</strong> {_cam_label(cam)}</li></ul>"
    )
    text = f"SAIRA: câmera {cam.name} ({cam.device_id}) — {titulo} normalizado."
    ok = send_email(to_addrs=recipients, subject=subject, html_body=html, text_body=text)
    logger.info(
        "health_monitor: RECOVERY device=%s cond=%s sent=%s", cam.device_id, cond, ok,
    )


async def _handle_degraded(redis, recipients: list[str], cam: Camera) -> None:
    """Avalia a saúde degradada de UMA câmera viva e gere o episódio por
    condição no Redis (1 alerta ao entrar, re-alerta com cooldown, e-mail de
    recuperação ao normalizar). Só dispositivos event-driven reportam health."""
    health = find_health_for_device(cam.device_id)
    if not health:
        return
    active = evaluate_degraded(health)
    realert = settings.CAMERA_HEALTH_REALERT_SECONDS
    debounce = settings.CAMERA_HEALTH_DEBOUNCE_ENABLED
    # 'seen' vive ~2,5 ciclos: sobrevive a UM tick para o ciclo seguinte
    # confirmar, mas some se a condição não repetir (flap descartado).
    seen_ttl = max(60, int(settings.CAMERA_OFFLINE_CHECK_INTERVAL_MINUTES * 60 * 2.5))

    for cond, detail in active.items():
        active_key = _HEALTH_ACTIVE_KEY.format(device_id=cam.device_id, cond=cond)
        cooldown_key = _HEALTH_COOLDOWN_KEY.format(device_id=cam.device_id, cond=cond)
        seen_key = _HEALTH_SEEN_KEY.format(device_id=cam.device_id, cond=cond)
        if not await redis.get(active_key):
            # Debounce: 1º avistamento só marca 'seen'; só vira episódio ATIVO se
            # a condição persistir no ciclo seguinte (histerese p/ flaps).
            if debounce and not await redis.get(seen_key):
                await redis.set(seen_key, "1", ex=seen_ttl)
                continue
            await redis.set(active_key, "1", ex=_HEALTH_ACTIVE_TTL)
            await redis.delete(seen_key)
        # (re)alerta só com o cooldown livre (1º alerta ou após REALERT)
        if await redis.set(cooldown_key, "1", ex=realert, nx=True):
            _send_degraded_email(recipients, cam, cond, detail)

    # Condições que não estão mais ativas: descarta o 'seen' pendente (flap) e,
    # se havia episódio confirmado, envia recuperação uma vez.
    for cond in _DEGRADED_TITLES:
        if cond in active:
            continue
        await redis.delete(_HEALTH_SEEN_KEY.format(device_id=cam.device_id, cond=cond))
        active_key = _HEALTH_ACTIVE_KEY.format(device_id=cam.device_id, cond=cond)
        if await redis.delete(active_key):
            await redis.delete(
                _HEALTH_COOLDOWN_KEY.format(device_id=cam.device_id, cond=cond)
            )
            _send_degraded_recovery_email(recipients, cam, cond)


async def run_offline_check() -> None:
    """Varre câmeras ativas e (re)alerta as que estão sem upload. Nunca levanta."""
    try:
        redis = get_redis()
    except Exception:
        logger.exception("offline_monitor: redis indisponível — pulando ciclo")
        return

    # Único runner por ciclo entre os workers uvicorn. TTL < intervalo p/ liberar no próximo tick.
    interval_s = max(60, settings.CAMERA_OFFLINE_CHECK_INTERVAL_MINUTES * 60)
    tick_ttl = max(30, min(interval_s // 2, 300))
    try:
        if not await redis.set(_TICK_LOCK_KEY, "1", ex=tick_ttl, nx=True):
            return
    except Exception:
        logger.exception("offline_monitor: falha no tick-lock — pulando ciclo")
        return

    recipients = _recipients()
    can_email = bool(recipients)
    if not can_email:
        logger.warning(
            "offline_monitor: sem destinatários (OFFLINE_ALERT_RECIPIENTS) — "
            "registrando heartbeat mas sem enviar e-mail"
        )

    threshold = settings.CAMERA_OFFLINE_THRESHOLD_SECONDS
    realert = settings.CAMERA_OFFLINE_REALERT_SECONDS

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Camera).where(Camera.is_active.is_(True), Camera.device_id.isnot(None))
            )
            cameras = result.scalars().all()
    except Exception:
        logger.exception("offline_monitor: falha ao listar câmeras")
        return

    now = time.time()
    checked_at = now_brazil()
    # Série temporal de conectividade (indicador I1). 1 linha por câmera por ciclo.
    heartbeats: list[tuple[int, str | None, bool]] = []
    for cam in cameras:
        try:
            # "Vivo" = última imagem OU keepalive recente. Aditivo: câmeras que
            # sobem imagem (esp32) seguem pelo mtime da imagem; a Pi event-driven
            # (que só manda frame em evento/sob demanda) fica online pelo keepalive.
            latest = find_latest_image_for_device(cam.device_id)
            img_mtime = latest[1] if latest else None
            ka_mtime = find_last_keepalive_for_device(cam.device_id)
            mtime = max((m for m in (img_mtime, ka_mtime) if m is not None), default=None)
            if mtime is None:
                age: float | None = None
                last_iso: str | None = None
                offline = True
            else:
                age = now - mtime
                last_iso = datetime.fromtimestamp(mtime, BRT).strftime("%Y-%m-%d %H:%M:%S %Z")
                offline = age > threshold

            cam_id = getattr(cam, "id", None)
            if cam_id is not None:
                heartbeats.append((cam_id, cam.device_id, not offline))

            if not can_email:
                continue

            active_key = _ACTIVE_KEY.format(device_id=cam.device_id)
            cooldown_key = _COOLDOWN_KEY.format(device_id=cam.device_id)

            if offline:
                was_active = await redis.get(active_key)
                if not was_active:
                    await redis.set(active_key, datetime.fromtimestamp(now, BRT).isoformat())
                # (re)alerta só se o cooldown estiver livre (1º alerta ou após REALERT)
                if await redis.set(cooldown_key, "1", ex=realert, nx=True):
                    _send_offline_email(recipients, cam, age, last_iso)
            else:
                # estava offline e voltou: só o worker que remove o active_key envia recovery
                removed = await redis.delete(active_key)
                if removed:
                    await redis.delete(cooldown_key)
                    _send_recovery_email(recipients, cam, last_iso)

            # Câmera viva (keepalive fresco): avalia saúde DEGRADADA a partir do
            # .health.json. Só quando NÃO offline (senão o alerta de offline já
            # cobre, e o health estaria velho de qualquer forma).
            if not offline and settings.CAMERA_HEALTH_MONITOR_ENABLED:
                await _handle_degraded(redis, recipients, cam)
        except Exception:
            logger.exception("offline_monitor: erro avaliando device=%s", cam.device_id)

    # Persiste os heartbeats do ciclo (best-effort; nunca derruba o monitor).
    if heartbeats:
        try:
            async with AsyncSessionLocal() as db:
                db.add_all(
                    CameraHeartbeat(
                        checked_at=checked_at,
                        camera_id=cam_id,
                        device_id=dev_id,
                        is_online=online,
                    )
                    for cam_id, dev_id, online in heartbeats
                )
                await db.commit()
        except Exception:
            logger.exception("offline_monitor: falha ao gravar camera_heartbeats")


def start_offline_monitor() -> None:
    global _scheduler
    if not settings.CAMERA_OFFLINE_MONITOR_ENABLED:
        logger.info("offline_monitor: disabled (CAMERA_OFFLINE_MONITOR_ENABLED=false)")
        return
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone=BRT)
    _scheduler.add_job(
        run_offline_check,
        trigger=IntervalTrigger(minutes=settings.CAMERA_OFFLINE_CHECK_INTERVAL_MINUTES),
        id="camera_offline_monitor",
        name="Camera offline monitor (email alert)",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "offline_monitor: started interval=%dmin threshold=%ds realert=%ds recipients=%s",
        settings.CAMERA_OFFLINE_CHECK_INTERVAL_MINUTES,
        settings.CAMERA_OFFLINE_THRESHOLD_SECONDS,
        settings.CAMERA_OFFLINE_REALERT_SECONDS,
        settings.OFFLINE_ALERT_RECIPIENTS or settings.BILLING_REPORT_RECIPIENTS,
    )


def stop_offline_monitor() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("offline_monitor: error during shutdown")
    _scheduler = None
