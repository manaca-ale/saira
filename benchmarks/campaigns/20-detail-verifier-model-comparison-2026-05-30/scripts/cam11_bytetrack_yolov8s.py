#!/usr/bin/env python3
"""cam_11 solution attempt — ByteTrack person dwell + object features.

cam_11 (Mangabeira) com DINOv2-only foi 47% / AUC 0.525 (chute). Hipótese: o
sinal de "depositando vs passando" está na DINAMICA, não no quadro estático.

Per evento cam_11:
  1. Amostra ~25 frames evenly do window.
  2. Roda YOLOv8n + ByteTrack (pessoas + objetos COCO relevantes).
  3. Extrai features de:
     - dwell de pessoas dentro do pile_zone_polygon
     - proximidade pessoa-polygon (closest approach)
     - objetos (bag/handbag/backpack/suitcase/bottle) detectados no polygon
     - persistência de objetos após pessoa sair
  4. 5-fold CV: tracking-only, tracking+DINOv2, comparativo.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import boto3
import cv2
import numpy as np
import psycopg2
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from ultralytics import YOLO

S3 = boto3.client("s3", region_name="sa-east-1")
TMP = Path("/tmp/cam11_track")
TMP.mkdir(parents=True, exist_ok=True)
EMB_CACHE = Path("/tmp/dinov2_eval/embeddings.npz")
TRACK_CACHE = TMP / "tracking_features.json"

# Mangabeira pile polygon
PILE_POLY = np.array([[480, 60], [920, 60], [920, 340], [480, 340]], dtype=np.int32)

N_FRAMES_SAMPLE = 40  # frames to sample per window for tracking
YOLO_IMGSZ = 1280  # full res to preserve small/distant people
YOLO_MODEL = "yolov8s.pt"
YOLO_CONF = 0.15
PERSON_CLASS = 0
OBJECT_CLASSES = {24: "backpack", 26: "handbag", 28: "suitcase", 39: "bottle",
                  41: "cup", 67: "cell_phone"}  # COCO ids
# Track results dir is required by ultralytics; use TMP


def resolve_path(image_url: str, frame_name: str, device_id: str = "esp32_002") -> Path | None:
    target = TMP / "frames" / device_id / frame_name
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


def fetch_events():
    conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                            password="postgres", dbname="saira_db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id::text, timestamp::text, status::text
        FROM detections
        WHERE camera_id = 11 AND status IN ('REJEITADO', 'CONFIRMADO')
        ORDER BY timestamp DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "ts": r[1], "status": r[2]} for r in rows]


def load_event(det_id: str):
    sf = Path(f"/app/state/detection_frames/{det_id}.json")
    if not sf.exists():
        return None
    return json.loads(sf.read_text())


def sample_n_frames(frames, n):
    if len(frames) <= n:
        return list(range(len(frames)))
    return [int(round(i * (len(frames) - 1) / (n - 1))) for i in range(n)]


def centroid_in_polygon(cx: float, cy: float, poly: np.ndarray) -> bool:
    return cv2.pointPolygonTest(poly, (float(cx), float(cy)), False) >= 0


def dist_to_polygon(cx: float, cy: float, poly: np.ndarray) -> float:
    """Negative inside, positive outside."""
    return -cv2.pointPolygonTest(poly, (float(cx), float(cy)), True)


def extract_tracking_features(model, paths, frame_dt_sec, pile_poly):
    """Run YOLO+ByteTrack on the sampled frames, aggregate features."""
    # Build a per-track timeline: track_id -> list of (frame_idx, cx, cy, cls)
    timelines: dict[int, list] = {}
    object_dets = []  # (frame_idx, cls_name, cx, cy)
    # imread each frame, pass through tracker
    for i, p in enumerate(paths):
        # ultralytics track() with persist=True maintains track ids across calls
        results = model.track(source=str(p), persist=True, verbose=False,
                              tracker="bytetrack.yaml", imgsz=YOLO_IMGSZ,
                              conf=YOLO_CONF,
                              classes=[PERSON_CLASS] + list(OBJECT_CLASSES.keys()))
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            continue
        boxes = r.boxes
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else None
        clss = boxes.cls.cpu().numpy().astype(int)
        xyxys = boxes.xyxy.cpu().numpy()
        for k in range(len(boxes)):
            cx = (xyxys[k, 0] + xyxys[k, 2]) / 2
            cy = (xyxys[k, 1] + xyxys[k, 3]) / 2
            cls_id = clss[k]
            if cls_id == PERSON_CLASS and ids is not None:
                tid = int(ids[k])
                timelines.setdefault(tid, []).append((i, float(cx), float(cy), cls_id))
            elif cls_id in OBJECT_CLASSES:
                object_dets.append((i, OBJECT_CLASSES[cls_id], float(cx), float(cy)))

    # Per-person features
    feats = {
        "n_persons_tracks": len(timelines),
        "n_persons_inside_polygon": 0,
        "dwell_max_sec": 0.0,
        "dwell_sum_sec": 0.0,
        "closest_approach_px": 1e6,
        "n_obj_dets": len(object_dets),
        "n_obj_in_polygon": 0,
        "obj_inside_after_person_leaves": 0,
    }

    # closest_approach across all persons
    last_person_inside_idx = -1
    for tid, traj in timelines.items():
        inside_frames = [t for t in traj if centroid_in_polygon(t[1], t[2], pile_poly)]
        dwell_frames = len(inside_frames)
        dwell_sec = dwell_frames * frame_dt_sec
        feats["dwell_sum_sec"] += dwell_sec
        feats["dwell_max_sec"] = max(feats["dwell_max_sec"], dwell_sec)
        if dwell_frames > 0:
            feats["n_persons_inside_polygon"] += 1
            last_idx_this_person = max(t[0] for t in inside_frames)
            last_person_inside_idx = max(last_person_inside_idx, last_idx_this_person)
        for t in traj:
            d = dist_to_polygon(t[1], t[2], pile_poly)
            if d < feats["closest_approach_px"]:
                feats["closest_approach_px"] = d
    if feats["closest_approach_px"] == 1e6:
        feats["closest_approach_px"] = 999.0

    # object features
    for fr_idx, cls_name, cx, cy in object_dets:
        if centroid_in_polygon(cx, cy, pile_poly):
            feats["n_obj_in_polygon"] += 1
            if last_person_inside_idx >= 0 and fr_idx > last_person_inside_idx:
                feats["obj_inside_after_person_leaves"] += 1

    return feats


def main():
    print(f"[init] loading {YOLO_MODEL} ...", flush=True)
    model = YOLO(YOLO_MODEL)
    print(f"  loaded; classes={len(model.names)}", flush=True)

    events = fetch_events()
    print(f"[fetch] {len(events)} cam_11 events", flush=True)

    cache = json.loads(TRACK_CACHE.read_text()) if TRACK_CACHE.exists() else {}
    print(f"[cache] {len(cache)} cached", flush=True)

    rows = []
    t_track_total = 0.0
    new_runs = 0
    for i, ev in enumerate(events, 1):
        det = load_event(ev["id"])
        if not det or not det.get("frames"):
            continue
        frames = det["frames"]
        # Resolve sampled frames
        idxs = sample_n_frames(frames, N_FRAMES_SAMPLE)
        paths = []
        for k in idxs:
            f = frames[k]
            p = resolve_path(f["image_url"], f["frame_name"])
            if p:
                paths.append(p)
        if len(paths) < 6:
            continue

        # Estimate frame_dt: parse first/last frame names
        # frame_name like "2026-05-29_12-46-48.jpg"
        try:
            def ts_of(name):
                stem = Path(name).stem
                return time.mktime(time.strptime(stem, "%Y-%m-%d_%H-%M-%S"))
            full_secs = ts_of(frames[-1]["frame_name"]) - ts_of(frames[0]["frame_name"])
            frame_dt = full_secs / max(len(frames) - 1, 1)
            # but we only ran on N_FRAMES_SAMPLE, so dwell_frames * (full_secs / N_sampled)
            sampled_dt = full_secs / max(len(paths) - 1, 1)
        except Exception:
            sampled_dt = 10.0  # fallback

        if ev["id"] in cache:
            feats = cache[ev["id"]]
        else:
            t0 = time.monotonic()
            feats = extract_tracking_features(model, paths, sampled_dt, PILE_POLY)
            t_track_total += time.monotonic() - t0
            cache[ev["id"]] = feats
            new_runs += 1
        rows.append({
            "id": ev["id"], "ts": ev["ts"],
            "gt": "CON" if ev["status"] == "CONFIRMADO" else "REJ",
            **feats,
        })
        if i % 5 == 0 or i == len(events):
            print(f"  {i}/{len(events)} (kept={len(rows)} new={new_runs})", flush=True)

    TRACK_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    if new_runs > 0:
        print(f"[track] {new_runs} new in {t_track_total:.1f}s "
              f"({t_track_total/new_runs:.2f}s/event)", flush=True)

    FEATS = ["n_persons_tracks", "n_persons_inside_polygon", "dwell_max_sec",
             "dwell_sum_sec", "closest_approach_px", "n_obj_dets",
             "n_obj_in_polygon", "obj_inside_after_person_leaves"]
    X_track = np.array([[r.get(f, 0.0) for f in FEATS] for r in rows], dtype=np.float32)
    y = np.array([1 if r["gt"] == "CON" else 0 for r in rows])
    print(f"[data] X_track={X_track.shape} CON={int(y.sum())} REJ={int((1-y).sum())}", flush=True)

    # Per-feature distribution by GT
    print("\n=== Feature distribution by GT (median ± p25/p75) ===")
    for i, f in enumerate(FEATS):
        for gt in ("REJ", "CON"):
            vals = sorted(X_track[y == (1 if gt == "CON" else 0), i].tolist())
            if not vals:
                continue
            n = len(vals)
            p25, med, p75 = vals[n // 4], vals[n // 2], vals[3 * n // 4]
            if gt == "REJ":
                rej_med = med
                rej_str = f"REJ med={med:.1f} (p25={p25:.1f} p75={p75:.1f})"
            else:
                print(f"  {f:<32s} {rej_str}  |  CON med={med:.1f} (p25={p25:.1f} p75={p75:.1f})")

    # Load DINOv2 embeddings if cache present
    X_emb = None
    if EMB_CACHE.exists():
        cache_e = np.load(EMB_CACHE, allow_pickle=True)
        emb_ids = list(cache_e["ids"])
        emb_X = cache_e["X"]
        emb_map = {str(emb_ids[k]): emb_X[k] for k in range(len(emb_ids))}
        X_emb_rows = []
        keep = []
        for k, r in enumerate(rows):
            if r["id"] in emb_map:
                X_emb_rows.append(emb_map[r["id"]])
                keep.append(k)
        if X_emb_rows:
            X_emb = np.stack(X_emb_rows)
            X_track_keep = X_track[keep]
            y_keep = y[keep]
            print(f"[merge] X_emb={X_emb.shape} (matching {len(keep)}/{len(rows)} events)", flush=True)

    def cv(X, y, name, n_splits=5):
        n_cls = sorted(np.bincount(y, minlength=2).tolist())
        n_splits = min(n_splits, n_cls[0])
        if n_splits < 2:
            print(f"  {name}: skip (n_cls={n_cls})")
            return
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        pipe = Pipeline([("sc", StandardScaler()),
                         ("lr", LogisticRegression(C=1.0, max_iter=2000))])
        accs = cross_val_score(pipe, X, y, cv=skf, scoring="accuracy")
        try:
            aucs = cross_val_score(pipe, X, y, cv=skf, scoring="roc_auc")
            auc_str = f"AUC={aucs.mean():.3f} ±{aucs.std():.3f}"
        except Exception:
            auc_str = "AUC=N/A"
        y_pred = cross_val_predict(pipe, X, y, cv=skf)
        cm = confusion_matrix(y, y_pred)
        tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, 0)
        print(f"  {name:<40s} n={len(y):<3} acc={accs.mean():.2%} ±{accs.std():.2%}  {auc_str}  TP={tp} TN={tn} FP={fp} FN={fn}",
              flush=True)

    print("\n=== 5-fold CV results (cam_11 only) ===", flush=True)
    cv(X_track, y, "tracking-only (8 feats)")
    if X_emb is not None:
        cv(X_emb, y_keep, "DINOv2-only (2304 feats)")
        cv(np.concatenate([X_track_keep, X_emb], axis=1), y_keep,
           "tracking + DINOv2 (2312 feats)")

    # LinearSVC for tracking-only
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    pipe = Pipeline([("sc", StandardScaler()),
                     ("svc", LinearSVC(C=1.0, max_iter=3000))])
    accs = cross_val_score(pipe, X_track, y, cv=skf, scoring="accuracy")
    print(f"\nLinearSVC tracking-only: acc={accs.mean():.2%} ±{accs.std():.2%}", flush=True)

    out = Path("/tmp/cam11_tracking_results.json")
    out.write_text(json.dumps({"features": FEATS, "rows": rows},
                              ensure_ascii=False, indent=2))
    print(f"saved: {out}")


if __name__ == "__main__":
    sys.exit(main())
