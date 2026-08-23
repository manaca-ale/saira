"""Testes do watchdog de WAN (lógica pura de decisão + cliente Tenda sem rede)."""
import hashlib
import json
from pathlib import Path

import pytest

import wan_watchdog as ww


def _cfg(**over):
    base = dict(
        router_url="http://192.168.0.1", router_user="admin", router_password="x",
        check_interval_s=60.0, wan_down_reboot_s=900.0, reboot_retry_s=1800.0,
        max_reboots_per_day=3, vpn_peer="10.8.0.1", http_probe_urls=("http://p/204",),
        state_file=Path("/tmp/x.json"), ec2_base="", device_id="pi-test",
    )
    base.update(over)
    return ww.Config(**base)


def test_decide_grace_then_reboot_then_retry_spacing():
    cfg, st, day = _cfg(), ww.State(), "2026-08-23"
    t0 = 1000.0
    assert ww.decide(cfg, st, True, t0, day) is None          # saudável
    assert ww.decide(cfg, st, False, t0 + 60, day) is None    # caiu: marca down_since
    assert st.down_since == t0 + 60
    assert ww.decide(cfg, st, False, t0 + 600, day) is None   # < 15 min: blip, espera
    assert ww.decide(cfg, st, False, t0 + 60 + 901, day) == "reboot"
    ww.record_reboot(st, t0 + 60 + 901, ok=True)
    # logo depois do reboot: espera o roteador subir (retry spacing)
    assert ww.decide(cfg, st, False, t0 + 60 + 901 + 600, day) is None
    # continua morta após 30 min: insiste
    assert ww.decide(cfg, st, False, t0 + 60 + 901 + 1801, day) == "reboot"
    ww.record_reboot(st, t0 + 60 + 901 + 1801, ok=True)
    assert st.reboots_this_outage == 2 and st.total_reboots == 2


def test_decide_daily_cap_and_reset_on_new_day():
    cfg, st = _cfg(max_reboots_per_day=2), ww.State()
    st.down_since = 0.0
    for i in range(2):
        now = 10_000.0 + i * 2000
        assert ww.decide(cfg, st, False, now, "d1") == "reboot"
        ww.record_reboot(st, now, ok=True)
    # teto do dia atingido -> não reinicia mais, mesmo com WAN morta
    assert ww.decide(cfg, st, False, 30_000.0, "d1") is None
    # dia virou -> contador zera e volta a agir
    assert ww.decide(cfg, st, False, 40_000.0, "d2") == "reboot"


def test_decide_wan_up_resets_outage_and_logs_history():
    cfg, st = _cfg(), ww.State()
    st.down_since, st.reboots_this_outage = 100.0, 1
    assert ww.decide(cfg, st, True, 5000.0, "d") is None
    assert st.down_since is None and st.reboots_this_outage == 0
    assert st.history[-1]["ev"] == "wan_up" and st.history[-1]["after_reboots"] == 1


def test_state_roundtrip(tmp_path):
    st = ww.State(down_since=1.0, reboots_today=2, reboots_day="d", total_reboots=5)
    p = tmp_path / "s.json"
    ww.save_state(p, st)
    back = ww.load_state(p)
    assert back.reboots_today == 2 and back.total_reboots == 5 and back.down_since == 1.0
    assert ww.load_state(tmp_path / "missing.json").total_reboots == 0


class _FakeResp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()
        self.status = 200

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_tenda_client_login_md5_and_reboot_payload(monkeypatch):
    seen = []
    r = ww.TendaRouter("http://r", "admin", "s3cret")

    def fake_open(req, timeout=0):
        seen.append((req.full_url, req.get_method(), req.data))
        return _FakeResp({"errCode": 0})

    monkeypatch.setattr(r.opener, "open", fake_open)
    assert r.login() is True
    url, method, body = seen[0]
    assert url == "http://r/login/Auth" and method == "POST"
    assert json.loads(body) == {"username": "admin",
                                "password": hashlib.md5(b"s3cret").hexdigest()}
    r.reboot()
    url, method, body = seen[1]
    assert url == "http://r/goform/setModules"
    assert json.loads(body) == {"reboot": {"action": "reboot"}}


def test_reboot_router_treats_dropped_connection_as_success(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(ww.TendaRouter, "reachable", lambda self: True)
    monkeypatch.setattr(ww.TendaRouter, "login", lambda self: True)

    def boom(self):
        raise ConnectionResetError("reset")

    monkeypatch.setattr(ww.TendaRouter, "reboot", boom)
    ok, detail = ww.reboot_router(cfg)
    assert ok is True and "conexão encerrada" in detail


def test_reboot_router_fails_when_unreachable_or_bad_login(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(ww.TendaRouter, "reachable", lambda self: False)
    assert ww.reboot_router(cfg)[0] is False
    monkeypatch.setattr(ww.TendaRouter, "reachable", lambda self: True)
    monkeypatch.setattr(ww.TendaRouter, "login", lambda self: False)
    ok, detail = ww.reboot_router(cfg)
    assert ok is False and "login" in detail
