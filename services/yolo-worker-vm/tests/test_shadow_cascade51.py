"""Tests do shadow Camp 51 Fase B — dois gates candidatos + kimi no detail.

Três garantias inegociáveis, na ordem em que doem se quebrarem:

1. **Log-only**: nunca cria detecção nem propaga exceção para o ciclo de produção.
2. **Detail chamado UMA vez** por janela, mesmo com os dois braços disparando — chamar
   duas vezes dobraria a parte cara (o detail custa ~25x o gate).
3. **`apply_v1_gate` fiel à pós-regra de produção** — é a cópia que separa "o modelo
   errou" de "a pós-regra matou o acerto do modelo", e uma divergência aqui invalidaria
   a leitura de toda a campanha.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from worker import _shadow_gate51, config, detector_bedrock
from worker.schemas_gemini import GeminiNewLitterReport


# ---------------------------------------------------------------- fixtures

def _write_frame(path: Path, w: int = 1280, h: int = 720) -> Path:
    rng = np.random.default_rng(abs(hash(path.name)) % (2**32))
    small = rng.integers(0, 255, (h // 12, w // 12, 3), dtype=np.uint8)
    img = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return path


@pytest.fixture
def frames(tmp_path):
    return [_write_frame(tmp_path / f"2026-08-01_21-09-{i:02d}.jpg") for i in range(12)]


@pytest.fixture
def camera():
    return SimpleNamespace(name="Via Mangue III - 2", logradouro="Rua Teste",
                           bairro="Imbiribeira", rpa="RPA-1", id=15)


@pytest.fixture
def manifest():
    return SimpleNamespace(event_id="evt-20260801_210902")


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """STATE_DIR próprio por teste: audit e orçamento não vazam entre casos."""
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(config, "SHADOW_C51_ENABLED", True)
    monkeypatch.setattr(config, "SHADOW_C51_DEVICES", {"pi-cam-001"})
    monkeypatch.setattr(config, "SHADOW_C51_DAILY_BUDGET_USD", 10.0)
    _shadow_gate51._BREAKER.update({"fails": 0, "open_until": 0.0})
    yield


def _report(scene="DUMPING", fired=True, conf=92, vehicle=True, person=True, ground=True):
    return GeminiNewLitterReport(
        scene_type=scene,
        vehicle_stopped=vehicle,
        person_handling_material=person,
        new_ground_material=ground,
        new_litter_detected=fired,
        confidence_0_100=conf,
        evidence_summary="teste",
    )


def _audit_rows(tmp_path_state: str, device="pi-cam-001") -> list[dict]:
    root = Path(tmp_path_state) / "shadow_c51_audit"
    rows = []
    for f in root.rglob(f"{device}.jsonl"):
        rows += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return rows


# ---------------------------------------------------------------- apply_v1_gate

def test_v1_forces_false_when_scene_is_not_dumping():
    out = _shadow_gate51.apply_v1_gate(_report(scene="TRAFFIC", fired=True, conf=95))
    assert out.new_litter_detected is False
    assert out.confidence_0_100 == 0


def test_v1_forces_false_with_fewer_than_two_booleans():
    r = _report(scene="DUMPING", fired=True, conf=95, vehicle=True, person=False, ground=False)
    out = _shadow_gate51.apply_v1_gate(r)
    assert out.new_litter_detected is False


def test_v1_positive_override_when_dumping_and_two_of_three():
    """A prod RESGATA o caso: scene=DUMPING + 2-de-3 vira positivo mesmo com o modelo dizendo não."""
    r = _report(scene="DUMPING", fired=False, conf=10, vehicle=True, person=True, ground=False)
    out = _shadow_gate51.apply_v1_gate(r)
    assert out.new_litter_detected is True
    assert out.confidence_0_100 >= 85


def test_v1_does_not_mutate_the_input():
    """O registro precisa guardar fire_raw E fire_v1 — mutar o original perderia o raw."""
    r = _report(scene="TRAFFIC", fired=True, conf=95)
    _shadow_gate51.apply_v1_gate(r)
    assert r.new_litter_detected is True
    assert r.confidence_0_100 == 95


# ---------------------------------------------------------------- orquestração

def _patch_arms(monkeypatch, a_fire: bool, b_fire: bool, detail_calls: list):
    monkeypatch.setattr(_shadow_gate51, "_arm_gemini",
                        lambda *a, **k: {"model": "gemini-3.1-flash-lite", "fire_v1": a_fire,
                                         "fire_raw": a_fire, "cost_usd": 0.0011, "error": ""})
    monkeypatch.setattr(_shadow_gate51, "_arm_bedrock",
                        lambda *a, **k: {"model": "magistral", "fire_v1": b_fire,
                                         "fire_raw": b_fire, "cost_usd": 0.0019, "error": ""})

    def fake_converse(alias, system, user, blobs, schema, **kw):
        detail_calls.append(alias)
        return SimpleNamespace(
            report=SimpleNamespace(infraction_confirmed=True, confidence_0_100=90,
                                   waste_type="Organico", offender_detected=True,
                                   evidence_summary="ok"),
            json_valid=True, cost_usd=0.0064, latency_ms=8000, error="", tok_in=1, tok_out=1)

    monkeypatch.setattr(detector_bedrock, "converse", fake_converse)


@pytest.mark.parametrize("a_fire,b_fire,expected_calls,expected_by", [
    (True, True, 1, ["a", "b"]),   # ambos disparam -> UMA chamada, atribuída aos dois
    (True, False, 1, ["a"]),
    (False, True, 1, ["b"]),
    (False, False, 0, []),         # ninguém dispara -> detail não roda
])
def test_detail_runs_once_and_only_when_a_gate_fires(
        monkeypatch, frames, camera, manifest, a_fire, b_fire, expected_calls, expected_by):
    calls: list[str] = []
    _patch_arms(monkeypatch, a_fire, b_fire, calls)

    _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                       prod_disposal=False, prod_detection_id=None)

    assert len(calls) == expected_calls
    rows = _audit_rows(config.STATE_DIR)
    assert len(rows) == 1
    assert rows[0]["detail"]["triggered_by"] == expected_by
    assert rows[0]["detail"]["ran"] is bool(expected_calls)


def test_one_arm_failing_does_not_block_the_other(monkeypatch, frames, camera, manifest):
    def boom(*a, **k):
        raise RuntimeError("bedrock fora do ar")

    monkeypatch.setattr(_shadow_gate51, "_arm_gemini",
                        lambda *a, **k: {"model": "g", "fire_v1": True, "fire_raw": True,
                                         "cost_usd": 0.0011, "error": ""})
    monkeypatch.setattr(_shadow_gate51, "_arm_bedrock", boom)
    monkeypatch.setattr(detector_bedrock, "converse", lambda *a, **k: SimpleNamespace(
        report=None, json_valid=False, cost_usd=0.0, latency_ms=1, error="x",
        tok_in=0, tok_out=0))

    _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                       prod_disposal=False, prod_detection_id=None)

    rows = _audit_rows(config.STATE_DIR)
    assert len(rows) == 1
    assert rows[0]["arm_a"]["fire_v1"] is True
    assert "bedrock fora do ar" in rows[0]["arm_b"]["error"]


def test_audit_carries_prod_link_for_operator_ground_truth(
        monkeypatch, frames, camera, manifest):
    """Sem prod_detection_id não dá para cruzar com detections.status depois."""
    _patch_arms(monkeypatch, False, False, [])
    _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                       prod_disposal=True, prod_detection_id="abc-123")
    row = _audit_rows(config.STATE_DIR)[0]
    assert row["prod_created_detection"] is True
    assert row["prod_detection_id"] == "abc-123"
    assert row["event_ref"] == "evt-20260801_210902"


# ---------------------------------------------------------------- guardrails

def test_daily_budget_stops_and_logs(monkeypatch, frames, camera, manifest, caplog):
    monkeypatch.setattr(config, "SHADOW_C51_DAILY_BUDGET_USD", 0.001)
    calls: list[str] = []
    _patch_arms(monkeypatch, True, True, calls)

    with caplog.at_level("WARNING"):
        _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                           prod_disposal=False, prod_detection_id=None)   # gasta e estoura
        _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                           prod_disposal=False, prod_detection_id=None)   # deve ser cortada

    assert len(_audit_rows(config.STATE_DIR)) == 1, "a 2a janela deveria ter sido cortada"
    assert any("shadow_c51_budget_exhausted" in r.message for r in caplog.records), \
        "o corte precisa ser LOGADO — silenciar faria os dados parecerem completos"


def test_budget_persists_across_restart(monkeypatch, frames, camera, manifest):
    """O acumulado vive em disco: reiniciar o worker não pode zerar o teto do dia."""
    _patch_arms(monkeypatch, True, True, [])
    _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                       prod_disposal=False, prod_detection_id=None)
    from datetime import datetime
    day = datetime.now(_shadow_gate51.BRASILIA).strftime("%Y-%m-%d")
    assert _shadow_gate51._budget_spent(day) > 0


def test_disabled_device_is_a_noop(monkeypatch, frames, camera, manifest):
    monkeypatch.setattr(config, "SHADOW_C51_DEVICES", {"outra-cam"})
    _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                       prod_disposal=False, prod_detection_id=None)
    assert _audit_rows(config.STATE_DIR) == []


def test_never_raises_into_the_production_loop(monkeypatch, frames, camera, manifest):
    """O ciclo de prod não pode cair por causa do shadow, aconteça o que acontecer."""
    monkeypatch.setattr(detector_bedrock, "prepare_images",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("catastrofe")))
    _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                       prod_disposal=False, prod_detection_id=None)  # não deve levantar


def test_gate_uses_five_images_first_mids_last(monkeypatch, frames, camera, manifest):
    """5 imagens (1º + 3 mids + último), igual à prod e ao bench_gate51."""
    real_prepare = detector_bedrock.prepare_images
    seen: dict[str, list] = {}

    def spy(paths, mode="low", **kw):
        seen.setdefault("gate", list(paths))   # a 1a chamada é a do gate
        return real_prepare(paths, mode=mode, **kw)

    monkeypatch.setattr(_shadow_gate51, "_arm_gemini",
                        lambda *a, **k: {"fire_v1": False, "cost_usd": 0.0})
    monkeypatch.setattr(_shadow_gate51, "_arm_bedrock",
                        lambda *a, **k: {"fire_v1": False, "cost_usd": 0.0})
    monkeypatch.setattr(detector_bedrock, "prepare_images", spy)

    _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                       prod_disposal=False, prod_detection_id=None)

    assert len(seen["gate"]) == 5
    assert seen["gate"][0] == frames[0]
    assert seen["gate"][-1] == frames[-1]


def test_both_arms_receive_the_exact_same_bytes(monkeypatch, frames, camera, manifest):
    """Bytes diferentes entre provedores mediriam resolução, não modelo (erro do Camp 49)."""
    got: dict[str, object] = {}

    monkeypatch.setattr(_shadow_gate51, "_arm_gemini",
                        lambda gem_frames, *a, **k: got.update(
                            a_bytes=[p.read_bytes() for p in gem_frames]) or
                        {"fire_v1": False, "cost_usd": 0.0})
    monkeypatch.setattr(_shadow_gate51, "_arm_bedrock",
                        lambda blobs, *a, **k: got.update(b_bytes=list(blobs)) or
                        {"fire_v1": False, "cost_usd": 0.0})

    _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                       prod_disposal=False, prod_detection_id=None)

    assert got["a_bytes"] == got["b_bytes"]


def test_arm_b_off_skips_bedrock_and_keeps_ledger_schema(monkeypatch, frames, camera, manifest):
    """SHADOW_C51_GATE_B=off desliga só o braço B (revisão 11/08): o bedrock não é
    chamado, o registro mantém o schema e o detail dispara apenas via A."""
    calls: list[str] = []
    _patch_arms(monkeypatch, True, True, calls)

    def bedrock_must_not_run(*a, **k):
        raise AssertionError("_arm_bedrock não deveria rodar com o braço B desligado")

    monkeypatch.setattr(_shadow_gate51, "_arm_bedrock", bedrock_must_not_run)
    monkeypatch.setattr(config, "SHADOW_C51_GATE_B", "off")

    _shadow_gate51.run(frames, "pi-cam-001", camera, manifest,
                       prod_disposal=False, prod_detection_id=None)

    rows = _audit_rows(config.STATE_DIR)
    assert len(rows) == 1
    assert rows[0]["arm_b"]["disabled"] is True
    assert rows[0]["arm_b"]["fire_v1"] is False
    assert rows[0]["arm_b"]["cost_usd"] == 0.0
    assert rows[0]["detail"]["triggered_by"] == ["a"]
    assert rows[0]["detail"]["ran"] is True
    assert calls == ["kimi-k2.5"]
