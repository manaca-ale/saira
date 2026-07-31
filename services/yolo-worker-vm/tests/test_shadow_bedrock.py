"""Tests do shadow Bedrock (Camp 49): payload, guardrails e a garantia de log-only.

O ponto inegociável é o último grupo: `_run_shadow_bedrock` NUNCA pode escrever uma
detecção nem derrubar o ciclo de produção, aconteça o que acontecer com o Bedrock.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from worker import config, detector_bedrock
from worker.schemas_gemini import GeminiInfractionReport


# ---------------------------------------------------------------- fixtures

def _write_frame(path: Path, w: int = 1280, h: int = 720) -> Path:
    """Frame sintético 1280x720 de ~200 KB, na ordem de grandeza de um frame do Pi.

    Ruído de baixa frequência (gerado pequeno e ampliado) em vez de ruído puro: ruído
    puro não comprime e daria frames de ~1,3 MB, que fariam `fit_frames_to_payload`
    encolher a janela e mascarar o que estes testes medem.
    """
    rng = np.random.default_rng(abs(hash(path.name)) % (2**32))
    small = rng.integers(0, 255, (h // 12, w // 12, 3), dtype=np.uint8)
    img = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return path


@pytest.fixture
def frames(tmp_path):
    return [_write_frame(tmp_path / f"f{i:02d}.jpg") for i in range(12)]


@pytest.fixture(autouse=True)
def _reset_client():
    detector_bedrock.reset_client()
    detector_bedrock._json_mode.clear()
    detector_bedrock._max_out.clear()
    detector_bedrock._no_system.clear()
    yield
    detector_bedrock.reset_client()


class FakeClient:
    """Cliente bedrock-runtime falso: devolve respostas roteirizadas, uma por chamada."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def converse(self, **body):
        self.calls.append(body)
        item = self.script.pop(0) if self.script else self.script
        if isinstance(item, Exception):
            raise item
        return item


def _resp(text: str = "", tool_input=None, tok_in=100, tok_out=50):
    content = []
    if tool_input is not None:
        content.append({"toolUse": {"name": "report", "input": tool_input}})
    if text:
        content.append({"text": text})
    return {"output": {"message": {"content": content}},
            "usage": {"inputTokens": tok_in, "outputTokens": tok_out},
            "stopReason": "end_turn"}


VALID_REPORT = {
    "baseline_description": "pilha existente na guia",
    "infraction_confirmed": True,
    "confidence_0_100": 92,
    "evidence_summary": "pessoa deposita saco na pilha",
    "offender_detected": False,
}


def _install(monkeypatch, client):
    monkeypatch.setattr(detector_bedrock, "_client", client)


# ---------------------------------------------------------------- prepare_images

def test_prepare_images_downscales_and_fits(frames):
    pay = detector_bedrock.prepare_images(frames, mode="low")
    assert pay.n_images == len(frames)
    assert pay.n_dropped == 0
    assert pay.raw_bytes <= detector_bedrock.MAX_RAW_BYTES
    # 640px é bem menor que os 1280px de origem
    orig = sum(p.stat().st_size for p in frames)
    assert pay.raw_bytes < orig


def test_prepare_images_drops_uniformly_and_reports(frames):
    """Corte silencioso viraria 'sub-amostrei sem contar' — o erro que matou os camps 20/21."""
    full = detector_bedrock.prepare_images(frames, mode="low")
    budget = full.raw_bytes // 3
    pay = detector_bedrock.prepare_images(frames, mode="low", budget=budget)
    assert pay.raw_bytes <= budget
    assert pay.n_dropped == len(frames) - pay.n_images
    assert pay.n_dropped > 0


def test_even_drop_keeps_first_and_last():
    items = list(range(48))
    kept = detector_bedrock._even_drop(items, 10)
    assert len(kept) == 10
    assert kept[0] == 0 and kept[-1] == 47


# ---------------------------------------------------------------- converse: contratos

def test_converse_rejects_unknown_alias_without_raising():
    res = detector_bedrock.converse("nao-existe", "sys", "user", [b"x"], GeminiInfractionReport)
    assert res.report is None
    assert "alias desconhecido" in res.error


def test_converse_rejects_oversized_payload():
    big = [b"0" * (detector_bedrock.MAX_RAW_BYTES + 1)]
    res = detector_bedrock.converse("kimi-k2.5", "sys", "user", big, GeminiInfractionReport)
    assert "payload" in res.error


def test_converse_parses_json_in_text(monkeypatch):
    client = FakeClient([_resp(text="```json\n" + json.dumps(VALID_REPORT) + "\n```")])
    _install(monkeypatch, client)
    res = detector_bedrock.converse("kimi-k2.5", "sys", "user", [b"img"],
                                    GeminiInfractionReport, force_mode="text")
    assert res.json_valid and res.json_mode == "text"
    assert res.report.infraction_confirmed is True
    assert res.report.confidence_0_100 == 92
    assert res.cost_usd > 0
    # force_mode="text" não manda toolConfig e carrega o schema no system
    assert "toolConfig" not in client.calls[0]
    assert "NESTA ORDEM" in client.calls[0]["system"][0]["text"]


def test_converse_strips_reasoning_block(monkeypatch):
    body = "<reasoning>penso muito</reasoning>\n" + json.dumps(VALID_REPORT)
    _install(monkeypatch, FakeClient([_resp(text=body)]))
    res = detector_bedrock.converse("kimi-k2.5", "sys", "user", [b"img"],
                                    GeminiInfractionReport, force_mode="text")
    assert res.json_valid and res.report.confidence_0_100 == 92


def test_converse_degrades_when_model_ignores_toolconfig(monkeypatch):
    """O kimi aceita toolConfig e não chama a tool. Tem que degradar, não falhar."""
    client = FakeClient([_resp(text="blá blá sem json"),
                         _resp(text=json.dumps(VALID_REPORT))])
    _install(monkeypatch, client)
    res = detector_bedrock.converse("kimi-k2.5", "sys", "user", [b"img"],
                                    GeminiInfractionReport)
    assert res.json_valid and res.json_mode == "text"
    assert "toolConfig" in client.calls[0] and "toolConfig" not in client.calls[1]
    assert detector_bedrock._json_mode["kimi-k2.5"] == "text"


def test_converse_reports_missing_json(monkeypatch):
    _install(monkeypatch, FakeClient([_resp(text="sem json nenhum aqui")]))
    res = detector_bedrock.converse("kimi-k2.5", "sys", "user", [b"img"],
                                    GeminiInfractionReport, force_mode="text")
    assert not res.json_valid and "sem JSON" in res.error


# ---------------------------------------------------------------- guardrails

class Throttled(Exception):
    """Simula ThrottlingException do botocore pelo nome da classe."""


class ThrottlingException(Exception):
    pass


def test_converse_stops_at_timeout_tries(monkeypatch):
    client = FakeClient([ThrottlingException("slow down")] * 10)
    _install(monkeypatch, client)
    monkeypatch.setattr(config, "SHADOW_BEDROCK_BACKOFF_CAP_S", 0)
    res = detector_bedrock.converse("kimi-k2.5", "sys", "user", [b"img"],
                                    GeminiInfractionReport, timeout_tries=3, force_mode="text")
    assert not res.json_valid
    assert len(client.calls) == 3


def test_converse_honours_wall_clock_deadline(monkeypatch):
    """O shadow roda na thread serial do pipeline: nunca pode virar backlog."""
    _install(monkeypatch, FakeClient([ThrottlingException("slow down")] * 10))
    monkeypatch.setattr(config, "SHADOW_BEDROCK_BACKOFF_CAP_S", 30)
    started = time.monotonic()
    res = detector_bedrock.converse("kimi-k2.5", "sys", "user", [b"img"],
                                    GeminiInfractionReport, timeout_tries=5,
                                    deadline_s=1, force_mode="text")
    assert time.monotonic() - started < 5
    assert "deadline" in res.error


def test_converse_learns_max_tokens_limit(monkeypatch):
    client = FakeClient([ValueError("maxTokens exceeds the model limit of 4096"),
                         _resp(text=json.dumps(VALID_REPORT))])
    _install(monkeypatch, client)
    res = detector_bedrock.converse("kimi-k2.5", "sys", "user", [b"img"],
                                    GeminiInfractionReport, max_tokens=8192,
                                    timeout_tries=1, force_mode="text")
    assert res.json_valid
    assert detector_bedrock._max_out["kimi-k2.5"] == 4096
    assert client.calls[1]["inferenceConfig"]["maxTokens"] == 4096


# ---------------------------------------------------------------- log-only

@pytest.fixture
def shadow_env(monkeypatch, tmp_path):
    from worker import main

    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(config, "SHADOW_BEDROCK_ENABLED", True)
    monkeypatch.setattr(config, "SHADOW_BEDROCK_DEVICES", {"pi-cam-001"})
    monkeypatch.setattr(config, "SHADOW_BEDROCK_ALIAS", "kimi-k2.5")
    main._SHADOW_BEDROCK_BREAKER.update({"fails": 0, "open_until": 0.0})
    # qualquer escrita em detections é falha do teste
    for fn in ("insert_detection", "insert_offenders", "insert_notifications",
               "insert_cascade_decision", "publish_detection_event"):
        monkeypatch.setattr(main, fn, _boom(fn))
    return main


def _boom(name):
    def _raise(*a, **k):
        raise AssertionError(f"o shadow chamou {name} — deveria ser log-only")
    return _raise


def _ledger(tmp_path, device="pi-cam-001") -> list[dict]:
    root = Path(tmp_path) / "state" / "shadow_bedrock_audit"
    return [json.loads(line) for p in sorted(root.rglob("*.jsonl"))
            for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


CAMERA = SimpleNamespace(id=15, name="Residencial Via Mangue III - 2",
                         logradouro="Rua Professor Pedro Augusto Carneiro Leão",
                         bairro="Imbiribeira", rpa="RPA-1")
MANIFEST = SimpleNamespace(event_id="evt-20260731_120000")


def test_run_shadow_bedrock_writes_ledger_and_no_detection(shadow_env, monkeypatch,
                                                           tmp_path, frames):
    main = shadow_env
    captured = {}

    def fake_converse(alias, system, user, images, schema_cls, **kw):
        captured.update(alias=alias, system=system, user=user, n=len(images), kw=kw)
        return detector_bedrock.BedrockResult(
            report=GeminiInfractionReport(**VALID_REPORT), json_valid=True,
            json_mode="text", tok_in=9000, tok_out=800, latency_ms=11500,
            n_images=len(images), cost_usd=0.00657, stop_reason="end_turn")

    monkeypatch.setattr(main.detector_bedrock, "converse", fake_converse)
    main._run_shadow_bedrock(frames, "pi-cam-001", CAMERA, MANIFEST,
                             prod_disposal=False, prod_detection_id=None)

    rows = _ledger(tmp_path)
    assert len(rows) == 1
    r = rows[0]
    assert r["event_ref"] == "evt-20260731_120000"
    assert r["would_confirm"] is True and r["detail_conf"] == 92
    assert r["prod_created_detection"] is False and r["prod_detection_id"] is None
    assert r["alias"] == "kimi-k2.5" and r["model"] == "moonshotai.kimi-k2.5"
    assert r["prompt"] == "v4picam" and r["json_mode"] == "text"
    assert r["n_images"] == len(frames) and r["n_dropped"] == 0
    assert r["cost_usd"] == 0.00657 and r["latency_ms"] == 11500
    assert r["error"] == ""
    # a chamada usa o prompt V4 e o modo texto forçado
    assert "CLÁUSULA DE CATADOR" in captured["system"]
    assert captured["kw"]["force_mode"] == "text"
    # os nomes permitidos são os frames REALMENTE enviados
    assert frames[0].name in captured["user"] and frames[-1].name in captured["user"]


def test_run_shadow_bedrock_never_raises(shadow_env, monkeypatch, tmp_path, frames):
    main = shadow_env

    def explode(*a, **k):
        raise RuntimeError("bedrock caiu")

    monkeypatch.setattr(main.detector_bedrock, "converse", explode)
    main._run_shadow_bedrock(frames, "pi-cam-001", CAMERA, MANIFEST,
                             prod_disposal=True, prod_detection_id="det-1")
    assert _ledger(tmp_path) == []


def test_run_shadow_bedrock_logs_model_error(shadow_env, monkeypatch, tmp_path, frames):
    """Erro do modelo vira linha no ledger com `error` — não some."""
    main = shadow_env
    monkeypatch.setattr(main.detector_bedrock, "converse",
                        lambda *a, **k: detector_bedrock.BedrockResult(
                            error="ServiceUnavailableException: nope", latency_ms=800))
    main._run_shadow_bedrock(frames, "pi-cam-001", CAMERA, MANIFEST,
                             prod_disposal=True, prod_detection_id="det-1")
    rows = _ledger(tmp_path)
    assert len(rows) == 1
    assert rows[0]["would_confirm"] is False
    assert "ServiceUnavailable" in rows[0]["error"]
    assert rows[0]["prod_detection_id"] == "det-1"


def test_run_shadow_bedrock_respects_flags(shadow_env, monkeypatch, tmp_path, frames):
    main = shadow_env
    monkeypatch.setattr(main.detector_bedrock, "converse", _boom("converse"))
    monkeypatch.setattr(config, "SHADOW_BEDROCK_ENABLED", False)
    main._run_shadow_bedrock(frames, "pi-cam-001", CAMERA, MANIFEST, False, None)
    monkeypatch.setattr(config, "SHADOW_BEDROCK_ENABLED", True)
    main._run_shadow_bedrock(frames, "esp32_002", CAMERA, MANIFEST, False, None)
    assert _ledger(tmp_path) == []


def test_breaker_opens_after_consecutive_failures(shadow_env, monkeypatch, tmp_path, frames):
    main = shadow_env
    monkeypatch.setattr(config, "SHADOW_BEDROCK_BREAKER_FAILS", 3)
    monkeypatch.setattr(config, "SHADOW_BEDROCK_BREAKER_COOLDOWN_S", 900)
    monkeypatch.setattr(main.detector_bedrock, "converse",
                        lambda *a, **k: detector_bedrock.BedrockResult(error="boom"))
    for _ in range(3):
        main._run_shadow_bedrock(frames, "pi-cam-001", CAMERA, MANIFEST, False, None)
    assert main._shadow_bedrock_breaker_open()
    # com o breaker aberto nem chama o modelo
    monkeypatch.setattr(main.detector_bedrock, "converse", _boom("converse"))
    main._run_shadow_bedrock(frames, "pi-cam-001", CAMERA, MANIFEST, False, None)
    assert len(_ledger(tmp_path)) == 3
