#!/usr/bin/env python3
"""Generate before_after_firstlast.csv = first frame (before) vs last frame (after).

This is the camp-20 proto heuristic (widest temporal gap) applied at N=213 with the
real pile polygon, to test whether camp-20's n=8 result survives large N + temporal
holdout. No motion picking — the loitering-person trap (see viz montages) made the
motion-picked 'after' frames retain people; first/last is the cleaner proxy when the
actor has usually left by the end of the evidence window.
"""
from __future__ import annotations
import csv
import glob
import sys
from pathlib import Path

ROOT = Path(r"c:\saira")
LARGEN = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "largeN"
FRAMES24 = LARGEN / "frames24"
RES = ROOT / "benchmarks" / "campaigns" / "41-structural-delta-mangabeira-2026-06-16" / "results"
sys.stdout.reconfigure(encoding="utf-8")

rows = []
for r in csv.DictReader((LARGEN / "manifest.csv").open(encoding="utf-8")):
    if r["bucket"] not in ("TP", "B3"):
        continue
    fr = sorted(Path(p) for p in glob.glob(str(FRAMES24 / f"{r['id'][:8]}__*.jpg")))
    if len(fr) < 4:
        continue
    rows.append({"event_id": r["id"], "bucket": r["bucket"], "created_at": r["created_at"],
                 "n_frames": len(fr), "before_frame": fr[0].name, "after_frame": fr[-1].name,
                 "before_motion": 0.0, "after_motion": 0.0})

out = RES / "before_after_firstlast.csv"
with out.open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"{len(rows)} events -> {out}")
