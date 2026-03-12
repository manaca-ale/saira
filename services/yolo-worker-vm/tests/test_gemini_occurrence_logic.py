from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import types

import pytest

from worker import config
from worker.models import GeminiUsage
from worker.schemas_gemini import GeminiInfractionReport

if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.SimpleNamespace(
        imread=lambda *args, **kwargs: None,
        imwrite=lambda *args, **kwargs: True,
    )

if "psycopg2" not in sys.modules:
    psycopg2_mod = types.ModuleType("psycopg2")
    extras_mod = types.ModuleType("psycopg2.extras")
    pool_mod = types.ModuleType("psycopg2.pool")

    extras_mod.register_uuid = lambda *args, **kwargs: None
    pool_mod.ThreadedConnectionPool = object
    psycopg2_mod.extras = extras_mod
    psycopg2_mod.pool = pool_mod

    sys.modules["psycopg2"] = psycopg2_mod
    sys.modules["psycopg2.extras"] = extras_mod
    sys.modules["psycopg2.pool"] = pool_mod

if "redis" not in sys.modules:
    redis_mod = types.ModuleType("redis")

    class _RedisStub:
        @staticmethod
        def from_url(*args, **kwargs):
            return _RedisStub()

        def ping(self):
            return True

        def publish(self, *args, **kwargs):
            return 1

    redis_mod.Redis = _RedisStub
    sys.modules["redis"] = redis_mod

from worker import main as main_mod


def _camera() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name="cam-1",
        logradouro="Rua A",
        bairro="Bairro B",
        rpa="1",
        latitude=None,
        longitude=None,
    )


def _result(report: GeminiInfractionReport) -> SimpleNamespace:
    return SimpleNamespace(
        report=report,
        usage=GeminiUsage(input_tokens=10, output_tokens=5, total_tokens=15, estimated_cost_usd=0.0001),
        latency_ms=123,
        model="gemini-2.5-flash-lite",
    )


def _report(
    *,
    infraction_confirmed: bool,
    offender_detected: bool,
    offender_types: list[str] | None,
) -> GeminiInfractionReport:
    return GeminiInfractionReport(
        infraction_confirmed=infraction_confirmed,
        confidence_0_100=88,
        evidence_summary="Resumo de evidencia.",
        waste_type="Entulho",
        material_type="Misto",
        volume_m3=0.2,
        offender_detected=offender_detected,
        offender_types=offender_types,
        vehicle_plate=None,
        vehicle_color=None,
        vehicle_model=None,
        plate_pattern=None,
        raw_reason_codes=["r1"],
        event_frame_name="2026-03-11_10-00-00.jpg",
        offender_frame_name="2026-03-11_10-00-10.jpg",
    )


def test_case_a_infraction_true_without_offender_still_records(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    jpg = tmp_path / "2026-03-11_10-00-00.jpg"
    jpg.write_bytes(b"jpg")
    seq = [jpg]
    calls: list[dict] = []

    monkeypatch.setattr(config, "GEMINI_DRY_RUN", False, raising=False)
    monkeypatch.setattr(
        main_mod,
        "analyze_with_gemini",
        lambda **_: _result(_report(infraction_confirmed=True, offender_detected=False, offender_types=None)),
    )
    monkeypatch.setattr(main_mod, "_record_detection", lambda **kwargs: calls.append(kwargs) or True)

    disposal, payload = main_mod._process_with_gemini(
        jpg=jpg,
        device_id="esp32_001",
        camera=_camera(),
        sequence_paths=seq,
        persist=True,
    )

    assert disposal is True
    assert payload["disposal"] is True
    assert payload["offender_types"] == []
    assert len(calls) == 1
    assert calls[0]["offenders_summary"] is None
    assert calls[0]["offender_rows"] == []


def test_case_b_infraction_true_with_offender_records_detection_and_offender(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jpg = tmp_path / "2026-03-11_10-00-00.jpg"
    jpg.write_bytes(b"jpg")
    seq = [jpg]
    calls: list[dict] = []

    monkeypatch.setattr(config, "GEMINI_DRY_RUN", False, raising=False)
    monkeypatch.setattr(
        main_mod,
        "analyze_with_gemini",
        lambda **_: _result(_report(infraction_confirmed=True, offender_detected=True, offender_types=["car"])),
    )
    monkeypatch.setattr(main_mod, "_record_detection", lambda **kwargs: calls.append(kwargs) or True)

    disposal, payload = main_mod._process_with_gemini(
        jpg=jpg,
        device_id="esp32_001",
        camera=_camera(),
        sequence_paths=seq,
        persist=True,
    )

    assert disposal is True
    assert payload["disposal"] is True
    assert payload["offender_types"] == ["Carro"]
    assert len(calls) == 1
    assert len(calls[0]["offender_rows"]) == 1


def test_case_c_infraction_false_does_not_record_occurrence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    jpg = tmp_path / "2026-03-11_10-00-00.jpg"
    jpg.write_bytes(b"jpg")
    seq = [jpg]
    calls: list[dict] = []

    monkeypatch.setattr(config, "GEMINI_DRY_RUN", False, raising=False)
    monkeypatch.setattr(
        main_mod,
        "analyze_with_gemini",
        lambda **_: _result(_report(infraction_confirmed=False, offender_detected=False, offender_types=None)),
    )
    monkeypatch.setattr(main_mod, "_record_detection", lambda **kwargs: calls.append(kwargs) or True)

    disposal, payload = main_mod._process_with_gemini(
        jpg=jpg,
        device_id="esp32_001",
        camera=_camera(),
        sequence_paths=seq,
        persist=True,
    )

    assert disposal is False
    assert payload["disposal"] is False
    assert calls == []


def test_case_d_error_keeps_window_for_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    device_dir = upload_dir / "esp32_001" / "2026" / "03" / "11"
    device_dir.mkdir(parents=True, exist_ok=True)
    for ts in ("10-00-00", "10-00-10", "10-00-20"):
        (device_dir / f"2026-03-11_{ts}.jpg").write_bytes(b"jpg")

    mark_calls: list[Path] = []

    monkeypatch.setattr(config, "UPLOAD_DIR", str(upload_dir), raising=False)
    monkeypatch.setattr(config, "AI_MODE", "gemini", raising=False)
    monkeypatch.setattr(config, "GEMINI_CASCADE_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "GEMINI_CASCADE_WINDOW_SECONDS", 120, raising=False)
    monkeypatch.setattr(config, "GEMINI_CASCADE_MAX_FRAMES", 12, raising=False)
    monkeypatch.setattr(config, "GEMINI_CASCADE_MIN_FRAMES", 2, raising=False)

    monkeypatch.setattr(main_mod, "resolve_camera", lambda _device_id: _camera())
    monkeypatch.setattr(main_mod, "update_camera_last_capture", lambda _camera_id: None)
    monkeypatch.setattr(
        main_mod,
        "_process_with_gemini_cascade_window",
        lambda **_: (None, {"provider": "gemini_cascade", "success": False, "error": "timeout"}),
    )
    monkeypatch.setattr(main_mod, "mark_processed", lambda image_path, *_: mark_calls.append(image_path))

    processed = main_mod.scan_and_process()
    assert processed == 0
    assert mark_calls == []
