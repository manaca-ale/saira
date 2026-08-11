#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Campaign 40 Phase B — DINOv2 retrain cam_11 OFFLINE on the official dataset.

CON=13 TP, REJ=48 FP (frames locais; prod purgou). Leakage-safe: out-of-fold
StratifiedKFold proba + temporal holdout (older 70% train / newer 30% test).
Scores eval (13 TP vs 20 B3) via out-of-fold proba. Does NOT touch prod artifact.
"""
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(r"c:\saira")
sys.stdout.reconfigure(encoding="utf-8")
DATASET = ROOT / "data" / "datasets" / "official"
RES = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "results"

BBOX = (480, 60, 920, 340)      # pile_zone bbox esp32_002 (= camp24 pile-crops)
INPUT, NF = 224, 3
_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)


def embed_all(rows):
    import torch, cv2
    torch.set_num_threads(4)
    model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", verbose=False)
    model.eval()
    x0, y0, x1, y1 = BBOX
    X, y, ids, ts, buck = [], [], [], [], []
    for r in rows:
        fdir = DATASET / r["local_path"] / "frames"
        frames = sorted(fdir.glob("*.jpg"))
        if not frames:
            continue
        sel = frames[-NF:] if len(frames) >= NF else frames
        crops = []
        for p in sel:
            img = cv2.imread(str(p))
            if img is None:
                continue
            h, w = img.shape[:2]
            cx0, cy0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
            cx1, cy1 = max(cx0 + 1, min(x1, w)), max(cy0 + 1, min(y1, h))
            crop = img[cy0:cy1, cx0:cx1]
            if crop.size == 0:
                continue
            crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            crop = cv2.resize(crop, (INPUT, INPUT), interpolation=cv2.INTER_AREA)
            crops.append((crop.astype(np.float32) / 255.0 - _MEAN) / _STD)
        if not crops:
            continue
        batch = np.stack(crops).transpose(0, 3, 1, 2)
        with torch.no_grad():
            emb = model(torch.from_numpy(batch).float()).cpu().numpy()
        X.append(emb.mean(0))
        y.append(1 if r["bucket"] == "TP" else 0)
        ids.append(r["event_id"]); ts.append(r["datetime"]); buck.append(r["bucket"])
    return (np.array(X, np.float32), np.array(y), np.array(ids, object),
            np.array(ts, object), np.array(buck, object))


def main() -> int:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    split = [r for r in csv.DictReader((RES / "b3_split.csv").open(encoding="utf-8"))
             if r["category"] in ("tp", "fp")]   # 13 TP + 48 FP
    X, y, ids, ts, buck = embed_all(split)
    print(f"embeddings: {len(y)}  (CON={int(y.sum())} REJ={int(len(y)-y.sum())})  dim={X.shape[1]}")

    # ---- out-of-fold CV proba ----
    proba = np.zeros(len(y))
    fold_of = np.zeros(len(y), int)
    skf = StratifiedKFold(5, shuffle=True, random_state=42)
    for k, (tr, te) in enumerate(skf.split(X, y)):
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
        clf.fit(sc.transform(X[tr]), y[tr])
        proba[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
        fold_of[te] = k
    cv_auc = roc_auc_score(y, proba)
    print(f"\nCV AUC (full 13/48, out-of-fold): {cv_auc:.3f}")

    # ---- temporal holdout ----
    order = np.argsort(ts)
    cut = int(0.7 * len(order))
    tr_i, te_i = order[:cut], order[cut:]
    sc = StandardScaler().fit(X[tr_i])
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(sc.transform(X[tr_i]), y[tr_i])
    p_te = clf.predict_proba(sc.transform(X[te_i]))[:, 1]
    try:
        temp_auc = roc_auc_score(y[te_i], p_te)
    except ValueError:
        temp_auc = float("nan")
    print(f"Temporal holdout AUC (train older 70% / test newer 30%): {temp_auc:.3f}"
          f"  (gap vs CV = {cv_auc - temp_auc:+.3f})")

    # ---- eval: TP vs B3 on out-of-fold proba ----
    b3_ids = {r["event_id"] for r in csv.DictReader((RES / "b3_split.csv").open(encoding="utf-8"))
              if r["bucket"] == "B3"}
    mask = np.array([(b == "TP") or (i in b3_ids) for b, i in zip(buck, ids)])
    ye = (buck[mask] == "TP").astype(int)
    pe = proba[mask]
    eval_auc = roc_auc_score(ye, pe)
    tv, bv = pe[ye == 1], pe[ye == 0]
    print(f"\nEval TP-vs-B3 AUC (out-of-fold p_con): {eval_auc:.3f}  (TP n={len(tv)}, B3 n={len(bv)})")
    print(f"  p_con TP med={np.median(tv):.3f}  B3 med={np.median(bv):.3f}")
    # veto: reject if p_con < thr, keep TP if p_con >= thr
    best = None
    for thr in np.unique(pe):
        tpk = int((tv >= thr).sum()); b3s = int((bv < thr).sum())
        if tpk >= 12 and (best is None or b3s > best[2]):
            best = (thr, tpk, b3s)
    if best:
        print(f"  veto p_con<thr @ recall>=12/13: thr={best[0]:.3f}  TPkeep={best[1]}/13  "
              f"B3supp={best[2]}/20 ({100*best[2]/len(bv):.0f}%)")

    with (RES / "phase_b_dinov2.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["event_id", "bucket", "p_con_oof", "fold"])
        for i, b, p, fo in zip(ids, buck, proba, fold_of):
            w.writerow([i, b, f"{p:.4f}", fo])
    print(f"\ncv_auc={cv_auc:.3f} temporal_auc={temp_auc:.3f} eval_auc={eval_auc:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
