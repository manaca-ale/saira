#!/usr/bin/env python3
"""DINOv2 v2 — per-camera training + handcrafted feature concat.

Builds on dinov2_eval.py:
- (a) Train one LogReg per camera (cam_10, cam_11) with 5-fold CV.
- (b) Concatenate DINOv2 (2304-d) with handcrafted pile-zone features (14-d)
      and re-evaluate globally and per-camera.

Uses cached embeddings from /tmp/dinov2_eval/embeddings.npz.
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import psycopg2
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

EMB_CACHE = Path("/tmp/dinov2_eval/embeddings.npz")
HANDCRAFTED = Path("/tmp/pilezone_full_results.json")
DEVICE_BY_CAM = {10: "esp32_001", 11: "esp32_002"}


def fetch_events():
    conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                            password="postgres", dbname="saira_db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id::text, timestamp::text, camera_id, status::text
        FROM detections
        WHERE status IN ('REJEITADO', 'CONFIRMADO')
          AND camera_id IN (10, 11)
        ORDER BY timestamp DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r[0]: {"ts": r[1], "cam": r[2], "status": r[3]} for r in rows}


def main():
    cache = np.load(EMB_CACHE, allow_pickle=True)
    X_emb = cache["X"]
    ids = list(cache["ids"])
    print(f"[load] embeddings X={X_emb.shape}", flush=True)

    events = fetch_events()
    hc_raw = json.loads(HANDCRAFTED.read_text())
    hc_map = {r["id"]: r for r in hc_raw}
    print(f"[load] events={len(events)} handcrafted={len(hc_map)}", flush=True)

    HC_FEATS = ["changed_pct", "edge_a_pct", "edge_b_pct", "edge_delta_pct",
                "sat_delta", "ncc"]

    rows = []
    X_rows_emb = []
    X_rows_full = []
    for i, det_id in enumerate(ids):
        ev = events.get(str(det_id))
        if not ev or str(det_id) not in hc_map:
            continue
        hc = hc_map[str(det_id)]
        X_rows_emb.append(X_emb[i])
        hc_vec = np.array([hc.get(f, 0.0) for f in HC_FEATS], dtype=np.float32)
        X_rows_full.append(np.concatenate([X_emb[i], hc_vec]))
        rows.append({
            "id": str(det_id), "ts": ev["ts"], "cam": ev["cam"],
            "gt": "CON" if ev["status"] == "CONFIRMADO" else "REJ",
        })
    X_emb_arr = np.stack(X_rows_emb)
    X_full_arr = np.stack(X_rows_full)
    y = np.array([1 if r["gt"] == "CON" else 0 for r in rows])
    cams = np.array([r["cam"] for r in rows])
    print(f"[align] usable rows={len(rows)} CON={int(y.sum())} REJ={int((1-y).sum())}", flush=True)

    def cv(X, y, name, n_splits=5):
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        pipe = Pipeline([("sc", StandardScaler()),
                         ("lr", LogisticRegression(C=1.0, max_iter=2000))])
        accs = cross_val_score(pipe, X, y, cv=skf, scoring="accuracy")
        try:
            aucs = cross_val_score(pipe, X, y, cv=skf, scoring="roc_auc")
            auc_str = f"AUC={aucs.mean():.3f} +- {aucs.std():.3f}"
        except Exception as exc:
            auc_str = f"AUC=N/A ({exc})"
        y_pred = cross_val_predict(pipe, X, y, cv=skf)
        cm = confusion_matrix(y, y_pred)
        tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, 0)
        print(f"  {name:<46s} n={len(y):<3} acc={accs.mean():.2%} +- {accs.std():.2%}  {auc_str}  "
              f"TP={tp} TN={tn} FP={fp} FN={fn}", flush=True)
        return accs.mean(), accs.std()

    print("\n=== (a) Per-camera training (5-fold) ===", flush=True)
    print("--- DINOv2 only (2304-d) ---")
    for cam in (10, 11):
        mask = cams == cam
        n = int(mask.sum())
        n_cls = sorted(np.bincount(y[mask], minlength=2).tolist())
        n_splits = min(5, n_cls[0])  # cv needs at least 1 sample per class per fold
        if n_splits < 2:
            print(f"  cam_{cam}: insufficient class balance ({n_cls}), skipping", flush=True)
            continue
        cv(X_emb_arr[mask], y[mask], f"cam_{cam} DINOv2-only", n_splits=n_splits)

    print("--- DINOv2 + handcrafted (2310-d) ---")
    for cam in (10, 11):
        mask = cams == cam
        n_cls = sorted(np.bincount(y[mask], minlength=2).tolist())
        n_splits = min(5, n_cls[0])
        if n_splits < 2:
            continue
        cv(X_full_arr[mask], y[mask], f"cam_{cam} DINOv2+hc", n_splits=n_splits)

    print("\n=== (b) Global + handcrafted concat ===", flush=True)
    cv(X_emb_arr, y, "global DINOv2-only", n_splits=5)
    cv(X_full_arr, y, "global DINOv2+hc", n_splits=5)

    # Try LinearSVC variants too
    print("\n=== LinearSVC global ===", flush=True)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    for X_arr, label in ((X_emb_arr, "DINOv2-only"), (X_full_arr, "DINOv2+hc")):
        pipe = Pipeline([("sc", StandardScaler()),
                         ("svc", LinearSVC(C=1.0, max_iter=3000))])
        accs = cross_val_score(pipe, X_arr, y, cv=skf, scoring="accuracy")
        print(f"  {label:<30s} acc={accs.mean():.2%} +- {accs.std():.2%}", flush=True)

    # cam_10 deep-dive: which events FP/FN-ed?
    print("\n=== cam_10 per-event predictions (DINOv2-only) ===", flush=True)
    mask = cams == 10
    rows_cam = [r for r, m in zip(rows, mask) if m]
    n_cls_cam = sorted(np.bincount(y[mask], minlength=2).tolist())
    n_splits_cam = min(5, n_cls_cam[0])
    if n_splits_cam >= 2:
        skf_cam = StratifiedKFold(n_splits=n_splits_cam, shuffle=True, random_state=42)
        pipe = Pipeline([("sc", StandardScaler()),
                         ("lr", LogisticRegression(C=1.0, max_iter=2000))])
        y_pred_cam = cross_val_predict(pipe, X_emb_arr[mask], y[mask], cv=skf_cam)
        wrong = 0
        for r, yt, yp in zip(rows_cam, y[mask], y_pred_cam):
            mark = "OK" if yt == yp else "MISS"
            if mark == "MISS":
                wrong += 1
                print(f"  {mark}  {r['ts']}  cam_{r['cam']}  GT={r['gt']}  pred={'CON' if yp else 'REJ'}",
                      flush=True)
        print(f"  cam_10 wrong: {wrong}/{int(mask.sum())}", flush=True)


if __name__ == "__main__":
    main()
