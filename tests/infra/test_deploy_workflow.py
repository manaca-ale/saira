"""O deploy de teste não pode tocar o checkout da produção (regressão, 24/11/2026).

Antes, os dois jobs faziam ``git reset --hard`` no mesmo /home/ubuntu/saira: um
push em develop trocava gateway.conf, alert.rules.yml, models/ e os scripts dos
crons que a produção usa, e os dois ambientes liam o mesmo .env.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8"))
PROD_DIR = "/home/ubuntu/saira"
TEST_DIR = "/home/ubuntu/saira-test"


def _script(job: str) -> str:
    return "\n".join(step["with"]["script"] for step in WF["jobs"][job]["steps"] if "with" in step)


def _dirs(script: str) -> set:
    # Caminhos absolutos citados em comandos (comentários e echo ficam de fora).
    code = "\n".join(
        line for line in script.splitlines()
        if not line.strip().startswith(("#", "echo"))
    )
    return set(re.findall(r"/home/ubuntu/saira[\w-]*", code))


def test_test_job_never_touches_prod_checkout():
    dirs = _dirs(_script("deploy-test"))
    assert dirs == {TEST_DIR}, dirs


def test_test_job_requires_its_own_env():
    script = _script("deploy-test")
    assert '"$TEST_DIR/services/.env"' in script
    assert 'cd "$TEST_DIR"' in script


def test_prod_job_stays_on_prod_checkout():
    dirs = _dirs(_script("deploy-production"))
    assert dirs and all(d == PROD_DIR for d in dirs), dirs
    assert "git reset --hard origin/main" in _script("deploy-production")


def test_both_deploys_still_gated_by_tests():
    for job in ("deploy-test", "deploy-production"):
        assert WF["jobs"][job]["needs"] == "tests"


def test_deploys_do_mesmo_ambiente_nao_rodam_ao_mesmo_tempo():
    """Regressão de 27/11/2026: dois merges seguidos em develop (PRs #116 e #117).

    Os dois deploys de teste rodaram juntos e o segundo falhou no
    ``docker compose up`` com "container name /saira-redis-test is already in
    use". Cada job de deploy precisa de um grupo de concorrência fixo e próprio,
    que enfileira em vez de cancelar o deploy em andamento.
    """
    grupos = {}
    for job in ("deploy-test", "deploy-production"):
        conc = WF["jobs"][job].get("concurrency")
        assert isinstance(conc, dict), f"{job} sem concurrency: deploys simultâneos colidem"
        assert conc.get("cancel-in-progress") is False, f"{job} não pode cancelar deploy no meio"
        assert "${{" not in conc["group"], f"{job}: grupo precisa ser fixo por ambiente"
        grupos[job] = conc["group"]
    assert grupos["deploy-test"] != grupos["deploy-production"], grupos


def test_fila_de_deploy_nao_segura_os_testes():
    """A fila é por job de deploy: no nível do workflow ela atrasaria as suítes."""
    assert "concurrency" not in WF
    assert "concurrency" not in WF["jobs"]["tests"]
