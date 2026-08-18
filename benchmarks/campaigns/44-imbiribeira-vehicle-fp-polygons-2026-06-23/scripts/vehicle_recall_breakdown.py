#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Per-arm recall split by manual vehicle GT + FP. Reads results.json + tp_labels.json.

The user's goal: catch VEHICLE disposals without raising FP. This shows, per prompt arm,
recall on the 12 vehicle-TPs vs the 8 on-foot-TPs, and the FP count (must stay <= baseline).
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CAMP = Path(__file__).resolve().parents[1]

res = json.loads((CAMP / "results.json").read_text(encoding="utf-8"))
lab = json.loads((CAMP / "labeling" / "tp_labels.json").read_text(encoding="utf-8"))
veh_gt = {e["event_id"][:8]: e.get("vehicle_present") for e in lab["events"]}
veh_ids = {k for k, v in veh_gt.items() if v is True}
nov_ids = {k for k, v in veh_gt.items() if v is False}

print(f"vehicle-TPs={len(veh_ids)}  on-foot-TPs={len(nov_ids)}\n")
print(f"{'arm':20s} {'veh-recall':>11s} {'foot-recall':>11s} {'tot-recall':>11s} {'FP':>9s}")
rows = []
base_fp = None
for arm, rs in res["results"].items():
    tp = [r for r in rs if r["label"] == "TP"]
    fp = [r for r in rs if r["label"] == "FP"]
    vh = [r for r in tp if r["id"] in veh_ids]
    ft = [r for r in tp if r["id"] in nov_ids]
    vh_c = sum(1 for r in vh if r["gate"].get("triggered"))
    ft_c = sum(1 for r in ft if r["gate"].get("triggered"))
    tot_c = sum(1 for r in tp if r["gate"].get("triggered"))
    fp_c = sum(1 for r in fp if r["gate"].get("triggered"))
    if arm == "A_baseline":
        base_fp = fp_c
    rows.append((arm, vh_c, len(vh), ft_c, len(ft), tot_c, len(tp), fp_c, len(fp)))

for arm, vc, vn, fc, fn, tc, tn, pc, pn in rows:
    dfp = "" if base_fp is None else f" (Δ{pc-base_fp:+d})"
    print(f"{arm:20s} {vc:>3d}/{vn:<3d}={100*vc//max(1,vn):>3d}% "
          f"{fc:>3d}/{fn:<3d}={100*fc//max(1,fn):>3d}% "
          f"{tc:>3d}/{tn:<3d}={100*tc//max(1,tn):>3d}% {pc:>3d}/{pn:<3d}{dfp}")

print("\nGoal = max vehicle-recall with FP <= baseline (66). On-foot recall is expendable.")
