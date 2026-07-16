"""Region fallback for Gemini calls (incident 2026-07-16: global DSQ 429).

_call_model must retry on the fallback Vertex region ONLY when the primary
location returns 429/RESOURCE_EXHAUSTED, and must NOT fall back on other errors
or on success.
"""
import pytest

from worker import detector_gemini as dg


class _Models:
    def __init__(self, exc=None, result="R"):
        self.exc, self.result, self.calls = exc, result, 0

    def generate_content(self, **kw):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


class _Client:
    def __init__(self, exc=None, result="R"):
        self.models = _Models(exc, result)


def _img(tmp_path):
    p = tmp_path / "f.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0jpegbytes")
    return p


def _call(tmp_path):
    return dg._call_model([_img(tmp_path)], "sys", "usr", "gemini-2.5-flash", {"type": "object"})


@pytest.fixture(autouse=True)
def _stub_config(monkeypatch):
    # generate_config content is irrelevant to the fake client; skip genai schema build.
    monkeypatch.setattr(dg, "_build_generate_config", lambda *a, **k: None)


def test_falls_back_on_429(tmp_path, monkeypatch):
    primary = _Client(exc=Exception("429 RESOURCE_EXHAUSTED. Resource has been exhausted"))
    fb = _Client(result="FROM_FALLBACK")
    monkeypatch.setattr(dg, "_get_client", lambda: primary)
    monkeypatch.setattr(dg, "_get_fallback_client", lambda: fb)
    assert _call(tmp_path) == "FROM_FALLBACK"
    assert primary.models.calls == 1
    assert fb.models.calls == 1


def test_no_fallback_on_other_error(tmp_path, monkeypatch):
    primary = _Client(exc=ValueError("invalid argument"))
    fb = _Client(result="SHOULD_NOT_BE_USED")
    monkeypatch.setattr(dg, "_get_client", lambda: primary)
    monkeypatch.setattr(dg, "_get_fallback_client", lambda: fb)
    with pytest.raises(ValueError):
        _call(tmp_path)
    assert fb.models.calls == 0


def test_no_fallback_on_success(tmp_path, monkeypatch):
    primary = _Client(result="PRIMARY_OK")
    fb = _Client(result="FB")
    monkeypatch.setattr(dg, "_get_client", lambda: primary)
    monkeypatch.setattr(dg, "_get_fallback_client", lambda: fb)
    assert _call(tmp_path) == "PRIMARY_OK"
    assert fb.models.calls == 0


def test_fallback_disabled_reraises_429(tmp_path, monkeypatch):
    primary = _Client(exc=Exception("429 RESOURCE_EXHAUSTED"))
    monkeypatch.setattr(dg, "_get_client", lambda: primary)
    monkeypatch.setattr(dg, "_get_fallback_client", lambda: None)  # disabled
    with pytest.raises(Exception, match="RESOURCE_EXHAUSTED"):
        _call(tmp_path)


def test_is_resource_exhausted():
    assert dg._is_resource_exhausted(Exception("429 RESOURCE_EXHAUSTED"))
    e = Exception("boom")
    e.code = 429
    assert dg._is_resource_exhausted(e)
    assert not dg._is_resource_exhausted(ValueError("bad request"))
    assert not dg._is_resource_exhausted(Exception("500 INTERNAL"))
