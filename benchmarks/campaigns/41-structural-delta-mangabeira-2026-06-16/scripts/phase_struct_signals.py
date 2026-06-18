#!/usr/bin/env python3
"""Phase 1.2 — micro-tile structural-delta descriptors, before vs after.

For each event (before/after picked in before_after.csv) compute, INSIDE the real
esp32_002 pile polygon, illumination-invariant structural change:
  - Census-Hamming  (census.py — invariant to monotonic brightness)
  - Canny new-edge  (edges in AFTER absent in dilated BEFORE — camp 20 proto idea)
  - NCC             (normalized cross-correlation; low = structurally different)

The pile bbox is split into 16x16 and 32x32 tiles; each descriptor is evaluated per
tile (restricted to polygon pixels). A tiny bag occupies 2-3 tiles at ~100% change,
so the discriminative aggregate is expected to be max_tile / n_tiles_changed, NOT a
global mean (which the huge undisturbed pile dilutes — Camp 40 lesson). We also emit
the camp-20 GLOBAL metrics over the whole mask for a direct apples-to-apples check.

Pure cv2 + numpy, $0. Outputs results/struct_signals.csv.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(r"c:\saira")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding="utf-8")

from census import census_hamming  # noqa: E402

CAMP = ROOT / "benchmarks" / "campaigns" / "41-structural-delta-mangabeira-2026-06-16"
LARGEN = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "largeN"
FRAMES24 = LARGEN / "frames24"
RES = CAMP / "results"

PILE_POLY = np.array([[461, 154], [704, 66], [939, 299], [617, 416]], dtype=np.int32)

# descriptor thresholds (operating point swept later by ROC; these define the per-tile
# "changed" booleans used for the n_tiles_changed aggregates)
HAM_THR = 3            # hamming >= 3 of 8 bits => structurally different pixel
CENSUS_TILE_FRAC = 0.50
EDGE_TILE_FRAC = 0.15
NCC_TILE_THR = 0.70
MIN_TILE_COVER_PX = 24  # tile must have >= this many polygon pixels to be scored


def build_mask(shape) -> np.ndarray:
    m = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(m, [PILE_POLY], 255)
    return m


def bbox_of_poly():
    x0, y0 = PILE_POLY[:, 0].min(), PILE_POLY[:, 1].min()
    x1, y1 = PILE_POLY[:, 0].max(), PILE_POLY[:, 1].max()
    return int(x0), int(y0), int(x1), int(y1)


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 8:
        return 1.0
    a = a.astype(np.float32) - a.mean()
    b = b.astype(np.float32) - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom > 1e-6 else 1.0


def tile_aggregates(changed_census, new_edges, gray_pre, gray_post, mask, tile):
    """Aggregate per-tile fractions across all tiles touching the polygon."""
    x0, y0, x1, y1 = bbox_of_poly()
    census_fracs, edge_fracs, nccs = [], [], []
    for ty in range(y0, y1, tile):
        for tx in range(x0, x1, tile):
            tm = mask[ty:ty + tile, tx:tx + tile] > 0
            cov = int(tm.sum())
            if cov < MIN_TILE_COVER_PX:
                continue
            cc = changed_census[ty:ty + tile, tx:tx + tile][tm]
            ne = new_edges[ty:ty + tile, tx:tx + tile][tm]
            gp = gray_pre[ty:ty + tile, tx:tx + tile][tm]
            gq = gray_post[ty:ty + tile, tx:tx + tile][tm]
            census_fracs.append(float(cc.mean()))
            edge_fracs.append(float(ne.mean()))
            nccs.append(ncc(gp, gq))
    census_fracs = np.array(census_fracs) if census_fracs else np.array([0.0])
    edge_fracs = np.array(edge_fracs) if edge_fracs else np.array([0.0])
    nccs = np.array(nccs) if nccs else np.array([1.0])
    return {
        f"census_max_t{tile}": round(float(census_fracs.max()), 4),
        f"census_mean_t{tile}": round(float(census_fracs.mean()), 4),
        f"census_ntiles_t{tile}": int((census_fracs > CENSUS_TILE_FRAC).sum()),
        f"edge_max_t{tile}": round(float(edge_fracs.max()), 4),
        f"edge_mean_t{tile}": round(float(edge_fracs.mean()), 4),
        f"edge_ntiles_t{tile}": int((edge_fracs > EDGE_TILE_FRAC).sum()),
        f"ncc_min_t{tile}": round(float(nccs.min()), 4),
        f"ncc_mean_t{tile}": round(float(nccs.mean()), 4),
        f"ncc_ntiles_t{tile}": int((nccs < NCC_TILE_THR).sum()),
        f"n_tiles_t{tile}": int(len(census_fracs)),
    }


def global_metrics(gray_pre, gray_post, mask, ham):
    """Camp-20 global metrics over the whole polygon (apples-to-apples baseline)."""
    mb = mask > 0
    area = int(mb.sum())
    # census global fraction
    census_global = float((ham[mb] >= HAM_THR).mean())
    # absdiff changed_pct (camp20)
    diff = cv2.absdiff(gray_pre, gray_post)
    changed_pct = float((diff[mb] > 25).mean()) * 100
    # edge delta pct (camp20)
    ea = cv2.Canny(gray_pre, 60, 180)
    eb = cv2.Canny(gray_post, 60, 180)
    edge_a = float((ea[mb] > 0).mean()) * 100
    edge_b = float((eb[mb] > 0).mean()) * 100
    # ncc global
    ncc_g = ncc(gray_pre[mb], gray_post[mb])
    return {
        "g_census_frac": round(census_global, 4),
        "g_changed_pct": round(changed_pct, 3),
        "g_edge_delta_pct": round(edge_b - edge_a, 3),
        "g_ncc": round(ncc_g, 4),
        "mask_area_px": area,
    }


def compute_event(before_path: Path, after_path: Path, mask: np.ndarray) -> dict | None:
    ia = cv2.imread(str(before_path))
    ib = cv2.imread(str(after_path))
    if ia is None or ib is None or ia.shape != ib.shape:
        return None
    gray_pre = cv2.cvtColor(ia, cv2.COLOR_BGR2GRAY)
    gray_post = cv2.cvtColor(ib, cv2.COLOR_BGR2GRAY)

    # Census-Hamming structural change map (illumination invariant)
    ham = census_hamming(gray_pre, gray_post)
    changed_census = (ham >= HAM_THR).astype(np.uint8)
    # morphological open to drop isolated sensor-noise bit flips
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    changed_census = cv2.morphologyEx(changed_census, cv2.MORPH_OPEN, k)

    # New edges in AFTER not present in dilated BEFORE (camouflage-robust)
    ea = cv2.Canny(gray_pre, 60, 180)
    eb = cv2.Canny(gray_post, 60, 180)
    ea_dil = cv2.dilate(ea, k)
    new_edges = cv2.subtract(eb, ea_dil)
    new_edges = (new_edges > 0).astype(np.uint8)

    out = {}
    for tile in (16, 32):
        out.update(tile_aggregates(changed_census, new_edges, gray_pre, gray_post, mask, tile))
    out.update(global_metrics(gray_pre, gray_post, mask, ham))
    return out


def main() -> int:
    suffix = sys.argv[1] if len(sys.argv) > 1 else ""
    ba = list(csv.DictReader((RES / f"before_after{suffix}.csv").open(encoding="utf-8")))
    mask = build_mask((720, 1280))
    rows = []
    for i, r in enumerate(ba, 1):
        bp = FRAMES24 / r["before_frame"]
        ap = FRAMES24 / r["after_frame"]
        if not bp.exists() or not ap.exists():
            continue
        m = compute_event(bp, ap, mask)
        if m is None:
            continue
        rows.append({
            "event_id": r["event_id"], "bucket": r["bucket"],
            "created_at": r["created_at"], "after_motion": r["after_motion"], **m,
        })
        if i % 40 == 0:
            print(f"  {i}/{len(ba)} ...", flush=True)

    out = RES / f"struct_signals{suffix}.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    tp = sum(1 for r in rows if r["bucket"] == "TP")
    b3 = sum(1 for r in rows if r["bucket"] == "B3")
    print(f"scored {len(rows)} events (TP={tp} B3={b3})  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
