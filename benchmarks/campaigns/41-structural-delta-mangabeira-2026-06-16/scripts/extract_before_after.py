#!/usr/bin/env python3
"""Phase 1.1 — pick before/after frames per event by MINIMUM motion in the pile zone.

For each Mangabeira event we have up to 24 frames (frames24/, already on disk, $0).
A real structural delta needs a quiet PRE frame (actor absent, pile pre-event) and a
quiet POST frame (actor gone, deposit settled). We approximate the Pi's frozen
reference by picking, inside the pile polygon:
  - before = lowest-motion frame in the first ~30% of the window
  - after  = lowest-motion frame in the last  ~30% of the window
where "motion" = mean abs grayscale frame-diff vs the previous frame, restricted to
the pile zone (reuses tools/motion_pick_proto.motion_scores).

CAVEAT (documented in the plan): esp32_002 is poll-driven, so this offline
before/after is a PROXY — there is no on-Pi freeze. Treat results as a LOWER BOUND.
We record the residual motion of the chosen 'after' frame so the ROC stage can flag
events where the actor never left (no quiet frame).
"""
from __future__ import annotations

import csv
import glob
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(r"c:\saira")
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

from motion_pick_proto import motion_scores  # noqa: E402

CAMP = ROOT / "benchmarks" / "campaigns" / "41-structural-delta-mangabeira-2026-06-16"
LARGEN = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "largeN"
FRAMES24 = LARGEN / "frames24"
RES = CAMP / "results"

# Real pile polygon for esp32_002 from the cameras table (1280x720 ref).
PILE_POLY = [(461, 154), (704, 66), (939, 299), (617, 416)]


def event_frames(event_id: str) -> list[Path]:
    return sorted(Path(p) for p in glob.glob(str(FRAMES24 / f"{event_id[:8]}__*.jpg")))


def pick_before_after(paths: list[Path]):
    """Return (before_path, after_path, before_motion, after_motion, n)."""
    n = len(paths)
    scores = motion_scores([str(p) for p in paths], poly=PILE_POLY)
    scores = np.asarray(scores)
    first_end = max(2, round(n * 0.30))          # first ~30%
    last_start = min(n - 1, round(n * 0.70))     # last ~30%
    # before: lowest motion in [1, first_end] (idx 0 has no motion value -> skip)
    bwin = list(range(1, first_end + 1))
    before_i = min(bwin, key=lambda i: scores[i]) if bwin else 0
    awin = list(range(last_start, n))
    after_i = min(awin, key=lambda i: scores[i]) if awin else n - 1
    return paths[before_i], paths[after_i], float(scores[before_i]), float(scores[after_i]), n


def main() -> int:
    manifest = list(csv.DictReader((LARGEN / "manifest.csv").open(encoding="utf-8")))
    rows = []
    skipped = 0
    for r in manifest:
        if r["bucket"] not in ("TP", "B3"):
            continue
        paths = event_frames(r["id"])
        if len(paths) < 4:
            skipped += 1
            continue
        bp, ap, bm, am, n = pick_before_after(paths)
        rows.append({
            "event_id": r["id"],
            "bucket": r["bucket"],
            "created_at": r["created_at"],
            "n_frames": n,
            "before_frame": bp.name,
            "after_frame": ap.name,
            "before_motion": round(bm, 3),
            "after_motion": round(am, 3),
        })

    RES.mkdir(parents=True, exist_ok=True)
    out = RES / "before_after.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    tp = [r for r in rows if r["bucket"] == "TP"]
    b3 = [r for r in rows if r["bucket"] == "B3"]
    am_tp = np.array([r["after_motion"] for r in tp])
    am_b3 = np.array([r["after_motion"] for r in b3])
    print(f"events: TP={len(tp)} B3={len(b3)}  (skipped <4 frames: {skipped})")
    print(f"after_motion  TP med={np.median(am_tp):.2f} p90={np.percentile(am_tp,90):.2f}"
          f"  B3 med={np.median(am_b3):.2f} p90={np.percentile(am_b3,90):.2f}")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
