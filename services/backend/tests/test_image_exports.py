"""Tests for image export endpoints + runner helpers."""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.core.timezone import now_brazil
from app.models.image_export import ImageExport
from app.services import image_export_runner

BRT = ZoneInfo("America/Sao_Paulo")


# ── Helpers ──────────────────────────────────────────────────────────────

def _camera_mock(camera_id=1, device_id="test-cam-001", name="Cam Boa Viagem"):
    cam = MagicMock()
    cam.id = camera_id
    cam.device_id = device_id
    cam.name = name
    return cam


def _make_db_execute(*results):
    queue = list(results)

    async def _execute(*args, **kwargs):
        return queue.pop(0)

    return AsyncMock(side_effect=_execute)


def _exec_result(value):
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=value)
    return res


def _exec_scalar_one(value):
    res = MagicMock()
    res.scalar_one = MagicMock(return_value=value)
    res.scalar_one_or_none = MagicMock(return_value=value)
    return res


def _exec_scalars(values):
    res = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=values)
    res.scalars = MagicMock(return_value=scalars)
    return res


# ── Pure helper tests ────────────────────────────────────────────────────

def test_iter_days_brt_single_day():
    start = datetime(2026, 5, 20, 9, 0, tzinfo=BRT)
    end = datetime(2026, 5, 20, 18, 0, tzinfo=BRT)
    days = list(image_export_runner._iter_days_brt(start, end))
    assert days == [start.date()]


def test_iter_days_brt_across_days():
    start = datetime(2026, 5, 20, 22, 0, tzinfo=BRT)
    end = datetime(2026, 5, 22, 3, 0, tzinfo=BRT)
    days = list(image_export_runner._iter_days_brt(start, end))
    assert days == [
        start.date(),
        (start + timedelta(days=1)).date(),
        end.date(),
    ]


def test_filename_in_window_inside():
    start = datetime(2026, 5, 20, 10, 0, tzinfo=BRT)
    end = datetime(2026, 5, 20, 12, 0, tzinfo=BRT)
    assert image_export_runner._filename_in_window(
        "2026-05-20_11-30-15.jpg", start, end,
    )


def test_filename_in_window_outside():
    start = datetime(2026, 5, 20, 10, 0, tzinfo=BRT)
    end = datetime(2026, 5, 20, 12, 0, tzinfo=BRT)
    assert not image_export_runner._filename_in_window(
        "2026-05-20_09-30-15.jpg", start, end,
    )
    assert not image_export_runner._filename_in_window(
        "2026-05-20_12-30-15.jpg", start, end,
    )


def test_filename_in_window_unparseable_kept():
    # Defensive: unknown naming gets included rather than silently dropped.
    start = datetime(2026, 5, 20, 10, 0, tzinfo=BRT)
    end = datetime(2026, 5, 20, 12, 0, tzinfo=BRT)
    assert image_export_runner._filename_in_window("weird-name.jpg", start, end)


# ── Schema validation tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_export_rejects_range_over_max_days(client):
    ac, _ = client
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=10)
    response = await ac.post(
        "/api/v1/exports/",
        json={
            "camera_id": 1,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "include_occurrences": True,
            "include_non_occurrences": True,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_export_rejects_end_before_start(client):
    ac, _ = client
    start = datetime.now(timezone.utc)
    end = start - timedelta(hours=1)
    response = await ac.post(
        "/api/v1/exports/",
        json={
            "camera_id": 1,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "include_occurrences": True,
            "include_non_occurrences": True,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_export_rejects_neither_image_type(client):
    ac, _ = client
    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=1)
    response = await ac.post(
        "/api/v1/exports/",
        json={
            "camera_id": 1,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "include_occurrences": False,
            "include_non_occurrences": False,
        },
    )
    assert response.status_code == 422


# ── Endpoint tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_export_404_when_camera_missing(client):
    ac, mock_db = client
    mock_db.get = AsyncMock(return_value=None)
    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=1)
    response = await ac.post(
        "/api/v1/exports/",
        json={
            "camera_id": 999,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "include_occurrences": True,
            "include_non_occurrences": True,
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_export_422_when_camera_has_no_device_id(client):
    ac, mock_db = client
    mock_db.get = AsyncMock(return_value=_camera_mock(device_id=None))
    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=1)
    response = await ac.post(
        "/api/v1/exports/",
        json={
            "camera_id": 1,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "include_occurrences": True,
            "include_non_occurrences": True,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_export_success_schedules_runner(client, fake_user):
    ac, mock_db = client
    mock_db.get = AsyncMock(return_value=_camera_mock())
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    export_id = uuid.uuid4()
    saved_camera = _camera_mock()

    async def fake_refresh(obj):
        obj.id = export_id
        obj.created_at = now_brazil()
        obj.updated_at = now_brazil()

    mock_db.refresh = AsyncMock(side_effect=fake_refresh)

    eager_export = MagicMock(spec=ImageExport)
    eager_export.id = export_id
    eager_export.user_id = fake_user.id
    eager_export.camera_id = 1
    eager_export.start_at = datetime.now(timezone.utc)
    eager_export.end_at = eager_export.start_at + timedelta(hours=1)
    eager_export.include_occurrences = True
    eager_export.include_non_occurrences = True
    eager_export.status = "pending"
    eager_export.progress = 0
    eager_export.total_images = None
    eager_export.download_url = None
    eager_export.expires_at = None
    eager_export.error_message = None
    eager_export.started_at = None
    eager_export.completed_at = None
    eager_export.created_at = now_brazil()
    eager_export.updated_at = now_brazil()
    eager_export.camera = saved_camera

    mock_db.execute = _make_db_execute(_exec_scalar_one(eager_export))

    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=1)
    with patch.object(image_export_runner, "schedule_export") as sched:
        response = await ac.post(
            "/api/v1/exports/",
            json={
                "camera_id": 1,
                "start_at": start.isoformat(),
                "end_at": end.isoformat(),
                "include_occurrences": True,
                "include_non_occurrences": True,
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["camera_device_id"] == "test-cam-001"
    sched.assert_called_once_with(export_id)


@pytest.mark.asyncio
async def test_list_exports_filters_by_current_user(client, fake_user):
    ac, mock_db = client

    exp = MagicMock(spec=ImageExport)
    exp.id = uuid.uuid4()
    exp.user_id = fake_user.id
    exp.camera_id = 1
    exp.start_at = datetime.now(timezone.utc)
    exp.end_at = exp.start_at + timedelta(hours=2)
    exp.include_occurrences = True
    exp.include_non_occurrences = True
    exp.status = "ready"
    exp.progress = 100
    exp.total_images = 42
    exp.download_url = "https://example.s3/x.zip"
    exp.expires_at = now_brazil() + timedelta(hours=12)
    exp.error_message = None
    exp.started_at = now_brazil() - timedelta(minutes=5)
    exp.completed_at = now_brazil()
    exp.created_at = now_brazil() - timedelta(minutes=10)
    exp.updated_at = now_brazil()
    exp.camera = _camera_mock()
    exp.s3_key = f"exports/{fake_user.id}/{exp.id}.zip"

    mock_db.execute = _make_db_execute(_exec_scalars([exp]))

    response = await ac.get("/api/v1/exports/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "ready"
    assert body[0]["total_images"] == 42


@pytest.mark.asyncio
async def test_get_export_404_when_belongs_to_other_user(client, fake_user):
    ac, mock_db = client

    exp = MagicMock(spec=ImageExport)
    exp.id = uuid.uuid4()
    exp.user_id = fake_user.id + 99  # different user
    exp.camera = _camera_mock()
    mock_db.execute = _make_db_execute(_exec_result(exp))

    response = await ac.get(f"/api/v1/exports/{exp.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_export_removes_s3_object(client, fake_user):
    ac, mock_db = client

    exp = MagicMock(spec=ImageExport)
    exp.id = uuid.uuid4()
    exp.user_id = fake_user.id
    exp.s3_key = f"exports/{fake_user.id}/{exp.id}.zip"
    exp.status = "ready"
    exp.download_url = "https://example.s3/x.zip"
    mock_db.execute = _make_db_execute(_exec_result(exp))
    mock_db.commit = AsyncMock()

    from app.services import s3 as s3_service

    with patch.object(s3_service, "s3_enabled", return_value=True), \
         patch.object(s3_service, "get_s3_client", return_value=MagicMock()) as mock_client, \
         patch.object(s3_service, "delete_object") as mock_delete:
        response = await ac.delete(f"/api/v1/exports/{exp.id}")

    assert response.status_code == 204
    mock_delete.assert_called_once()
    assert exp.status == "expired"
    assert exp.download_url is None


# ── Runner integration: _build_zip with local files only ─────────────────

def _make_image(path: Path, content: bytes = b"\xff\xd8\xff\xe0fake-jpeg"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_build_zip_packs_local_files_per_day(tmp_path, monkeypatch):
    """End-to-end build of a ZIP using only local files (S3 disabled)."""
    uploads = tmp_path / "uploads"
    device_id = "test-cam-001"
    # Day 1 (2026-05-20): one ocorrencia + one sem_ocorrencia
    _make_image(
        uploads / device_id / "ocorrencias" / "2026" / "05" / "20" / "2026-05-20_10-15-30.jpg",
    )
    _make_image(
        uploads / device_id / "sem_ocorrencia" / "2026" / "05" / "20" / "2026-05-20_10-16-00.jpg",
    )
    # Day 2 (2026-05-21): only ocorrencia
    _make_image(
        uploads / device_id / "ocorrencias" / "2026" / "05" / "21" / "2026-05-21_09-00-00.jpg",
    )
    # Out-of-window file (after the end_at time) — must be excluded
    _make_image(
        uploads / device_id / "ocorrencias" / "2026" / "05" / "21" / "2026-05-21_20-00-00.jpg",
    )

    monkeypatch.setattr(
        "app.services.image_export_runner.settings.EXPORT_UPLOADS_DIR",
        str(uploads),
    )
    monkeypatch.setattr(
        "app.services.image_export_runner.s3_service.s3_enabled",
        lambda: False,
    )

    export = MagicMock(spec=ImageExport)
    export.id = uuid.uuid4()
    export.camera_id = 1
    export.start_at = datetime(2026, 5, 20, 9, 0, tzinfo=BRT)
    export.end_at = datetime(2026, 5, 21, 18, 0, tzinfo=BRT)
    export.include_occurrences = True
    export.include_non_occurrences = True

    progress_called = []

    def progress_cb(pct, total):
        progress_called.append((pct, total))

    zip_path, manifest = image_export_runner._build_zip(
        export, device_id, tmp_path / "work", progress_cb,
    )

    import json
    import zipfile

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())

    assert "2026-05-20/ocorrencias/2026-05-20_10-15-30.jpg" in names
    assert "2026-05-20/sem_ocorrencia/2026-05-20_10-16-00.jpg" in names
    assert "2026-05-21/ocorrencias/2026-05-21_09-00-00.jpg" in names
    # File outside the window must NOT appear
    assert "2026-05-21/ocorrencias/2026-05-21_20-00-00.jpg" not in names
    assert "manifest.json" in names

    assert manifest["days"]["2026-05-20"]["ocorrencias"] == 1
    assert manifest["days"]["2026-05-20"]["sem_ocorrencia"] == 1
    assert manifest["days"]["2026-05-21"]["ocorrencias"] == 1
    assert manifest["days"]["2026-05-21"]["sem_ocorrencia"] == 0
    assert manifest["total_images"] == 3
    assert progress_called[-1][1] == 3  # last progress reports total=3


def test_build_zip_only_occurrences(tmp_path, monkeypatch):
    """When user opts out of sem_ocorrencia, only ocorrencias are included."""
    uploads = tmp_path / "uploads"
    device_id = "test-cam-001"
    _make_image(
        uploads / device_id / "ocorrencias" / "2026" / "05" / "20" / "2026-05-20_10-15-30.jpg",
    )
    _make_image(
        uploads / device_id / "sem_ocorrencia" / "2026" / "05" / "20" / "2026-05-20_10-16-00.jpg",
    )

    monkeypatch.setattr(
        "app.services.image_export_runner.settings.EXPORT_UPLOADS_DIR",
        str(uploads),
    )
    monkeypatch.setattr(
        "app.services.image_export_runner.s3_service.s3_enabled",
        lambda: False,
    )

    export = MagicMock(spec=ImageExport)
    export.id = uuid.uuid4()
    export.camera_id = 1
    export.start_at = datetime(2026, 5, 20, 0, 0, tzinfo=BRT)
    export.end_at = datetime(2026, 5, 20, 23, 59, 59, tzinfo=BRT)
    export.include_occurrences = True
    export.include_non_occurrences = False

    zip_path, manifest = image_export_runner._build_zip(
        export, device_id, tmp_path / "work", lambda *a: None,
    )

    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())

    assert "2026-05-20/ocorrencias/2026-05-20_10-15-30.jpg" in names
    assert "2026-05-20/sem_ocorrencia/2026-05-20_10-16-00.jpg" not in names
    assert manifest["days"]["2026-05-20"]["sem_ocorrencia"] == 0
    assert manifest["days"]["2026-05-20"]["ocorrencias"] == 1
