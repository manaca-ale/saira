"""Testes do endurecimento do agente de campo SAIRA.

Cobrem o que dá para validar sem hardware: config à prova de brick (validação,
rejeição, clamps, safe_mode, guard de polígono), telemetria de saúde, descarte
de frame corrompido, degradação de spool, lógica do watchdog e a sonda de
calibração. O fluxo end-to-end na Pi real é validado à parte.
"""
import os
import shutil
import time
import types

import pytest

import config as cfgmod
import saira_agent as sa


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("MOTION_ENABLED", "off")
    monkeypatch.setenv("DEVICE_ID", "pi-test-001")
    monkeypatch.setenv("SPOOL_DIR", str(tmp_path / "spool"))
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setenv("VIDEO_SEG_DIR", str(tmp_path / "segs"))
    monkeypatch.setenv("SNAPSHOT_JPG", str(tmp_path / "latest.jpg"))
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "agent.log"))
    cfg = cfgmod.load_config()
    return sa.Agent(cfg)


def _stub_gate():
    g = types.SimpleNamespace(
        min_px_active=200, delta_start_px=120, warmup_seconds=90,
        event_max_s=120, event_end_quiet_s=10, _set=[],
    )
    g.set_polygon = lambda s: g._set.append(s)
    return g


# ---------------------------------------------------------------- polygon
def test_validate_polygon():
    v = sa.Agent._validate_polygon
    assert v("") is True  # vazio = frame inteiro
    assert v("[[100,100],[1100,100],[1100,600],[100,600]]") is True
    assert v("[[[100,100],[1100,100],[1100,600],[100,600]]]") is True  # aninhado
    assert v("[[0,0],[10,10]]") is False           # < 3 pontos
    assert v("[[0,0],[1,0],[1,1]]") is False        # área minúscula
    assert v("[[0,0],[5000,0],[5000,5000],[0,5000]]") is False  # fora dos limites
    assert v("não é json") is False


# ---------------------------------------------------------------- config OK
def test_apply_config_good(agent):
    body = (
        "version=2026-06-21\n"
        "timer_delay_ms=10000\n"
        "ip_cam_url=http://1.2.3.4/snap\n"
        "burst_interval_ms=2000\n"
        "idle_analyze_interval_ms=3000\n"
        "heartbeat_interval_ms=30000\n"
        "event_min_residual_px=300\n"
        "event_batch_size=4\n"
        "motion_send_pre_frame=off\n"
        "snapshot_source=rtsp\n"
        "heartbeat_mode=keepalive\n"
        "log_level=DEBUG\n"
    )
    agent._apply_config(body)
    assert agent._interval == 10.0
    assert agent._cam_url == "http://1.2.3.4/snap"
    assert agent._recalibrate_requested is True
    assert agent._burst_interval == 2.0
    assert agent._idle_analyze_interval == 3.0
    assert agent._heartbeat_interval == 30.0
    assert agent._event_min_residual_px == 300
    assert agent._event_batch_size == 4
    assert agent._send_pre_frame is False
    assert agent._snapshot_source == "rtsp"
    assert agent._heartbeat_mode == "keepalive"
    assert agent._log_level == "DEBUG"
    assert agent._config_version == "2026-06-21"
    assert agent._rejected_config == {}


# ------------------------------------------------------------ config rejeita
def test_apply_config_rejects_bad(agent):
    before = agent._interval
    body = (
        "timer_delay_ms=abc\n"
        "event_min_residual_px=-5\n"
        "event_batch_size=999\n"
        "snapshot_source=zzz\n"
        "heartbeat_mode=weird\n"
        "motion_enabled=banana\n"
        "log_level=LOUD\n"
    )
    agent._apply_config(body)
    rej = agent._rejected_config
    for key in ("timer_delay_ms", "event_min_residual_px", "event_batch_size",
                "snapshot_source", "heartbeat_mode", "motion_enabled", "log_level"):
        assert key in rej, f"esperava {key} rejeitado"
    assert agent._interval == before          # mantido
    assert agent._motion_mode == "off"        # banana ignorado
    assert agent._log_level != "LOUD"


def test_timer_clamps_not_rejects(agent):
    agent._apply_config("timer_delay_ms=1000\n")   # 1.0s < piso 5.0 -> clampa
    assert agent._interval == sa.MIN_CAPTURE_INTERVAL_S
    assert "timer_delay_ms" not in agent._rejected_config
    agent._apply_config("timer_delay_ms=99999999\n")  # acima do teto -> clampa
    assert agent._interval == 3600.0


# -------------------------------------------------------------- safe_mode
def test_safe_mode_forces_safe_state(agent):
    agent._motion_mode = "shadow"
    agent._heartbeat_mode = "keepalive"
    agent._apply_config("safe_mode=1\nmotion_enabled=on\n")
    assert agent._safe_mode is True
    assert agent._motion_mode == "off"          # forçado
    assert agent._heartbeat_mode == "image"
    # motion_enabled=on foi IGNORADO (safe pula as chaves de runtime)
    agent._apply_config("safe_mode=0\n")
    assert agent._safe_mode is False


# ------------------------------------------------------------ gate guard
def test_polygon_guard_keeps_last_good(agent):
    agent._gate = _stub_gate()
    agent._last_good_polygon = "OLD"
    good = "[[100,100],[1100,100],[1100,600],[100,600]]"
    agent._apply_config(f"pile_zone_polygon={good}\n")
    assert agent._gate._set[-1] == good
    assert agent._last_good_polygon == good
    assert "pile_zone_polygon" not in agent._rejected_config
    # degenerado: rejeita, NÃO aplica no gate, mantém o último bom
    agent._apply_config("pile_zone_polygon=[[0,0],[1,0],[1,1]]\n")
    assert agent._last_good_polygon == good
    assert len(agent._gate._set) == 1
    assert "pile_zone_polygon" in agent._rejected_config


def test_gate_tuning_clamp_and_reject(agent):
    agent._gate = _stub_gate()
    agent._apply_config("motion_min_px_active=500\nmotion_delta_start_px=5\n")
    assert agent._gate.min_px_active == 500          # válido aplicado
    assert agent._gate.delta_start_px == 120         # 5 < piso 10 -> rejeitado
    assert "motion_delta_start_px" in agent._rejected_config


# -------------------------------------------------------------- telemetria
def test_health_snapshot_shape(agent):
    snap = agent._health_snapshot()
    for key in ("device_id", "agent_version", "uptime_s", "motion_mode",
                "gate_state", "config_version", "camera_ok", "spool_depth",
                "disk_free_mb", "events_today", "rejected_config_keys",
                "safe_mode", "log_level"):
        assert key in snap
    assert snap["device_id"] == "pi-test-001"
    assert snap["gate_state"] == "off"
    assert snap["camera_ok"] is False  # nunca capturou


def test_health_snapshot_includes_zoom(agent, monkeypatch):
    """O zoom óptico atual é reportado na telemetria (alimenta o 'Zoom atual')."""
    snap = agent._health_snapshot()
    assert "zoom" in snap
    assert snap["zoom"] is None  # ainda não lido

    # Valor cacheado (ex.: após CMD_ZOOM) aparece direto no snapshot.
    agent._last_zoom = 0.42
    assert agent._health_snapshot()["zoom"] == 0.42


def test_refresh_zoom_cached_throttles(agent, monkeypatch):
    """_refresh_zoom_cached relê no máx. 1×/ZOOM_REFRESH_S e mantém o cache no None."""
    calls = {"n": 0}

    def fake_read():
        calls["n"] += 1
        return 0.5

    monkeypatch.setattr(agent, "_read_zoom", fake_read)
    agent._refresh_zoom_cached()
    assert agent._last_zoom == 0.5
    assert calls["n"] == 1
    # Dentro da janela: não relê de novo.
    agent._refresh_zoom_cached()
    assert calls["n"] == 1

    # Leitura None não sobrescreve o cache anterior.
    agent._last_zoom_read_at = 0.0  # força passar do throttle
    monkeypatch.setattr(agent, "_read_zoom", lambda: None)
    agent._refresh_zoom_cached()
    assert agent._last_zoom == 0.5


# -------------------------------------------------------- frame corrompido
def test_upload_frame_drops_corrupt(agent):
    p = agent.cfg.spool_dir / "x.jpg"
    p.write_bytes(b"isto nao e um jpeg")
    called = []
    agent._ec2_session.post = lambda *a, **k: called.append(1)
    assert agent._upload_frame(p) is False
    assert not p.exists()
    assert called == []  # nem tentou subir


def test_spool_write_failure_is_graceful(agent):
    shutil.rmtree(agent.cfg.spool_dir)  # diretório some -> write falha
    # não deve levantar exceção (degradação graciosa)
    agent._spool_and_upload(b"\xff\xd8" + b"x" * 600)


# ---------------------------------------------------------------- watchdog
def test_watchdog_overdue(agent):
    now, wall = 1000.0, 50000.0
    agent._beats = {k: now for k in ("capture", "config", "command", "telemetry")}
    agent._last_upload_at = wall
    assert agent._watchdog_overdue(now, wall) is None
    # captura travada
    agent._beats["capture"] = now - (agent.cfg.watchdog_capture_stall_s + 1)
    assert agent._watchdog_overdue(now, wall) == "thread:capture"
    # 'vivo mas mudo'
    agent._beats["capture"] = now
    agent._last_upload_at = wall - (agent.cfg.watchdog_mute_restart_s + 1)
    assert agent._watchdog_overdue(now, wall) == "mute"


def test_sd_notify_noop_without_socket(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    sa.sd_notify("WATCHDOG=1")  # não deve levantar


# ------------------------------------------------- CMD_SNAPSHOT / frescor
_VALID_JPEG = b"\xff\xd8" + b"x" * 600  # SOI válido + corpo > 500 bytes


def test_fresh_local_snapshot_age_guard(agent):
    p = agent.cfg.snapshot_jpg
    p.write_bytes(_VALID_JPEG)
    # fresco -> devolve os bytes do latest.jpg
    assert agent._fresh_local_snapshot() == _VALID_JPEG
    # velho (mtime além do teto) -> None: buffer congelado NÃO vaza como "ao vivo"
    old = time.time() - (agent.cfg.snapshot_max_age_s + 5)
    os.utime(p, (old, old))
    assert agent._fresh_local_snapshot() is None
    # corrompido/curto -> None
    p.write_bytes(b"nao-jpeg")
    assert agent._fresh_local_snapshot() is None
    # inexistente -> None
    p.unlink()
    assert agent._fresh_local_snapshot() is None


def test_snapshot_falls_back_to_http_when_buffer_stale(agent, monkeypatch):
    """CMD_SNAPSHOT: com o latest.jpg velho (cam-rtsp-buffer travado), deve subir o
    snapshot HTTP fresco, não o frame congelado."""
    p = agent.cfg.snapshot_jpg
    p.write_bytes(_VALID_JPEG)
    old = time.time() - (agent.cfg.snapshot_max_age_s + 5)
    os.utime(p, (old, old))
    http_frame = b"\xff\xd8HTTP" + b"y" * 600
    monkeypatch.setattr(agent, "_fetch_snapshot_http", lambda: http_frame)
    sent: list[bytes] = []
    monkeypatch.setattr(agent, "_spool_and_upload",
                        lambda data, **k: sent.append(data))
    agent._upload_snapshot_now()
    assert sent == [http_frame]  # usou o HTTP, não o frame congelado


def test_snapshot_uses_fresh_local_when_available(agent, monkeypatch):
    p = agent.cfg.snapshot_jpg
    p.write_bytes(_VALID_JPEG)  # recém-escrito = fresco
    monkeypatch.setattr(agent, "_fetch_snapshot_http",
                        lambda: pytest.fail("não deveria cair no HTTP com latest fresco"))
    sent: list[bytes] = []
    monkeypatch.setattr(agent, "_spool_and_upload",
                        lambda data, **k: sent.append(data))
    agent._upload_snapshot_now()
    assert sent == [_VALID_JPEG]


# ------------------------------------------------------- modo ao vivo (CMD_LIVE)
@pytest.fixture
def live_agent(agent, monkeypatch):
    """Agente com o /status stubado (o handler do CMD_LIVE reporta rejeição)."""
    monkeypatch.setattr(agent, "_post_status", lambda *a, **k: None)
    return agent


def test_live_cmd_clamps_arg(live_agent):
    live_agent._handle_live_cmd("9999")
    remaining = live_agent._live_until - time.time()
    assert 0 < remaining <= sa.LIVE_MAX_SECONDS
    assert live_agent._live_active() is True


def test_live_cmd_zero_stops(live_agent):
    live_agent._handle_live_cmd("60")
    assert live_agent._live_active() is True
    live_agent._handle_live_cmd("0")
    assert live_agent._live_until == 0.0
    assert live_agent._live_active() is False


def test_live_cmd_garbage_arg(live_agent):
    for bad in ("abc", "", "None", "60s"):
        live_agent._handle_live_cmd(bad)  # não deve levantar
        assert live_agent._live_active() is False


def test_live_rejected_in_safe_mode(live_agent):
    live_agent._safe_mode = True
    live_agent._handle_live_cmd("60")
    # kill-switch tem que segurar o live: comandos não passam por _apply_runtime_keys
    assert live_agent._live_active() is False


def test_live_expires(live_agent, monkeypatch):
    live_agent._handle_live_cmd("60")
    assert live_agent._live_active() is True
    monkeypatch.setattr(sa.time, "time", lambda: live_agent._live_until + 1)
    assert live_agent._live_active() is False


def test_health_reports_live(live_agent):
    snap = live_agent._health_snapshot()
    assert snap["live_active"] is False
    assert snap["live_remaining_s"] is None
    live_agent._handle_live_cmd("60")
    snap = live_agent._health_snapshot()
    assert snap["live_active"] is True
    assert 0 < snap["live_remaining_s"] <= 60


def test_live_skips_stale_snapshot(live_agent, monkeypatch):
    """Buffer RTSP travado (latest.jpg velho) não pode virar frame 'ao vivo'."""
    p = live_agent.cfg.snapshot_jpg
    p.write_bytes(_VALID_JPEG)
    old = time.time() - (live_agent.cfg.snapshot_max_age_s + 5)
    os.utime(p, (old, old))
    sent: list[bytes] = []
    monkeypatch.setattr(live_agent, "_upload_live_frame",
                        lambda data: sent.append(data) or True)
    live_agent._handle_live_cmd("60")
    live_agent._live_capture_once()
    assert sent == []


def test_live_dedups_by_mtime(live_agent, monkeypatch):
    """Sem keyframe novo, não sobe o mesmo JPEG de novo (4G à toa)."""
    p = live_agent.cfg.snapshot_jpg
    p.write_bytes(_VALID_JPEG)
    sent: list[bytes] = []
    monkeypatch.setattr(live_agent, "_upload_live_frame",
                        lambda data: sent.append(data) or True)
    live_agent._handle_live_cmd("60")
    live_agent._live_capture_once()
    live_agent._live_capture_once()  # mesmo mtime -> skip
    assert sent == [_VALID_JPEG]
    # keyframe novo -> sobe de novo
    newer = time.time() + 1
    os.utime(p, (newer, newer))
    live_agent._live_capture_once()
    assert len(sent) == 2


def test_live_upload_bypasses_spool(live_agent, monkeypatch):
    """REGRESSÃO (bug de campo 14/07): o frame ao vivo NÃO pode entrar no spool.

    O spool é compartilhado com a thread de captura, que drena o backlog. Como o
    `.uploaded` só é marcado depois do POST, a captura lia os pendentes antes da
    marca e reenviava o frame que o live acabara de subir — 2× o mesmo arquivo,
    dobrando o 4G (medido em prod: 41 uploads para 21 arquivos distintos).
    """
    p = live_agent.cfg.snapshot_jpg
    p.write_bytes(_VALID_JPEG)

    class _Resp:
        status_code = 200

    posted: list = []
    monkeypatch.setattr(
        live_agent._ec2_session, "post",
        lambda *a, **k: (posted.append(k.get("files")), _Resp())[1],
    )
    live_agent._handle_live_cmd("60")
    live_agent._live_capture_once()
    assert len(posted) == 1                                    # subiu uma vez
    assert list(live_agent.cfg.spool_dir.glob("*.jpg")) == []  # nada p/ a captura re-enviar


# ------------------------------------------- circuit-breaker do fallback HTTP
def _fake_monotonic(monkeypatch):
    """Relógio monotônico controlável para os testes de breaker."""
    clock = {"t": 1000.0}
    monkeypatch.setattr(sa.time, "monotonic", lambda: clock["t"])
    return clock


def test_http_breaker_opens_and_stops_hammering(agent, monkeypatch):
    """Após N falhas consecutivas o breaker abre e PARA de tocar a porta 80
    durante o cooldown (a dor de campo: ~800 erros martelando o snapshot.cgi)."""
    _fake_monotonic(monkeypatch)
    calls = {"n": 0}

    def fail():
        calls["n"] += 1
        return None

    monkeypatch.setattr(agent, "_fetch_snapshot_http", fail)

    for _ in range(sa.HTTP_BREAKER_FAILS):
        assert agent._fetch_snapshot_http_guarded() is None
    assert calls["n"] == sa.HTTP_BREAKER_FAILS
    assert agent._http_fail_count >= sa.HTTP_BREAKER_FAILS
    assert agent._http_backoff_s == sa.HTTP_BREAKER_BASE_S

    # dentro do cooldown: NÃO chama a porta 80 (breaker segura)
    for _ in range(10):
        assert agent._fetch_snapshot_http_guarded() is None
    assert calls["n"] == sa.HTTP_BREAKER_FAILS  # nenhuma chamada nova


def test_http_breaker_half_open_probe(agent, monkeypatch):
    """No fim do cooldown, 1 probe (half-open); se falhar, reabre com backoff 2×."""
    clock = _fake_monotonic(monkeypatch)
    monkeypatch.setattr(agent, "_fetch_snapshot_http", lambda: None)

    for _ in range(sa.HTTP_BREAKER_FAILS):
        agent._fetch_snapshot_http_guarded()
    assert agent._http_backoff_s == sa.HTTP_BREAKER_BASE_S

    clock["t"] += sa.HTTP_BREAKER_BASE_S + 1  # cooldown expirou
    calls = {"n": 0}
    monkeypatch.setattr(agent, "_fetch_snapshot_http",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    agent._fetch_snapshot_http_guarded()  # probe (retorna None do setitem)
    assert calls["n"] == 1                 # tocou a porta 80 exatamente 1×
    assert agent._http_backoff_s == sa.HTTP_BREAKER_BASE_S * 2  # backoff dobrou


def test_http_breaker_backoff_caps(agent, monkeypatch):
    """O backoff satura em HTTP_BREAKER_MAX_S (não cresce sem limite)."""
    clock = _fake_monotonic(monkeypatch)
    monkeypatch.setattr(agent, "_fetch_snapshot_http", lambda: None)
    for _ in range(sa.HTTP_BREAKER_FAILS):
        agent._fetch_snapshot_http_guarded()
    for _ in range(20):  # muitas reaberturas
        clock["t"] = agent._http_breaker_until + 1
        agent._fetch_snapshot_http_guarded()
    assert agent._http_backoff_s == sa.HTTP_BREAKER_MAX_S


def test_http_breaker_closes_on_recovery(agent, monkeypatch):
    """Sucesso do probe fecha o breaker e zera o backoff/contador."""
    clock = _fake_monotonic(monkeypatch)
    state = {"ok": False}
    monkeypatch.setattr(
        agent, "_fetch_snapshot_http",
        lambda: (_VALID_JPEG if state["ok"] else None),
    )
    for _ in range(sa.HTTP_BREAKER_FAILS):
        agent._fetch_snapshot_http_guarded()
    assert agent._http_fail_count >= sa.HTTP_BREAKER_FAILS

    clock["t"] += sa.HTTP_BREAKER_BASE_S + 1
    state["ok"] = True
    data = agent._fetch_snapshot_http_guarded()
    assert data == _VALID_JPEG
    assert agent._http_fail_count == 0
    assert agent._http_backoff_s == 0.0
    assert agent._http_breaker_until == 0.0


def test_health_reports_http_breaker(agent, monkeypatch):
    """A telemetria expõe o breaker engatado (sinal p/ o alerta do backend)."""
    _fake_monotonic(monkeypatch)
    assert agent._health_snapshot()["http_fallback_breaker"] is False
    monkeypatch.setattr(agent, "_fetch_snapshot_http", lambda: None)
    for _ in range(sa.HTTP_BREAKER_FAILS):
        agent._fetch_snapshot_http_guarded()
    assert agent._health_snapshot()["http_fallback_breaker"] is True


def test_live_upload_failure_is_silent(live_agent, monkeypatch):
    """POST falhou: descarta e segue. Frame ao vivo é efêmero — o próximo vem em ~1s."""
    p = live_agent.cfg.snapshot_jpg
    p.write_bytes(_VALID_JPEG)

    def _boom(*a, **k):
        raise sa.requests.RequestException("rede caiu")

    monkeypatch.setattr(live_agent._ec2_session, "post", _boom)
    live_agent._handle_live_cmd("60")
    live_agent._live_capture_once()  # não deve levantar
    assert list(live_agent.cfg.spool_dir.glob("*.jpg")) == []


def test_live_does_not_change_capture_cadence(live_agent):
    """INVARIANTE: o modo ao vivo não pode tocar a cadência de captura.

    O gate conta FRAMES (consec_start) e aprende POR FRAME (lr_idle). Se ligar o
    live acelerasse o capture_loop, o gate ficaria mais sensível e a adaptação do
    fundo mudaria — gerando evento falso (e custo de Gemini) justo enquanto o
    técnico se mexe na frente da lente durante a instalação.
    """
    before = live_agent._capture_cadence()
    live_agent._handle_live_cmd("60")
    assert live_agent._live_active() is True
    assert live_agent._capture_cadence() == before


def test_live_interval_config_clamps(live_agent):
    live_agent._apply_config("live_interval_ms=100\n")   # abaixo do piso -> clampa
    assert live_agent._live_interval == 0.5
    live_agent._apply_config("live_interval_ms=999999\n")  # acima do teto -> clampa
    assert live_agent._live_interval == 10.0
    live_agent._apply_config("live_interval_ms=2000\n")
    assert live_agent._live_interval == 2.0


# ------------------------------------------------------------- calibração
def test_calibration_probe():
    import numpy as np
    import cv2
    from motion_gate import CalibrationProbe

    frame0 = np.zeros((720, 1280, 3), np.uint8)
    frame1 = frame0.copy()
    cv2.rectangle(frame1, (500, 300), (700, 450), (255, 255, 255), -1)
    j0 = cv2.imencode(".jpg", frame0)[1].tobytes()
    j1 = cv2.imencode(".jpg", frame1)[1].tobytes()

    probe = CalibrationProbe(polygon_json="")
    m0 = probe.measure(j0)
    m1 = probe.measure(j1)
    assert m0 is not None and len(m0) == 2
    assert m1 is not None and m1[1] > 0  # movimento detectado entre frames
    ann = probe.annotate(j1, ["linha 1", "linha 2"])
    assert ann is not None and ann[:2] == b"\xff\xd8"
    assert probe.measure(b"lixo") is None
