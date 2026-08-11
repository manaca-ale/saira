#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validação visual do polígono + A/B de geometria (DB vs handoff) para o Shadow B.

(a) Overlay polígono (verde) + máscara census-changed (vermelho) sobre o par 1º/último
    frame legível de ~4 TP + 4 FP → viz/pair_<cat>_<id>.jpg. Confirma alinhamento da
    pile-zone e mostra ONDE o sinal acende.
(b) A/B: recomputa n_tiles_changed e AUC(TP vs FP) e AUC(TP vs baseline) para o polígono
    VIGENTE de prod vs o polígono (mais concentrado) do handoff — diz se re-marcar o
    polígono é a alavanca para o gate.
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import numpy as np

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
HERE = Path(__file__).resolve().parent.parent
CAM = ROOT / "data" / "datasets" / "official" / "cam_picam001"
VIZ = HERE / "viz"; VIZ.mkdir(exist_ok=True)

os.environ.setdefault("STATE_DIR", str(HERE / "results" / "_state_tmp"))
os.environ.setdefault("DATABASE_URL", "postgresql://bench:bench@localhost/bench")
sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
import worker.detector_structural as ds  # noqa: E402

POLY_DB = [[[18, 550], [12, 709], [1264, 709], [1262, 540]],
           [[325, 3], [288, 73], [1191, 162], [1167, 8]]]
POLY_HANDOFF = [[[409, 498], [217, 714], [1177, 719], [1204, 545]],
                [[491, 109], [410, 164], [1218, 332], [1163, 202]]]


def first_last(evt: Path):
    import cv2
    frames = sorted((evt / "frames").glob("*.jpg"))
    before = b = after = a = None
    for p in frames:
        im = cv2.imread(str(p))
        if im is not None:
            before, b = im, p; break
    for p in reversed(frames):
        im = cv2.imread(str(p))
        if im is not None:
            after, a = im, p; break
    return before, after, frames


def make_overlays():
    import cv2
    for cat, ids in [("tp", 4), ("fp", 4)]:
        evts = sorted((CAM / cat).glob("evt-*"))[:ids]
        for evt in evts:
            before, after, frames = first_last(evt)
            if before is None or after is None or before.shape != after.shape:
                continue
            mask = ds._build_mask(POLY_DB, before.shape[:2])
            gray_pre = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
            gray_post = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
            ham = ds._census_hamming(gray_pre, gray_post)
            changed = (ham >= 3).astype(np.uint8)
            k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, k)
            vis = after.copy()
            if mask is not None:
                red = (changed > 0) & (mask > 0)
                vis[red] = (0, 0, 255)
                for poly in POLY_DB:
                    cv2.polylines(vis, [np.array(poly, np.int32)], True, (0, 255, 0), 2)
            res = ds.score_window(frames, POLY_DB)
            pair = np.hstack([before, vis])
            cv2.putText(pair, f"{cat} {evt.name}  n_tiles={res.n_tiles_changed}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            out = VIZ / f"pair_{cat}_{evt.name}.jpg"
            cv2.imwrite(str(out), pair)
            print(f"  {out.relative_to(ROOT)}  n_tiles={res.n_tiles_changed}")


def auc(pos, neg):
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    n = sum(float(np.sum(p > neg)) + 0.5 * float(np.sum(p == neg)) for p in pos)
    return n / (len(pos) * len(neg))


def ab_polygons():
    cats = {}
    for cat in ["tp", "fp", "baseline"]:
        vals_db, vals_ho = [], []
        for evt in sorted((CAM / cat).glob("evt-*")):
            frames = sorted((evt / "frames").glob("*.jpg"))
            r1 = ds.score_window(frames, POLY_DB)
            r2 = ds.score_window(frames, POLY_HANDOFF)
            if r1.reason == "scored":
                vals_db.append(r1.n_tiles_changed)
            if r2.reason == "scored":
                vals_ho.append(r2.n_tiles_changed)
        cats[cat] = (np.array(vals_db), np.array(vals_ho))
    tp_db, tp_ho = cats["tp"]
    fp_db, fp_ho = cats["fp"]
    bs_db, bs_ho = cats["baseline"]
    print("\n=== A/B de polígono (AUC) ===")
    print(f"  polígono DB (prod, largo):     TP-vs-FP {auc(tp_db, fp_db):.4f}   TP-vs-baseline {auc(tp_db, bs_db):.4f}")
    print(f"  polígono handoff (concentrado):TP-vs-FP {auc(tp_ho, fp_ho):.4f}   TP-vs-baseline {auc(tp_ho, bs_ho):.4f}")
    print(f"  medianas DB      TP={np.median(tp_db):.0f} FP={np.median(fp_db):.0f} base={np.median(bs_db):.0f}")
    print(f"  medianas handoff TP={np.median(tp_ho):.0f} FP={np.median(fp_ho):.0f} base={np.median(bs_ho):.0f}")


if __name__ == "__main__":
    print("=== overlays (polígono DB de prod) ===")
    make_overlays()
    ab_polygons()
