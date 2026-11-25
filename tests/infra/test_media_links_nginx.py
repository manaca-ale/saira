"""Regressão: `/uploads/*` e `/s3-images/*` do site abriam sem login (achado em 24/11/2026).

O nginx do frontend fazia proxy aberto para o esp32-server (uploads, vídeos e `server-events.jsonl`)
e para o bucket. Estes testes leem o template, o Dockerfile e os composes e falham se a conferência
do link assinado (`secure_link`) sair de alguma das duas rotas ou se o segredo deixar de chegar ao
nginx e ao backend.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "services" / "frontend" / "nginx.conf.template"
DOCKERFILE = ROOT / "services" / "frontend" / "Dockerfile"
COMPOSES = {
    "prod": (ROOT / "services" / "docker-compose.prod.yml", "MEDIA_LINK_SECRET"),
    "test": (ROOT / "services" / "docker-compose.test.yml", "TEST_MEDIA_LINK_SECRET"),
}


def _bloco(location: str) -> str:
    texto = TEMPLATE.read_text(encoding="utf-8")
    inicio = texto.index(f"location ^~ {location} {{")
    fim = texto.index("\n    }", inicio)
    return texto[inicio:fim]


@pytest.mark.parametrize("location", ["/uploads/", "/s3-images/"])
def test_rota_exige_link_assinado(location):
    bloco = _bloco(location)
    assert "secure_link $arg_md5,$arg_expires;" in bloco
    assert 'secure_link_md5 "$secure_link_expires$uri ${MEDIA_LINK_SECRET}";' in bloco
    assert re.search(r'if \(\$secure_link = ""\) \{ return 403; \}', bloco)
    assert re.search(r'if \(\$secure_link = "0"\) \{ return 410; \}', bloco)
    # a conferência vem antes do proxy
    assert bloco.index("secure_link ") < bloco.index("proxy_pass")
    assert '"public' not in bloco, "link assinado não pode ir para cache compartilhado"


def test_envsubst_injeta_o_segredo_no_nginx():
    cmd = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"envsubst '[^']*\$MEDIA_LINK_SECRET[^']*'", cmd)


def _env(service: dict) -> dict:
    out = {}
    for item in service.get("environment") or []:
        key, _, value = str(item).partition("=")
        out[key] = value
    return out


@pytest.mark.parametrize("env_name", list(COMPOSES))
@pytest.mark.parametrize("svc_name", ["web", "backend"])
def test_compose_exige_o_segredo(env_name, svc_name):
    path, var = COMPOSES[env_name]
    svc = yaml.safe_load(path.read_text(encoding="utf-8"))["services"][svc_name]
    valor = _env(svc).get("MEDIA_LINK_SECRET", "")
    assert valor.startswith("${" + var + ":?"), f"{env_name}:{svc_name} MEDIA_LINK_SECRET={valor!r}"
