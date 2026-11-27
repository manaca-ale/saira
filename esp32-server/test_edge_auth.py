"""Autenticação da borda (X-Device-Token / X-Admin-Token) e a chave de transição.

Antes, qualquer um que alcançasse a porta mandava comando para a câmera
(/device/<id>/trigger) ou subia imagem em nome dela, sem token nenhum.
"""
import importlib

import pytest

server = importlib.import_module("server")

# Rotas que continuam sem token de propósito: o painel antigo e as imagens
# (o navegador não manda cabeçalho; a proteção delas é o link assinado no nginx
# e fechar a porta pública). Rota nova precisa entrar numa das listas.
OPEN_ENDPOINTS = {
    "static", "get_uploaded_file", "dashboard", "dashboard_summary",
    "dashboard_devices", "dashboard_recent_images", "dashboard_recent_logs",
    "dashboard_state", "dashboard_camera_latest_image",
    "dashboard_camera_registration_options",
}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(server, "REDIS_URL", "")
    monkeypatch.setattr(server, "_redis_client", None)
    monkeypatch.setattr(server, "_redis_failed", False)
    monkeypatch.setattr(server, "_sse_queues", {})
    monkeypatch.setattr(server, "_sse_pending", {})
    monkeypatch.setattr(server, "_edge_warned", {})
    for name in ("EDGE_AUTH_REQUIRED", "EDGE_DEVICE_TOKENS", "EDGE_SHARED_TOKEN", "ADMIN_TOKEN"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    return server.app.test_client()


@pytest.fixture
def required(monkeypatch):
    monkeypatch.setenv("EDGE_AUTH_REQUIRED", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "adm-123")
    monkeypatch.setenv("EDGE_DEVICE_TOKENS", "dev-1:tok-1, dev-2:tok-2")
    monkeypatch.setenv("EDGE_SHARED_TOKEN", "tok-shared")


def gate(method, path, headers=None):
    """Roda só o portão de autenticação, sem executar a rota. None = passou."""
    with server.app.test_request_context(path, method=method, headers=headers or {}):
        rv = server._edge_auth_gate()
    return None if rv is None else rv.status_code


def test_every_route_is_classified():
    listed = (server.EDGE_DEVICE_ENDPOINTS | server.EDGE_SERVICE_ENDPOINTS
              | server.EDGE_MIXED_ENDPOINTS)
    endpoints = {rule.endpoint for rule in server.app.url_map.iter_rules()}
    assert endpoints - listed - OPEN_ENDPOINTS == set(), "rota nova sem decisão de autenticação"
    assert listed - endpoints == set(), "lista aponta rota que não existe"


# ---------- transição (padrão): aceita e só registra ----------

def test_transition_accepts_without_token_and_logs(client, capsys):
    resp = client.post("/device/dev-1/trigger", json={"cmd": "CMD_SNAPSHOT"})
    assert resp.status_code == 200
    out = capsys.readouterr().out
    assert "[EDGE-AUTH]" in out and "dev-1" in out


def test_transition_accepts_device_routes_without_token():
    assert gate("POST", "/upload-batch", {"X-Device-Id": "pi-cam-sim-001"}) is None
    assert gate("GET", "/device/dev-1/poll") is None
    assert gate("POST", "/status") is None


def test_transition_log_is_rate_limited(capsys):
    for _ in range(5):
        gate("GET", "/device/dev-1/poll")
    assert capsys.readouterr().out.count("[EDGE-AUTH]") == 1


def test_transition_valid_token_does_not_log(required, monkeypatch, capsys):
    monkeypatch.setenv("EDGE_AUTH_REQUIRED", "false")
    assert gate("GET", "/device/dev-1/poll", {"X-Device-Token": "tok-1"}) is None
    assert "[EDGE-AUTH]" not in capsys.readouterr().out


# ---------- exigência ligada ----------

def test_required_trigger_without_token_is_401(required, client):
    resp = client.post("/device/dev-1/trigger", json={"cmd": "CMD_SNAPSHOT"})
    assert resp.status_code == 401
    with pytest.raises(server._QueueEmpty):  # o comando não entrou na fila
        server._pop_sse_cmd("dev-1", 0.01)


def test_required_trigger_with_admin_token_passes(required, client):
    resp = client.post("/device/dev-1/trigger", json={"cmd": "CMD_SNAPSHOT"},
                       headers={"X-Admin-Token": "adm-123"})
    assert resp.status_code == 200


@pytest.mark.parametrize("method,path", [
    ("POST", "/device/dev-1/trigger"),
    ("POST", "/device/dev-1/config"),
    ("POST", "/ota/upload"),
    ("GET", "/device/dev-1/health"),
    ("GET", "/device/dev-1/logs"),
    ("POST", "/api/dashboard/camera-registration"),
])
def test_required_service_routes_need_admin_token(required, method, path):
    assert gate(method, path) == 401
    assert gate(method, path, {"X-Admin-Token": "errado"}) == 401
    assert gate(method, path, {"X-Device-Token": "tok-1"}) == 401
    assert gate(method, path, {"X-Admin-Token": "adm-123"}) is None


def test_required_without_admin_token_configured_fails_closed(required, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN")
    assert gate("POST", "/device/dev-1/trigger") == 401
    assert gate("POST", "/device/dev-1/trigger", {"X-Admin-Token": ""}) == 401


@pytest.mark.parametrize("method,path", [
    ("GET", "/device/dev-1/poll"),
    ("GET", "/device/dev-1/events"),
    ("GET", "/device/dev-1/config.txt"),
    ("POST", "/device/dev-1/keepalive"),
    ("POST", "/device/dev-1/bulk-upload"),
    ("POST", "/device/dev-1/video"),
    ("POST", "/device/dev-1/logs"),
])
def test_required_device_routes_need_own_token(required, method, path):
    assert gate(method, path) == 401
    assert gate(method, path, {"X-Device-Token": "tok-2"}) == 401       # token de outra câmera
    assert gate(method, path, {"X-Device-Token": "tok-shared"}) == 401  # tem token próprio
    assert gate(method, path, {"X-Device-Token": "tok-1"}) is None
    assert gate(method, path, {"X-Admin-Token": "adm-123"}) is None     # backend lendo config.txt


@pytest.mark.parametrize("path", ["/upload", "/upload-batch", "/status"])
def test_required_upload_routes_use_x_device_id(required, path):
    assert gate("POST", path, {"X-Device-Id": "dev-1"}) == 401
    assert gate("POST", path, {"X-Device-Id": "dev-1", "X-Device-Token": "tok-2"}) == 401
    assert gate("POST", path, {"X-Device-Id": "dev-1", "X-Device-Token": "tok-1"}) is None


def test_required_shared_token_only_for_devices_without_own_token(required):
    headers = {"X-Device-Id": "pi-cam-sim-001", "X-Device-Token": "tok-shared"}
    assert gate("POST", "/upload-batch", headers) is None
    assert gate("POST", "/upload-batch", {"X-Device-Token": "tok-shared"}) is None  # firmware sem X-Device-Id
    assert gate("POST", "/upload-batch", {"X-Device-Id": "pi-cam-sim-001", "X-Device-Token": "x"}) == 401


def test_required_empty_shared_token_never_matches(required, monkeypatch):
    monkeypatch.delenv("EDGE_SHARED_TOKEN")
    assert gate("GET", "/device/dev-9/poll") == 401
    assert gate("GET", "/device/dev-9/poll", {"X-Device-Token": "qualquer"}) == 401


def test_open_routes_stay_open(required):
    assert gate("GET", "/dashboard") is None
    assert gate("GET", "/uploads/dev-1/x.jpg") is None
