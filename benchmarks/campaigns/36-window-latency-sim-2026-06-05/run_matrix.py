#!/usr/bin/env python3
"""Camp 36 Phase 2 — strategy matrix over the positive corpus.

For each (strategy, event, poll_phase) replays the cascade and records when/if the labeled
disposal is first confirmed. Timelines are trimmed to [disposal_start-90s, +240s] to isolate
the single labeled disposal (kills multi-event coalescing confounds, esp. Imbiribeira).

Each confirm is classified:
  - TP        : data_ready >= -30s  (detects the disposal; latency counted)
  - early_FP  : data_ready < -30s   (fires on pre-existing litter -> cost of the lever)
  - miss      : never confirmed within the trimmed timeline

Latency is reported as a DISTRIBUTION over poll phases (p50/p90) because the poll phase
dominates. Runs replays concurrently (Vertex); Gemini calls are memoized + crash-safe.

Run:  PYTHONPATH="services/yolo-worker-vm/src;benchmarks/campaigns/36-window-latency-sim-2026-06-05" \
        python -X utf8 benchmarks/campaigns/36-window-latency-sim-2026-06-05/run_matrix.py
"""
from __future__ import annotations

import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import sim

CAMPAIGN = Path(__file__).resolve().parent
CORPUS = CAMPAIGN / "corpus" / "positives"
# Full timelines (no trim) — matches the validated fidelity-gate setup. Pre-trimming
# removed the clean "before" reference the gate needs when the CV disposal_start label
# lands late in the clip (e.g. 9085ad0e idx 34/41), spuriously zeroing recall. With full
# timelines a confirm before disposal_start is scored as early-FP (an honest lever cost).
TP_TOLERANCE = -30     # data_ready >= this -> counts as detecting the labeled disposal
N_PHASES = 12
MAX_WORKERS = 6        # lowered from 10 to avoid Vertex 429 RESOURCE_EXHAUSTED

# name, mode, window_s, max_f, min_f, poll_interval
STRATEGIES = [
    ("prod_240_poll180", "fixed", 240, 48, 12, 180),   # baseline (prod)
    ("fix_120_poll180",  "fixed", 120, 24, 12, 180),   # #4 shrink
    ("fix_90_poll180",   "fixed",  90, 18,  9, 180),
    ("fix_60_poll180",   "fixed",  60, 12,  6, 180),
    ("prod_240_poll60",  "fixed", 240, 48, 12,  60),   # POLL lever (free)
    ("prod_240_poll30",  "fixed", 240, 48, 12,  30),
    ("fix_90_poll60",    "fixed",  90, 18,  9,  60),   # combined
    ("fix_60_poll30",    "fixed",  60, 12,  6,  30),
    ("slide_120_str60",  "sliding",120, 24, 12,  60),  # #3 sliding
    ("slide_90_str30",   "sliding", 90, 18,  9,  30),
    ("slide_60_str30",   "sliding", 60, 12,  6,  30),
]


def ev_epoch(meta: dict, hhmmss: str) -> float:
    date = meta["db_timestamp"][:10]
    return datetime.strptime(f"{date}_{hhmmss.replace(':','-')}", "%Y-%m-%d_%H-%M-%S").timestamp()


def load_events() -> list[dict]:
    out = []
    for d in sorted(CORPUS.iterdir()):
        if not d.is_dir():
            continue
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        ds = ev_epoch(meta, meta["disposal_start_ts"])
        frames = [d / "frames" / fr["frame_name"] for fr in meta["frames"]]  # full timeline
        out.append({"event_id": meta["event_id"], "device_id": meta["device_id"],
                    "bairro": meta["bairro"], "ds_epoch": ds, "frames": frames,
                    "n_frames": len(frames)})
    return out


def phases_for(poll_interval: int) -> list[float]:
    step = max(1, poll_interval // N_PHASES)
    return [float(p) for p in range(0, poll_interval, step)]


def run_task(strat, event, phase) -> dict:
    name, mode, win, maxf, minf, poll = strat
    try:
        r = sim.poll_replay(event["frames"], event["device_id"], window_s=win, max_f=maxf,
                            min_f=minf, poll_interval=poll, poll_phase=phase,
                            disposal_start_epoch=event["ds_epoch"], mode=mode)
    except Exception as exc:
        return {"strategy": name, "event_id": event["event_id"], "bairro": event["bairro"],
                "phase": phase, "error": f"{type(exc).__name__}", "cls": "error"}
    cls = "miss"
    if r["confirmed"]:
        cls = "tp" if r["data_ready_latency_s"] >= TP_TOLERANCE else "early_fp"
    return {"strategy": name, "event_id": event["event_id"], "bairro": event["bairro"],
            "phase": phase, "cls": cls, "confirmed": r["confirmed"],
            "latency_s": r.get("latency_s"), "data_ready_s": r.get("data_ready_latency_s"),
            "f_star": r.get("f_star"), "window_size": r.get("window_size"),
            "cost_usd": r.get("cost_usd", 0.0), "n_gate": r.get("n_gate", 0),
            "n_detail": r.get("n_detail", 0)}


def aggregate(rows: list[dict]) -> dict:
    out = {}
    by_strat: dict[str, list[dict]] = {}
    for r in rows:
        by_strat.setdefault(r["strategy"], []).append(r)
    for name, rs in by_strat.items():
        valid = [r for r in rs if r["cls"] != "error"]
        n = len(valid) or 1
        tp = [r for r in valid if r["cls"] == "tp"]
        efp = [r for r in valid if r["cls"] == "early_fp"]
        miss = [r for r in valid if r["cls"] == "miss"]
        lat = sorted(r["latency_s"] for r in tp)
        out[name] = {
            "n_tasks": len(valid), "n_errors": len(rs) - len(valid),
            "recall_tp_pct": round(100 * len(tp) / n, 1),
            "early_fp_pct": round(100 * len(efp) / n, 1),
            "miss_pct": round(100 * len(miss) / n, 1),
            "lat_p50": round(statistics.median(lat)) if lat else None,
            "lat_p90": round(lat[int(0.9 * (len(lat) - 1))]) if lat else None,
            "lat_min": round(min(lat)) if lat else None,
            "lat_max": round(max(lat)) if lat else None,
            "cost_mean_usd": round(statistics.mean([r["cost_usd"] for r in valid]), 5),
            "calls_mean": round(statistics.mean([r["n_gate"] + r["n_detail"] for r in valid]), 1),
        }
    return out


def main() -> int:
    events = load_events()
    print(f"Corpus: {len(events)} events (trimmed). Strategies: {len(STRATEGIES)}.")
    tasks = [(s, e, ph) for s in STRATEGIES for e in events for ph in phases_for(s[5])]
    print(f"Total tasks: {len(tasks)} (running {MAX_WORKERS}-way concurrent via Vertex)\n")

    rows: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = [pool.submit(run_task, s, e, ph) for (s, e, ph) in tasks]
        for fut in as_completed(futs):
            rows.append(fut.result())
            done += 1
            if done % 50 == 0:
                sim.save_caches()
                print(f"  {done}/{len(tasks)} tasks  |  {sim.cache_stats()}")
    sim.save_caches()

    (CAMPAIGN / "results_raw.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    agg = aggregate(rows)
    (CAMPAIGN / "results_agg.json").write_text(
        json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== STRATEGY MATRIX (positive corpus) ===")
    hdr = f"{'strategy':18} {'recallTP':8} {'earlyFP':8} {'miss':6} {'latP50':7} {'latP90':7} {'cost$':8} {'calls':6}"
    print(hdr)
    for name, _m, *_ in STRATEGIES:
        m = agg[name]
        print(f"{name:18} {str(m['recall_tp_pct'])+'%':8} {str(m['early_fp_pct'])+'%':8} "
              f"{str(m['miss_pct'])+'%':6} {str(m['lat_p50'])+'s':7} {str(m['lat_p90'])+'s':7} "
              f"{m['cost_mean_usd']:<8} {m['calls_mean']}")
    print(f"\ncache: {sim.cache_stats()}")
    print("results -> results_raw.json + results_agg.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
