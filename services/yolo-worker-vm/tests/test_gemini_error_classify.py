"""Tests for worker.metrics.classify_gemini_error (gate-failure alerting, item 2).

The classifier maps a (lower-cased) error message to a provider-agnostic class
so Alertmanager can page specifically on a dead gate (quota/auth) vs transient
timeout/parse. Must work for both AI Studio and Vertex error surfaces.
"""
from __future__ import annotations

import pytest

from worker.metrics import classify_gemini_error as classify


@pytest.mark.parametrize(
    "msg, expected",
    [
        # quota — the 2026-06-08/09 incident (AI Studio prepaid depleted)
        ("google.api_core.exceptions.resourceexhausted: 429 resource_exhausted", "quota"),
        ("429 prepayment credits depleted", "quota"),
        ("quota exceeded for quota metric 'generate requests'", "quota"),
        # auth — Vertex/WIF credential failures
        ("refresherror: unable to refresh access token", "auth"),
        ("could not automatically determine credentials", "auth"),
        ("permissiondenied: 403 caller does not have permission", "auth"),
        ("401 unauthenticated", "auth"),
        # transient
        ("request timeout after 30s", "timeout"),
        ("response schema validation error: missing field", "parse"),
        ("invalid json in model response", "parse"),
        # fallback
        ("some unexpected runtime error", "other"),
    ],
)
def test_classify(msg, expected):
    assert classify(msg) == expected


def test_timeout_precedes_quota():
    # a message mentioning both should classify as timeout (transient first)
    assert classify("timeout while waiting; 429 resource_exhausted") == "timeout"
