"""Tests for notification API endpoints (app.api.v1.endpoints.notifications)."""
import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from tests.conftest import FakeNotification, FakeUser


# ── GET /api/v1/notifications/ ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_notifications(client):
    """Should return notification list with unread_count and total."""
    ac, mock_db = client

    notifs = [FakeNotification(user_id=1), FakeNotification(user_id=1, is_read=True)]

    with patch("app.services.notification_service.get_notifications", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = (notifs, 1, 2)
        response = await ac.get("/api/v1/notifications/")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["unread_count"] == 1
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_list_notifications_with_filter(client):
    """Should pass is_read filter to service."""
    ac, mock_db = client

    with patch("app.services.notification_service.get_notifications", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([], 0, 0)
        response = await ac.get("/api/v1/notifications/?is_read=false&skip=0&limit=10")

    assert response.status_code == 200
    mock_get.assert_awaited_once()
    call_kwargs = mock_get.call_args[1]
    assert call_kwargs["is_read"] is False
    assert call_kwargs["skip"] == 0
    assert call_kwargs["limit"] == 10


@pytest.mark.asyncio
async def test_list_notifications_empty(client):
    """Should return empty list when no notifications."""
    ac, mock_db = client

    with patch("app.services.notification_service.get_notifications", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([], 0, 0)
        response = await ac.get("/api/v1/notifications/")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


# ── GET /api/v1/notifications/summary ────────────────────────────────────

@pytest.mark.asyncio
async def test_get_summary(client):
    """Should return summary data."""
    ac, mock_db = client

    summary = {
        "unread_count": 5,
        "since_last_login": 10,
        "last_login_at": datetime.utcnow(),
        "by_rpa": {"3": 6, "5": 4},
    }

    with patch("app.services.notification_service.get_summary", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = summary
        response = await ac.get("/api/v1/notifications/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["unread_count"] == 5
    assert data["since_last_login"] == 10
    assert data["by_rpa"]["3"] == 6


# ── PATCH /api/v1/notifications/{id}/read ────────────────────────────────

@pytest.mark.asyncio
async def test_mark_as_read_success(client):
    """Should mark notification as read."""
    ac, mock_db = client
    nid = str(uuid.uuid4())

    with patch("app.services.notification_service.mark_as_read", new_callable=AsyncMock) as mock_mark:
        mock_mark.return_value = True
        response = await ac.patch(f"/api/v1/notifications/{nid}/read")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_mark_as_read_not_found(client):
    """Should return 404 if notification not found."""
    ac, mock_db = client
    nid = str(uuid.uuid4())

    with patch("app.services.notification_service.mark_as_read", new_callable=AsyncMock) as mock_mark:
        mock_mark.return_value = False
        response = await ac.patch(f"/api/v1/notifications/{nid}/read")

    assert response.status_code == 404


# ── PATCH /api/v1/notifications/read-all ─────────────────────────────────

@pytest.mark.asyncio
async def test_mark_all_as_read(client):
    """Should mark all notifications as read."""
    ac, mock_db = client

    with patch("app.services.notification_service.mark_all_as_read", new_callable=AsyncMock) as mock_mark:
        mock_mark.return_value = 8
        response = await ac.patch("/api/v1/notifications/read-all")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["count"] == 8


# ── Model & Schema Tests ────────────────────────────────────────────────

def test_notification_type_enum():
    """NotificationType should have expected values."""
    from app.models.notification import NotificationType
    assert NotificationType.NOVA_OCORRENCIA.value == "nova_ocorrencia"
    assert NotificationType.LOTE_OCORRENCIAS.value == "lote_ocorrencias"


def test_notification_response_schema():
    """NotificationResponse should validate from ORM attributes."""
    from app.schemas.notification import NotificationResponse

    nid = uuid.uuid4()
    data = {
        "id": nid,
        "user_id": 1,
        "detection_id": uuid.uuid4(),
        "type": "nova_ocorrencia",
        "title": "Test",
        "message": "Test msg",
        "metadata_": {"key": "value"},
        "is_read": False,
        "created_at": datetime.utcnow(),
    }
    schema = NotificationResponse(**data)
    assert schema.id == nid
    assert schema.is_read is False
    assert schema.metadata_["key"] == "value"


def test_notification_summary_schema():
    """NotificationSummaryResponse should validate."""
    from app.schemas.notification import NotificationSummaryResponse

    data = {
        "unread_count": 5,
        "since_last_login": 10,
        "last_login_at": None,
        "by_rpa": {"3": 6},
    }
    schema = NotificationSummaryResponse(**data)
    assert schema.unread_count == 5
    assert schema.last_login_at is None
    assert schema.by_rpa["3"] == 6


def test_notification_list_response_schema():
    """NotificationListResponse should validate."""
    from app.schemas.notification import NotificationListResponse, NotificationResponse

    item = NotificationResponse(
        id=uuid.uuid4(),
        user_id=1,
        type="nova_ocorrencia",
        title="T",
        message="M",
        is_read=False,
        created_at=datetime.utcnow(),
    )
    schema = NotificationListResponse(items=[item], unread_count=1, total=1)
    assert schema.total == 1
    assert len(schema.items) == 1


# ── Redis module tests ───────────────────────────────────────────────────

def test_get_redis_raises_when_not_initialized():
    """get_redis should raise RuntimeError before init."""
    from app.core import redis as redis_mod

    original = redis_mod._redis
    redis_mod._redis = None
    try:
        with pytest.raises(RuntimeError, match="Redis not initialized"):
            redis_mod.get_redis()
    finally:
        redis_mod._redis = original


@pytest.mark.asyncio
async def test_init_and_close_redis():
    """init_redis / close_redis lifecycle."""
    from app.core import redis as redis_mod

    original = redis_mod._redis

    with patch("app.core.redis.aioredis") as mock_aioredis:
        mock_client = AsyncMock()
        mock_aioredis.from_url.return_value = mock_client

        result = await redis_mod.init_redis()
        assert result is mock_client
        assert redis_mod._redis is mock_client

        # get_redis should now work
        assert redis_mod.get_redis() is mock_client

        await redis_mod.close_redis()
        mock_client.close.assert_awaited_once()
        assert redis_mod._redis is None

    redis_mod._redis = original
