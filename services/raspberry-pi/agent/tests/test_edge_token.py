"""A Pi manda o X-Device-Token ao esp32-server quando DEVICE_TOKEN está configurado."""
import config
import saira_agent


def _cfg(monkeypatch, tmp_path, token):
    monkeypatch.setenv("SAIRA_ENV_FILE", str(tmp_path / "nao-existe.env"))
    monkeypatch.setenv("DEVICE_ID", "pi-cam-777")
    if token is None:
        monkeypatch.delenv("DEVICE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("DEVICE_TOKEN", token)
    return config.load_config()


def test_token_configured_goes_in_header(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch, tmp_path, "segredo-da-camera")
    assert saira_agent.ec2_auth_headers(cfg) == {
        "X-Device-Id": "pi-cam-777",
        "X-Device-Token": "segredo-da-camera",
    }


def test_without_token_only_device_id(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch, tmp_path, None)
    assert saira_agent.ec2_auth_headers(cfg) == {"X-Device-Id": "pi-cam-777"}


def test_blank_token_is_not_sent(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch, tmp_path, "   ")
    assert "X-Device-Token" not in saira_agent.ec2_auth_headers(cfg)
