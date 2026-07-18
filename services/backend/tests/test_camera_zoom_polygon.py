"""Testes dos endpoints de zoom atual e edição de polígono da câmera.

- GET /cameras/{id}/zoom: lê o zoom da telemetria (.health.json) sem chamar a câmera.
- POST /cameras/{id}/polygon: valida, grava pile_zone_polygon e aplica ao vivo
  (push best-effort pro esp32-server para o Pi recarregar por poll).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.endpoints import cameras


# ── Fakes / helpers ──────────────────────────────────────────────────────
class FakeCamera:
    def __init__(self, id=1, device_id="pi-cam-001", camera_type="pi"):
        self.id = id
        self.device_id = device_id
        self.camera_type = camera_type
        self.pile_zone_polygon = None


def _exec_result(value):
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=value)
    return res


def _db_returns(*results):
    queue = list(results)

    async def _execute(*args, **kwargs):
        return queue.pop(0)

    return AsyncMock(side_effect=_execute)


_SQUARE = [[[100, 100], [1100, 100], [1100, 600], [100, 600]]]


# ── _validate_polygon (pura) ─────────────────────────────────────────────
def test_validate_polygon_ok():
    assert cameras._validate_polygon([]) is None  # vazio = limpar
    assert cameras._validate_polygon(_SQUARE) is None
    # múltiplos polígonos
    assert cameras._validate_polygon([_SQUARE[0], _SQUARE[0]]) is None


def test_validate_polygon_rejects():
    assert cameras._validate_polygon([[[0, 0], [1, 1]]]) is not None  # < 3 pontos
    assert cameras._validate_polygon([[[0, 0], [5000, 0], [0, 500]]]) is not None  # fora do frame
    assert cameras._validate_polygon([[[0, 0, 0], [1, 1, 1], [2, 2, 2]]]) is not None  # ponto != [x,y]
    assert cameras._validate_polygon("não é lista") is not None


def test_camera_is_remote_lens():
    assert cameras._camera_is_remote_lens(FakeCamera(camera_type="pi")) is True
    assert cameras._camera_is_remote_lens(FakeCamera(camera_type="esp32")) is False
    # fallback pelo prefixo do device_id quando camera_type é None
    assert cameras._camera_is_remote_lens(FakeCamera(camera_type=None, device_id="esp32_002")) is False
    assert cameras._camera_is_remote_lens(FakeCamera(camera_type=None, device_id="pi-cam-001")) is True


# ── GET /cameras/{id}/zoom ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_zoom_reports_value(client, monkeypatch):
    ac, mock_db = client
    mock_db.execute = _db_returns(_exec_result(FakeCamera()))
    monkeypatch.setattr(
        cameras, "find_health_for_device",
        lambda dev: {"zoom": 0.42, "camera_ok": True, "received_at": "2026-07-18T10:00:00"},
    )
    resp = await ac.get("/api/v1/cameras/1/zoom")
    assert resp.status_code == 200
    body = resp.json()
    assert body["zoom"] == 0.42
    assert body["camera_ok"] is True
    assert body["reported_at"] == "2026-07-18T10:00:00"


@pytest.mark.asyncio
async def test_get_zoom_null_when_no_health(client, monkeypatch):
    ac, mock_db = client
    mock_db.execute = _db_returns(_exec_result(FakeCamera()))
    monkeypatch.setattr(cameras, "find_health_for_device", lambda dev: None)
    resp = await ac.get("/api/v1/cameras/1/zoom")
    assert resp.status_code == 200
    assert resp.json()["zoom"] is None


# ── POST /cameras/{id}/polygon ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_post_polygon_saves_and_pushes(client, monkeypatch):
    ac, mock_db = client
    cam = FakeCamera()
    mock_db.execute = _db_returns(_exec_result(cam))
    push = AsyncMock(return_value=(True, None))
    monkeypatch.setattr(cameras, "_push_polygon_to_device", push)

    resp = await ac.post("/api/v1/cameras/1/polygon", json={"polygon": _SQUARE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["saved"] is True
    assert body["pushed_to_device"] is True
    assert cam.pile_zone_polygon == _SQUARE  # gravado no "banco"
    push.assert_awaited_once()
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_post_polygon_rejects_invalid(client, monkeypatch):
    ac, mock_db = client
    monkeypatch.setattr(cameras, "_push_polygon_to_device", AsyncMock(return_value=(True, None)))
    resp = await ac.post("/api/v1/cameras/1/polygon", json={"polygon": [[[0, 0], [1, 1]]]})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_polygon_empty_clears(client, monkeypatch):
    ac, mock_db = client
    cam = FakeCamera()
    cam.pile_zone_polygon = _SQUARE
    mock_db.execute = _db_returns(_exec_result(cam))
    monkeypatch.setattr(cameras, "_push_polygon_to_device", AsyncMock(return_value=(True, None)))
    resp = await ac.post("/api/v1/cameras/1/polygon", json={"polygon": []})
    assert resp.status_code == 200
    assert cam.pile_zone_polygon is None  # lista vazia limpa o polígono
