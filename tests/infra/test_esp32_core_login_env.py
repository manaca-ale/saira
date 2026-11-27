"""Login do esp32-server no backend chega pelos composes (regressão, 27/11/2026).

Bug: a senha do admin@saira.com de produção foi trocada em 25/11 e gravada no
`.env` como CORE_API_LOGIN_PASSWORD, mas o serviço `esp32-server` de
`services/docker-compose.prod.yml` só recebe o que está na lista `environment`,
e a variável não estava lá: o contêiner seguia tentando a senha de fábrica.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

# compose -> nome do serviço que roda o esp32-server
COMPOSES = {
    "services/docker-compose.prod.yml": "esp32-server",
    "esp32-server/docker-compose.prod.yml": "esp32-receiver",
    "esp32-server/docker-compose.test.yml": "esp32-receiver",
}


def _env(compose: str, service: str) -> dict:
    svc = yaml.safe_load((ROOT / compose).read_text(encoding="utf-8"))["services"][service]
    out = {}
    for item in svc["environment"]:
        key, _, value = str(item).partition("=")
        out[key] = value
    return out


@pytest.mark.parametrize("compose,service", COMPOSES.items())
def test_compose_passes_the_core_login_to_the_esp32_server(compose, service):
    env = _env(compose, service)
    assert env.get("CORE_API_LOGIN_EMAIL") == "${CORE_API_LOGIN_EMAIL:-admin@saira.com}", compose
    # a senha vem só do .env: nenhum valor padrão escrito no compose
    assert env.get("CORE_API_LOGIN_PASSWORD") == "${CORE_API_LOGIN_PASSWORD:-}", compose


@pytest.mark.parametrize("example", ["services/.env.example", "esp32-server/.env.example"])
def test_env_examples_document_the_variables_without_a_value(example):
    lines = (ROOT / example).read_text(encoding="utf-8-sig").splitlines()
    assert "CORE_API_LOGIN_PASSWORD=" in lines, example
    assert any(line.startswith("CORE_API_LOGIN_EMAIL=") for line in lines), example


def test_server_has_no_factory_password_as_default():
    source = (ROOT / "esp32-server" / "server.py").read_text(encoding="utf-8")
    assert 'os.getenv("CORE_API_LOGIN_PASSWORD", "")' in source
    assert "admin" + "123" not in source
