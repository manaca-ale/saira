"""Tests for app.services.notification_service."""
import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from tests.conftest import FakeUser, FakeDetection, FakeNotification


# ── on_new_detection ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_new_detection_creates_notifications_for_active_users(mock_db, fake_detection, fake_redis):
    """Should create one Notification per active user and publish to Redis."""
    from app.services.notification_service import on_new_detection

    user1 = FakeUser(id=1, email="a@test.com")
    user2 = FakeUser(id=2, email="b@test.com")

    # Mock db.execute to return active users
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [user1, user2]
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_db.execute = AsyncMock(return_value=result_mock)

    await on_new_detection(fake_detection, mock_db, fake_redis)

    # Should bulk add notifications
    mock_db.add_all.assert_called_once()
    added = mock_db.add_all.call_args[0][0]
    assert len(added) == 2

    # Should flush
    mock_db.flush.assert_awaited_once()

    # Should publish to per-user channels + global channel
    assert fake_redis.publish.await_count == 3  # user1 + user2 + global

    # Verify published data is valid JSON
    first_call_data = fake_redis.publish.call_args_list[0][0][1]
    parsed = json.loads(first_call_data)
    assert parsed["type"] == "new_detection"
    assert "RPA" in parsed["title"]
    assert parsed["detection_id"] == str(fake_detection.id)


@pytest.mark.asyncio
async def test_on_new_detection_no_users(mock_db, fake_detection, fake_redis):
    """Should return early if no active users."""
    from app.services.notification_service import on_new_detection

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_db.execute = AsyncMock(return_value=result_mock)

    await on_new_detection(fake_detection, mock_db, fake_redis)

    mock_db.add_all.assert_not_called()
    fake_redis.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_new_detection_redis_failure_does_not_raise(mock_db, fake_detection, fake_redis):
    """Redis publish failure should be logged, not raised."""
    from app.services.notification_service import on_new_detection

    user1 = FakeUser(id=1)
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [user1]
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_db.execute = AsyncMock(return_value=result_mock)

    fake_redis.publish = AsyncMock(side_effect=ConnectionError("Redis down"))

    # Should NOT raise
    await on_new_detection(fake_detection, mock_db, fake_redis)

    # Notifications should still have been added to DB
    mock_db.add_all.assert_called_once()


@pytest.mark.asyncio
async def test_on_new_detection_notification_fields(mock_db, fake_redis):
    """Notifications should have correct title, message, and metadata."""
    from app.services.notification_service import on_new_detection

    detection = FakeDetection(rpa="5", bairro="Torre", logradouro="Av Norte")
    user = FakeUser(id=10)

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [user]
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_db.execute = AsyncMock(return_value=result_mock)

    await on_new_detection(detection, mock_db, fake_redis)

    notif = mock_db.add_all.call_args[0][0][0]
    assert notif.user_id == 10
    assert notif.detection_id == detection.id
    assert "RPA 5" in notif.title
    assert "Torre" in notif.message
    assert "Av Norte" in notif.message
    assert notif.metadata_["rpa"] == "5"
    assert notif.metadata_["bairro"] == "Torre"
    # is_read defaults at DB level, so in-memory it's None before flush
    assert notif.is_read in (False, None)


# ── get_notifications ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_notifications_returns_items_and_counts(mock_db):
    """Should return (items, unread_count, total)."""
    from app.services.notification_service import get_notifications

    notifs = [FakeNotification(user_id=1, is_read=False), FakeNotification(user_id=1, is_read=True)]

    # First call: count (total)
    # Second call: unread count
    # Third call: items
    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            mock.scalar.return_value = 2  # total
        elif call_count == 2:
            mock.scalar.return_value = 1  # unread
        else:
            mock.scalars.return_value = MagicMock(all=MagicMock(return_value=notifs))
        return mock

    mock_db.execute = AsyncMock(side_effect=side_effect)

    items, unread_count, total = await get_notifications(user_id=1, db=mock_db)

    assert total == 2
    assert unread_count == 1
    assert len(items) == 2


# ── mark_as_read ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_as_read_found(mock_db):
    """Should set is_read=True and return True."""
    from app.services.notification_service import mark_as_read

    notif = FakeNotification(user_id=1, is_read=False)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = notif
    mock_db.execute = AsyncMock(return_value=result_mock)

    nid = notif.id
    found = await mark_as_read(nid, user_id=1, db=mock_db)

    assert found is True
    assert notif.is_read is True


@pytest.mark.asyncio
async def test_mark_as_read_not_found(mock_db):
    """Should return False if notification doesn't exist."""
    from app.services.notification_service import mark_as_read

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=result_mock)

    found = await mark_as_read(uuid.uuid4(), user_id=1, db=mock_db)
    assert found is False


# ── mark_all_as_read ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_all_as_read(mock_db):
    """Should return rowcount."""
    from app.services.notification_service import mark_all_as_read

    result_mock = MagicMock()
    result_mock.rowcount = 5
    mock_db.execute = AsyncMock(return_value=result_mock)

    count = await mark_all_as_read(user_id=1, db=mock_db)
    assert count == 5


# ── get_summary ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_summary_with_last_login(mock_db):
    """Should return summary with correct structure."""
    from app.services.notification_service import get_summary

    user = FakeUser(id=1, last_login_at=datetime.utcnow() - timedelta(hours=2))

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            mock.scalar.return_value = 3  # unread
        elif call_count == 2:
            mock.scalar.return_value = 7  # since last login
        else:
            mock.all.return_value = [("3", 4), ("5", 3)]  # by_rpa
        return mock

    mock_db.execute = AsyncMock(side_effect=side_effect)

    result = await get_summary(user, mock_db)

    assert result["unread_count"] == 3
    assert result["since_last_login"] == 7
    assert result["last_login_at"] == user.last_login_at
    assert result["by_rpa"] == {"3": 4, "5": 3}


@pytest.mark.asyncio
async def test_get_summary_without_last_login(mock_db):
    """Should use 24h fallback when user has no last_login_at."""
    from app.services.notification_service import get_summary

    user = FakeUser(id=1, last_login_at=None)

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            mock.scalar.return_value = 0
        elif call_count == 2:
            mock.scalar.return_value = 2
        else:
            mock.all.return_value = []
        return mock

    mock_db.execute = AsyncMock(side_effect=side_effect)

    result = await get_summary(user, mock_db)

    assert result["unread_count"] == 0
    assert result["since_last_login"] == 2
    assert result["last_login_at"] is None
    assert result["by_rpa"] == {}
