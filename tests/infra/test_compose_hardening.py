"""Travas de segurança e disco nos composes do servidor (regressão, 24/11/2026).

Medido no servidor: Postgres, backend, pgAdmin, Grafana, Prometheus e métricas
publicados em 0.0.0.0 (só o Security Group protegia), JWT assinado com a chave
padrão escrita no compose e log do Docker sem teto (1,1 GB no esp32-server).
Estes testes leem os YAML e falham se alguma dessas portas voltar a abrir.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSES = {
    "prod": ROOT / "services" / "docker-compose.prod.yml",
    "test": ROOT / "services" / "docker-compose.test.yml",
}
# Borda: recebem as câmeras (Pi pelo WireGuard em 10.8.0.1, ESP32 pela
# internet). Fechar estas é regra do Security Group, não do bind.
EDGE_SERVICES = {"esp32-server", "esp32-receiver"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _env(service: dict) -> dict:
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {k: str(v) for k, v in env.items()}
    out = {}
    for item in env:
        key, _, value = str(item).partition("=")
        out[key] = value
    return out


def _services():
    for name, path in COMPOSES.items():
        for svc_name, svc in _load(path)["services"].items():
            yield pytest.param(name, svc_name, svc, id=f"{name}:{svc_name}")


@pytest.mark.parametrize("env_name,svc_name,svc", list(_services()))
def test_internal_ports_only_on_loopback(env_name, svc_name, svc):
    if svc_name in EDGE_SERVICES:
        pytest.skip("porta de borda (câmeras)")
    for port in svc.get("ports") or []:
        spec = str(port)
        assert spec.startswith("127.0.0.1:"), (
            f"{env_name}:{svc_name} publica {spec!r} fora do loopback; "
            "use 127.0.0.1:HOST:CONTAINER (cloudflared e túnel SSH chegam por lá)"
        )


@pytest.mark.parametrize("env_name,svc_name,svc", list(_services()))
def test_every_service_rotates_logs(env_name, svc_name, svc):
    logging = svc.get("logging") or {}
    assert logging.get("driver") == "json-file", f"{env_name}:{svc_name} sem logging"
    assert logging.get("options", {}).get("max-size"), f"{env_name}:{svc_name} sem max-size"


@pytest.mark.parametrize("env_name,svc_name,svc", list(_services()))
def test_no_literal_passwords(env_name, svc_name, svc):
    env = _env(svc)
    for key in ("POSTGRES_PASSWORD", "PGADMIN_DEFAULT_PASSWORD", "GF_SECURITY_ADMIN_PASSWORD"):
        if key in env:
            assert env[key].startswith("${"), f"{env_name}:{svc_name} {key} escrito no compose"
    url = env.get("DATABASE_URL", "")
    assert "postgres:postgres@" not in url, f"{env_name}:{svc_name} senha do banco no DATABASE_URL"


@pytest.mark.parametrize("env_name,var", [("prod", "SECRET_KEY"), ("test", "TEST_SECRET_KEY")])
def test_jwt_secret_is_required_and_separate(env_name, var):
    backend = _load(COMPOSES[env_name])["services"]["backend"]
    value = _env(backend)["SECRET_KEY"]
    # ${VAR:?msg}: sem a variável o compose falha antes de recriar qualquer container.
    assert re.fullmatch(r"\$\{" + var + r":\?[^}]+\}", value), value


def test_esp32_test_receiver_rotates_logs():
    svc = _load(ROOT / "esp32-server" / "docker-compose.test.yml")["services"]["esp32-receiver"]
    assert svc["logging"]["options"]["max-size"]
