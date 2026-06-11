"""Tests for app.services.offline_monitor (camera offline alert).

Exercises the Redis-backed state machine without touching the filesystem,
DB, or Resend: offline → alert, cooldown → silent, recovery → email,
no-recipients → skip, tick-lock lost → skip.
"""
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class FakeCamera:
    def __init__(self, device_id="esp32_001", name="Imbiribeira"):
        self.device_id = device_id
        self.name = name
        self.bairro = "Imbiribeira"
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


def _make_redis(*, tick_lock=True, active_get=None, cooldown_nx=True, delete_count=0):
    """Redis double whose set/get/delete are routed by key prefix."""
    redis = AsyncMock()

    async def fake_set(key, val, ex=None, nx=None):
        if key.endswith("tick_lock"):
            return tick_lock
        if ":cooldown:" in key:
            return cooldown_nx
        return True  # plain active_key set

    redis.set = AsyncMock(side_effect=fake_set)
    redis.get = AsyncMock(return_value=active_get)
    redis.delete = AsyncMock(return_value=delete_count)
    return redis


def _run(redis, cameras, *, latest):
    """Drive run_offline_check with patched deps; return the send_email mock."""
    import app.services.offline_monitor as om

    db = _make_db(cameras)
    with patch.object(om, "get_redis", return_value=redis), \
         patch.object(om, "AsyncSessionLocal", return_value=_FakeSessionCtx(db)), \
         patch.object(om, "find_latest_image_for_device", return_value=latest), \
         patch.object(om, "send_email", return_value=True) as send_mock, \
         patch.object(om.settings, "OFFLINE_ALERT_RECIPIENTS", "ops@saira.com"), \
         patch.object(om.settings, "CAMERA_OFFLINE_THRESHOLD_SECONDS", 3600):
        asyncio.run(om.run_offline_check())
    return send_mock


def _stale():
    return (Path("x.jpg"), time.time() - 2 * 3600)  # 2h old → offline


def _fresh():
    return (Path("x.jpg"), time.time() - 60)        # 1min old → online


def test_offline_first_time_sends_alert():
    redis = _make_redis(active_get=None, cooldown_nx=True)
    send = _run(redis, [FakeCamera()], latest=_stale())
    send.assert_called_once()
    assert "sem upload" in send.call_args.kwargs["subject"]


def test_no_image_at_all_sends_alert():
    redis = _make_redis(active_get=None, cooldown_nx=True)
    send = _run(redis, [FakeCamera()], latest=None)
    send.assert_called_once()


def test_offline_within_cooldown_is_silent():
    # already in episode (active_get set) AND cooldown still held (nx -> None)
    redis = _make_redis(active_get="2026-06-09T10:00:00", cooldown_nx=None)
    send = _run(redis, [FakeCamera()], latest=_stale())
    send.assert_not_called()


def test_recovery_sends_email_once():
    # camera back online and active_key existed (delete returns 1)
    redis = _make_redis(active_get=None, delete_count=1)
    send = _run(redis, [FakeCamera()], latest=_fresh())
    send.assert_called_once()
    assert "voltou" in send.call_args.kwargs["subject"]


def test_online_no_prior_episode_is_silent():
    redis = _make_redis(delete_count=0)
    send = _run(redis, [FakeCamera()], latest=_fresh())
    send.assert_not_called()


def test_tick_lock_lost_skips_cycle():
    redis = _make_redis(tick_lock=None)
    send = _run(redis, [FakeCamera()], latest=_stale())
    send.assert_not_called()


def test_no_recipients_skips(monkeypatch):
    import app.services.offline_monitor as om
    redis = _make_redis()
    db = _make_db([FakeCamera()])
    with patch.object(om, "get_redis", return_value=redis), \
         patch.object(om, "AsyncSessionLocal", return_value=_FakeSessionCtx(db)), \
         patch.object(om, "find_latest_image_for_device", return_value=_stale()), \
         patch.object(om, "send_email", return_value=True) as send, \
         patch.object(om.settings, "OFFLINE_ALERT_RECIPIENTS", ""), \
         patch.object(om.settings, "BILLING_REPORT_RECIPIENTS", ""):
        asyncio.run(om.run_offline_check())
    send.assert_not_called()
