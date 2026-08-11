#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase C — cross-reference TP locations vs pile_zone_polygon + propose new polygons.

Answers the user's first question ("where do TPs fall vs the current 4 polygons, are they
hurting?") and proposes a RECALL-SAFE polygon set that covers 100% of TP points while
cutting as much FP area as possible.

Inputs:
  labeling/tp_labels.json        manual TP points (x,y in 1280x720)  [primary]
  data/current_polygons_live.json  the 4 live polygons (Phase A dump)
  (optional) camp-41 proposal      benchmarks/.../41-.../results/proposed_polygons.json
  a baseline frame                 data/datasets/official/cam_imbiribeira/baseline/day

FP points (supporting, APPROXIMATE): derived from detections.waste_bbox, which is in
Gemini's 0-1000 normalized [ymin,xmin,ymax,xmax] space — flagged approximate, NOT used to
drive the recall-safe proposal (TP points do).

Outputs: results/points_overlay.png, results/coverage.json, results/proposed_polygons.json
+ the UPDATE SQL (a deliverable; not auto-applied).
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.path import Path as MplPath

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
CAMP = Path(__file__).resolve().parents[1]
OFFICIAL = ROOT / "data" / "datasets" / "official"
RES = CAMP / "results"
RES.mkdir(parents=True, exist_ok=True)
REF_W, REF_H = 1280, 720
CAMP41 = ROOT / "benchmarks" / "campaigns" / "41-structural-delta-mangabeira-2026-06-16" / "results" / "proposed_polygons.json"


def load_polys(path: Path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def load_camp41():
    if not CAMP41.exists():
        return []
    d = json.loads(CAMP41.read_text(encoding="utf-8"))
    for k, v in d.items():
        if "esp32_001" in k or "imbiri" in k.lower():
            return v.get("proposed", [])
    return []


def tp_points_manual(path: Path):
    """Manual TP clicks (x,y in 1280x720). Returns list of (x,y)."""
    if not path.exists():
        return []
    d = json.loads(path.read_text(encoding="utf-8"))
    pts = []
    for e in d.get("events", []):
        if e.get("x") is not None and e.get("y") is not None and not e.get("skipped"):
            pts.append((float(e["x"]), float(e["y"])))
    return pts


def points_from_bbox(category):
    """Approximate centroids from detections.waste_bbox (Gemini 0-1000 [ymin,xmin,ymax,xmax]).
    APPROXIMATE — convention-dependent. Used only for FP support / preliminary TP preview."""
    import csv
    pts = []
    rows = [r for r in csv.DictReader((OFFICIAL / "manifest.csv").open(encoding="utf-8"))
            if r.get("camera") == "cam_imbiribeira" and r.get("category") == category]
    for r in rows:
        lj = OFFICIAL / r["local_path"] / "label.json"
        if not lj.exists():
            continue
        b = json.loads(lj.read_text(encoding="utf-8")).get("waste_bbox", "")
        if not b:
            continue
        try:
            ymin, xmin, ymax, xmax = json.loads(b)
        except Exception:
            continue
        cx = (xmin + xmax) / 2 / 1000 * REF_W
        cy = (ymin + ymax) / 2 / 1000 * REF_H
        if 0 <= cx <= REF_W and 0 <= cy <= REF_H:
            pts.append((cx, cy))
    return pts


def coverage(points, polys):
    """Fraction of points inside ANY polygon, + total polygon area % of frame."""
    if not points:
        cov = None
    else:
        inside = np.zeros(len(points), dtype=bool)
        for poly in polys:
            if len(poly) >= 3:
                inside |= MplPath(poly).contains_points(points)
        cov = float(inside.mean())
    area = 0.0
    for poly in polys:
        if len(poly) >= 3:
            a = np.array(poly)
            area += 0.5 * abs(np.dot(a[:, 0], np.roll(a[:, 1], -1)) - np.dot(a[:, 1], np.roll(a[:, 0], -1)))
    return cov, area / (REF_W * REF_H)


def propose_recall_safe(tp_pts, fp_pts, cell=40, ratio=0.5, pad=28):
    """Grid TP/FP-ratio proposal that COVERS 100% of TP points (recall-safe).

    1) keep grid cells with >=1 TP and tp/(tp+fp) >= ratio,
    2) plus a padded box around EVERY TP point (guarantees 100% TP coverage even for
       isolated/low-ratio TPs),
    3) merge into connected components -> convex hull per component.
    """
    from scipy import ndimage
    nx, ny = REF_W // cell + 1, REF_H // cell + 1
    tpg = np.zeros((ny, nx)); fpg = np.zeros((ny, nx))
    for x, y in tp_pts:
        tpg[int(y // cell), int(x // cell)] += 1
    for x, y in fp_pts:
        fpg[int(y // cell), int(x // cell)] += 1
    keep = (tpg >= 1) & ((tpg / np.maximum(tpg + fpg, 1)) >= ratio)
    # recall-safe: also force-keep every cell containing a TP + its 8-neighbourhood
    tp_cells = tpg >= 1
    keep = keep | ndimage.binary_dilation(tp_cells, iterations=1)
    polys = _cells_to_polys(keep, cell)
    # ensure every TP point is inside; if not, add a padded box around it
    extra = []
    for (x, y) in tp_pts:
        if not any(len(p) >= 3 and MplPath(p).contains_point((x, y)) for p in polys + extra):
            extra.append([[max(0, x - pad), max(0, y - pad)], [min(REF_W, x + pad), max(0, y - pad)],
                          [min(REF_W, x + pad), min(REF_H, y + pad)], [max(0, x - pad), min(REF_H, y + pad)]])
    return polys + extra


def _cells_to_polys(keep, cell):
    from scipy import ndimage
    lbl, n = ndimage.label(keep)
    out = []
    for k in range(1, n + 1):
        ys, xs = np.where(lbl == k)
        pts = []
        for cy, cx in zip(ys, xs):
            x0, y0, x1, y1 = cx * cell, cy * cell, (cx + 1) * cell, (cy + 1) * cell
            pts += [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        pts = np.clip(np.array(pts), [0, 0], [REF_W, REF_H])
        hull = _convex_hull(pts)
        if len(hull) >= 3:
            out.append([[int(x), int(y)] for x, y in hull])
    return out


def _convex_hull(points):
    pts = sorted(set(map(tuple, points)))
    if len(pts) <= 2:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def plot_overlay(frame, tp_pts, fp_pts, current, camp41, proposed, out):
    fig, ax = plt.subplots(figsize=(12.8, 7.2), dpi=100)
    if frame and Path(frame).exists():
        img = plt.imread(frame)
        ax.imshow(img, extent=[0, REF_W, REF_H, 0])
    ax.set_xlim(0, REF_W); ax.set_ylim(REF_H, 0)
    for poly in current:
        _draw(ax, poly, "#4ea1ff", "current (live x4)")
    for poly in camp41:
        _draw(ax, poly, "#fbbd23", "camp-41")
    for poly in proposed:
        _draw(ax, poly, "#36d399", "proposed (recall-safe)", lw=2.5)
    if fp_pts:
        fp = np.array(fp_pts); ax.scatter(fp[:, 0], fp[:, 1], c="#f87272", s=18, alpha=.55, label=f"FP~bbox ({len(fp)})", marker="x")
    if tp_pts:
        tp = np.array(tp_pts); ax.scatter(tp[:, 0], tp[:, 1], c="#19d36b", s=90, edgecolors="k", linewidths=1.2, label=f"TP ({len(tp)})", zorder=5)
    # de-dup legend
    h, l = ax.get_legend_handles_labels()
    seen = {}; hh = []; ll = []
    for hi, li in zip(h, l):
        if li not in seen:
            seen[li] = 1; hh.append(hi); ll.append(li)
    ax.legend(hh, ll, loc="upper right", fontsize=9)
    ax.set_title("Imbiribeira (esp32_001) — TP locations vs pile_zone_polygon", fontsize=12)
    fig.tight_layout(); fig.savefig(out, bbox_inches="tight"); plt.close(fig)


def _draw(ax, poly, color, label, lw=1.8):
    if len(poly) < 3:
        return
    p = np.array(poly + [poly[0]])
    ax.plot(p[:, 0], p[:, 1], color=color, lw=lw, label=label)
    ax.fill(p[:, 0], p[:, 1], color=color, alpha=0.10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tp-source", choices=["manual", "bbox"], default="manual",
                    help="manual=labeling/tp_labels.json (default); bbox=preliminary from waste_bbox")
    ap.add_argument("--ratio", type=float, default=0.5)
    ap.add_argument("--cell", type=int, default=40)
    args = ap.parse_args()

    current = load_polys(CAMP / "data" / "current_polygons_live.json")
    camp41 = load_camp41()
    fp_pts = points_from_bbox("fp")
    if args.tp_source == "manual":
        tp_pts = tp_points_manual(CAMP / "labeling" / "tp_labels.json")
        if not tp_pts:
            print("WARN no manual tp_labels.json yet — falling back to --tp-source bbox (PRELIMINARY)")
            tp_pts = points_from_bbox("tp"); args.tp_source = "bbox"
    else:
        tp_pts = points_from_bbox("tp")

    proposed = propose_recall_safe(tp_pts, fp_pts, cell=args.cell, ratio=args.ratio) if tp_pts else []

    cov = {}
    for name, polys in [("current_live", current), ("camp41", camp41), ("proposed", proposed)]:
        tc, area = coverage(tp_pts, polys)
        fc, _ = coverage(fp_pts, polys)
        cov[name] = {"tp_coverage": tc, "fp_coverage_approx": fc, "area_pct": round(area * 100, 2),
                     "n_polys": len(polys)}

    frames = sorted((OFFICIAL / "cam_imbiribeira" / "baseline" / "day").glob("*.jpg"))
    frame = str(frames[0]) if frames else None
    plot_overlay(frame, tp_pts, fp_pts, current, camp41, proposed, RES / "points_overlay.png")

    sql = ("UPDATE cameras SET pile_zone_polygon = '%s'::jsonb\nWHERE device_id = 'esp32_001';"
           % json.dumps(proposed)) if proposed else ""
    (RES / "proposed_polygons.json").write_text(json.dumps({
        "esp32_001_Imbiribeira": {"proposed": proposed, "tp_source": args.tp_source,
                                  "tp_coverage": cov["proposed"]["tp_coverage"],
                                  "fp_coverage_approx": cov["proposed"]["fp_coverage_approx"],
                                  "area_pct": cov["proposed"]["area_pct"]},
        "update_sql": sql}, ensure_ascii=False, indent=2), encoding="utf-8")
    (RES / "coverage.json").write_text(json.dumps({
        "tp_source": args.tp_source, "n_tp": len(tp_pts), "n_fp_bbox": len(fp_pts),
        "coverage": cov}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"TP points: {len(tp_pts)} ({args.tp_source}) | FP~bbox points: {len(fp_pts)}")
    for name, c in cov.items():
        tcv = f"{c['tp_coverage']*100:.0f}%" if c['tp_coverage'] is not None else "n/a"
        fcv = f"{c['fp_coverage_approx']*100:.0f}%" if c['fp_coverage_approx'] is not None else "n/a"
        print(f"  {name:13s}: TP_cov={tcv:>5s} FP_cov~={fcv:>5s} area={c['area_pct']:.1f}% polys={c['n_polys']}")
    print(f"-> {RES/'points_overlay.png'}")
    print(f"-> {RES/'coverage.json'} ; {RES/'proposed_polygons.json'}")


if __name__ == "__main__":
    main()
