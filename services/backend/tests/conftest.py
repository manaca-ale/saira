"""Shared test fixtures for notification system tests."""
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.core.timezone import now_brazil


# ── Fake ORM objects ─────────────────────────────────────────────────────
class FakeUser:
    """Mimics app.models.user.User for tests."""
    def __init__(self, id=1, email="test@saira.com", is_active=True, last_login_at=None):
        self.id = id
        self.email = email
        self.name = "Test User"
        self.phone = "81999990000"
        self.secretaria = "SEINFRA"
        self.cargo = "Operador"
        self.rpa = "3"
        self.password_hash = "fake"
        self.is_active = is_active
        self.last_login_at = last_login_at
        self.created_at = now_brazil()
        self.updated_at = now_brazil()


class FakeDetection:
    """Mimics app.models.detection.Detection for tests."""
    def __init__(self, rpa="3", bairro="Boa Vista", logradouro="Rua do Sol"):
        self.id = uuid.uuid4()
        self.rpa = rpa
        self.bairro = bairro
        self.logradouro = logradouro
        self.timestamp = now_brazil()
        self.camera_id = 1
        self.latitude = -8.05
        self.longitude = -34.87


class FakeNotification:
    """Mimics app.models.notification.Notification for tests."""
    def __init__(self, user_id=1, is_read=False, detection_id=None):
        self.id = uuid.uuid4()
        self.user_id = user_id
        self.detection_id = detection_id or uuid.uuid4()
        self.type = "nova_ocorrencia"
        self.title = "Nova ocorrência - RPA 3"
        self.message = "Rua do Sol, Boa Vista"
        self.metadata_ = {"rpa": "3", "detection_id": str(self.detection_id)}
        self.is_read = is_read
        self.created_at = now_brazil()


# ── Fixtures ─────────────────────────────────────────────────────────────
@pytest.fixture
def fake_user():
    return FakeUser()


@pytest.fixture
def fake_detection():
    return FakeDetection()


@pytest.fixture
def fake_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value=1)
    redis.pubsub = MagicMock()
    return redis


@pytest.fixture
def mock_db():
    """Mock async database session."""
    session = AsyncMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def auth_token():
    """Valid JWT token for test user."""
    return create_access_token(data={"sub": "test@saira.com"})


@pytest_asyncio.fixture
async def client(auth_token, fake_user):
    """httpx AsyncClient with dependency overrides for app."""
    from app.main import app
    from app.api.deps import get_db, get_current_user, get_current_user_from_query

    mock_db = AsyncMock()

    async def override_get_db():
        yield mock_db

    async def override_get_current_user():
        return fake_user

    async def override_get_current_user_from_query():
        return fake_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_current_user_from_query] = override_get_current_user_from_query

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, mock_db

    app.dependency_overrides.clear()
