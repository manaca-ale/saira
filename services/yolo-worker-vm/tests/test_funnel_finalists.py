"""Campaign 54 funnel finalists in the worker: Decisions pre-filter, v1p gate prompt,
Gemini-3 gate knobs and the Bedrock (Nova Lite) gate.

What these tests pin down:
  - everything is OFF by default and the production gate call is unchanged;
  - the request each new stage sends is the one the benchmark measured (prompt text,
    question, frames, resolution), compared against the benchmark scripts themselves;
  - the pre-filter fails OPEN in every error path and never leaks its API key;
  - a Bedrock failure falls back to the Gemini gate instead of losing the window.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from worker import config, detector_bedrock, gate_bedrock, gate_prefilter
from worker import detector_gemini as dg
from worker import main as main_mod
from worker.models import GeminiUsage
from worker.schemas_gemini import GeminiNewLitterReport

BENCH = Path(__file__).resolve().parents[3] / "benchmarks" / "campaigns"
C53 = BENCH / "53-picam001-migration-post-25flash-2026-11-16" / "scripts"
C54 = BENCH / "54-picam001-history-replay-2026-11-18" / "scripts"
KEY = "FAKE-KEY-not-a-real-key-0123456789"
DEVICE = "pi-cam-001"
PRIOR = ("- The previous 2-minute window ALREADY had waste at this location (type: Entulho). "
         "Confirm NEW_SOLID_WASTE only if a NEW object appeared or the volume visibly increased.")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gate_report(**over) -> dict:
    base = {
        "scene_type": "DUMPING", "vehicle_stopped": False, "person_handling_material": True,
        "new_ground_material": True, "new_litter_detected": True, "confidence_0_100": 90,
        "evidence_summary": "pessoa deixa saco na pilha", "waste_type": "Entulho",
        "last_frame_has_litter": True,
    }
    base.update(over)
    return base


@pytest.fixture
def frames(tmp_path):
    out = []
    rng = np.random.default_rng(54)
    for i in range(5):
        p = tmp_path / f"2026-11-16_10-00-{i:02d}.jpg"
        small = rng.integers(0, 255, (60, 106, 3), dtype=np.uint8)
        cv2.imwrite(str(p), cv2.resize(small, (1280, 720), interpolation=cv2.INTER_CUBIC))
        out.append(p)
    return out


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "state"), raising=False)
    monkeypatch.setitem(gate_prefilter._BREAKER, "fails", 0)
    monkeypatch.setitem(gate_prefilter._BREAKER, "open_until", 0.0)
    for k in ("disabled_day", "warned_budget_day"):
        monkeypatch.setitem(gate_prefilter._STATE, k, None)
    monkeypatch.setitem(gate_prefilter._STATE, "warned_no_key", False)
    monkeypatch.setitem(gate_bedrock._BREAKER, "fails", 0)
    monkeypatch.setitem(gate_bedrock._BREAKER, "open_until", 0.0)


# ───────────────────────────────────────────────────────────── defaults: all off

def test_new_stages_are_off_by_default():
    assert config.GATE_PREFILTER_ENABLED is False
    assert config.GATE_PREFILTER_LOG_ONLY is True
    assert config.GATE_BEDROCK_ENABLED is False
    assert config.GEMINI_GATE_PROMPT_VARIANT == ""
    assert config.GEMINI_AGENT1_THINKING_LEVEL == ""
    assert config.GEMINI_AGENT1_MEDIA_RESOLUTION == ""
    assert not gate_prefilter.enabled_for(DEVICE)
    assert not gate_bedrock.enabled_for(DEVICE)


# ───────────────────────────────────────────────────────────── v1p gate prompt

def test_v1p_changes_only_the_vehicle_requirement():
    v1, v1p = dg.NEW_LITTER_SYSTEM_PROMPT, dg.NEW_LITTER_SYSTEM_PROMPT_V1P
    assert v1p != v1
    for old, new in dg._V1P_EDITS:
        assert old in v1 and old not in v1p
        assert new in v1p
    restored = v1p
    for old, new in dg._V1P_EDITS:
        restored = restored.replace(new, old)
    assert restored == v1
    assert "A vehicle is NOT required." in v1p
    assert dg.new_litter_system_prompt("") == v1
    assert dg.new_litter_system_prompt("v1p") == v1p


@pytest.mark.skipif(not (C54 / "prompts54.py").is_file(), reason="benchmarks not in this checkout")
def test_v1p_is_the_benchmark_prompt():
    prompts54 = _load(C54 / "prompts54.py", "prompts54_parity")
    assert dg.NEW_LITTER_SYSTEM_PROMPT_V1P == prompts54.GATE_PROMPTS["v1p"]


class _GateResp:
    text = json.dumps(_gate_report())
    usage_metadata = None


@pytest.fixture
def gate_call(monkeypatch):
    seen = {}

    def fake_call_model(image_paths, system_prompt, user_prompt, model_name, response_schema,
                        max_output_tokens=None, **kwargs):
        seen.update(kwargs)
        seen.update({"model": model_name, "system": system_prompt, "user": user_prompt,
                     "n_images": len(image_paths)})
        return _GateResp()

    monkeypatch.setattr(dg, "_call_model", fake_call_model)
    monkeypatch.setattr(dg._breaker, "before_call", lambda: None)
    for name in ("GEMINI_AGENT1_THINKING_LEVEL", "GEMINI_AGENT1_MEDIA_RESOLUTION",
                 "GEMINI_GATE_PROMPT_VARIANT"):
        monkeypatch.setattr(config, name, "", raising=False)
    return seen


def _gemini_gate(frames, **kwargs):
    return dg.analyze_new_litter_with_gemini(
        first_frame=frames[0], last_frame=frames[-1], mid_frames=frames[1:-1],
        request_id="t", prior_window_context=PRIOR, **kwargs)


def test_gemini_gate_defaults_are_unchanged(gate_call, frames):
    res = _gemini_gate(frames)
    assert gate_call["system"] == dg.NEW_LITTER_SYSTEM_PROMPT
    assert gate_call["thinking_level"] is None
    assert gate_call["media_resolution"] is None
    assert gate_call["thinking_budget"] == config.GEMINI_AGENT1_THINKING_BUDGET
    assert gate_call["n_images"] == 5
    assert res.report.new_litter_detected is True


def test_gemini_gate_finalist_b_knobs_reach_the_call(gate_call, frames, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_AGENT1_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setattr(config, "GEMINI_AGENT1_THINKING_LEVEL", "minimal")
    monkeypatch.setattr(config, "GEMINI_AGENT1_MEDIA_RESOLUTION", "low")
    monkeypatch.setattr(config, "GEMINI_GATE_PROMPT_VARIANT", "v1p")
    res = _gemini_gate(frames)
    assert gate_call["model"] == "gemini-3.1-flash-lite"
    assert gate_call["system"] == dg.NEW_LITTER_SYSTEM_PROMPT_V1P
    assert gate_call["thinking_level"] == "minimal"
    assert gate_call["media_resolution"] == "low"
    # the API rejects thinking_level together with thinking_budget
    assert gate_call["thinking_budget"] is None
    assert "Prior window context" in gate_call["user"] and PRIOR in gate_call["user"]
    assert res.model == "gemini-3.1-flash-lite"


def test_gemini_gate_shadow_override_ignores_the_env_knobs(gate_call, frames, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_AGENT1_THINKING_LEVEL", "minimal")
    monkeypatch.setattr(config, "GEMINI_AGENT1_MEDIA_RESOLUTION", "low")
    monkeypatch.setattr(config, "GEMINI_GATE_PROMPT_VARIANT", "v1p")
    _gemini_gate(frames, override=dg.ModelOverride(model="gemini-3.5-flash-lite"))
    assert gate_call["model"] == "gemini-3.5-flash-lite"
    assert gate_call["system"] == dg.NEW_LITTER_SYSTEM_PROMPT
    assert gate_call["thinking_level"] is None
    assert gate_call["media_resolution"] is None
    assert gate_call["thinking_budget"] == config.GEMINI_AGENT1_THINKING_BUDGET


def test_price_table_has_the_finalist_models():
    assert dg._MODEL_PRICES[dg._price_key("gemini-3.1-flash-lite")]
    assert dg._MODEL_PRICES[dg._price_key("gemini-3.8-flash")]
    assert detector_bedrock.cost("nova-lite", 1_000_000, 1_000_000) == pytest.approx(0.30)


# ───────────────────────────────────────────────────────────── Bedrock gate

@pytest.fixture
def bedrock_call(monkeypatch):
    seen = {"calls": 0, "report": _gate_report(), "error": ""}

    def fake_converse(alias, system, user, images, schema_cls, **kwargs):
        seen["calls"] += 1
        seen.update({"alias": alias, "system": system, "user": user, "images": images,
                     "schema": schema_cls, **kwargs})
        if seen["error"]:
            return detector_bedrock.BedrockResult(error=seen["error"], n_images=len(images))
        return detector_bedrock.BedrockResult(
            report=schema_cls.model_validate(seen["report"]), raw_text=json.dumps(seen["report"]),
            json_valid=True, json_mode="text", tok_in=4724, tok_out=200, latency_ms=1500,
            n_images=len(images), cost_usd=detector_bedrock.cost(alias, 4724, 200))

    monkeypatch.setattr(detector_bedrock, "converse", fake_converse)
    monkeypatch.setattr(config, "GATE_BEDROCK_ENABLED", True)
    monkeypatch.setattr(config, "GATE_BEDROCK_DEVICES", {DEVICE})
    return seen



def test_bedrock_gate_cuts_each_attempt_at_15s(bedrock_call, frames):
    # regression (campaign 54, mission 9 item 3): the gate used to inherit the shadow
    # client's 60 s read timeout per attempt; it must cut each attempt like the Gemini gate.
    _bedrock_gate(frames)
    assert bedrock_call["attempt_timeout_s"] == config.GATE_BEDROCK_ATTEMPT_TIMEOUT_S == 15
    assert bedrock_call["deadline_s"] == config.GATE_BEDROCK_DEADLINE_S


def test_converse_uses_a_client_with_the_attempt_timeout(monkeypatch):
    made = []

    class _Fake:
        def __init__(self, timeout):
            self.timeout = timeout

        def converse(self, **body):
            return {"output": {"message": {"content": [{"text": json.dumps(_gate_report())}]}},
                    "usage": {"inputTokens": 10, "outputTokens": 5}, "stopReason": "end_turn"}

    def fake_new_client(timeout):
        made.append(timeout)
        return _Fake(timeout)

    detector_bedrock.reset_client()
    monkeypatch.setattr(detector_bedrock, "_new_client", fake_new_client)
    try:
        for _ in range(2):
            res = detector_bedrock.converse("nova-lite", "s", "u", [b"x"], GeminiNewLitterReport,
                                            force_mode="text", attempt_timeout_s=15)
            assert res.error == "" and res.report is not None
        detector_bedrock.converse("nova-lite", "s", "u", [b"x"], GeminiNewLitterReport,
                                  force_mode="text")
        # one cached client per timeout; the shadow path keeps its own (60 s) client
        assert made == [15, max(10, config.SHADOW_BEDROCK_DEADLINE_S)]
    finally:
        detector_bedrock.reset_client()

def _bedrock_gate(frames):
    return gate_bedrock.analyze_new_litter_with_bedrock(
        first_frame=frames[0], last_frame=frames[-1], mid_frames=frames[1:-1],
        camera_context={"device_id": DEVICE, "camera_name": "cam"}, request_id="t",
        prior_window_context=PRIOR)


def test_bedrock_gate_sends_the_measured_request(bedrock_call, frames):
    res = _bedrock_gate(frames)
    assert bedrock_call["alias"] == "nova-lite"
    assert bedrock_call["system"] == dg.NEW_LITTER_SYSTEM_PROMPT_V1P
    assert bedrock_call["schema"] is GeminiNewLitterReport
    assert bedrock_call["force_mode"] == "text"
    assert bedrock_call["max_tokens"] == 2000
    # same user text as the Gemini gate, prior-window notice included
    assert bedrock_call["user"] == dg._new_litter_user_prompt(
        frames[0].name, frames[-1].name, {"device_id": DEVICE, "camera_name": "cam"},
        prior_window_context=PRIOR, mosaic=False, mid_frame_names=[f.name for f in frames[1:-1]])
    assert PRIOR in bedrock_call["user"]
    assert len(bedrock_call["images"]) == 5
    for blob in bedrock_call["images"]:
        img = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_COLOR)
        assert img.shape[1] == 640
    assert res.model == "amazon.nova-lite-v1:0"
    assert res.usage.input_tokens == 4724 and res.usage.output_tokens == 200
    assert res.usage.estimated_cost_usd == pytest.approx(4724 * 0.06e-6 + 200 * 0.24e-6)
    assert res.report.new_litter_detected is True and res.report.confidence_0_100 == 90


@pytest.mark.parametrize("raw, expect_fire, expect_conf", [
    # scene is not DUMPING: forced to false
    (dict(scene_type="PARKED", new_litter_detected=True, confidence_0_100=95), False, 0),
    # fewer than 2 of the 3 signals: forced to false
    (dict(person_handling_material=False, vehicle_stopped=False, new_ground_material=True), False, 0),
    # DUMPING + 2 of 3 with a hedged "false": forced to true at 85
    (dict(new_litter_detected=False, confidence_0_100=40), True, 85),
    (dict(), True, 90),
])
def test_bedrock_gate_applies_the_v1_post_rule(bedrock_call, frames, raw, expect_fire, expect_conf):
    bedrock_call["report"] = _gate_report(**raw)
    rep = _bedrock_gate(frames).report
    assert rep.new_litter_detected is expect_fire
    assert rep.confidence_0_100 == expect_conf


def test_bedrock_gate_error_raises_and_breaker_opens(bedrock_call, frames, monkeypatch):
    monkeypatch.setattr(config, "GATE_BEDROCK_BREAKER_FAILS", 2)
    bedrock_call["error"] = "ThrottlingException: slow down"
    for _ in range(2):
        with pytest.raises(gate_bedrock.BedrockGateError):
            _bedrock_gate(frames)
    assert bedrock_call["calls"] == 2
    assert gate_bedrock.breaker_open()
    with pytest.raises(gate_bedrock.BedrockGateError):
        _bedrock_gate(frames)
    assert bedrock_call["calls"] == 2   # breaker open: Bedrock is not called


def _gate_kwargs(frames):
    return dict(first_frame=frames[0], last_frame=frames[-1], mid_frames=frames[1:-1],
                camera_context={"device_id": DEVICE}, request_id="t",
                prior_window_context=PRIOR, use_mosaic=False, prompt_version="current")


@pytest.fixture
def router(monkeypatch):
    seen = {"gemini": 0, "log": []}

    def fake_gemini(**kwargs):
        seen["gemini"] += 1
        seen["gemini_kwargs"] = kwargs
        return SimpleNamespace(model="gemini-2.5-flash-lite")

    monkeypatch.setattr(main_mod, "analyze_new_litter_with_gemini", fake_gemini)
    monkeypatch.setattr(main_mod, "_log_gemini_call", lambda **kw: seen["log"].append(kw))
    return seen


def test_run_gate_uses_gemini_when_bedrock_is_off(router, frames, monkeypatch):
    monkeypatch.setattr(gate_bedrock, "analyze_new_litter_with_bedrock",
                        lambda **kw: pytest.fail("bedrock must not be called"))
    res = main_mod._run_gate(DEVICE, None, **_gate_kwargs(frames))
    assert res.model == "gemini-2.5-flash-lite"
    assert router["gemini_kwargs"] == _gate_kwargs(frames)


def test_run_gate_uses_bedrock_only_for_listed_devices(router, bedrock_call, frames):
    res = main_mod._run_gate(DEVICE, None, **_gate_kwargs(frames))
    assert res.model == "amazon.nova-lite-v1:0" and router["gemini"] == 0
    res = main_mod._run_gate("esp32_001", None, **_gate_kwargs(frames))
    assert res.model == "gemini-2.5-flash-lite" and bedrock_call["calls"] == 1


def test_run_gate_falls_back_to_gemini_when_bedrock_fails(router, bedrock_call, frames, monkeypatch):
    bedrock_call["error"] = "ModelTimeoutException"
    res = main_mod._run_gate(DEVICE, None, **_gate_kwargs(frames))
    assert res.model == "gemini-2.5-flash-lite" and router["gemini"] == 1
    assert router["log"][0]["success"] is False
    assert router["log"][0]["model"] == "amazon.nova-lite-v1:0"
    monkeypatch.setattr(config, "GATE_BEDROCK_FALLBACK_GEMINI", False)
    with pytest.raises(gate_bedrock.BedrockGateError):
        main_mod._run_gate(DEVICE, None, **_gate_kwargs(frames))
    assert router["gemini"] == 1


# ───────────────────────────────────────────────────────────── Decisions pre-filter

@pytest.mark.skipif(not (C54 / "qsets54.py").is_file(), reason="benchmarks not in this checkout")
def test_prefilter_request_is_the_benchmark_request(monkeypatch):
    monkeypatch.syspath_prepend(str(C53))
    bench_decisions = _load(C53 / "bench_decisions.py", "bench_decisions")
    monkeypatch.setitem(sys.modules, "bench_decisions", bench_decisions)
    qsets54 = _load(C54 / "qsets54.py", "qsets54_parity")
    assert gate_prefilter.QUESTIONS == qsets54.QSETS["q5"]
    assert gate_prefilter.CONTEXT == bench_decisions.CONTEXT
    assert config.GATE_PREFILTER_MODEL == bench_decisions.MODEL
    assert config.GATE_PREFILTER_ENDPOINT == bench_decisions.ENDPOINT
    assert config.GATE_PREFILTER_THRESHOLD == pytest.approx(0.30)


def test_prefilter_body_layout(frames):
    body = gate_prefilter.build_body(frames)
    assert body["model"] == "gemini-decision-1"
    assert list(body["questions"]) == ["wl_v2"]
    blocks = body["input"]
    assert blocks[0] == {"type": "text", "text": gate_prefilter.CONTEXT}
    assert len(blocks) == 1 + 2 * 5
    assert blocks[1]["text"] == "\nFrame 1 of 5:\n" and blocks[9]["text"] == "\nFrame 5 of 5:\n"
    assert blocks[2]["resolution"] == "low" and blocks[2]["mime_type"] == "image/jpeg"
    assert base64.b64decode(blocks[10]["data"]) == frames[-1].read_bytes()


@pytest.fixture
def decisions(monkeypatch):
    seen = {"calls": 0, "score": 0.10, "raise": None, "resp": None}

    def fake_post(body):
        seen["calls"] += 1
        seen["body"] = body
        if seen["raise"] is not None:
            raise seen["raise"]
        if seen["resp"] is not None:
            return seen["resp"]
        return {"answers": {"wl_v2": {"type": "noul", "noul": seen["score"],
                                      "confidence": 1 - seen["score"]}},
                "usage": {"total_tokens": 1691, "total_input_tokens": 1691, "total_output_tokens": 0}}

    monkeypatch.setattr(gate_prefilter, "_http_post", fake_post)
    monkeypatch.setattr(config, "GATE_PREFILTER_ENABLED", True)
    monkeypatch.setattr(config, "GATE_PREFILTER_DEVICES", {DEVICE})
    monkeypatch.setattr(config, "GATE_PREFILTER_API_KEY", KEY)
    monkeypatch.setattr(config, "GATE_PREFILTER_LOG_ONLY", False)
    return seen


def test_prefilter_does_nothing_when_disabled(decisions, frames, monkeypatch):
    monkeypatch.setattr(config, "GATE_PREFILTER_ENABLED", False)
    res = gate_prefilter.evaluate(frames, DEVICE)
    assert not res.ran and not res.should_skip and decisions["calls"] == 0
    monkeypatch.setattr(config, "GATE_PREFILTER_ENABLED", True)
    res = gate_prefilter.evaluate(frames, "esp32_001")
    assert not res.ran and not res.should_skip and decisions["calls"] == 0


@pytest.mark.parametrize("score, skip", [(0.10, True), (0.2999, True), (0.30, False), (0.95, False)])
def test_prefilter_threshold(decisions, frames, score, skip):
    decisions["score"] = score
    res = gate_prefilter.evaluate(frames, DEVICE, event_ref="ev1")
    assert res.ran and res.score == pytest.approx(score)
    assert res.should_skip is skip
    assert res.tok_in == 1691
    assert res.cost_usd == pytest.approx(1691 * 0.10 / 1e6)
    assert len(decisions["body"]["input"]) == 11


def test_prefilter_log_only_never_skips(decisions, frames, monkeypatch):
    monkeypatch.setattr(config, "GATE_PREFILTER_LOG_ONLY", True)
    res = gate_prefilter.evaluate(frames, DEVICE)
    assert res.ran and res.below_threshold and not res.should_skip


@pytest.mark.parametrize("failure", [
    gate_prefilter.DecisionsHTTPError(500, "internal"),
    gate_prefilter.DecisionsHTTPError(429, "quota"),
    TimeoutError(f"timed out calling ...?key={KEY}"),
    ValueError("bad json"),
])
def test_prefilter_fails_open_on_errors(decisions, frames, failure):
    decisions["raise"] = failure
    res = gate_prefilter.evaluate(frames, DEVICE)
    assert res.ran and res.score is None and res.error
    assert not res.should_skip
    assert KEY not in res.error


@pytest.mark.parametrize("resp", [
    {}, {"answers": {}}, {"answers": {"wl_v2": {"type": "noul"}}},
    {"answers": {"wl_v2": {"noul": "abc"}}}, {"answers": {"wl_v2": {"noul": 7}}}, ["not", "a", "dict"],
])
def test_prefilter_fails_open_on_answers_without_a_score(decisions, frames, resp):
    decisions["resp"] = resp
    res = gate_prefilter.evaluate(frames, DEVICE)
    assert res.score is None and not res.should_skip


def test_prefilter_fails_open_without_key_budget_or_credit(decisions, frames, monkeypatch):
    monkeypatch.setattr(config, "GATE_PREFILTER_API_KEY", "")
    res = gate_prefilter.evaluate(frames, DEVICE)
    assert not res.ran and res.reason == "no_key" and not res.should_skip
    monkeypatch.setattr(config, "GATE_PREFILTER_API_KEY", KEY)

    monkeypatch.setattr(config, "GATE_PREFILTER_DAILY_BUDGET_USD", 0.0003)
    assert gate_prefilter.evaluate(frames, DEVICE).ran      # US$ 0.00017
    assert gate_prefilter.evaluate(frames, DEVICE).ran      # US$ 0.00034 (acima do teto)
    res = gate_prefilter.evaluate(frames, DEVICE)
    assert not res.ran and res.reason == "budget_exhausted" and not res.should_skip
    monkeypatch.setattr(config, "GATE_PREFILTER_DAILY_BUDGET_USD", 1.0)

    decisions["raise"] = gate_prefilter.DecisionsHTTPError(402, "credit depleted")
    assert gate_prefilter.evaluate(frames, DEVICE).ran
    decisions["raise"] = None
    res = gate_prefilter.evaluate(frames, DEVICE)
    assert not res.ran and res.reason == "credit_depleted" and not res.should_skip


def test_prefilter_breaker_opens_after_consecutive_failures(decisions, frames, monkeypatch):
    monkeypatch.setattr(config, "GATE_PREFILTER_BREAKER_FAILS", 2)
    decisions["raise"] = gate_prefilter.DecisionsHTTPError(503, "unavailable")
    gate_prefilter.evaluate(frames, DEVICE)
    gate_prefilter.evaluate(frames, DEVICE)
    res = gate_prefilter.evaluate(frames, DEVICE)
    assert decisions["calls"] == 2 and not res.ran and res.reason == "breaker_open"


def test_prefilter_audit_has_the_score_and_never_the_key(decisions, frames, tmp_path):
    decisions["raise"] = RuntimeError(f"boom {KEY}")
    gate_prefilter.evaluate(frames, DEVICE, event_ref="ev1")
    decisions["raise"] = None
    gate_prefilter.evaluate(frames, DEVICE, event_ref="ev2")
    files = list((tmp_path / "state" / "gate_prefilter_audit").rglob(f"{DEVICE}.jsonl"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    assert KEY not in text
    assert rows[0]["wl_v2"] is None and rows[0]["skipped_gate"] is False and rows[0]["error"]
    assert rows[1]["wl_v2"] == pytest.approx(0.10) and rows[1]["skipped_gate"] is True
    assert rows[1]["frames"] == [f.name for f in frames]


def test_http_post_scrubs_the_key_from_error_bodies(monkeypatch):
    import io
    import urllib.error

    def boom(req, timeout):
        assert req.get_header("X-goog-api-key") == KEY
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                     io.BytesIO(f"API key {KEY} is invalid".encode()))

    monkeypatch.setattr(config, "GATE_PREFILTER_API_KEY", KEY)
    monkeypatch.setattr(gate_prefilter.urllib.request, "urlopen", boom)
    with pytest.raises(gate_prefilter.DecisionsHTTPError) as err:
        gate_prefilter._http_post({"model": "m"})
    assert err.value.status == 400 and KEY not in str(err.value)


# ───────────────────────────────────────────────────────────── cascade wiring

@pytest.fixture
def cascade(monkeypatch, decisions, frames):
    seen = {"saved": [], "log": [], "gate": 0}
    state = {"last_window_had_litter": True, "last_window_waste_type": "Entulho", "keep": 1}

    def fake_gate(device_id, camera, **kwargs):
        seen["gate"] += 1
        seen["gate_kwargs"] = kwargs
        raise RuntimeError("gate reached")

    monkeypatch.setattr(main_mod, "load_state", lambda device_id: dict(state))
    monkeypatch.setattr(main_mod, "save_state", lambda device_id, st: seen["saved"].append(st))
    monkeypatch.setattr(main_mod, "_log_gemini_call", lambda **kw: seen["log"].append(kw))
    monkeypatch.setattr(main_mod, "_register_gemini_call", lambda **kw: None)
    monkeypatch.setattr(main_mod, "_register_gemini_error", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "_run_gate", fake_gate)
    monkeypatch.setattr(config, "BGSUB_PREFILTER_ENABLED", False)
    monkeypatch.setattr(config, "CROP_TO_ZONE_DEVICES", set())
    monkeypatch.setattr(config, "GEMINI_GATE_MID_FRAMES", 3)
    seen["camera"] = SimpleNamespace(id=1, name="cam-1", logradouro="Rua A", bairro="B", rpa="1")
    seen["state"] = state
    return seen


def _cascade(cascade, frames):
    return main_mod._process_with_gemini_cascade_window(frames, DEVICE, cascade["camera"], False)


def test_cascade_skips_the_gate_when_the_prefilter_rejects(cascade, decisions, frames):
    disposal, payload = _cascade(cascade, frames)
    assert disposal is False
    assert payload["skipped"] is True and payload["skip_reason"] == "decisions_prefilter"
    assert payload["prefilter_score"] == pytest.approx(0.10)
    assert cascade["gate"] == 0
    # the pre-filter saw the 5 gate frames: first, 3 evenly spaced mids, last
    assert len(decisions["body"]["input"]) == 11
    # the reference frame advances; the litter flags keep their last known value
    assert cascade["saved"] == [{**cascade["state"], "last_window_last_frame": str(frames[-1])}]
    row = cascade["log"][0]
    assert row["agent"] == "prefilter" and row["model"] == "gemini-decision-1"
    assert row["success"] is True and row["usage"].input_tokens == 1691
    assert isinstance(row["usage"], GeminiUsage)


def test_cascade_reaches_the_gate_when_the_prefilter_passes_or_only_logs(cascade, decisions, frames, monkeypatch):
    decisions["score"] = 0.80
    disposal, payload = _cascade(cascade, frames)
    assert cascade["gate"] == 1 and payload.get("stage") == "agent1_new_litter"
    assert cascade["gate_kwargs"]["prior_window_context"] == PRIOR

    decisions["score"] = 0.05
    monkeypatch.setattr(config, "GATE_PREFILTER_LOG_ONLY", True)
    _cascade(cascade, frames)
    assert cascade["gate"] == 2 and cascade["saved"] == []


def test_cascade_reaches_the_gate_when_the_prefilter_errors(cascade, decisions, frames):
    decisions["raise"] = gate_prefilter.DecisionsHTTPError(500, "internal")
    _cascade(cascade, frames)
    assert cascade["gate"] == 1
    assert cascade["log"][0]["agent"] == "prefilter" and cascade["log"][0]["success"] is False


def test_cascade_does_not_call_the_prefilter_when_disabled(cascade, decisions, frames, monkeypatch):
    monkeypatch.setattr(config, "GATE_PREFILTER_ENABLED", False)
    _cascade(cascade, frames)
    assert decisions["calls"] == 0 and cascade["gate"] == 1
    assert [r for r in cascade["log"] if r["agent"] == "prefilter"] == []
