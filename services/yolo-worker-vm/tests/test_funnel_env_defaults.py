"""Funil A com as variáveis vazias = o worker de hoje (rollout para develop, 24/11/2026).

O que os composes entregam ao worker quando o `.env` não tem nenhuma variável do funil é
o padrão escrito em cada linha (`${GATE_PREFILTER_ENABLED:-false}`, no teste
`${TEST_GATE_PREFILTER_ENABLED:-false}`). Este teste lê esses padrões nos dois composes,
carrega `worker.config` num processo novo com eles e confere duas coisas:

  1. a configuração resultante é IDÊNTICA à de um ambiente sem nenhuma dessas variáveis
     (o compose não liga nada por conta própria);
  2. essa configuração é a do worker de antes do PR #95: filtro e gate Bedrock
     desligados, prompt V1 no gate, nenhum parâmetro novo enviado ao Gemini, bbox
     exigida com área mínima de 1%.

A fiação na cascata (filtro desligado = o gate é chamado como antes) está em
test_funnel_finalists.py (test_cascade_does_not_call_the_prefilter_when_disabled,
test_gemini_gate_defaults_are_unchanged, test_run_gate_uses_gemini_when_bedrock_is_off).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[2]
SRC = SERVICES / "yolo-worker-vm" / "src"
COMPOSES = {
    "prod": SERVICES / "docker-compose.prod.yml",
    "test": SERVICES / "docker-compose.test.yml",
}
FUNNEL_VARS = [
    "GEMINI_DETAIL_THINKING_LEVEL", "GEMINI_DETAIL_MEDIA_RESOLUTION",
    "GEMINI_AGENT1_THINKING_LEVEL", "GEMINI_AGENT1_MEDIA_RESOLUTION",
    "GEMINI_GATE_PROMPT_VARIANT",
    "GATE_PREFILTER_ENABLED", "GATE_PREFILTER_DEVICES", "GATE_PREFILTER_LOG_ONLY",
    "GATE_PREFILTER_THRESHOLD", "GATE_PREFILTER_API_KEY", "GATE_PREFILTER_DAILY_BUDGET_USD",
    "GATE_BEDROCK_ENABLED", "GATE_BEDROCK_DEVICES", "GATE_BEDROCK_ALIAS",
    "GATE_BEDROCK_FALLBACK_GEMINI",
    "GEMINI_REQUIRE_BBOX", "GEMINI_BBOX_MIN_AREA_RATIO",
]
# Atributos de worker.config que o funil lê (os acima e os derivados).
ATTRS = [
    "GEMINI_DETAIL_THINKING_LEVEL", "GEMINI_DETAIL_MEDIA_RESOLUTION",
    "GEMINI_AGENT1_THINKING_LEVEL", "GEMINI_AGENT1_MEDIA_RESOLUTION",
    "GEMINI_GATE_PROMPT_VARIANT", "GEMINI_DETAIL_PROMPT_VERSION", "GEMINI_PROMPT_VERSION",
    "GATE_PREFILTER_ENABLED", "GATE_PREFILTER_DEVICES", "GATE_PREFILTER_LOG_ONLY",
    "GATE_PREFILTER_THRESHOLD", "GATE_PREFILTER_API_KEY", "GATE_PREFILTER_DAILY_BUDGET_USD",
    "GATE_BEDROCK_ENABLED", "GATE_BEDROCK_DEVICES", "GATE_BEDROCK_ALIAS",
    "GATE_BEDROCK_FALLBACK_GEMINI",
    "GEMINI_REQUIRE_BBOX", "GEMINI_BBOX_MIN_AREA_RATIO", "GEMINI_AGENT1_THINKING_BUDGET",
]

_DEFAULT = re.compile(r"^\$\{(?:TEST_)?([A-Z0-9_]+):-(.*)\}$")


def _compose_defaults(path: Path) -> dict[str, str]:
    """Valor que o compose passa ao worker para cada variável do funil com o .env vazio."""
    text = path.read_text(encoding="utf-8")
    worker = text[text.index("\n  yolo-worker:\n"):]
    worker = worker[:re.search(r"\n  [a-z][a-z0-9-]*:\n", worker[1:]).start() + 1]
    out = {}
    for var in FUNNEL_VARS:
        m = re.search(r"^\s+- %s=(.*)$" % var, worker, re.M)
        assert m, f"{path.name}: o worker não recebe {var}"
        d = _DEFAULT.match(m.group(1).strip())
        assert d and d.group(1) == var, f"{path.name}: {var}={m.group(1)!r} sem padrão"
        out[var] = d.group(2)
    return out


def _load_config(extra_env: dict[str, str]) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in FUNNEL_VARS
           and not k.startswith(("GEMINI_", "GATE_"))}
    env.update(extra_env)
    env["PYTHONPATH"] = str(SRC)
    code = (
        "import json\nfrom worker import config as c\n"
        f"attrs = {ATTRS!r}\n"
        "out = {}\n"
        "for a in attrs:\n"
        "    v = getattr(c, a)\n"
        "    out[a] = sorted(v) if isinstance(v, (set, frozenset)) else v\n"
        "print(json.dumps(out))\n"
    )
    res = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                         text=True, timeout=120)
    assert res.returncode == 0, res.stderr[-2000:]
    return json.loads(res.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def baseline():
    return _load_config({})


@pytest.mark.parametrize("name", sorted(COMPOSES))
def test_compose_defaults_equal_an_env_without_the_funnel_vars(name, baseline):
    assert _load_config(_compose_defaults(COMPOSES[name])) == baseline


def test_empty_funnel_vars_mean_the_worker_of_today(baseline):
    assert baseline == {
        # filtro e gate Bedrock desligados
        "GATE_PREFILTER_ENABLED": False, "GATE_PREFILTER_DEVICES": [],
        "GATE_PREFILTER_LOG_ONLY": True, "GATE_PREFILTER_THRESHOLD": 0.30,
        "GATE_PREFILTER_API_KEY": "", "GATE_PREFILTER_DAILY_BUDGET_USD": 1.00,
        "GATE_BEDROCK_ENABLED": False, "GATE_BEDROCK_DEVICES": [],
        "GATE_BEDROCK_ALIAS": "nova-lite", "GATE_BEDROCK_FALLBACK_GEMINI": True,
        # gate: prompt V1 e thinking_budget de sempre, nada novo enviado
        "GEMINI_GATE_PROMPT_VARIANT": "", "GEMINI_PROMPT_VERSION": "current",
        "GEMINI_AGENT1_THINKING_LEVEL": "", "GEMINI_AGENT1_MEDIA_RESOLUTION": "",
        "GEMINI_AGENT1_THINKING_BUDGET": 2048,
        # detail: sem prompt g3, sem thinking_level nem media_resolution
        "GEMINI_DETAIL_PROMPT_VERSION": "",
        "GEMINI_DETAIL_THINKING_LEVEL": "", "GEMINI_DETAIL_MEDIA_RESOLUTION": "",
        # grounding de antes
        "GEMINI_REQUIRE_BBOX": True, "GEMINI_BBOX_MIN_AREA_RATIO": 0.01,
    }
