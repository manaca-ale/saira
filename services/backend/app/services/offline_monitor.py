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
from app.utils.uploads import find_latest_image_for_device

logger = logging.getLogger(__name__)
BRT = ZoneInfo("America/Sao_Paulo")

_scheduler: AsyncIOScheduler | None = None

_TICK_LOCK_KEY = "saira:camera_offline:tick_lock"
_ACTIVE_KEY = "saira:camera_offline:active:{device_id}"      # set enquanto em episódio offline
_COOLDOWN_KEY = "saira:camera_offline:cooldown:{device_id}"  # rate-limit do (re)alerta


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
            latest = find_latest_image_for_device(cam.device_id)
            if latest is None:
                age: float | None = None
                last_iso: str | None = None
                offline = True
            else:
                _, mtime = latest
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
