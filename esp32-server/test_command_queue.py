"""Testes da fila de comandos por dispositivo (/trigger -> /poll).

Cobrem o que quebrava em campo: comando descartado em silêncio enquanto o
dispositivo estava ocupado, com a API respondendo 200 "queued" mesmo assim.

Rodar dentro da imagem construída (flask/gevent/redis lá dentro):
    docker run --rm -v "$PWD":/app -w /app saira-esp32-server \
        sh -c "pip install pytest >/dev/null && pytest -q test_command_queue.py"

A entrega entre workers gunicorn via Redis é validada à parte, com o servidor
real de pé (ver o repro de 2 workers + Redis).
"""
import importlib

import pytest

server = importlib.import_module("server")


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch):
    """Força o caminho de memória (sem Redis) e zera o estado entre testes."""
    monkeypatch.setattr(server, "REDIS_URL", "")
    monkeypatch.setattr(server, "_redis_client", None)
    monkeypatch.setattr(server, "_redis_failed", False)
    monkeypatch.setattr(server, "_sse_queues", {})
    monkeypatch.setattr(server, "_sse_pending", {})


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    return server.app.test_client()


def test_push_new_command_is_queued():
    assert server._push_sse_cmd("dev-1", "CMD_SNAPSHOT") == server.PUSH_QUEUED


def test_push_identical_command_collapses():
    assert server._push_sse_cmd("dev-1", "CMD_SNAPSHOT") == server.PUSH_QUEUED
    assert server._push_sse_cmd("dev-1", "CMD_SNAPSHOT") == server.PUSH_DUPLICATE


def test_push_reports_full_instead_of_dropping_silently(monkeypatch):
    """O bug de campo: com o dispositivo ocupado, tudo além da profundidade era
    descartado e a API respondia 'queued'. Agora satura em 'full'."""
    monkeypatch.setattr(server, "COMMAND_QUEUE_DEPTH", 3)
    monkeypatch.setattr(server, "_sse_queues", {})
    for i in range(3):
        assert server._push_sse_cmd("dev-2", f"CMD_{i}") == server.PUSH_QUEUED
    assert server._push_sse_cmd("dev-2", "CMD_EXTRA") == server.PUSH_FULL


def test_pop_returns_in_order_and_clears_dedup():
    server._push_sse_cmd("dev-3", "CMD_A")
    server._push_sse_cmd("dev-3", "CMD_B")
    assert server._pop_sse_cmd("dev-3", timeout=1) == "CMD_A"
    assert server._pop_sse_cmd("dev-3", timeout=1) == "CMD_B"
    # dedup liberado após o pop: o mesmo comando pode ser reenfileirado
    assert server._push_sse_cmd("dev-3", "CMD_A") == server.PUSH_QUEUED


def test_pop_raises_when_empty():
    with pytest.raises(server._QueueEmpty):
        server._pop_sse_cmd("dev-vazio", timeout=1)


def test_trigger_returns_429_when_full(monkeypatch, client):
    """A API não pode mais mentir: fila cheia => 429, não 200 'queued'."""
    monkeypatch.setattr(server, "COMMAND_QUEUE_DEPTH", 2)
    monkeypatch.setattr(server, "_sse_queues", {})
    for i in range(2):
        r = client.post("/device/dev-4/trigger", json={"cmd": f"CMD_{i}"})
        assert r.status_code == 200 and r.get_json()["status"] == "queued"

    r = client.post("/device/dev-4/trigger", json={"cmd": "CMD_DEMAIS"})
    assert r.status_code == 429, "fila cheia tem de falhar alto"
    body = r.get_json()
    assert body["status"] == "full"
    assert "cheia" in body["detail"]


def test_trigger_duplicate_is_200_not_error(client):
    """Clicar 2x no mesmo botão não é erro — o comando já está pendente."""
    client.post("/device/dev-5/trigger", json={"cmd": "CMD_SNAPSHOT"})
    r = client.post("/device/dev-5/trigger", json={"cmd": "CMD_SNAPSHOT"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "duplicate"


def test_trigger_then_poll_delivers(client):
    client.post("/device/dev-6/trigger", json={"cmd": "CMD_VIDEO_CLIP:evt-1"})
    r = client.get("/device/dev-6/poll?timeout=5")
    assert r.status_code == 200
    assert r.get_json()["cmd"] == "CMD_VIDEO_CLIP:evt-1"


def test_redis_failure_falls_back_to_memory(monkeypatch):
    """Redis fora do ar não pode derrubar a entrega — degrada para memória."""
    monkeypatch.setattr(server, "REDIS_URL", "redis://nao-existe:6379/0")
    monkeypatch.setattr(server, "_redis_client", None)
    monkeypatch.setattr(server, "_redis_failed", False)
    assert server._push_sse_cmd("dev-7", "CMD_X") == server.PUSH_QUEUED
    assert server._pop_sse_cmd("dev-7", timeout=1) == "CMD_X"
