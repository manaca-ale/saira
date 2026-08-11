#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Larger-N DINOv2: train CON(72 TP) vs REJ(188) on prod cam_11 detections.

Frames = last-3 already downloaded (largeN/manifest.csv). Out-of-fold StratifiedKFold
+ temporal holdout. Eval TP-vs-B3 (144) AUC + veto operating point + bootstrap CI.
"""
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(r"c:\saira")
sys.stdout.reconfigure(encoding="utf-8")
LN = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "largeN"
BBOX = (480, 60, 920, 340)
INPUT = 224
_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)
RNG = np.random.default_rng(7)


def embed(rows):
    import torch, cv2
    torch.set_num_threads(4)
    m = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", verbose=False)
    m.eval()
    x0, y0, x1, y1 = BBOX
    X, y, ids, ts, buck = [], [], [], [], []
    for r in rows:
        crops = []
        for p in r["frames"].split("|"):
            img = cv2.imread(p)
            if img is None:
                continue
            h, w = img.shape[:2]
            cx0, cy0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
            cx1, cy1 = max(cx0 + 1, min(x1, w)), max(cy0 + 1, min(y1, h))
            c = img[cy0:cy1, cx0:cx1]
            if c.size == 0:
                continue
            c = cv2.cvtColor(c, cv2.COLOR_BGR2RGB)
            c = cv2.resize(c, (INPUT, INPUT), interpolation=cv2.INTER_AREA)
            crops.append((c.astype(np.float32) / 255.0 - _MEAN) / _STD)
        if not crops:
            continue
        b = np.stack(crops).transpose(0, 3, 1, 2)
        with torch.no_grad():
            e = m(torch.from_numpy(b).float()).cpu().numpy()
        X.append(e.mean(0)); y.append(int(r["label"]))
        ids.append(r["id"]); ts.append(r["created_at"]); buck.append(r["bucket"])
    return (np.array(X, np.float32), np.array(y), np.array(ids, object),
            np.array(ts, object), np.array(buck, object))


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    rows = [r for r in csv.DictReader((LN / "manifest.csv").open(encoding="utf-8"))]
    X, y, ids, ts, buck = embed(rows)
    print(f"embeddings: {len(y)}  CON={int(y.sum())} REJ={int(len(y)-y.sum())}  "
          f"(B3={int((buck=='B3').sum())} B1B2={int((buck=='B1B2').sum())})")

    proba = np.zeros(len(y)); fold = np.zeros(len(y), int)
    skf = StratifiedKFold(5, shuffle=True, random_state=42)
    for k, (tr, te) in enumerate(skf.split(X, y)):
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
        clf.fit(sc.transform(X[tr]), y[tr])
        proba[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]; fold[te] = k
    cv_auc = roc_auc_score(y, proba)

    order = np.argsort(ts); cut = int(0.7 * len(order))
    tri, tei = order[:cut], order[cut:]
    sc = StandardScaler().fit(X[tri])
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0).fit(sc.transform(X[tri]), y[tri])
    temp_auc = roc_auc_score(y[tei], clf.predict_proba(sc.transform(X[tei]))[:, 1])

    # eval TP vs B3 (out-of-fold)
    mask = (buck == "TP") | (buck == "B3")
    ye = (buck[mask] == "TP").astype(int); pe = proba[mask]
    eval_auc = roc_auc_score(ye, pe)
    tv, bv = pe[ye == 1], pe[ye == 0]

    print(f"\nCV AUC (CON-vs-REJ, out-of-fold, n={len(y)}): {cv_auc:.3f}")
    print(f"Temporal holdout AUC (older 70% / newer 30%): {temp_auc:.3f}  (gap {cv_auc-temp_auc:+.3f})")
    print(f"Eval TP-vs-B3 AUC: {eval_auc:.3f}  (TP={len(tv)} B3={len(bv)})  "
          f"p_con TP med={np.median(tv):.3f} B3 med={np.median(bv):.3f}")

    # veto sweep: reject if p_con < thr; recall floor as fraction
    print(f"\n{'thr':>6s} {'recall':>10s} {'B3-supr':>14s}")
    floor = int(np.ceil(len(tv) * 11 / 13))  # same proportion as small-N floor (~0.846)
    best = {}
    for thr in np.unique(pe):
        tpk = int((tv >= thr).sum()); b3s = int((bv < thr).sum())
        for tag, cond in (("recall_safe", tpk == len(tv)), ("floor85", tpk >= floor)):
            if cond and (tag not in best or b3s > best[tag][2]):
                best[tag] = (thr, tpk, b3s)
    for tag, (thr, tpk, b3s) in best.items():
        # bootstrap CI on B3 suppression at this thr
        ss = []
        for _ in range(10000):
            bi = RNG.integers(0, len(bv), len(bv))
            ss.append((bv[bi] < thr).sum() / len(bv) * 100)
        lo, hi = np.percentile(ss, [2.5, 97.5])
        print(f"{thr:6.3f} {tpk:>3d}/{len(tv):<3d}({tag:11s}) {b3s:>3d}/{len(bv):<3d} "
              f"{100*b3s/len(bv):.0f}% CI[{lo:.0f},{hi:.0f}]")

    with (LN / "dinov2_scores.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["id", "bucket", "p_con_oof", "fold", "created_at"])
        for i, b, p, fo, t in zip(ids, buck, proba, fold, ts):
            w.writerow([i, b, f"{p:.4f}", fo, t])
    print(f"\ncv_auc={cv_auc:.3f} temporal_auc={temp_auc:.3f} eval_auc={eval_auc:.3f}")


if __name__ == "__main__":
    main()
