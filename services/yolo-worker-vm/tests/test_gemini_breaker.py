"""Gemini 429 circuit breaker (G2, resilience — incident 2026-07-23).

The breaker must trip after GEMINI_BREAKER_THRESHOLD RESOURCE_EXHAUSTED failures
within GEMINI_BREAKER_WINDOW_SECONDS, short-circuit calls (before_call raises)
for the cooldown, then let a single half-open probe decide close vs reopen.
"""
import pytest

from worker import config, detector_gemini as dg
from worker.detector_gemini import GeminiBreakerOpen, _GeminiCircuitBreaker


class FakeClock:
    """Deterministic monotonic clock so cooldown/window logic needs no sleeps."""

    def __init__(self, t0: float = 1000.0):
        self.t = t0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(dg.time, "monotonic", c)
    return c


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_BREAKER_ENABLED", True)
    monkeypatch.setattr(config, "GEMINI_BREAKER_THRESHOLD", 3)
    monkeypatch.setattr(config, "GEMINI_BREAKER_WINDOW_SECONDS", 60)
    monkeypatch.setattr(config, "GEMINI_BREAKER_COOLDOWN_SECONDS", 30)


def test_disabled_is_noop(monkeypatch, clock):
    monkeypatch.setattr(config, "GEMINI_BREAKER_ENABLED", False)
    b = _GeminiCircuitBreaker()
    for _ in range(50):
        b.record_exhausted()
    b.before_call()  # must not raise
    assert b.is_open() is False


def test_opens_after_threshold(cfg, clock):
    b = _GeminiCircuitBreaker()
    b.record_exhausted()
    b.before_call()  # 1/3 — still closed
    b.record_exhausted()
    b.before_call()  # 2/3 — still closed
    b.record_exhausted()  # 3/3 — trips
    assert b.is_open() is True
    with pytest.raises(GeminiBreakerOpen):
        b.before_call()
    assert b.opens_total() == 1


def test_sliding_window_prunes_old_failures(cfg, clock):
    b = _GeminiCircuitBreaker()
    b.record_exhausted()          # t=1000
    clock.advance(61)             # first failure now outside the 60s window
    b.record_exhausted()
    b.record_exhausted()          # only 2 within the window -> below threshold 3
    assert b.is_open() is False
    b.before_call()               # must not raise


def test_cooldown_then_halfopen_probe_success_closes(cfg, clock):
    b = _GeminiCircuitBreaker()
    for _ in range(3):
        b.record_exhausted()
    assert b.is_open() is True
    clock.advance(31)             # cooldown (30s) elapsed
    b.before_call()               # transitions to half-open, lets ONE probe through
    with pytest.raises(GeminiBreakerOpen):
        b.before_call()           # concurrent call blocked while probe in flight
    b.record_success()            # probe succeeded -> close
    assert b.is_open() is False
    b.before_call()               # closed again, allows


def test_halfopen_probe_429_reopens(cfg, clock):
    b = _GeminiCircuitBreaker()
    for _ in range(3):
        b.record_exhausted()
    clock.advance(31)
    b.before_call()               # half-open probe
    b.record_exhausted()          # probe still throttled -> reopen
    assert b.is_open() is True
    assert b.opens_total() == 2
    with pytest.raises(GeminiBreakerOpen):
        b.before_call()


def test_success_resets_failure_window(cfg, clock):
    b = _GeminiCircuitBreaker()
    b.record_exhausted()
    b.record_exhausted()          # 2/3
    b.record_success()            # recovery clears the window
    b.record_exhausted()
    b.record_exhausted()          # 2/3 again, not 4 -> still closed
    assert b.is_open() is False


def test_still_open_before_cooldown(cfg, clock):
    b = _GeminiCircuitBreaker()
    for _ in range(3):
        b.record_exhausted()
    clock.advance(29)             # cooldown 30s NOT yet elapsed
    assert b.is_open() is True
    with pytest.raises(GeminiBreakerOpen):
        b.before_call()
