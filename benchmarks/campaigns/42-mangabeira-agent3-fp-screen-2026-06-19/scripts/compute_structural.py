#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compute the Camp-41 structural-delta signal (census_ntiles_t32) for the
Camp-42 eval events, on the SAME first/last frames the screener saw.

Reuses census.py + the exact pile polygon, HAM_THR, tile logic from Camp 41 so
the values are directly comparable. Output: struct_scores.csv
(event_id, census_ntiles_t32, census_ntiles_t16, g_ncc).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(r"c:\saira")
C41 = ROOT / "benchmarks" / "campaigns" / "41-structural-delta-mangabeira-2026-06-16" / "scripts"
sys.path.insert(0, str(C41))
sys.stdout.reconfigure(encoding="utf-8")
from census import census_hamming  # noqa: E402

CAMP = Path(__file__).resolve().parents[1]
PILE_POLY = np.array([[461, 154], [704, 66], [939, 299], [617, 416]], dtype=np.int32)
HAM_THR = 3
CENSUS_TILE_FRAC = 0.50
NCC_TILE_THR = 0.70
MIN_TILE_COVER_PX = 24


def build_mask(shape):
    m = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(m, [PILE_POLY], 255)
    return m


def bbox_of_poly():
    x0, y0 = PILE_POLY[:, 0].min(), PILE_POLY[:, 1].min()
    x1, y1 = PILE_POLY[:, 0].max(), PILE_POLY[:, 1].max()
    return int(x0), int(y0), int(x1), int(y1)


def ncc(a, b):
    if a.size < 8:
        return 1.0
    a = a.astype(np.float32) - a.mean(); b = b.astype(np.float32) - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom > 1e-6 else 1.0


def census_ntiles(changed_census, mask, tile):
    x0, y0, x1, y1 = bbox_of_poly()
    fracs = []
    for ty in range(y0, y1, tile):
        for tx in range(x0, x1, tile):
            tm = mask[ty:ty + tile, tx:tx + tile] > 0
            if int(tm.sum()) < MIN_TILE_COVER_PX:
                continue
            cc = changed_census[ty:ty + tile, tx:tx + tile][tm]
            fracs.append(float(cc.mean()))
    fracs = np.array(fracs) if fracs else np.array([0.0])
    return int((fracs > CENSUS_TILE_FRAC).sum())


def compute(before_path, after_path, mask):
    ia = cv2.imread(str(before_path)); ib = cv2.imread(str(after_path))
    if ia is None or ib is None or ia.shape != ib.shape:
        return None
    gp = cv2.cvtColor(ia, cv2.COLOR_BGR2GRAY); gq = cv2.cvtColor(ib, cv2.COLOR_BGR2GRAY)
    ham = census_hamming(gp, gq)
    changed = (ham >= HAM_THR).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, k)
    mb = mask > 0
    return {
        "census_ntiles_t32": census_ntiles(changed, mask, 32),
        "census_ntiles_t16": census_ntiles(changed, mask, 16),
        "g_ncc": round(ncc(gp[mb], gq[mb]), 4),
    }


def main():
    rows = list(csv.DictReader((CAMP / "eval_manifest.csv").open(encoding="utf-8")))
    mask = build_mask((720, 1280))
    out_rows, miss = [], 0
    for i, r in enumerate(rows, 1):
        fdir = Path(r["frames_dir"])
        jpgs = sorted(p for p in fdir.glob("*.jpg") if p.stat().st_size > 1000)
        if len(jpgs) < 2:
            miss += 1; continue
        m = compute(jpgs[0], jpgs[-1], mask)
        if m is None:
            miss += 1; continue
        out_rows.append({"event_id": r["event_id"], "gold": r["gold"],
                         "subtype": r["subtype"], **m})
        if i % 50 == 0:
            print(f"  {i}/{len(rows)} ...", flush=True)
    out = CAMP / "struct_scores.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader(); w.writerows(out_rows)
    print(f"scored {len(out_rows)} events (missing {miss}) -> {out}")
    # quick separation check
    import statistics as st
    for g in ("keep", "kill"):
        vals = [r["census_ntiles_t32"] for r in out_rows if r["gold"] == g]
        print(f"  census_ntiles_t32 {g}: median={st.median(vals)} mean={st.mean(vals):.1f} n={len(vals)}")


if __name__ == "__main__":
    main()
