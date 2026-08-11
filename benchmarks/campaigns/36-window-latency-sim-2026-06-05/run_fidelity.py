#!/usr/bin/env python3
"""Camp 36 Phase 1 — fidelity gate.

Replays the 2 anchors with prod params (window=240, max=48, min=12, poll=180), sweeping
the poll phase, and checks the simulator reproduces:
  - the confirming-window F* observed in prod (a5a72209 -> 20:47:29, c9c2c83e -> 19:33:09)
  - the measured latency (3:13 / 0:59) at the prod-like phase

Run:  PYTHONPATH=services/yolo-worker-vm/src python -X utf8 \
        benchmarks/campaigns/36-window-latency-sim-2026-06-05/run_fidelity.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import sim

CAMPAIGN = Path(__file__).resolve().parent
CORPUS = CAMPAIGN / "corpus" / "positives"

ANCHORS = {
    "a5a72209-6f36-44c2-b3b2-69dab4445103": {
        "bairro": "Arruda", "prod_f_star": "2026-06-04_20-47-29.jpg",
        "measured_latency_s": 193,  # 3:13
    },
    "c9c2c83e-b5e3-495c-99b7-93ef0b387c63": {
        "bairro": "Imbiribeira", "prod_f_star": "2026-06-03_19-33-09.jpg",
        "measured_latency_s": 59,
    },
}


def ev_epoch(meta: dict, hhmmss: str) -> float:
    date = meta["db_timestamp"][:10]  # YYYY-MM-DD
    return datetime.strptime(f"{date}_{hhmmss.replace(':','-')}", "%Y-%m-%d_%H-%M-%S").timestamp()


def main() -> int:
    print("=== Camp 36 Phase 1 — FIDELITY GATE (prod params 240/48/12, poll 180) ===\n")
    all_ok = True
    for eid, info in ANCHORS.items():
        d = CORPUS / eid
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        device_id = meta["device_id"]
        frames = [d / "frames" / fr["frame_name"] for fr in meta["frames"]]
        ds_epoch = ev_epoch(meta, meta["disposal_start_ts"])

        print(f"--- {info['bairro']} {eid[:8]} ({device_id}) "
              f"n={meta['n_frames']} disposal_start={meta['disposal_start_ts']} "
              f"prod_F*={info['prod_f_star']} measured={info['measured_latency_s']}s ---")
        f_stars = {}
        latencies = []
        n_miss = 0
        for phase in range(0, 180, 5):
            try:
                r = sim.poll_replay(
                    frames, device_id, window_s=240, max_f=48, min_f=12,
                    poll_interval=180, poll_phase=float(phase), disposal_start_epoch=ds_epoch)
            except Exception as exc:  # transient Gemini 503/timeout — skip phase, cache persists
                print(f"  phase={phase:3}s  ERR {type(exc).__name__} (skip; re-run resumes from cache)")
                continue
            if r["confirmed"]:
                fs = r["f_star"]
                f_stars[fs] = f_stars.get(fs, 0) + 1
                latencies.append(r["latency_s"])
                mark = "  <== matches prod F*" if fs == info["prod_f_star"] else ""
                print(f"  phase={phase:3}s  F*={fs}  win={r['window_size']:2}f  "
                      f"data_ready={r['data_ready_latency_s']:+.0f}s  latency={r['latency_s']:.0f}s{mark}")
            else:
                print(f"  phase={phase:3}s  NOT CONFIRMED")
                n_miss += 1

        matched = info["prod_f_star"] in f_stars
        n_phases = len(latencies) + n_miss
        recall = len(latencies) / n_phases if n_phases else 0.0
        print(f"  -> reproduces prod F* exactly? {'YES' if matched else 'NO'}  "
              f"(prod F*={info['prod_f_star']})")
        print(f"  -> recall over phases: {len(latencies)}/{n_phases} = {recall:.0%}")
        if latencies:
            import statistics
            print(f"  -> latency over phases: min={min(latencies):.0f} "
                  f"p50={statistics.median(latencies):.0f} max={max(latencies):.0f}s "
                  f"(prod measured {info['measured_latency_s']}s)")
        if not matched:
            all_ok = False
        print()

    sim.save_caches()
    print(f"cache: {sim.cache_stats()}")
    print(f"\nFIDELITY GATE: {'PASS' if all_ok else 'FAIL — fix before strategy matrix'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
