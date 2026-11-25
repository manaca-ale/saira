"""O backend manda X-Admin-Token ao esp32-server quando ESP32_ADMIN_TOKEN está definido.

Sem isso, ligar a exigência de token na borda (EDGE_AUTH_REQUIRED) derrubaria
foto sob demanda, ao vivo, zoom e pedido de vídeo, que passam por /device/<id>/trigger.
"""
import importlib
import inspect

import pytest

MODULES = [
    "app.api.v1.endpoints.cameras",
    "app.api.v1.endpoints.detections",
    "app.services.daily_report_service",
]


@pytest.mark.parametrize("name", MODULES)
def test_header_sent_when_token_configured(name, monkeypatch):
    module = importlib.import_module(name)
    monkeypatch.setattr(module, "ESP32_ADMIN_TOKEN", "adm-123")
    assert module.esp32_service_headers() == {"X-Admin-Token": "adm-123"}


@pytest.mark.parametrize("name", MODULES)
def test_no_header_without_token(name, monkeypatch):
    module = importlib.import_module(name)
    monkeypatch.setattr(module, "ESP32_ADMIN_TOKEN", "")
    assert module.esp32_service_headers() == {}


@pytest.mark.parametrize("name,needle", [
    ("app.api.v1.endpoints.cameras", 'json={"cmd": "CMD_SNAPSHOT"}, headers=esp32_service_headers()'),
    ("app.api.v1.endpoints.cameras", 'json={"cmd": cmd}, headers=esp32_service_headers()'),
    ("app.api.v1.endpoints.detections", "headers=esp32_service_headers(),"),
    ("app.services.daily_report_service", "client.get(url, headers=esp32_service_headers())"),
])
def test_every_esp32_call_uses_the_header(name, needle):
    assert needle in inspect.getsource(importlib.import_module(name))
