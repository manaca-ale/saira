"""Tests do shadow Camp 53 — gate candidato `gemini-decision-1` (API de Decisões).

Garantias, na ordem em que doem se quebrarem:

1. **Log-only e falha aberta**: nunca cria detecção nem propaga exceção para a produção.
2. **Desligado por padrão**, e sem chave ou fora da lista de dispositivos não chama nada.
3. **A chave nunca aparece** em auditoria, log ou `gemini_call_log`.
4. **Mesma chamada da medição** (5 frames do gate, em ordem, resolução baixa, seis
   perguntas): mudar isso invalida a comparação com o Camp 53.
"""
from __future__ import annotations

import io
import json
import logging
import urllib.error
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from worker import _shadow_decisions as sd
from worker import _shadow_gate51, config

KEY = "chave-falsa-de-teste-123"
DEVICE = "pi-cam-001"


# ---------------------------------------------------------------- fixtures

def _write_frame(path: Path, w: int = 640, h: int = 360) -> Path:
    rng = np.random.default_rng(abs(hash(path.name)) % (2**32))
    small = rng.integers(0, 255, (h // 12, w // 12, 3), dtype=np.uint8)
    cv2.imwrite(str(path), cv2.resize(small, (w, h)), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return path


@pytest.fixture
def frames(tmp_path):
    return [_write_frame(tmp_path / f"2026-08-01_21-09-{i:02d}.jpg") for i in range(12)]


@pytest.fixture
def camera():
    return SimpleNamespace(id="cam-uuid-1", device_id=DEVICE)


@pytest.fixture
def manifest():
    return SimpleNamespace(event_id="evt-20260801_210900")


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "state"))
    sd._BREAKER.update(fails=0, open_until=0.0)
    sd._STATE.update(disabled_day=None, warned_no_key=False)
    yield
    sd._BREAKER.update(fails=0, open_until=0.0)
    sd._STATE.update(disabled_day=None, warned_no_key=False)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(config, "SHADOW_DECISIONS_ENABLED", True)
    monkeypatch.setattr(config, "SHADOW_DECISIONS_DEVICES", {DEVICE})
    monkeypatch.setattr(config, "SHADOW_DECISIONS_API_KEY", KEY)


def _response(deposit=0.42, tokens=2097):
    return {
        "answers": {
            "deposit": {"noul": deposit}, "actor_at_pile": {"noul": 0.61},
            "removal": {"noul": 0.05}, "pile_grew": {"noul": 0.33},
            "carrying_in": {"noul": 0.12},
            "scene": {"probabilities": {"EMPTY": 0.01, "TRAFFIC": 0.4, "PARKED": 0.09,
                                        "COLLECTION": 0.1, "DUMPING": 0.4}},
        },
        "usage": {"total_input_tokens": tokens},
    }


@pytest.fixture
def api(monkeypatch):
    """Cliente falso: guarda os corpos enviados e devolve `api.result` (ou levanta)."""
    fake = SimpleNamespace(bodies=[], result=_response())

    def _post(body):
        fake.bodies.append(body)
        if isinstance(fake.result, Exception):
            raise fake.result
        return fake.result

    monkeypatch.setattr(sd, "_http_post", _post)
    return fake


def _audit_rows(device=DEVICE):
    day = datetime.now(sd.BRASILIA).strftime("%Y-%m-%d")
    p = Path(config.STATE_DIR) / "shadow_decisions_audit" / day / f"{device}.jsonl"
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]


def _run(frames, camera, manifest, device=DEVICE, calls=None, **kw):
    log_call = (lambda **k: calls.append(k)) if calls is not None else None
    kw.setdefault("prod_disposal", False)
    kw.setdefault("prod_detection_id", None)
    return sd.run(frames, device, camera, manifest, log_call=log_call, **kw)


# ---------------------------------------------------------------- a chamada

def test_body_has_the_five_gate_frames_in_order(frames, camera, manifest, enabled, api):
    _run(frames, camera, manifest)

    body = api.bodies[0]
    assert body["model"] == "gemini-decision-1"
    assert list(body["questions"]) == [
        "deposit", "actor_at_pile", "removal", "pile_grew", "carrying_in", "scene"]
    blocks = body["input"]
    assert blocks[0] == {"type": "text", "text": sd.CONTEXT}
    images = [b for b in blocks if b["type"] == "image"]
    labels = [b["text"] for b in blocks[1:] if b["type"] == "text"]
    assert labels == [f"\nFrame {i} of 5:\n" for i in range(1, 6)]
    assert all(b["resolution"] == "low" and b["mime_type"] == "image/jpeg" for b in images)

    # mesma seleção do gate de produção (1º + 3 mids + último), com os bytes originais
    expected = [frames[0]] + _shadow_gate51._gate_mids(frames) + [frames[-1]]
    assert len(expected) == 5
    assert [b["data"] for b in images] == [
        sd.base64.b64encode(p.read_bytes()).decode("ascii") for p in expected]
    assert _audit_rows()[0]["frames"] == [p.name for p in expected]


def test_record_keeps_raw_probabilities_and_production_outcome(frames, camera, manifest,
                                                              enabled, api):
    calls = []
    api.result = _response(deposit=0.2371234567)
    _run(frames, camera, manifest, calls=calls, prod_disposal=True, prod_detection_id="det-1",
         prod_gate_triggered=True, prod_gate_confidence=75)

    (row,) = _audit_rows()
    assert row["deposit"] == 0.2371234567  # sem arredondar
    assert row["probabilities"] == {"deposit": 0.2371234567, "actor_at_pile": 0.61,
                                    "removal": 0.05, "pile_grew": 0.33, "carrying_in": 0.12,
                                    "scene": 0.4}
    assert row["scene"]["TRAFFIC"] == 0.4
    assert (row["fire_t20"], row["fire_t25"], row["fire_t30"]) == (True, False, False)
    assert row["prod_gate_triggered"] is True and row["prod_gate_confidence"] == 75
    assert row["prod_created_detection"] is True and row["prod_detection_id"] == "det-1"
    assert row["event_ref"] == manifest.event_id and row["window_size"] == 12
    assert row["tok_in"] == 2097 and row["cost_usd"] == pytest.approx(0.0002097)
    assert row["http_status"] == 200 and row["error"] == ""

    (call,) = calls
    assert call["agent"] == "shadow_decisions_gate" and call["success"] is True
    assert call["usage"].input_tokens == 2097 and call["usage"].output_tokens == 0
    assert call["usage"].estimated_cost_usd == pytest.approx(0.0002097)


@pytest.mark.parametrize("deposit, fires", [
    (0.199, (False, False, False)), (0.200, (True, False, False)),
    (0.25, (True, True, False)), (0.30, (True, True, True)),
])
def test_threshold_edges(frames, camera, manifest, enabled, api, deposit, fires):
    api.result = _response(deposit=deposit)
    _run(frames, camera, manifest)
    row = _audit_rows()[0]
    assert (row["fire_t20"], row["fire_t25"], row["fire_t30"]) == fires


def test_probability_reads_noul_and_choice():
    answers = _response()["answers"]
    assert sd.probability(answers, "deposit") == 0.42
    assert sd.probability(answers, "scene") == 0.4
    assert sd.probability(answers, "missing") is None
    assert sd.probability({"deposit": {"noul": "abc"}}, "deposit") is None
    assert sd.probability({"deposit": None}, "deposit") is None
    assert sd.probability(None, "deposit") is None


@pytest.mark.parametrize("bad", [
    {}, {"answers": {}}, {"answers": {"deposit": {}}}, {"answers": "x"}, ["not", "a", "dict"]])
def test_malformed_response_is_logged_as_error(frames, camera, manifest, enabled, api, bad):
    calls = []
    api.result = bad
    _run(frames, camera, manifest, calls=calls)

    (row,) = _audit_rows()
    assert row["error"].startswith("resposta sem answers[deposit]")
    assert row["deposit"] is None
    assert (row["fire_t20"], row["fire_t25"], row["fire_t30"]) == (False, False, False)
    assert calls[0]["success"] is False


# ---------------------------------------------------------------- desligado

def test_off_by_default(frames, camera, manifest, api):
    assert config.SHADOW_DECISIONS_ENABLED is False
    assert config.SHADOW_DECISIONS_DEVICES == set()
    assert config.SHADOW_DECISIONS_API_KEY == ""
    _run(frames, camera, manifest)
    assert api.bodies == [] and _audit_rows() == []


def test_device_outside_the_list_is_not_called(frames, camera, manifest, enabled, api):
    _run(frames, camera, manifest, device="esp32-cam-009")
    assert api.bodies == [] and _audit_rows("esp32-cam-009") == []


def test_no_key_never_calls_and_warns_once(frames, camera, manifest, enabled, api,
                                           monkeypatch, caplog):
    monkeypatch.setattr(config, "SHADOW_DECISIONS_API_KEY", "")
    with caplog.at_level(logging.WARNING, logger=sd.logger.name):
        _run(frames, camera, manifest)
        _run(frames, camera, manifest)
    assert api.bodies == [] and _audit_rows() == []
    assert caplog.text.count("shadow_decisions_no_key") == 1


# ---------------------------------------------------------------- falhas

def test_run_never_raises_when_the_api_is_down(frames, camera, manifest, enabled, api):
    calls = []
    api.result = TimeoutError("timed out")
    assert _run(frames, camera, manifest, calls=calls) is None

    (row,) = _audit_rows()
    assert row["http_status"] == 0 and "TimeoutError" in row["error"]
    assert row["cost_usd"] == 0 and row["deposit"] is None
    assert calls[0]["success"] is False


def test_run_never_raises_on_internal_failure(camera, manifest, enabled, api, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("falha interna")

    monkeypatch.setattr(sd.event_windows, "fit_frames_to_payload", _boom)
    assert sd.run([Path("nao-existe.jpg")], DEVICE, camera, manifest, False, None) is None
    assert api.bodies == []


def test_breaker_opens_after_consecutive_failures_and_closes(frames, camera, manifest,
                                                            enabled, api, monkeypatch):
    monkeypatch.setattr(config, "SHADOW_BEDROCK_BREAKER_FAILS", 2)
    api.result = sd.DecisionsHTTPError(503, "unavailable")
    for _ in range(4):
        _run(frames, camera, manifest)
    assert len(api.bodies) == 2  # as duas últimas janelas nem chamam
    assert [r["http_status"] for r in _audit_rows()] == [503, 503]

    sd._BREAKER["open_until"] = 0.0  # passou o tempo de espera
    api.result = _response()
    _run(frames, camera, manifest)
    assert len(api.bodies) == 3 and _audit_rows()[-1]["error"] == ""


def test_429_counts_on_the_breaker_without_retry(frames, camera, manifest, enabled, api):
    api.result = sd.DecisionsHTTPError(429, "quota")
    _run(frames, camera, manifest)
    assert len(api.bodies) == 1 and sd._BREAKER["fails"] == 1


def test_daily_budget_blocks_the_call(frames, camera, manifest, enabled, api, monkeypatch):
    monkeypatch.setattr(config, "SHADOW_DECISIONS_DAILY_BUDGET_USD", 0.0003)
    _run(frames, camera, manifest)  # 0,00021
    _run(frames, camera, manifest)  # 0,00042: estourou
    _run(frames, camera, manifest)
    assert len(api.bodies) == 2 and len(_audit_rows()) == 2
    day = datetime.now(sd.BRASILIA).strftime("%Y-%m-%d")
    assert sd._budget_spent(day) == pytest.approx(2 * 0.0002097)


def test_402_disables_until_the_next_day(frames, camera, manifest, enabled, api, caplog):
    api.result = sd.DecisionsHTTPError(402, "prepayment credits are depleted")
    with caplog.at_level(logging.WARNING, logger=sd.logger.name):
        for _ in range(3):
            _run(frames, camera, manifest)
    assert len(api.bodies) == 1
    assert caplog.text.count("shadow_decisions_credit_depleted") == 1
    assert sd._BREAKER["fails"] == 0  # 402 não é instabilidade da API

    sd._STATE["disabled_day"] = "2000-01-01"  # virou o dia
    api.result = _response()
    _run(frames, camera, manifest)
    assert len(api.bodies) == 2


# ---------------------------------------------------------------- a chave

def test_key_goes_only_in_the_header(frames, camera, manifest, enabled, monkeypatch):
    seen = {}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout):
        seen.update(url=req.full_url, headers=dict(req.header_items()), timeout=timeout,
                    body=req.data.decode("utf-8"))
        return _Resp(json.dumps(_response()).encode("utf-8"))

    monkeypatch.setattr(sd.urllib.request, "urlopen", _urlopen)
    _run(frames, camera, manifest)

    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/decisions"
    assert seen["headers"]["X-goog-api-key"] == KEY
    assert seen["timeout"] == 15
    assert KEY not in seen["body"] and KEY not in seen["url"]
    assert _audit_rows()[0]["deposit"] == 0.42


@pytest.mark.parametrize("failure", ["http", "exception", "malformed"])
def test_key_never_appears_in_any_record(frames, camera, manifest, enabled, monkeypatch,
                                         caplog, failure):
    def _urlopen(req, timeout):
        if failure == "http":
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", None,
                                         io.BytesIO(f"API key {KEY} not valid".encode()))
        if failure == "exception":
            raise OSError(f"proxy recusou x-goog-api-key={KEY}")
        return _MalformedResp(json.dumps({"error": f"echo {KEY}"}).encode("utf-8"))

    class _MalformedResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(sd.urllib.request, "urlopen", _urlopen)
    calls = []
    with caplog.at_level(logging.DEBUG):
        _run(frames, camera, manifest, calls=calls)

    (row,) = _audit_rows()
    assert row["error"]
    everything = json.dumps(row) + caplog.text + repr(calls)
    assert KEY not in everything
    assert "<chave>" in row["error"]
