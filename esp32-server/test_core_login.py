"""Login do esp32-server no backend (painel antigo de câmeras), regressão de 27/11/2026.

Bug: sem CORE_API_LOGIN_PASSWORD o servidor tentava entrar com a senha de
fábrica escrita no código. Depois que a senha do administrador foi trocada, cada
abertura do painel antigo virava uma senha errada contra a conta, e o backend
bloqueia o e-mail por 15 min depois de 10 erradas.
"""
import importlib
from pathlib import Path

import pytest

server = importlib.import_module("server")

BASE = "http://backend:8001/api/v1"


class Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"x"
        self.text = str(self._payload)

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(server, "_core_api_cached_base", "")
    monkeypatch.setattr(server, "_core_api_cached_token", "")
    monkeypatch.setattr(server, "_core_api_cached_expiry", 0.0)
    monkeypatch.setattr(server, "_core_api_login_refused_until", {}, raising=False)
    monkeypatch.setattr(server, "CORE_API_LOGIN_EMAIL", "admin@saira.com")
    monkeypatch.setattr(server, "CORE_API_LOGIN_PASSWORD", "senha-do-ambiente")
    monkeypatch.setattr(server, "CORE_API_LOGIN_RETRY_SECONDS", 900, raising=False)


@pytest.fixture
def posts(monkeypatch):
    """Registra cada POST de login; a resposta vem de `posts.answer`."""
    calls = []

    def fake_post(url, data=None, timeout=None, **_kw):
        calls.append({"url": url, "data": dict(data or {})})
        return fake_post.answer

    fake_post.calls = calls
    fake_post.answer = Resp(200, {"access_token": "jwt-1"})
    monkeypatch.setattr(server.requests, "post", fake_post)
    return fake_post


def test_source_has_no_factory_password():
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "admin" + "123" not in source


def test_without_password_it_does_not_even_try(monkeypatch, posts):
    monkeypatch.setattr(server, "CORE_API_LOGIN_PASSWORD", "")
    with pytest.raises(RuntimeError, match="CORE_API_LOGIN_PASSWORD"):
        server._core_api_login(BASE)
    assert posts.calls == []


def test_login_sends_the_configured_credentials_and_caches_the_token(posts):
    assert server._core_api_login(BASE) == "jwt-1"
    assert server._core_api_login(BASE) == "jwt-1"
    assert posts.calls == [{
        "url": BASE + "/auth/login",
        "data": {"username": "admin@saira.com", "password": "senha-do-ambiente"},
    }]


@pytest.mark.parametrize("status", [401, 429])
def test_refused_login_is_not_repeated_before_the_wait(monkeypatch, posts, status):
    now = [1_000_000.0]
    monkeypatch.setattr(server.time, "time", lambda: now[0])
    posts.answer = Resp(status, {"detail": "Incorrect email or password"})

    # 12 aberturas do painel antigo em seguida: só a primeira chega ao backend.
    for _ in range(12):
        with pytest.raises(RuntimeError):
            server._core_api_login(BASE)
    assert len(posts.calls) == 1

    # Outro endereço do backend tem a sua própria espera.
    with pytest.raises(RuntimeError):
        server._core_api_login("http://localhost:8001/api/v1")
    assert len(posts.calls) == 2

    # Passada a espera, tenta de novo (a senha pode ter sido corrigida).
    now[0] += 901
    posts.answer = Resp(200, {"access_token": "jwt-2"})
    assert server._core_api_login(BASE) == "jwt-2"
    assert len(posts.calls) == 3


def test_backend_error_does_not_start_the_wait(posts):
    # 5xx não é senha errada: não conta contra a conta, pode tentar de novo.
    posts.answer = Resp(502)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            server._core_api_login(BASE)
    assert len(posts.calls) == 2


def test_refused_login_reaches_the_dashboard_as_an_error_not_a_crash(posts):
    posts.answer = Resp(401, {"detail": "Incorrect email or password"})
    resp, _base, err = server._core_api_request("GET", "/cameras/")
    assert resp is None and "login 401" in (err or "")
