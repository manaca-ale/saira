#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Aggregate the 3 benchmark reps (flash-lite non-determinism). Reads .tmp/rep{1,2,3}.json.

Reports per arm: mean +/- range of vehicle-recall, on-foot-recall, FP across reps; and a
per-vehicle-TP catch-frequency (how stably each arm catches each vehicle-TP) to separate
robust catches from flaky ones.
"""
import json
import statistics as st
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CAMP = Path(__file__).resolve().parents[1]

lab = json.loads((CAMP / "labeling" / "tp_labels.json").read_text(encoding="utf-8"))
veh = {e["event_id"][:8] for e in lab["events"] if e.get("vehicle_present") is True}
nov = {e["event_id"][:8] for e in lab["events"] if e.get("vehicle_present") is False}

reps = []
for i in (1, 2, 3):
    p = CAMP / ".tmp" / f"rep{i}.json"
    if p.exists():
        reps.append(json.loads(p.read_text(encoding="utf-8")))
print(f"reps loaded: {len(reps)}  | vehicle-TPs={len(veh)} on-foot-TPs={len(nov)}\n")

arms = list(reps[0]["results"].keys())


def counts(rep, arm):
    rs = rep["results"][arm]
    vh = sum(1 for r in rs if r["label"] == "TP" and r["id"] in veh and r["gate"].get("triggered"))
    ft = sum(1 for r in rs if r["label"] == "TP" and r["id"] in nov and r["gate"].get("triggered"))
    fp = sum(1 for r in rs if r["label"] == "FP" and r["gate"].get("triggered"))
    return vh, ft, fp


def fmt(vals):
    return f"{st.mean(vals):.1f} [{min(vals)}-{max(vals)}]"


print(f"{'arm':20s} {'veh/12':>14s} {'foot/8':>13s} {'FP/147':>15s}")
for arm in arms:
    vs, fs, ps = zip(*[counts(r, arm) for r in reps])
    print(f"{arm:20s} {fmt(vs):>14s} {fmt(fs):>13s} {fmt(ps):>15s}")

print("\n=== per vehicle-TP catch frequency (x / (reps*?) per arm) ===")
print(f"{'veh-TP':10s} " + " ".join(f"{a.split('_')[0]:>8s}" for a in arms))
for vid in sorted(veh):
    cells = []
    for arm in arms:
        c = sum(1 for r in reps if next((x for x in r["results"][arm] if x["id"] == vid), {}).get("gate", {}).get("triggered"))
        cells.append(f"{c}/{len(reps)}")
    flag = "  <- never" if all(c.startswith("0") for c in cells) else ""
    print(f"{vid:10s} " + " ".join(f"{c:>8s}" for c in cells) + flag)
