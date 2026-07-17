"""Tests for the DEGRADED health alert in app.services.offline_monitor.

Two layers:
  - evaluate_degraded / _has_undervoltage: pure functions, no I/O.
  - run_offline_check episode machine for degraded conditions, driven with an
    in-memory Redis fake so multi-tick transitions (alert → cooldown → recovery)
    are exercised faithfully.
"""
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import app.services.offline_monitor as om


# ----------------------------------------------------------- pure functions
def test_has_undervoltage_parses_bits():
    f = om._has_undervoltage
    assert f("0x50005") is True     # bit 0 setado (subtensão AGORA)
    assert f("0x1") is True
    assert f("0x50000") is False    # só bit 16 (ocorreu-desde-boot) -> não alerta
    assert f("0x0") is False
    assert f(0) is False
    assert f(None) is False
    assert f("") is False
    assert f("lixo") is False


def test_evaluate_degraded_camera_stale_capture():
    # motion on + 30min sem captura -> câmera parada
    d = om.evaluate_degraded({"motion_mode": "on", "last_capture_age_s": 1800})
    assert "camera_sem_imagem" in d


def test_evaluate_degraded_off_mode_ignores_stale_capture():
    # off com intervalo longo: idade alta é NORMAL, não pode alertar
    d = om.evaluate_degraded({"motion_mode": "off", "last_capture_age_s": 1800})
    assert "camera_sem_imagem" not in d


def test_evaluate_degraded_camera_ok_false_without_age():
    # nunca capturou (idade ausente) + camera_ok=false -> ruim em qualquer modo
    d = om.evaluate_degraded({"last_capture_age_s": None, "camera_ok": False})
    assert "camera_sem_imagem" in d


def test_evaluate_degraded_fresh_capture_is_clean():
    d = om.evaluate_degraded({"last_capture_age_s": 3, "camera_ok": True,
                              "rtsp_buffer_ok": True, "disk_low": False,
                              "throttled": "0x0"})
    assert d == {}


def test_evaluate_degraded_rtsp_and_undervoltage_and_disk():
    d = om.evaluate_degraded({
        "last_capture_age_s": 2, "rtsp_buffer_ok": False,
        "throttled": "0x50005", "disk_low": True, "disk_free_mb": 30,
    })
    assert set(d) == {"rtsp_travado", "subtensao", "disco_baixo"}
    assert "30 MB" in d["disco_baixo"]


def test_evaluate_degraded_no_events_is_opt_in():
    health = {"last_capture_age_s": 2, "last_event_age_s": 3 * 3600}
    # default (0 = desligado): não alerta
    with patch.object(om.settings, "CAMERA_HEALTH_NO_EVENTS_HOURS", 0):
        assert "sem_eventos" not in om.evaluate_degraded(health)
    # habilitado (2h): 3h sem evento -> alerta
    with patch.object(om.settings, "CAMERA_HEALTH_NO_EVENTS_HOURS", 2):
        assert "sem_eventos" in om.evaluate_degraded(health)


# ------------------------------------------------------------ integration
class FakeCamera:
    def __init__(self, device_id="pi-cam-001", name="Via Mangue III-2"):
        self.device_id = device_id
        self.name = name
        self.bairro = "Boa Viagem"
        self.rpa = "6"
        self.is_active = True


class _FakeSessionCtx:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


def _make_db(cameras):
    db = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = cameras
    result = MagicMock()
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    return db


class FakeRedis:
    """In-memory async Redis (subset used by the monitor). TTLs are ignored;
    state persists across run_offline_check calls so multi-tick transitions work.
    tick_lock always succeeds (simula o TTL expirando entre ciclos)."""

    def __init__(self):
        self.store: dict = {}

    async def set(self, key, val, ex=None, nx=None):
        if key.endswith("tick_lock"):
            return True
        if nx and key in self.store:
            return None
        self.store[key] = val
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


def _fresh():
    return (Path("x.jpg"), time.time() - 60)  # 1min -> online


def _run(redis, cameras, *, health):
    db = _make_db(cameras)
    with patch.object(om, "get_redis", return_value=redis), \
         patch.object(om, "AsyncSessionLocal", return_value=_FakeSessionCtx(db)), \
         patch.object(om, "find_latest_image_for_device", return_value=_fresh()), \
         patch.object(om, "find_last_keepalive_for_device", return_value=time.time() - 60), \
         patch.object(om, "find_health_for_device", return_value=health), \
         patch.object(om, "send_email", return_value=True) as send_mock, \
         patch.object(om.settings, "OFFLINE_ALERT_RECIPIENTS", "ops@saira.com"), \
         patch.object(om.settings, "CAMERA_OFFLINE_THRESHOLD_SECONDS", 3600):
        asyncio.run(om.run_offline_check())
    return send_mock


_RTSP_BAD = {"last_capture_age_s": 2, "rtsp_buffer_ok": False}
_RTSP_OK = {"last_capture_age_s": 2, "rtsp_buffer_ok": True}


def test_degraded_debounced_first_tick_silent_second_alerts():
    """Histerese: o 1º avistamento só marca 'seen'; o alerta sai no 2º ciclo."""
    redis = FakeRedis()
    send1 = _run(redis, [FakeCamera()], health=_RTSP_BAD)   # 1º tick: seen, sem e-mail
    send1.assert_not_called()
    send2 = _run(redis, [FakeCamera()], health=_RTSP_BAD)   # 2º tick: confirma -> alerta
    send2.assert_called_once()
    assert "RTSP" in send2.call_args.kwargs["subject"]


def test_degraded_single_tick_flap_is_suppressed():
    """Condição que aparece 1 ciclo e some não pode gerar e-mail nenhum."""
    redis = FakeRedis()
    _run(redis, [FakeCamera()], health=_RTSP_BAD)          # avistou (seen)
    send = _run(redis, [FakeCamera()], health=_RTSP_OK)    # sumiu -> descarta seen
    send.assert_not_called()
    # e mesmo reaparecendo depois, volta a exigir 2 ciclos
    send_a = _run(redis, [FakeCamera()], health=_RTSP_BAD)
    send_a.assert_not_called()


def test_degraded_within_cooldown_is_silent():
    redis = FakeRedis()
    _run(redis, [FakeCamera()], health=_RTSP_BAD)          # seen
    _run(redis, [FakeCamera()], health=_RTSP_BAD)          # alerta
    send = _run(redis, [FakeCamera()], health=_RTSP_BAD)   # 3º: cooldown -> silêncio
    send.assert_not_called()


def test_degraded_recovers_sends_recovery_once():
    redis = FakeRedis()
    _run(redis, [FakeCamera()], health=_RTSP_BAD)          # seen
    _run(redis, [FakeCamera()], health=_RTSP_BAD)          # alerta (ativo)
    send = _run(redis, [FakeCamera()], health=_RTSP_OK)    # normaliza -> recuperação
    send.assert_called_once()
    assert "normalizado" in send.call_args.kwargs["subject"]
    send3 = _run(redis, [FakeCamera()], health=_RTSP_OK)   # já normal -> silêncio
    send3.assert_not_called()


def test_no_health_reported_is_silent():
    redis = FakeRedis()
    send = _run(redis, [FakeCamera()], health=None)  # esp32 (sem .health.json)
    send.assert_not_called()


def test_multiple_conditions_alert_independently():
    redis = FakeRedis()
    health = {"last_capture_age_s": 2, "rtsp_buffer_ok": False,
              "disk_low": True, "disk_free_mb": 10}
    _run(redis, [FakeCamera()], health=health)             # seen (ambas)
    send = _run(redis, [FakeCamera()], health=health)      # confirma -> 2 e-mails
    assert send.call_count == 2  # rtsp_travado + disco_baixo, um e-mail cada
