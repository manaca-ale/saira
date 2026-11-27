"""coletar.sh: o comando que empacota os manifestos no servidor (sem rede)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "coletar.sh"
BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None, reason="precisa de bash e tar")
def test_manifests_command_packs_the_event_manifests(tmp_path):
    # Regressão da R0 de 26/11/2026: `tar c --wildcards 'sim*.json'` não achava nada
    # e a coleta trazia 0 manifestos de 20, sem erro.
    events = tmp_path / "events"
    (events / "arquivo" / "202611").mkdir(parents=True)
    for name in ("sim0-a.json", "sim0-a.json.lock", "sim0-a.json.processed", "evt-real.json",
                 "arquivo/202611/sim0-b.json", "arquivo/202611/sim0-b.json.processed"):
        (events / name).write_text("{}", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    cmd = subprocess.run([BASH, str(SCRIPT), "--cmd-manifestos", events.as_posix()],
                         capture_output=True, text=True, check=True).stdout
    packed = subprocess.run([BASH, "-c", cmd], capture_output=True, check=True).stdout
    subprocess.run(["tar", "xf", "-", "-C", out.as_posix()], input=packed, check=True, cwd=tmp_path)
    assert sorted(p.name for p in out.iterdir()) == ["sim0-a.json", "sim0-b.json"]


@pytest.mark.skipif(BASH is None, reason="precisa de bash e tar")
def test_manifests_command_with_no_folder_gives_an_empty_archive(tmp_path):
    cmd = subprocess.run([BASH, str(SCRIPT), "--cmd-manifestos", (tmp_path / "nada").as_posix()],
                         capture_output=True, text=True, check=True).stdout
    done = subprocess.run([BASH, "-c", cmd], capture_output=True)
    assert done.returncode == 0
