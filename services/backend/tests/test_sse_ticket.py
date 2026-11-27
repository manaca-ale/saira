"""SSE sem JWT na URL: a conexão usa um bilhete de uso único.

Antes, o painel abria /notifications/stream?token=<JWT>; o token de 24 h
ficava nos logs do proxy e servia para qualquer rota da API.
"""
import json
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


def _user(active=True, token_version=0, must_change_password=False):
    return SimpleNamespace(
        email="operador@recife.pe.gov.br",
        is_active=active,
        token_version=token_version,
        must_change_password=must_change_password,
    )


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
    assert json.loads(redis.store[key]) == {"sub": "operador@recife.pe.gov.br", "ver": 0}
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
    redis.store[f"{deps.SSE_TICKET_PREFIX}abc"] = deps.sse_ticket_value(user).encode("utf-8")
    got = await deps.get_current_user_from_sse_ticket(ticket="abc", db=FakeDB(user), redis=redis)
    assert got is user


async def test_inactive_user_is_403_and_ticket_is_spent():
    redis, user = FakeRedis(), _user(active=False)
    ticket = await _ticket(redis, user)
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_from_sse_ticket(ticket=ticket, db=FakeDB(user), redis=redis)
    assert exc.value.status_code == 403
    assert redis.store == {}


async def test_password_change_kills_tickets_already_issued():
    # Trocar a senha soma 1 em token_version: o bilhete emitido antes não abre o stream.
    redis, user = FakeRedis(), _user(token_version=3)
    ticket = await _ticket(redis, user)
    user.token_version = 4
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_from_sse_ticket(ticket=ticket, db=FakeDB(user), redis=redis)
    assert exc.value.status_code == 401
    assert redis.store == {}


async def test_user_with_provisional_password_does_not_open_the_stream():
    redis, user = FakeRedis(), _user(must_change_password=True)
    ticket = await _ticket(redis, user)
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_from_sse_ticket(ticket=ticket, db=FakeDB(user), redis=redis)
    assert exc.value.status_code == 403
    assert exc.value.detail == deps.PASSWORD_CHANGE_REQUIRED


async def test_malformed_ticket_value_is_401():
    redis = FakeRedis()
    redis.store[f"{deps.SSE_TICKET_PREFIX}abc"] = b"operador@recife.pe.gov.br"
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_from_sse_ticket(ticket="abc", db=FakeDB(_user()), redis=redis)
    assert exc.value.status_code == 401


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
