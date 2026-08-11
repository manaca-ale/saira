#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Campaign 40 Phase A — CV signal diagnostic, Mangabeira only.

Reuses spike_bgsub_filter (bg model over baseline, pile zone mask). Computes per
event: persistence, ratio_in_pile, permanence (new fg at end not at start),
peak_fg. Reports ROC/AUC (TP=keep vs B3=suppress) + threshold sweep (veto =
suppress if signal < thr) + bootstrap AUC CI. Zero Gemini.
"""
import csv
import sys
from pathlib import Path

import numpy as np
import cv2

ROOT = Path(r"c:\saira")
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import spike_bgsub_filter as spk  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

DATASET = ROOT / "data" / "datasets" / "official"
CAMP = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16"
RES = CAMP / "results"
CAM = "cam_mangabeira"
RNG = np.random.default_rng(42)


def score_event(bg, zm, kernel, frames):
    """Returns persistence, ratio, permanence, peak_fg using zone masks per frame."""
    masks, fgz = [], []
    for fp in frames:
        img = cv2.imread(str(fp))
        if img is None:
            continue
        m = bg.apply(img, learningRate=0)
        m = (m > 200).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel)
        inz = cv2.bitwise_and(m, zm)
        masks.append(inz > 0)
        fgz.append(int(np.count_nonzero(inz)))
    if len(masks) < 2:
        return None
    stack = np.stack(masks, 0)
    votes = stack.sum(0)
    persistence = int(np.count_nonzero(votes >= max(1, int(0.6 * len(masks)))))
    # permanence: fg present in last-2 union AND absent in first-2 union
    k = min(2, len(masks) // 2)
    first_u = np.any(stack[:k], 0)
    last_u = np.any(stack[-k:], 0)
    permanence = int(np.count_nonzero(last_u & ~first_u))
    peak = max(fgz)
    total_out = 1  # ratio reuses spike score; recompute cheap proxy
    return {
        "persistence": float(persistence),
        "permanence": float(permanence),
        "peak_fg": float(peak),
    }


def main() -> int:
    split = list(csv.DictReader((RES / "b3_split.csv").open(encoding="utf-8")))
    bg = spk.build_bg_model(CAM)
    zm = spk.build_zone_mask(CAM, (720, 1280))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    rows = []
    for r in split:
        if r["bucket"] not in ("TP", "B3", "B1B2"):
            continue
        fdir = DATASET / r["local_path"] / "frames"
        frames = spk.sample_frames_from_window(fdir)
        s = score_event(bg, zm, kernel, frames) if len(frames) >= 2 else None
        if not s:
            continue
        rows.append({"event_id": r["event_id"], "bucket": r["bucket"],
                     "justificativa": r["justificativa"][:50], **s})

    with (RES / "phase_a_signals.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    tp = [r for r in rows if r["bucket"] == "TP"]
    b3 = [r for r in rows if r["bucket"] == "B3"]
    print(f"N: TP={len(tp)}  B3={len(b3)}\n")

    for sig in ("persistence", "permanence", "peak_fg"):
        tv = np.array([r[sig] for r in tp])
        bv = np.array([r[sig] for r in b3])
        y = np.r_[np.ones(len(tv)), np.zeros(len(bv))]
        x = np.r_[tv, bv]
        auc = roc_auc_score(y, x)
        # bootstrap AUC CI
        aucs = []
        for _ in range(5000):
            i_tp = RNG.integers(0, len(tv), len(tv))
            i_b3 = RNG.integers(0, len(bv), len(bv))
            yy = np.r_[np.ones(len(tv)), np.zeros(len(bv))]
            xx = np.r_[tv[i_tp], bv[i_b3]]
            try:
                aucs.append(roc_auc_score(yy, xx))
            except ValueError:
                pass
        lo, hi = np.percentile(aucs, [2.5, 97.5])
        print(f"=== {sig} ===")
        print(f"  TP   med={np.median(tv):8.0f}  IQR=[{np.percentile(tv,25):.0f},{np.percentile(tv,75):.0f}]")
        print(f"  B3   med={np.median(bv):8.0f}  IQR=[{np.percentile(bv,25):.0f},{np.percentile(bv,75):.0f}]")
        print(f"  AUC(keep TP)={auc:.3f}  95%CI=[{lo:.3f},{hi:.3f}]")
        # veto sweep: suppress (REJ) if signal < thr -> keep TP if signal>=thr
        thrs = np.unique(np.r_[tv, bv])
        best = None
        for thr in thrs:
            tp_keep = int((tv >= thr).sum())
            b3_supp = int((bv < thr).sum())
            if tp_keep >= 12 and (best is None or b3_supp > best[2]):
                best = (thr, tp_keep, b3_supp)
        if best:
            print(f"  veto<thr @ recall>=12/13: thr={best[0]:.0f}  TPkeep={best[1]}/13  B3supp={best[2]}/20 ({100*best[2]/len(bv):.0f}%)")
        else:
            print("  nenhum thr mantem >=12/13 TP")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
