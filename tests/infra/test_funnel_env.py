"""Variáveis do funil A (campanha 54) nos composes (regressão, 24/11/2026).

Bug: o PR #95 repassava as variáveis novas no compose de TESTE pelo mesmo nome da
produção (`GATE_PREFILTER_ENABLED=${GATE_PREFILTER_ENABLED:-false}`), contra o idioma
`TEST_*` do arquivo. Com um `.env` copiado da produção, armar o funil no teste armava a
produção junto (e vice-versa), e o teste não tinha como ligar o detail novo sem mexer no
`GEMINI_MODEL` da produção.

Estes testes leem os YAML e garantem que:
  - no teste, cada variável do funil vem de uma `TEST_*` própria, com o mesmo padrão da
    produção (vazio = desligado = o que roda hoje);
  - no teste, as variáveis antigas que o funil precisa trocar (modelo, prompt e timeout do
    detail, dispositivos de evento...) aceitam uma `TEST_*` e, sem ela, caem no valor de
    antes (`${TEST_X:-${X:-padrão}}`);
  - a produção nunca lê `TEST_*` e repassa as mesmas variáveis com os padrões desligados.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PROD = ROOT / "services" / "docker-compose.prod.yml"
TEST = ROOT / "services" / "docker-compose.test.yml"

# Variável nova -> padrão (o valor que reproduz o worker de hoje).
FUNNEL_VARS = {
    "GEMINI_DETAIL_THINKING_LEVEL": "",
    "GEMINI_DETAIL_MEDIA_RESOLUTION": "",
    "GEMINI_AGENT1_THINKING_LEVEL": "",
    "GEMINI_AGENT1_MEDIA_RESOLUTION": "",
    "GEMINI_GATE_PROMPT_VARIANT": "",
    "GATE_PREFILTER_ENABLED": "false",
    "GATE_PREFILTER_DEVICES": "",
    "GATE_PREFILTER_LOG_ONLY": "true",
    "GATE_PREFILTER_THRESHOLD": "0.30",
    "GATE_PREFILTER_API_KEY": "",
    "GATE_PREFILTER_DAILY_BUDGET_USD": "1.00",
    "GATE_BEDROCK_ENABLED": "false",
    "GATE_BEDROCK_DEVICES": "",
    "GATE_BEDROCK_ALIAS": "nova-lite",
    "GATE_BEDROCK_FALLBACK_GEMINI": "true",
    "GEMINI_REQUIRE_BBOX": "true",
    "GEMINI_BBOX_MIN_AREA_RATIO": "0.01",
}

# Variáveis que já existiam no compose de teste e que o teste do funil A precisa trocar
# sem depender do nome que a produção usa. Sem a TEST_*, vale o que valia antes.
TEST_OVERRIDABLE = [
    "GEMINI_MODEL",
    "GEMINI_DETAIL_PROMPT_VERSION",
    "GEMINI_TIMEOUT_SECONDS",
    "GEMINI_AGENT1_MODEL",
    "GEMINI_GATE_MID_FRAMES",
    "GEMINI_GATE_REVOTE_ENABLED",
    "EVENT_DRIVEN_DEVICES",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
]


def _worker_env(path: Path) -> dict:
    svc = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]["yolo-worker"]
    out = {}
    for item in svc["environment"]:
        key, _, value = str(item).partition("=")
        out[key] = value
    return out


@pytest.mark.parametrize("var,default", FUNNEL_VARS.items())
def test_test_compose_reads_funnel_vars_from_test_prefix(var, default):
    value = _worker_env(TEST).get(var)
    assert value is not None, f"teste não repassa {var}"
    assert value == "${TEST_%s:-%s}" % (var, default), (
        f"teste: {var}={value!r}; use ${{TEST_{var}:-{default}}} para o teste não "
        "herdar o valor da produção"
    )


@pytest.mark.parametrize("var,default", FUNNEL_VARS.items())
def test_prod_compose_passes_funnel_vars_off_by_default(var, default):
    value = _worker_env(PROD).get(var)
    assert value == "${%s:-%s}" % (var, default), f"produção: {var}={value!r}"


@pytest.mark.parametrize("var", TEST_OVERRIDABLE)
def test_test_compose_lets_test_override_without_changing_the_old_default(var):
    value = _worker_env(TEST).get(var)
    assert value is not None, f"teste não repassa {var}"
    assert re.fullmatch(r"\$\{TEST_%s:-\$\{%s:-[^${}]*\}\}" % (var, var), value), (
        f"teste: {var}={value!r}; esperado ${{TEST_{var}:-${{{var}:-<padrão de antes>}}}}"
    )


def test_prod_compose_never_reads_test_vars():
    for key, value in _worker_env(PROD).items():
        assert "TEST_" not in value, f"produção lê variável de teste em {key}={value!r}"
