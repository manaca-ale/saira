#!/usr/bin/env python3
"""Camp 36 Phase 2b — clean FP measurement on no-disposal baselines.

Replays the official-dataset baseline hours (sem_ocorrencia, continuous ~1h, 5s cadence)
through each contender strategy and counts false-positive confirmations (coalesced to
operator-facing FP/hour). This is the ONLY clean FP measure — the positive corpus FP was
confounded by coalesced multi-event clips (see report). BGSUB is NOT applied (cascade-alone
FP, upper bound); relative ordering across strategies holds.

Run: PYTHONPATH="services/yolo-worker-vm/src;benchmarks/campaigns/36-window-latency-sim-2026-06-05" \
       python -X utf8 benchmarks/campaigns/36-window-latency-sim-2026-06-05/run_negatives.py
"""
from __future__ import annotations

import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import sim

CAMPAIGN = Path(__file__).resolve().parent
REPO = CAMPAIGN.parents[2]
BASE = REPO / "data" / "datasets" / "official"
MAX_WORKERS = 6

# (cam_dir, device_id, segment)
HOURS = [
    ("cam_mangabeira", "esp32_002", "day"), ("cam_mangabeira", "esp32_002", "night"),
    ("cam_imbiribeira", "esp32_001", "day"), ("cam_imbiribeira", "esp32_001", "night"),
]
# contenders on the latency Pareto front + one aggressive
STRATEGIES = [
    ("prod_240_poll180", "fixed", 240, 48, 12, 180),
    ("prod_240_poll60",  "fixed", 240, 48, 12,  60),
    ("fix_60_poll30",    "fixed",  60, 12,  6,  30),
    ("slide_120_str60",  "sliding",120, 24, 12,  60),
    ("slide_90_str30",   "sliding", 90, 18,  9,  30),
]
PHASES = 1  # FP rate over a full hour is phase-independent (verified on smoke test)


def load_hours():
    out = []
    for cam, dev, seg in HOURS:
        d = BASE / cam / "baseline" / seg
        frames = sorted(d.glob("*.jpg"))
        if frames:
            out.append({"label": f"{cam.split('_')[1]}/{seg}", "device_id": dev, "frames": frames})
    return out


def run_task(strat, hour, phase):
    name, mode, win, maxf, minf, poll = strat
    try:
        r = sim.fp_replay(hour["frames"], hour["device_id"], window_s=win, max_f=maxf,
                          min_f=minf, poll_interval=poll, poll_phase=phase, mode=mode)
    except Exception as exc:
        return {"strategy": name, "hour": hour["label"], "phase": phase, "error": str(type(exc).__name__)}
    return {"strategy": name, "hour": hour["label"], "device": hour["device_id"],
            "phase": phase, **r}


def main() -> int:
    hours = load_hours()
    print(f"Baseline hours: {[h['label'] for h in hours]}  ({len(hours)} hours)")
    tasks = [(s, h, float(p)) for s in STRATEGIES for h in hours
             for p in range(0, s[5], max(1, s[5] // PHASES))][: len(STRATEGIES) * len(hours) * PHASES]
    # rebuild cleanly: PHASES phases per strategy
    tasks = []
    for s in STRATEGIES:
        step = max(1, s[5] // PHASES)
        for h in hours:
            for p in range(0, s[5], step):
                tasks.append((s, h, float(p)))
    print(f"Tasks: {len(tasks)} ({MAX_WORKERS}-way concurrent)\n")

    rows = []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = [pool.submit(run_task, s, h, p) for (s, h, p) in tasks]
        for fut in as_completed(futs):
            rows.append(fut.result())
            done += 1
            if done % 10 == 0:
                sim.save_caches()
                print(f"  {done}/{len(tasks)}  |  {sim.cache_stats()}")
    sim.save_caches()
    (CAMPAIGN / "results_negatives.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== FALSE POSITIVES on no-disposal baselines (coalesced FP/hour) ===")
    print(f"{'strategy':18} {'overall':9} {'Imbiribeira':12} {'Mangabeira':11} {'raw/h':7}")
    agg = {}
    for s in STRATEGIES:
        name = s[0]
        rs = [r for r in rows if r.get("strategy") == name and "error" not in r]
        if not rs:
            continue
        overall = statistics.mean([r["fp_per_hour"] for r in rs])
        imb = [r["fp_per_hour"] for r in rs if r["device"] == "esp32_001"]
        man = [r["fp_per_hour"] for r in rs if r["device"] == "esp32_002"]
        raw = statistics.mean([r["raw_fp"] for r in rs])
        agg[name] = {"overall_fp_h": round(overall, 2),
                     "imbiribeira_fp_h": round(statistics.mean(imb), 2) if imb else None,
                     "mangabeira_fp_h": round(statistics.mean(man), 2) if man else None,
                     "raw_fp_mean": round(raw, 1)}
        print(f"{name:18} {round(overall,2):<9} "
              f"{round(statistics.mean(imb),2) if imb else '-':<12} "
              f"{round(statistics.mean(man),2) if man else '-':<11} {round(raw,1)}")
    (CAMPAIGN / "results_negatives_agg.json").write_text(
        json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ncache: {sim.cache_stats()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
