#!/usr/bin/env python3
"""DINOv2 + LogReg verifier — full eval on 52 REJ + CONFIRMADO events.

Per Deep Research 2026-05-29 recommendation: extract 3 keyframes (entry / peak /
exit) from each window, embed with facebook/dinov2-base (768-d), concatenate
into a 2304-d feature, train LogisticRegression with 5-fold CV.

Compare with:
- Agent-3 (Gemini Pro few-shot): 87.5% acc on 8 events ($0.015/call)
- Pile-zone delta (OpenCV): 67% LogReg ceiling on 52 events ($0)
- Baseline (always CON): 57.7% (30/52)
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import boto3
import numpy as np
import psycopg2
import torch
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from transformers import AutoImageProcessor, AutoModel

S3 = boto3.client("s3", region_name="sa-east-1")
TMP = Path("/tmp/dinov2_eval")
TMP.mkdir(parents=True, exist_ok=True)
EMB_CACHE = TMP / "embeddings.npz"
MODEL_ID = "facebook/dinov2-base"
DEVICE_BY_CAM = {10: "esp32_001", 11: "esp32_002"}


def resolve_path(image_url: str, frame_name: str, device_id: str) -> Path | None:
    target = TMP / device_id / frame_name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1000:
        return target
    if "/uploads/" in image_url:
        rel = image_url.split("/uploads/", 1)[-1]
        local = Path("/app/uploads") / rel
        if local.exists():
            return local
        s3_key = f"ocorrencias/{rel}".replace("labeled/", "")
    elif image_url.startswith("https://saira-images.s3"):
        s3_key = urlparse(image_url).path.lstrip("/")
    elif image_url.startswith("/s3-images/"):
        s3_key = image_url[len("/s3-images/"):]
    else:
        return None
    try:
        S3.download_file("saira-images", s3_key, str(target))
        return target if target.stat().st_size > 1000 else None
    except Exception:
        return None


def load_event(det_id: str) -> dict | None:
    sf = Path(f"/app/state/detection_frames/{det_id}.json")
    if not sf.exists():
        return None
    return json.loads(sf.read_text())


def fetch_events() -> list[dict]:
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
    return [{"id": r[0], "ts": r[1], "cam": r[2], "status": r[3]} for r in rows]


def sample_3_keyframes(frames: list[dict], selected_name: str | None) -> list[int]:
    """Entry / peak / exit. Peak = detail's selected_frame if not at edge; else mid."""
    n = len(frames)
    names = [f["frame_name"] for f in frames]
    if selected_name and selected_name in names:
        sel_i = names.index(selected_name)
        if 2 < sel_i < n - 3:
            return sorted({0, sel_i, n - 1})
    return sorted({0, n // 2, n - 1})


def night_flag(ts: str) -> bool:
    try:
        h, m = int(ts[11:13]), int(ts[14:16])
        mins = h * 60 + m
        return mins >= 17 * 60 + 30 or mins <= 6 * 60 + 30
    except Exception:
        return False


def embed_image(model, processor, path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    inputs = processor(images=img, return_tensors="pt")
    with torch.no_grad():
        out = model(**inputs)
    # pooler_output is mean-pooled CLS-like; falls back to CLS token if absent
    if hasattr(out, "pooler_output") and out.pooler_output is not None:
        feat = out.pooler_output[0]
    else:
        feat = out.last_hidden_state[0, 0]
    return feat.cpu().numpy().astype(np.float32)


def main():
    print(f"[init] loading {MODEL_ID} ...", flush=True)
    t0 = time.monotonic()
    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).eval()
    print(f"  loaded in {time.monotonic()-t0:.1f}s, dim={model.config.hidden_size}", flush=True)

    events = fetch_events()
    print(f"[fetch] {len(events)} events", flush=True)

    if EMB_CACHE.exists():
        print(f"[cache] loading {EMB_CACHE.name}", flush=True)
        cache = np.load(EMB_CACHE, allow_pickle=True)
        X_cached = cache["X"]
        ids_cached = cache["ids"]
        cache_map = {str(i): X_cached[k] for k, i in enumerate(ids_cached)}
    else:
        cache_map = {}

    X_rows: list[np.ndarray] = []
    meta: list[dict] = []
    t_emb_total = 0.0
    new_embeds = 0

    for i, ev in enumerate(events, 1):
        device_id = DEVICE_BY_CAM.get(ev["cam"])
        if not device_id:
            continue
        det = load_event(ev["id"])
        if not det or not det.get("frames"):
            continue

        if ev["id"] in cache_map:
            feat = cache_map[ev["id"]]
        else:
            idxs = sample_3_keyframes(det["frames"], det.get("selected_frame_name"))
            paths = []
            for k in idxs:
                f = det["frames"][k]
                p = resolve_path(f["image_url"], f["frame_name"], device_id)
                if p:
                    paths.append(p)
            if len(paths) < 2:
                continue
            t_emb_start = time.monotonic()
            embs = [embed_image(model, processor, p) for p in paths]
            # If we got 2 instead of 3, duplicate the last so dim stays 2304
            while len(embs) < 3:
                embs.append(embs[-1])
            feat = np.concatenate(embs[:3])
            t_emb_total += time.monotonic() - t_emb_start
            new_embeds += 1

        X_rows.append(feat)
        meta.append({"id": ev["id"], "ts": ev["ts"], "cam": ev["cam"],
                     "gt": "CON" if ev["status"] == "CONFIRMADO" else "REJ",
                     "night": night_flag(ev["ts"])})
        if i % 10 == 0 or i == len(events):
            print(f"  {i}/{len(events)} (kept={len(X_rows)} new_embeds={new_embeds})", flush=True)

    X = np.stack(X_rows)
    y = np.array([1 if m["gt"] == "CON" else 0 for m in meta])
    print(f"[data] X={X.shape} y={y.shape} (CON={int(y.sum())} REJ={int((1-y).sum())})", flush=True)
    if new_embeds > 0:
        print(f"[embed] {new_embeds} new events embedded in {t_emb_total:.1f}s "
              f"({t_emb_total/new_embeds:.2f}s/event)", flush=True)

    # cache
    ids = np.array([m["id"] for m in meta])
    np.savez(EMB_CACHE, X=X, ids=ids)

    print("\n=== LogReg 5-fold CV ===", flush=True)
    pipe = Pipeline([("sc", StandardScaler()), ("lr", LogisticRegression(C=1.0, max_iter=1000))])
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    accs = cross_val_score(pipe, X, y, cv=skf, scoring="accuracy")
    aucs = cross_val_score(pipe, X, y, cv=skf, scoring="roc_auc")
    f1s = cross_val_score(pipe, X, y, cv=skf, scoring="f1")
    print(f"acc: mean={accs.mean():.2%} +- {accs.std():.2%}  folds={[f'{s:.2%}' for s in accs]}")
    print(f"AUC: mean={aucs.mean():.3f} +- {aucs.std():.3f}  folds={[f'{s:.3f}' for s in aucs]}")
    print(f"F1 : mean={f1s.mean():.3f} +- {f1s.std():.3f}  folds={[f'{s:.3f}' for s in f1s]}")

    # Confusion via cross_val_predict (out-of-fold predictions)
    y_pred = cross_val_predict(pipe, X, y, cv=skf)
    cm = confusion_matrix(y, y_pred)
    tn, fp, fn, tp = cm.ravel()
    print(f"\nConfusion (out-of-fold): TN={tn} FP={fp} FN={fn} TP={tp}")
    print(f"  precision (CON): {tp/max(tp+fp,1):.2%}")
    print(f"  recall (CON):    {tp/max(tp+fn,1):.2%}")
    print(f"  specificity:     {tn/max(tn+fp,1):.2%}")

    # Per-camera and per-period
    print("\n=== Out-of-fold by stratum ===")
    for tag, mask in (
        ("cam_10",  np.array([m["cam"] == 10 for m in meta])),
        ("cam_11",  np.array([m["cam"] == 11 for m in meta])),
        ("day",     np.array([not m["night"] for m in meta])),
        ("night",   np.array([m["night"] for m in meta])),
    ):
        if mask.sum() == 0:
            continue
        acc_s = (y_pred[mask] == y[mask]).mean()
        n_s = int(mask.sum())
        gt_s = y[mask]
        pred_s = y_pred[mask]
        tp_s = int(((pred_s == 1) & (gt_s == 1)).sum())
        tn_s = int(((pred_s == 0) & (gt_s == 0)).sum())
        fp_s = int(((pred_s == 1) & (gt_s == 0)).sum())
        fn_s = int(((pred_s == 0) & (gt_s == 1)).sum())
        print(f"  {tag:<8s} n={n_s:<3} acc={acc_s:.2%}  TP={tp_s} TN={tn_s} FP={fp_s} FN={fn_s}")

    # also try LinearSVC
    from sklearn.svm import LinearSVC
    pipe_svc = Pipeline([("sc", StandardScaler()), ("lr", LinearSVC(C=1.0, max_iter=2000))])
    accs_svc = cross_val_score(pipe_svc, X, y, cv=skf, scoring="accuracy")
    print(f"\nLinearSVC acc: mean={accs_svc.mean():.2%} +- {accs_svc.std():.2%}")

    # save predictions
    out = Path("/tmp/dinov2_results.json")
    rows_out = []
    for m, yt, yp in zip(meta, y, y_pred):
        rows_out.append({**m, "y_true": int(yt), "y_pred": int(yp)})
    out.write_text(json.dumps({
        "model": MODEL_ID,
        "n": len(meta),
        "cv_acc_mean": float(accs.mean()),
        "cv_acc_std": float(accs.std()),
        "cv_auc_mean": float(aucs.mean()),
        "cv_auc_std": float(aucs.std()),
        "cv_f1_mean": float(f1s.mean()),
        "confusion": cm.tolist(),
        "rows": rows_out,
    }, ensure_ascii=False, indent=2))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    sys.exit(main())
