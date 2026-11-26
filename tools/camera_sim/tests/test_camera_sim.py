"""Simulador da pi-cam (tools/camera_sim): requisições iguais às da Pi, sem rede."""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import camera_sim as cs  # noqa: E402

JPEG = b"\xff\xd8" + b"\x00" * 600

# Um evento com dois lotes de 5 (-000..-004) e um lote final de 2, como os nomes reais.
EVENT_FRAMES = [
    *(f"2026-07-14_21-45-16-75411{i}-00{i}.jpg" for i in range(5)),
    *(f"2026-07-14_21-45-22-48707{i}-00{i}.jpg" for i in range(5)),
    "2026-07-14_21-45-28-116515-000.jpg", "2026-07-14_21-45-28-117000-001.jpg",
]


def _event(**over) -> dict:
    e = {"event_id": "evt-20260714_214509", "split": "dev", "estrato": "S0", "sub": "S0",
         "status": "", "dia": "2026-07-14", "inicio": "21:45:16", "fonte": "janela",
         "n_quadros": str(len(EVENT_FRAMES)), "quadros": "|".join(EVENT_FRAMES), "rodada": "R0"}
    e.update(over)
    return e


@pytest.fixture
def frames_dir(tmp_path):
    d = tmp_path / "frames"
    d.mkdir()
    for n in EVENT_FRAMES:
        (d / n).write_bytes(JPEG)
    return d


def test_batches_follow_the_pi_batch_indexes():
    b = cs.split_batches(EVENT_FRAMES)
    assert [len(x[1]) for x in b] == [5, 5, 2]
    assert [round(x[0], 1) for x in b] == [0.0, 5.7, 11.4]


def test_requests_are_the_pi_upload_batch(frames_dir):
    reqs = cs.build_requests(_event(), "http://127.0.0.1:5002/", "pi-cam-sim-001", "0",
                             lambda n: (frames_dir / n).read_bytes(),
                             manifest={"gate_fg_px": 812, "gate_delta_px": None})
    assert [r.url for r in reqs] == ["http://127.0.0.1:5002/upload-batch"] * 3
    assert all(r.headers == {"X-Device-Id": "pi-cam-sim-001"} for r in reqs)
    assert [r.data["event_state"] for r in reqs] == ["active", "active", "end"]
    assert {r.data["event_id"] for r in reqs} == {"sim0-evt-20260714_214509"}
    assert reqs[0].data["gate_fg_px"] == "812" and "gate_delta_px" not in reqs[0].data
    field, (name, data, mime) = reqs[0].files[0]
    assert (field, name, mime, data) == ("imageFile", "f000.jpg", "image/jpeg", JPEG)
    assert [f[1][0] for f in reqs[2].files] == ["f000.jpg", "f001.jpg"]


def test_speed_scales_the_gap_between_batches(frames_dir):
    reqs = cs.build_requests(_event(), "http://x", "pi-cam-sim-001", "0",
                             lambda n: JPEG, velocidade=2.0)
    assert [round(r.offset_s, 2) for r in reqs] == [0.0, 2.87, 5.68]


def test_never_the_real_camera():
    with pytest.raises(cs.SimError):
        cs.check_device("pi-cam-001")
    with pytest.raises(cs.SimError):
        cs.build_requests(_event(), "http://x", "PI-CAM-001", "0", lambda n: JPEG)


def test_aval_events_are_refused(frames_dir, tmp_path):
    with pytest.raises(cs.SimError):
        cs.run_send([_event(split="aval")], base_url="http://x", device_id="pi-cam-sim-001",
                    tag="0", frame_dirs=[frames_dir], manifest_dir=None,
                    log_path=tmp_path / "log.jsonl", seco=True, limite=10,
                    hora_original=False, intervalo_s=0, velocidade=1)


def test_build_events_reads_only_dev(tmp_path, frames_dir):
    sample = tmp_path / "sample.csv"
    cols = ["event_id", "estrato", "split", "dia", "status", "detection_id",
            "gate_conf_producao", "window_size", "fonte", "gate5", "window"]
    with sample.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for eid, split in (("evt-a", "dev"), ("evt-b", "aval")):
            w.writerow({"event_id": eid, "estrato": "S2", "split": split, "dia": "2026-07-14",
                        "status": "CONFIRMADO", "gate5": "|".join(EVENT_FRAMES[:5]),
                        "window": "|".join(EVENT_FRAMES)})
    res = tmp_path / "res"
    res.mkdir()
    (res / "dgate54__q5_gate5_low__r1.jsonl").write_text(json.dumps(
        {"event_id": "evt-a", "answers": {"wl_v2": {"noul": 0.7}}}) + "\n", encoding="utf-8")
    (res / "gate54__nvl_v1p_low_ctx__r1.jsonl").write_text(json.dumps(
        {"event_id": "evt-a", "fire": True, "conf": 90}) + "\n", encoding="utf-8")
    (res / "detail54__d38f_g3_low_low__r1.jsonl").write_text(json.dumps(
        {"event_id": "evt-a", "raw_disposal": 1, "disposal": 0}) + "\n", encoding="utf-8")
    rows = cs.build_events(sample, res, [frames_dir])
    assert [r["event_id"] for r in rows] == ["evt-a"]
    r = rows[0]
    assert (r["sub"], r["fonte"], r["filtro_passa"], r["gate_r1"]) == ("S2C", "janela", 1, 1)
    # REQUIRE_BBOX=false no rollout: o alerta previsto segue a resposta crua do detail
    assert (r["detail_cru"], r["detail_final"], r["previsto_alerta"]) == (1, 0, 1)


def test_dry_run_builds_and_logs_without_network(frames_dir, tmp_path):
    def no_net(*a, **k):
        raise AssertionError("modo seco não pode enviar")

    log = tmp_path / "log.jsonl"
    recs = cs.run_send([_event(), _event(event_id="evt-20260714_220000", inicio="22:00:00")],
                       base_url="http://x", device_id="pi-cam-sim-001", tag="0",
                       frame_dirs=[frames_dir], manifest_dir=None, log_path=log, seco=True,
                       limite=1, hora_original=False, intervalo_s=30, velocidade=1,
                       post=no_net)
    assert len(recs) == 1 and recs[0]["n_quadros"] == 12 and recs[0]["lotes"] == 3
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[0])["seco"] is True


def test_send_posts_every_batch_in_order(frames_dir, tmp_path):
    calls = []

    class Resp:
        status_code = 200

    def post(url, headers, data, files, timeout):
        calls.append((data["event_state"], len(files)))
        return Resp()

    recs = cs.run_send([_event()], base_url="http://x", device_id="pi-cam-sim-001", tag="1",
                       frame_dirs=[frames_dir], manifest_dir=None,
                       log_path=tmp_path / "l.jsonl", seco=False, limite=5,
                       hora_original=False, intervalo_s=0, velocidade=1e6, post=post,
                       sleep=lambda s: None)
    assert calls == [("active", 5), ("active", 5), ("end", 2)]
    assert recs[0]["http"] == [200, 200, 200] and recs[0]["erro"] == ""


def test_schedule_at_original_time_of_day_keeps_a_gap():
    now = datetime(2026, 11, 25, 21, 0, 0)
    evs = [_event(event_id="a", inicio="21:45:16"), _event(event_id="b", inicio="21:45:20"),
           _event(event_id="c", inicio="08:00:00")]
    plan = cs.schedule(evs, now, hora_original=True, intervalo_s=30, min_gap_s=10)
    assert [(e["event_id"], at.isoformat()) for at, e in plan] == [
        ("a", "2026-11-25T21:45:16"), ("b", "2026-11-25T21:45:26"), ("c", "2026-11-26T08:00:00")]


class _Resp:
    status_code = 200


def _send(events, tmp_path, frames_dir, post, **over):
    kw = dict(base_url="http://x", device_id="pi-cam-sim-001", tag="1", frame_dirs=[frames_dir],
              manifest_dir=None, log_path=tmp_path / "l.jsonl", seco=False, limite=50,
              hora_original=True, intervalo_s=0, velocidade=1e6, post=post)
    kw.update(over)
    return cs.run_send(events, **kw)


def test_parallel_event_starts_while_the_previous_one_is_still_on_air(frames_dir, tmp_path):
    """Regressão: um atrás do outro, 33 h de eventos não cabem em 24 h e a hora do dia
    (que o gate recebe) atrasava até 12 h. Com `paralelo`, o 2º evento começa na hora
    marcada mesmo com o 1º ainda mandando lotes."""
    import threading

    b_started = threading.Event()
    seen = []

    def post(url, headers, data, files, timeout):
        if data["event_id"].endswith("evt-a") and data["event_state"] == "end":
            # o fim de A só sai depois que B começou: sem paralelismo, B nunca começaria
            assert b_started.wait(5), "B não começou enquanto A estava no ar"
        seen.append((data["event_id"], data["event_state"]))
        if data["event_id"].endswith("evt-b"):
            b_started.set()
        return _Resp()

    now = datetime(2026, 11, 25, 21, 45, 0)
    evs = [_event(event_id="evt-a", inicio="21:45:01"), _event(event_id="evt-b", inicio="21:45:02")]
    recs = _send(evs, tmp_path, frames_dir, post, paralelo=2, sleep=lambda s: None,
                 clock=lambda: now)
    assert [r["http"] for r in recs] == [[200, 200, 200], [200, 200, 200]]
    assert seen.index(("sim1-evt-b", "active")) < seen.index(("sim1-evt-a", "end"))
    # dentro de cada evento a ordem dos lotes continua a da Pi
    for eid in ("sim1-evt-a", "sim1-evt-b"):
        assert [s for i, s in seen if i == eid] == ["active", "active", "end"]
    assert len((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_batch_is_retried_only_when_there_is_no_response(frames_dir, tmp_path):
    n = {"calls": 0}

    def post(url, headers, data, files, timeout):
        n["calls"] += 1
        if n["calls"] == 2:
            raise ConnectionError("túnel caído")
        return _Resp()

    recs = _send([_event()], tmp_path, frames_dir, post, hora_original=False, tentativas=3,
                 sleep=lambda s: None)
    assert recs[0]["http"] == [200, 200, 200] and recs[0]["erro"] == ""
    assert recs[0]["novas_tentativas"] == 1 and n["calls"] == 4


def test_no_response_after_every_attempt_stops_the_event(frames_dir, tmp_path):
    def post(url, headers, data, files, timeout):
        raise ConnectionError("túnel caído")

    recs = _send([_event()], tmp_path, frames_dir, post, hora_original=False, tentativas=2,
                 sleep=lambda s: None)
    assert recs[0]["http"] == [0] and "túnel caído" in recs[0]["erro"]


def test_resume_skips_what_the_log_already_has_as_sent(frames_dir, tmp_path):
    log = tmp_path / "l.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in (
        {"event_id": "evt-ok", "seco": False, "http": [200, 200], "erro": ""},
        {"event_id": "evt-falhou", "seco": False, "http": [200, 0], "erro": "ConnectionError"},
        {"event_id": "evt-seco", "seco": True, "http": [], "erro": ""},
    )) + "\n", encoding="utf-8")
    sent = []

    def post(url, headers, data, files, timeout):
        sent.append(data["event_id"])
        return _Resp()

    evs = [_event(event_id=i) for i in ("evt-ok", "evt-falhou", "evt-seco", "evt-novo")]
    _send(evs, tmp_path, frames_dir, post, hora_original=False, retomar=True,
          sleep=lambda s: None)
    assert sorted(set(sent)) == ["sim1-evt-falhou", "sim1-evt-novo", "sim1-evt-seco"]
