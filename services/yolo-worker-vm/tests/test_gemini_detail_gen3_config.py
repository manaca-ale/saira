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
    # must not fall back to the gemini-2.5-flash price through the generic "flash" rule
    ("gemini-3.8-flash", "gemini-3.8-flash"),
    ("gemini-3.6-flash", "gemini-3.6-flash"),
])
def test_price_key(name, key):
    assert dg._price_key(name) == key


def test_list_prices():
    assert dg._MODEL_PRICES["gemini-3.5-flash-lite"] == (0.30, 2.50)
    # synchronous calls pay Standard, not Batch/Flex (0.125 / 0.75)
    assert dg._MODEL_PRICES["gemini-3.1-flash-lite"] == (0.25, 1.50)
    assert dg._MODEL_PRICES["gemini-3.8-flash"] == (0.75, 3.75)
    assert dg._MODEL_PRICES["gemini-3.6-flash"] == (0.75, 3.75)


def test_38_flash_cost_uses_its_own_price():
    class _Meta:
        prompt_token_count = 9163
        candidates_token_count = 420
        thoughts_token_count = 11
        total_token_count = 9594

    class _R:
        usage_metadata = _Meta()

    usage = dg._extract_usage(_R(), "gemini-3.8-flash")
    expected = 9163 / 1e6 * 0.75 + (420 + 11) / 1e6 * 3.75
    assert usage.estimated_cost_usd == pytest.approx(expected, rel=1e-3)


# --- detail-only prompt selection (main._detail_prompt_version) ---------------
def test_detail_prompt_defaults_to_global(monkeypatch):
    from worker import main
    monkeypatch.setattr(config, "GEMINI_PROMPT_VERSION", "current", raising=False)
    monkeypatch.setattr(config, "GEMINI_DETAIL_PROMPT_VERSION", "", raising=False)
    assert main._detail_prompt_version() == "current"


def test_detail_prompt_g3_switches_only_the_detail(monkeypatch):
    from worker import main
    monkeypatch.setattr(config, "GEMINI_PROMPT_VERSION", "current", raising=False)
    monkeypatch.setattr(config, "GEMINI_DETAIL_PROMPT_VERSION", "g3", raising=False)
    assert main._detail_prompt_version() == "g3"
    # the gate keeps reading the global version
    assert config.GEMINI_PROMPT_VERSION == "current"


@pytest.mark.parametrize("legacy", ["audit", "audit_v2", "v2", "v3", "current"])
def test_legacy_detail_values_stay_inert(monkeypatch, legacy):
    """These values were never read by the worker; deploying must not activate them."""
    from worker import main
    monkeypatch.setattr(config, "GEMINI_PROMPT_VERSION", "current", raising=False)
    monkeypatch.setattr(config, "GEMINI_DETAIL_PROMPT_VERSION", legacy, raising=False)
    assert main._detail_prompt_version() == "current"


def test_g3_detail_uses_the_g3_system_prompt(captured, monkeypatch):
    from worker import _prompts_g3
    seen_prompt = {}
    orig = dg._call_model

    def spy(image_paths, system_prompt, *a, **k):
        seen_prompt["system"] = system_prompt
        return orig(image_paths, system_prompt, *a, **k)

    monkeypatch.setattr(dg, "_call_model", spy)
    _run(captured, prompt_version="g3")
    assert seen_prompt["system"] == _prompts_g3.G3_DETAIL_PROMPT
