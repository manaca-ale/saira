"""Testes da cadeia de clipes (persistência por confirmação + adjacência).

Cobrem a lógica pura (parse do event_id, membros da cadeia), a promoção em
cadeia, a persistência por adjacência, o orçamento LRU do SD, o janitor e o
wiring de config/telemetria — tudo SEM ffmpeg (mp4 fake = bytes + utime).
A costura real (concat) é validada nos testes marcados com ffmpeg, que
rodam na Pi (ou em qualquer máquina com ffmpeg no PATH).
"""
import os
import shutil
import subprocess
import time

import pytest

import clip_store as cs
import config as cfgmod
import saira_agent as sa

FFMPEG = shutil.which("ffmpeg")

# Cadeia real do incidente de 2026-07-17 (diffs de início: 201s e 124s).
EVT_A = "evt-20260717_163625"
EVT_B = "evt-20260717_163946"
EVT_C = "evt-20260717_164150"
EVT_FAR = "evt-20260717_120000"  # horas antes — nunca encadeia


def _ts(event_id):
    ts = cs.parse_event_start(event_id)
    assert ts is not None, event_id
    return ts


def _mk_store(tmp_path, **over):
    kw = dict(
        seg_dir=tmp_path / "segs",
        archive_dir=tmp_path / "archive",
        clips_dir=tmp_path / "clips",
        archive_max_bytes=200 * 1024 * 1024,
        clip_seconds=120,
        seg_seconds=2,
        pre_roll_seconds=30,
        tail_seconds=6,
        retention_days=7,
        chain_enabled=True,
        chain_gap_s=180,
        chain_max_s=600,
        clips_max_bytes=8 * 1024 ** 3,
        event_max_s=120,
    )
    kw.update(over)
    (tmp_path / "segs").mkdir(parents=True, exist_ok=True)
    return cs.ClipStore(**kw)


def _fake_clip(store, event_id, mtime=None, size=10, confirmed=False):
    p = store.clips_dir / f"{event_id}.mp4"
    p.write_bytes(b"x" * size)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    if confirmed:
        store._confirmed_marker(event_id).touch()
    return p


def _fake_ram(store, event_id):
    d = store.archive_dir / event_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "0000_seg_000.ts").write_bytes(b"t")
    return d


def _patch_concat(store, monkeypatch, created):
    """_concat_from_ram fake: registra a chamada e materializa o mp4."""
    def fake(eid):
        created.append(eid)
        shutil.rmtree(store.archive_dir / eid, ignore_errors=True)
        return _fake_clip(store, eid)
    monkeypatch.setattr(store, "_concat_from_ram", fake)


# ------------------------------------------------------------ parse
def test_parse_event_start():
    p = cs.parse_event_start
    assert p(EVT_A) == time.mktime(time.strptime("20260717_163625", "%Y%m%d_%H%M%S"))
    assert p("evt-test-20260717_163625") == p(EVT_A)  # sintético encadeia
    assert p("evt-warmup-20260717_163625") is None    # warmup fora, por regex
    assert p("evt-20260717_163625.part") is None
    assert p("evt-20260717_163625.export") is None
    assert p("evt-20261399_251299") is None            # data inválida
    assert p("qualquer coisa") is None
    assert p("") is None
    # Virada de ano ordena por epoch, não por string.
    assert p("evt-20261231_235959") < p("evt-20270101_000001")


# ------------------------------------------------------------ chain_members
def test_chain_members_incident_chain():
    inv = {e: _ts(e) for e in (EVT_A, EVT_B, EVT_C, EVT_FAR)}
    chain = cs.chain_members(EVT_A, inv, gap_s=180, est_len_s=126)
    assert chain == [EVT_A, EVT_B, EVT_C]  # transitivo; EVT_FAR fora
    # Ancorar no MEIO ou no FIM acha a mesma cadeia (walk bidirecional).
    assert cs.chain_members(EVT_B, inv, gap_s=180, est_len_s=126) == chain
    assert cs.chain_members(EVT_C, inv, gap_s=180, est_len_s=126) == chain


def test_chain_members_gap_splits():
    inv = {e: _ts(e) for e in (EVT_A, EVT_B)}
    # gap_s=10: 201s − 126s = 75s > 10 → cadeias separadas.
    assert cs.chain_members(EVT_A, inv, gap_s=10, est_len_s=126) == [EVT_A]


def test_chain_members_anchor_bridges_neighbors():
    # Anchor sem clipe no inventário liga A e C (A~anchor~C).
    anchor = EVT_B
    inv = {e: _ts(e) for e in (EVT_A, EVT_C)}
    chain = cs.chain_members(anchor, inv, gap_s=180, est_len_s=126)
    assert chain == [EVT_A, anchor, EVT_C]


def test_chain_members_malformed_anchor():
    inv = {EVT_A: _ts(EVT_A)}
    assert cs.chain_members("evt-warmup-x", inv, gap_s=180, est_len_s=126) == ["evt-warmup-x"]


def test_chain_members_overlap_negative_gap():
    # Início do próximo ANTES do fim estimado do anterior (overlap) encadeia.
    inv = {EVT_A: _ts(EVT_A), "evt-20260717_163700": _ts("evt-20260717_163700")}
    chain = cs.chain_members(EVT_A, inv, gap_s=0, est_len_s=126)
    assert chain == [EVT_A, "evt-20260717_163700"]


# ------------------------------------------------------------ known_events
def test_known_events_tiers_and_exclusions(tmp_path):
    store = _mk_store(tmp_path)
    _fake_clip(store, EVT_A)
    _fake_ram(store, EVT_B)
    _fake_ram(store, EVT_A)  # colisão: SD vence
    (store.clips_dir / "evt-20260717_163625.part.mp4").write_bytes(b"x")
    (store.exports_dir / f"{EVT_A}.export.mp4").write_bytes(b"x")
    (store.archive_dir / "evt-warmup-20260717_120000").mkdir()
    inv = store.known_events()
    assert inv[EVT_A][1] == "sd"
    assert inv[EVT_B][1] == "ram"
    assert set(inv) == {EVT_A, EVT_B}


# ------------------------------------------------------------ persist_if_chained
def test_persist_if_chained_with_confirmed_anchor(tmp_path, monkeypatch):
    store = _mk_store(tmp_path)
    _fake_clip(store, EVT_A, confirmed=True)   # head CONFIRMADO no SD
    _fake_ram(store, EVT_B)                    # a "saída" acabou de arquivar
    created = []
    _patch_concat(store, monkeypatch, created)
    out = store.persist_if_chained(EVT_B)
    assert out is not None and created == [EVT_B]
    # E o membro seguinte também (17/07: evt_164150, +325s da âncora ≤ 600s).
    _fake_ram(store, EVT_C)
    out = store.persist_if_chained(EVT_C)
    assert out is not None and created == [EVT_B, EVT_C]


def test_persist_if_chained_unconfirmed_neighbor_is_noop(tmp_path, monkeypatch):
    """Freio da cadeia: vizinho no SD SEM confirmação não ancora — senão em
    zona de tráfego contínuo a adjacência transitiva persiste tudo."""
    store = _mk_store(tmp_path)
    _fake_clip(store, EVT_A)      # no SD, mas NÃO confirmado (adjacência)
    _fake_ram(store, EVT_B)
    created = []
    _patch_concat(store, monkeypatch, created)
    assert store.persist_if_chained(EVT_B) is None
    assert created == []


def test_persist_if_chained_no_neighbor_is_noop(tmp_path, monkeypatch):
    store = _mk_store(tmp_path)
    _fake_ram(store, EVT_B)       # nada confirmado no SD
    created = []
    _patch_concat(store, monkeypatch, created)
    assert store.persist_if_chained(EVT_B) is None
    assert created == []          # pedestre não desgasta o cartão


def test_persist_if_chained_beyond_span_is_noop(tmp_path, monkeypatch):
    store = _mk_store(tmp_path)
    _fake_clip(store, EVT_FAR, confirmed=True)   # confirmado, mas horas antes
    _fake_ram(store, EVT_B)
    created = []
    _patch_concat(store, monkeypatch, created)
    assert store.persist_if_chained(EVT_B) is None
    assert created == []
    # Encolhendo o span abaixo do gap real (201s) também barra o vizinho.
    _fake_clip(store, EVT_A, confirmed=True)
    store.chain_span_s = 100
    assert store.persist_if_chained(EVT_B) is None
    assert created == []


def test_persist_if_chained_kill_switch(tmp_path, monkeypatch):
    store = _mk_store(tmp_path, chain_enabled=False)
    _fake_clip(store, EVT_A, confirmed=True)
    _fake_ram(store, EVT_B)
    created = []
    _patch_concat(store, monkeypatch, created)
    assert store.persist_if_chained(EVT_B) is None
    assert created == []


# ------------------------------------------------------------ promote_chain
def test_promote_chain_promotes_whole_chain(tmp_path, monkeypatch):
    store = _mk_store(tmp_path)
    _fake_ram(store, EVT_A)
    _fake_ram(store, EVT_B)
    _fake_ram(store, EVT_FAR)     # alheio: não pode ser promovido
    created = []
    _patch_concat(store, monkeypatch, created)
    done = store.promote_chain(EVT_A)
    assert done == [EVT_A, EVT_B]
    assert sorted(created) == [EVT_A, EVT_B]
    assert (store.archive_dir / EVT_FAR).is_dir()
    # Só a ÂNCORA (confirmada pelo worker) ganha o marker.
    assert store._confirmed_marker(EVT_A).is_file()
    assert not store._confirmed_marker(EVT_B).is_file()


def test_promote_chain_idempotent(tmp_path):
    store = _mk_store(tmp_path)
    _fake_clip(store, EVT_A)
    _fake_clip(store, EVT_B)
    # Já no SD: _concat_from_ram REAL retorna os existentes sem ffmpeg.
    assert store.promote_chain(EVT_A) == [EVT_A, EVT_B]


def test_promote_chain_disabled_falls_back(tmp_path):
    store = _mk_store(tmp_path, chain_enabled=False)
    _fake_clip(store, EVT_A)
    _fake_ram(store, EVT_B)
    assert store.promote_chain(EVT_A) == [EVT_A]  # só o pedido, sem cadeia
    assert not (store.clips_dir / f"{EVT_B}.mp4").is_file()


def test_promote_chain_missing_member_skipped(tmp_path, monkeypatch):
    store = _mk_store(tmp_path)
    _fake_ram(store, EVT_A)
    # EVT_B aparece no inventário via RAM... não: só EVT_A existe. A cadeia
    # é só ele; membros ausentes não quebram nada.
    created = []
    _patch_concat(store, monkeypatch, created)
    assert store.promote_chain(EVT_A) == [EVT_A]


# ------------------------------------------------------------ export (sem ffmpeg)
def test_export_single_sd_member_zero_cost(tmp_path):
    store = _mk_store(tmp_path)
    p = _fake_clip(store, EVT_A)
    path, is_temp = store.export_clip(EVT_A)
    assert path == p and is_temp is False


def test_export_unknown_event(tmp_path):
    store = _mk_store(tmp_path)
    assert store.export_clip(EVT_A) == (None, False)


def test_export_chain_cap_prioritizes_anchor_and_later(tmp_path, monkeypatch):
    # 4 clipes encadeados, teto de 2 membros: ancorando no 2º, leva 2º+3º.
    ids = [EVT_A, EVT_B, EVT_C, "evt-20260717_164400"]
    store = _mk_store(tmp_path, chain_max_s=240)  # 240//120 = 2 membros
    for e in ids:
        _fake_clip(store, e)
    stitched = []
    def fake_concat(parts, out):
        stitched.append([p.name for p in parts])
        out.write_bytes(b"stitched")
        return True
    monkeypatch.setattr(store, "_concat", fake_concat)
    path, is_temp = store.export_clip(EVT_B)
    assert is_temp is True and path.parent == store.exports_dir
    assert stitched == [[f"{EVT_B}.mp4", f"{EVT_C}.mp4"]]


def test_export_stitch_failure_returns_none(tmp_path, monkeypatch):
    store = _mk_store(tmp_path)
    _fake_clip(store, EVT_A)
    _fake_clip(store, EVT_B)
    monkeypatch.setattr(store, "_concat", lambda parts, out: False)
    assert store.export_clip(EVT_A) == (None, False)


# ------------------------------------------------------------ prune / orçamento
def test_evict_clips_budget_lru(tmp_path):
    store = _mk_store(tmp_path, clips_max_bytes=25)
    now = time.time()
    _fake_clip(store, EVT_A, mtime=now - 300, size=10)   # mais antigo
    _fake_clip(store, EVT_B, mtime=now - 200, size=10)
    _fake_clip(store, EVT_C, mtime=now - 100, size=10)
    with store._persist_lock:
        store._evict_clips_budget()
    assert not (store.clips_dir / f"{EVT_A}.mp4").exists()   # LRU saiu
    assert (store.clips_dir / f"{EVT_B}.mp4").exists()
    assert (store.clips_dir / f"{EVT_C}.mp4").exists()


def test_evict_clips_budget_confirmed_last(tmp_path):
    """Ruído de cauda (adjacência) sai ANTES da evidência confirmada, mesmo
    sendo o confirmado o mais antigo."""
    store = _mk_store(tmp_path, clips_max_bytes=25)
    now = time.time()
    _fake_clip(store, EVT_A, mtime=now - 300, size=10, confirmed=True)
    _fake_clip(store, EVT_B, mtime=now - 200, size=10)
    _fake_clip(store, EVT_C, mtime=now - 100, size=10)
    with store._persist_lock:
        store._evict_clips_budget()
    assert (store.clips_dir / f"{EVT_A}.mp4").exists()       # confirmado fica
    assert not (store.clips_dir / f"{EVT_B}.mp4").exists()   # adjacência sai
    assert (store.clips_dir / f"{EVT_C}.mp4").exists()


def test_prune_retention_and_janitor(tmp_path):
    store = _mk_store(tmp_path)
    now = time.time()
    old = _fake_clip(store, EVT_A, mtime=now - 8 * 86400)    # > 7 dias
    fresh = _fake_clip(store, EVT_B, mtime=now - 3600)
    part_old = store.clips_dir / f"{EVT_C}.part.mp4"
    part_old.write_bytes(b"x")
    os.utime(part_old, (now - 7200, now - 7200))
    part_new = store.clips_dir / "evt-20260717_164400.part.mp4"
    part_new.write_bytes(b"x")
    exp_old = store.exports_dir / f"{EVT_A}.export.mp4"
    exp_old.write_bytes(b"x")
    os.utime(exp_old, (now - 7200, now - 7200))
    orphan_marker = store._confirmed_marker(EVT_FAR)   # marker sem mp4
    orphan_marker.touch()
    store.prune()
    assert not old.exists()          # retenção
    assert fresh.exists()
    assert not part_old.exists()     # janitor
    assert part_new.exists()         # recente: pode estar em uso
    assert not exp_old.exists()      # janitor
    assert not orphan_marker.exists()  # marker órfão limpo


# ------------------------------------------------------------ Agent wiring
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


def test_config_defaults():
    cfg = cfgmod.load_config()
    assert cfg.clip_chain_enabled is True
    assert cfg.clip_chain_gap_s == 180
    assert cfg.clip_chain_span_s == 600
    assert cfg.clip_chain_max_s == 600
    assert cfg.clips_max_bytes == 8 * 1024 ** 3


def test_apply_config_chain_keys(agent):
    agent._apply_config(
        "clip_chain_enabled=false\n"
        "clip_chain_gap_s=60\n"
        "clip_chain_span_s=300\n"
        "clip_chain_max_s=240\n"
        "clips_max_mb=1024\n"
    )
    assert agent._clips.chain_enabled is False
    assert agent._clips.chain_gap_s == 60
    assert agent._clips.chain_span_s == 300
    assert agent._clips.chain_max_s == 240
    assert agent._clips.clips_max_bytes == 1024 * 1024 * 1024
    assert agent._rejected_config == {}


def test_apply_config_chain_keys_rejected(agent):
    before = (agent._clips.chain_gap_s, agent._clips.chain_max_s,
              agent._clips.clips_max_bytes)
    agent._apply_config(
        "clip_chain_gap_s=-1\n"      # < 0
        "clip_chain_max_s=10\n"      # < 60
        "clips_max_mb=64\n"          # < 512
    )
    rej = agent._rejected_config
    for key in ("clip_chain_gap_s", "clip_chain_max_s", "clips_max_mb"):
        assert key in rej, f"esperava {key} rejeitado"
    assert (agent._clips.chain_gap_s, agent._clips.chain_max_s,
            agent._clips.clips_max_bytes) == before


def test_event_max_s_propagates_to_clips(agent):
    import types
    g = types.SimpleNamespace(
        min_px_active=200, delta_start_px=120, warmup_seconds=90,
        event_max_s=120, event_end_quiet_s=10,
    )
    g.set_polygon = lambda s: None
    agent._gate = g
    agent._apply_config("event_max_s=300\n")
    assert g.event_max_s == 300
    assert agent._clips.event_max_s == 300


def test_archive_and_persist_wiring(agent, monkeypatch):
    calls = []
    monkeypatch.setattr(agent._clips, "archive_event",
                        lambda eid, s, e: calls.append(("archive", eid)) or True)
    monkeypatch.setattr(agent._clips, "persist_if_chained",
                        lambda eid: calls.append(("persist", eid)))
    agent._archive_and_persist("evt-x", 1.0, 2.0)
    assert calls == [("archive", "evt-x"), ("persist", "evt-x")]


def test_archive_and_persist_skips_on_archive_fail(agent, monkeypatch):
    calls = []
    monkeypatch.setattr(agent._clips, "archive_event", lambda eid, s, e: False)
    monkeypatch.setattr(agent._clips, "persist_if_chained",
                        lambda eid: calls.append(eid))
    agent._archive_and_persist("evt-x", 1.0, 2.0)
    assert calls == []


def test_archive_and_persist_skips_on_disk_low(agent, monkeypatch):
    calls = []
    monkeypatch.setattr(agent._clips, "archive_event", lambda eid, s, e: True)
    monkeypatch.setattr(agent._clips, "persist_if_chained",
                        lambda eid: calls.append(eid))
    monkeypatch.setattr(sa.Agent, "_disk_free_mb", staticmethod(lambda p: 0))
    agent._archive_and_persist("evt-x", 1.0, 2.0)
    assert calls == []


def test_health_snapshot_has_clip_stats(agent):
    snap = agent._health_snapshot()
    assert snap["clips_count"] == 0
    assert snap["clips_mb"] == 0


def test_clip_upload_timeout_scales(agent):
    assert agent._clip_upload_timeout(0) == agent.cfg.upload_timeout_s * 4
    assert agent._clip_upload_timeout(10 * 1024 * 1024) == 209   # ~10 MB
    assert agent._clip_upload_timeout(450 * 1024 * 1024) == 900  # teto


# ------------------------------------------------------------ ffmpeg (Pi)
def _gen_segments(seg_dir, count, base_ts, seg_seconds=2):
    """Gera segmentos .ts reais e espaça os mtimes como o ring faria."""
    seg_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=duration={count * seg_seconds}:size=128x72:rate=5",
         "-c:v", "libx264", "-f", "segment", "-segment_time", str(seg_seconds),
         "-reset_timestamps", "1", str(seg_dir / "seg_%03d.ts")],
        check=True, timeout=120,
    )
    for i, seg in enumerate(sorted(seg_dir.glob("seg_*.ts"))):
        mt = base_ts + i * seg_seconds
        os.utime(seg, (mt, mt))


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg indisponível")
def test_ffmpeg_archive_persist_and_stitch(tmp_path):
    store = _mk_store(tmp_path, clip_seconds=20)
    now = time.time()
    # Evento A: segmentos ~40-20s atrás; evento B: ~18-4s atrás.
    _gen_segments(store.seg_dir, 18, now - 40)
    evt_a = time.strftime("evt-%Y%m%d_%H%M%S", time.localtime(now - 36))
    evt_b = time.strftime("evt-%Y%m%d_%H%M%S", time.localtime(now - 16))
    assert store.archive_event(evt_a, now - 36, now - 24)
    assert store.archive_event(evt_b, now - 16, now - 6)
    assert store.promote_chain(evt_a)                      # A confirmado (worker)
    assert store._confirmed_marker(evt_a).is_file()
    # B fecha no span de A confirmado → persiste por adjacência.
    # (promote_chain pode já ter levado B junto — ambos os caminhos valem.)
    store.persist_if_chained(evt_b)
    assert (store.clips_dir / f"{evt_b}.mp4").is_file()
    # Costura: um mp4 único cobrindo A+B.
    path, is_temp = store.export_clip(evt_a)
    assert is_temp is True and path.is_file() and path.parent == store.exports_dir
    probe = subprocess.run(
        [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
         "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    dur = float(probe.stdout.strip())
    single = subprocess.run(
        [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
         "format=duration", "-of", "csv=p=0",
         str(store.clips_dir / f"{evt_a}.mp4")],
        capture_output=True, text=True, timeout=60,
    )
    assert dur > float(single.stdout.strip()) * 1.5   # ≈ soma das partes
    store.cleanup_export(path, is_temp)
    assert not path.exists()
