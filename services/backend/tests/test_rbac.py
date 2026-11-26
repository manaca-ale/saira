"""Regressão das brechas de acesso do backend (ART-02 seção 11, corrigidas em 25/11/2026).

Antes da correção:
- qualquer usuário logado listava, criava, alterava e apagava usuários, câmeras
  e detecções (`get_current_user` só conferia login ativo);
- `POST /api/v1/auth/register` era aberto: qualquer um se cadastrava já ativo.

Depois: papel derivado do `cargo` (app.core.roles), `require_admin` nas rotas de
gestão e configuração, e o register removido.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.core.roles import Role, is_admin, role_from_cargo
from tests.conftest import FakeUser

API = "/api/v1"

# Rotas sem login por desenho (login, fluxo OIDC do Conecta, relatório diário).
PUBLIC_ROUTES = {
    ("POST", "/auth/login"),
    ("GET", "/integrations/conecta/login-url"),
    ("GET", "/integrations/conecta/callback"),
    ("POST", "/integrations/conecta/exchange-ticket"),
    ("GET", "/integrations/conecta/logout-url"),
    ("POST", "/integrations/conecta/revoke-consent"),  # valida o token no Conecta
    ("GET", "/reports/daily"),
}

# Rotas só de administrador. Todo o resto exige login (operador ou administrador).
ADMIN_ROUTES = {
    # gestão de usuários
    ("GET", "/users/"),
    ("GET", "/users/{user_id}"),
    ("POST", "/users/"),
    ("PATCH", "/users/{user_id}"),
    ("DELETE", "/users/{user_id}"),
    # configuração de câmera (muda o que a câmera vê e o que o sistema detecta)
    ("POST", "/cameras/"),
    ("PATCH", "/cameras/{camera_id}"),
    ("PATCH", "/cameras/{camera_id}/bgsub_config"),
    ("DELETE", "/cameras/{camera_id}"),
    ("POST", "/cameras/{camera_id}/zoom"),
    ("POST", "/cameras/{camera_id}/autofocus"),
    ("POST", "/cameras/{camera_id}/polygon"),
    # criação manual e exclusão de registros
    ("POST", "/detections/"),
    ("DELETE", "/detections/{detection_id}"),
    ("DELETE", "/offenders/{offender_id}"),
    # custo de API (interno da Manacá)
    ("GET", "/billing/daily"),
    ("GET", "/billing/range"),
    ("POST", "/billing/test-email"),
}

# Dependencies que autenticam o usuário (por nome, para valer também com a
# autenticação do SSE, que não usa o header Authorization).
AUTH_DEP_NAMES = {
    "get_current_user",
    "get_current_user_from_query",
    "get_current_user_from_sse_ticket",
}


def _walk(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _walk(dep)


def _route_policy(route) -> str:
    calls = list(_walk(route.dependant))
    if any(Role.ADMIN in getattr(c, "required_roles", ()) and len(c.required_roles) == 1 for c in calls):
        return "admin"
    if any(getattr(c, "__name__", "") in AUTH_DEP_NAMES for c in calls):
        return "logged"
    return "public"


def _api_routes():
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith(API + "/") or not hasattr(route, "dependant"):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, path[len(API):], route


def test_policy_matrix_every_route_has_the_expected_protection():
    """Cada rota da API tem a proteção esperada; rota nova sem classificar falha aqui."""
    wrong = []
    seen = set()
    for method, path, route in _api_routes():
        key = (method, path)
        seen.add(key)
        expected = "admin" if key in ADMIN_ROUTES else "public" if key in PUBLIC_ROUTES else "logged"
        actual = _route_policy(route)
        # /test/whatsapp confere administrador dentro da função (depois do 404 da flag)
        if key == ("POST", "/test/whatsapp"):
            expected = "logged"
        if actual != expected:
            wrong.append(f"{method} {path}: esperado {expected}, está {actual}")
    assert not wrong, "\n".join(wrong)
    missing = (ADMIN_ROUTES | PUBLIC_ROUTES) - seen
    assert not missing, f"rotas da tabela que não existem mais: {sorted(missing)}"


def test_register_route_is_gone():
    """POST /auth/register (cadastro aberto, já ativo) não existe mais."""
    assert ("POST", "/auth/register") not in {(m, p) for m, p, _ in _api_routes()}


async def test_register_without_login_creates_nobody(client):
    ac, mock_db = client
    mock_db.add = MagicMock()
    response = await ac.post(
        f"{API}/auth/register",
        json={"name": "Intruso", "email": "intruso@example.com", "password": "senha-forte-123",
              "cargo": "Administrador"},
    )
    assert response.status_code in (404, 405)
    mock_db.add.assert_not_called()


OPERATOR_FORBIDDEN = [
    ("get", "/users/", None),
    ("get", "/users/1", None),
    ("post", "/users/", {"name": "X", "email": "x@example.com", "password": "senha-forte-123",
                         "cargo": "Administrador"}),
    ("patch", "/users/1", {"cargo": "Administrador"}),
    ("delete", "/users/2", None),
    ("post", "/cameras/", {}),
    ("patch", "/cameras/1", {}),
    ("patch", "/cameras/1/bgsub_config", {}),
    ("delete", "/cameras/1", None),
    ("post", "/cameras/1/zoom", {"zoom": 2}),
    ("post", "/cameras/1/autofocus", None),
    ("post", "/cameras/1/polygon", {"polygon": []}),
    ("post", "/detections/", {}),
    ("delete", f"/detections/{uuid4()}", None),
    ("delete", "/offenders/1", None),
    ("get", "/billing/daily", None),
    ("get", "/billing/range?start=2026-11-01&end=2026-11-02", None),
    ("post", "/billing/test-email", {}),
]


@pytest.mark.parametrize("method,path,body", OPERATOR_FORBIDDEN)
async def test_operator_gets_403_on_admin_routes(client, fake_user, method, path, body):
    """Operador logado (cargo fora de Administrador/admin) recebe 403 e nada vai ao banco."""
    ac, mock_db = client
    fake_user.cargo = "Operador"
    kwargs = {"json": body} if body is not None else {}
    response = await getattr(ac, method)(f"{API}{path}", **kwargs)
    assert response.status_code == 403, response.text
    mock_db.execute.assert_not_called()


@pytest.mark.parametrize("cargo", [None, "", "Fiscal", "Operador", "administradora adjunta"])
async def test_user_without_admin_cargo_cannot_list_users(client, fake_user, cargo):
    ac, _ = client
    fake_user.cargo = cargo
    response = await ac.get(f"{API}/users/")
    assert response.status_code == 403


@pytest.mark.parametrize("cargo", ["Administrador", "admin", "  ADMIN ", "administrador"])
async def test_admin_lists_users(client, fake_user, cargo):
    ac, mock_db = client
    fake_user.cargo = cargo
    result = MagicMock()
    result.scalars.return_value.all.return_value = [FakeUser(id=7, email="a@saira.com")]
    mock_db.execute.return_value = result
    response = await ac.get(f"{API}/users/")
    assert response.status_code == 200, response.text
    assert response.json()[0]["role"] == "operador"


async def test_admin_cannot_delete_own_user(client, fake_user):
    """O último administrador não se tranca para fora."""
    ac, mock_db = client
    fake_user.cargo = "Administrador"
    result = MagicMock()
    result.scalar_one_or_none.return_value = fake_user
    mock_db.execute.return_value = result
    response = await ac.delete(f"{API}/users/{fake_user.id}")
    assert response.status_code == 400
    mock_db.delete.assert_not_called()


@pytest.mark.parametrize("body", [{"cargo": "Operador"}, {"cargo": None}, {"is_active": False}])
async def test_admin_cannot_remove_own_access(client, fake_user, body):
    ac, mock_db = client
    fake_user.cargo = "Administrador"
    result = MagicMock()
    result.scalar_one_or_none.return_value = fake_user
    mock_db.execute.return_value = result
    response = await ac.patch(f"{API}/users/{fake_user.id}", json=body)
    assert response.status_code == 400
    assert fake_user.cargo == "Administrador" and fake_user.is_active is True
    mock_db.commit.assert_not_called()


async def test_operator_cannot_change_status_by_patch(client, fake_user):
    """Status por PATCH pula as regras do /classify: só administrador."""
    ac, mock_db = client
    fake_user.cargo = "Operador"
    detection = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = detection
    mock_db.execute.return_value = result
    response = await ac.patch(f"{API}/detections/{uuid4()}", json={"status": "Confirmado"})
    assert response.status_code == 403, response.text
    mock_db.commit.assert_not_called()


def test_role_from_cargo():
    assert role_from_cargo("Administrador") is Role.ADMIN
    assert role_from_cargo(" admin ") is Role.ADMIN
    assert role_from_cargo("Operador") is Role.OPERATOR
    assert role_from_cargo(None) is Role.OPERATOR
    assert role_from_cargo("") is Role.OPERATOR
    assert is_admin(FakeUser()) is False


async def test_me_exposes_role(client, fake_user):
    """O frontend usa `role` para esconder o que é de administrador."""
    ac, _ = client
    fake_user.cargo = "Administrador"
    response = await ac.get(f"{API}/auth/me")
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
