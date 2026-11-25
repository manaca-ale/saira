"""SSE sem JWT na URL: a conexão usa um bilhete de uso único.

Antes, o painel abria /notifications/stream?token=<JWT>; o token de 24 h
ficava nos logs do proxy e servia para qualquer rota da API.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.v1.endpoints import notifications
from app.main import app


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttl = {}

    async def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttl[key] = ttl

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


class FakeDB:
    def __init__(self, user):
        self.user = user

    async def execute(self, _stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self.user)


def _user(active=True):
    return SimpleNamespace(email="operador@recife.pe.gov.br", is_active=active)


async def _ticket(redis, user):
    out = await notifications.create_stream_ticket(current_user=user, redis=redis)
    return out["ticket"]


async def test_ticket_is_random_short_lived_and_not_the_jwt():
    redis = FakeRedis()
    first = await _ticket(redis, _user())
    second = await _ticket(redis, _user())
    assert first != second and len(first) >= 32
    assert "." not in first  # não é um JWT
    key = f"{deps.SSE_TICKET_PREFIX}{first}"
    assert redis.store[key] == "operador@recife.pe.gov.br"
    assert 0 < redis.ttl[key] <= 60


async def test_ticket_opens_the_stream_only_once():
    redis, user = FakeRedis(), _user()
    ticket = await _ticket(redis, user)
    got = await deps.get_current_user_from_sse_ticket(ticket=ticket, db=FakeDB(user), redis=redis)
    assert got is user
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_from_sse_ticket(ticket=ticket, db=FakeDB(user), redis=redis)
    assert exc.value.status_code == 401


async def test_unknown_or_expired_ticket_is_401():
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_from_sse_ticket(
            ticket="x" * 43, db=FakeDB(_user()), redis=FakeRedis()
        )
    assert exc.value.status_code == 401


async def test_ticket_value_in_bytes_is_accepted():
    redis, user = FakeRedis(), _user()
    redis.store[f"{deps.SSE_TICKET_PREFIX}abc"] = b"operador@recife.pe.gov.br"
    got = await deps.get_current_user_from_sse_ticket(ticket="abc", db=FakeDB(user), redis=redis)
    assert got is user


async def test_inactive_user_is_403_and_ticket_is_spent():
    redis, user = FakeRedis(), _user(active=False)
    ticket = await _ticket(redis, user)
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_from_sse_ticket(ticket=ticket, db=FakeDB(user), redis=redis)
    assert exc.value.status_code == 403
    assert redis.store == {}


def _query_params(dependant):
    names = {p.name for p in dependant.query_params}
    for child in dependant.dependencies:
        names |= _query_params(child)
    return names


def test_stream_route_no_longer_takes_the_jwt_in_the_url():
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/v1/notifications/stream")
    params = _query_params(route.dependant)
    assert "token" not in params
    assert "ticket" in params
    assert not hasattr(deps, "get_current_user_from_query")
