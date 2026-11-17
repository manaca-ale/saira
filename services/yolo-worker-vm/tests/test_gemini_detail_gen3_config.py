"""Detail (Agent-2) knobs for Gemini 3 models (campaign 53, 2.5-flash -> 3.5-flash-lite).

gemini-3.5-flash-lite does not reason by default. With the request unchanged, detail
recall on pi-cam-001 dropped from 15/19 to 9/19; thinking_level=high + media_resolution=low
restored it. The knobs come from the environment and must:
  - default to "not sent" (production behaviour with gemini-2.5-flash is unchanged);
  - reach _call_model when set and no ModelOverride is given;
  - never leak into a shadow call that passes its own ModelOverride.
Also covers the price table used for cost logging.
"""
import json

import pytest

from worker import config
from worker import detector_gemini as dg

_REPORT = {
    "infraction_confirmed": False,
    "confidence_0_100": 10,
    "evidence_summary": "nada",
    "offender_detected": False,
}


class _Resp:
    text = json.dumps(_REPORT)
    usage_metadata = None


@pytest.fixture
def captured(monkeypatch, tmp_path):
    seen = {}

    def fake_call_model(image_paths, system_prompt, user_prompt, model_name, response_schema,
                        max_output_tokens=None, **kwargs):
        seen.update(kwargs)
        seen["model"] = model_name
        return _Resp()

    monkeypatch.setattr(dg, "_call_model", fake_call_model)
    monkeypatch.setattr(dg, "_sanitize_report", lambda report, allowed_frame_names: report)
    frame = tmp_path / "2026-11-16_10-00-00-000000-000.jpg"
    frame.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    seen["frame"] = frame
    return seen


def _run(captured, **kwargs):
    return dg.analyze_with_gemini(image_paths=[captured["frame"]], request_id="t", **kwargs)


def test_defaults_send_nothing(captured, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_DETAIL_THINKING_LEVEL", "", raising=False)
    monkeypatch.setattr(config, "GEMINI_DETAIL_MEDIA_RESOLUTION", "", raising=False)
    _run(captured)
    assert captured["thinking_level"] is None
    assert captured["media_resolution"] is None
    assert captured["model"] == config.GEMINI_MODEL


def test_env_knobs_reach_the_call(captured, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_DETAIL_THINKING_LEVEL", "high", raising=False)
    monkeypatch.setattr(config, "GEMINI_DETAIL_MEDIA_RESOLUTION", "low", raising=False)
    _run(captured)
    assert captured["thinking_level"] == "high"
    assert captured["media_resolution"] == "low"


def test_override_wins_over_env(captured, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_DETAIL_THINKING_LEVEL", "high", raising=False)
    monkeypatch.setattr(config, "GEMINI_DETAIL_MEDIA_RESOLUTION", "low", raising=False)
    _run(captured, override=dg.ModelOverride(model="gemini-3.1-flash-lite"))
    assert captured["model"] == "gemini-3.1-flash-lite"
    assert captured["thinking_level"] is None
    assert captured["media_resolution"] is None


@pytest.mark.parametrize("name,key", [
    ("gemini-2.5-flash", "gemini-2.5-flash"),
    ("gemini-2.5-flash-002", "gemini-2.5-flash"),
    ("gemini-2.5-flash-lite", "gemini-2.5-flash-lite"),
    ("gemini-3.1-flash-lite", "gemini-3.1-flash-lite"),
    ("gemini-3.5-flash-lite", "gemini-3.5-flash-lite"),
    ("GEMINI-3.5-FLASH-LITE", "gemini-3.5-flash-lite"),
])
def test_price_key(name, key):
    assert dg._price_key(name) == key


def test_list_prices():
    assert dg._MODEL_PRICES["gemini-3.5-flash-lite"] == (0.30, 2.50)
    # synchronous calls pay Standard, not Batch/Flex (0.125 / 0.75)
    assert dg._MODEL_PRICES["gemini-3.1-flash-lite"] == (0.25, 1.50)
