#!/usr/bin/env python3
"""Camp 27 — DINOv2 embeddings cam_10 (Imbiribeira), conjunto COMPLETO + timestamps.

Igual à Camp 26 (extract_embeddings.py), mas:
  - somente cam_10 (camera_id=10),
  - salva TIMESTAMP de cada evento (necessário para split temporal),
  - re-extrai TODOS os eventos rotulados (CON+REJ) atuais.

Roda DENTRO do container saira-yolo-worker-prod (torch + cv2 + frames locais).
Reusa _bench_common.resolve_frame (já em /tmp).

Saída: /tmp/dinov2_cam27/embeddings_cam10.npz  (X, y, ids, ts)
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "/tmp")
from _bench_common import resolve_frame  # noqa: E402

CAM_ID = 10
DEVICE_ID = "esp32_001"
N_FRAMES_PER_EVENT = 3          # últimos N frames (descarte mais visível no fim)
DINO_INPUT = 224                # múltiplo de 14 p/ ViT-S/14
OUT = Path("/tmp/dinov2_cam27/embeddings_cam10.npz")
OUT.parent.mkdir(parents=True, exist_ok=True)
TMP = Path("/tmp/flash_per_camera")  # reusa cache de frames


def log(m): print(m, flush=True)


def fetch_events():
    import psycopg2
    conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                            password="postgres", dbname="saira_db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id::text, timestamp::text, status::text
        FROM detections
        WHERE status IN ('REJEITADO', 'CONFIRMADO')
          AND camera_id = %s
        ORDER BY timestamp ASC
    """, (CAM_ID,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{"id": r[0], "ts": r[1], "status": r[2]} for r in rows]


def pile_bbox(cam_id):
    import psycopg2
    conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                            password="postgres", dbname="saira_db")
    cur = conn.cursor()
    cur.execute("SELECT pile_zone_polygon FROM cameras WHERE id = %s", (cam_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row or not row[0]:
        return None
    pts = [pt for poly in row[0] for pt in poly]
    xs = [int(p[0]) for p in pts]; ys = [int(p[1]) for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def load_event_frames(det_id):
    sf = Path(f"/app/state/detection_frames/{det_id}.json")
    if not sf.exists():
        return []
    return json.loads(sf.read_text()).get("frames", [])


def main():
    t0 = time.time()
    import torch
    import cv2
    log("[dinov2] loading model (ViT-S/14)...")
    model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14")
    model.eval()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(dev)
    log(f"[dinov2] device={dev}")

    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    bbox = pile_bbox(CAM_ID)
    log(f"[dinov2] cam_{CAM_ID} bbox={bbox}")

    events = fetch_events()
    log(f"[dinov2] {len(events)} labeled events (cam_{CAM_ID})")

    X, y, ids, ts = [], [], [], []
    skipped = []
    for i, ev in enumerate(events, 1):
        frames = load_event_frames(ev["id"])
        if not frames:
            skipped.append((ev["id"], "no_frames_json"))
            continue
        sel = frames[-N_FRAMES_PER_EVENT:] if len(frames) >= N_FRAMES_PER_EVENT else frames
        crops = []
        for f in sel:
            p = resolve_frame(TMP, f["image_url"], f["frame_name"], DEVICE_ID)
            if not p:
                continue
            img = cv2.imread(str(p))
            if img is None:
                continue
            h, w = img.shape[:2]
            x0, y0, x1, y1 = bbox
            x0 = max(0, min(x0, w - 1)); y0 = max(0, min(y0, h - 1))
            x1 = max(x0 + 1, min(x1, w)); y1 = max(y0 + 1, min(y1, h))
            crop = img[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            crop = cv2.resize(crop, (DINO_INPUT, DINO_INPUT),
                              interpolation=cv2.INTER_AREA)
            arr = crop.astype(np.float32) / 255.0
            arr = (arr - mean) / std
            crops.append(arr)
        if not crops:
            skipped.append((ev["id"], "no_resolvable_frames"))
            continue
        batch = np.stack(crops).transpose(0, 3, 1, 2)
        with torch.no_grad():
            t = torch.from_numpy(batch).float().to(dev)
            emb = model(t)
            emb = emb.cpu().numpy()
        feat = emb.mean(axis=0)
        X.append(feat)
        y.append(1 if ev["status"] == "CONFIRMADO" else 0)
        ids.append(ev["id"])
        ts.append(ev["ts"])

    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.int64)
    ids = np.array(ids, dtype=object)
    ts = np.array(ts, dtype=object)
    np.savez(OUT, X=X, y=y, ids=ids, ts=ts, bbox=np.array(bbox or []))
    log(f"[dinov2] saved {OUT}  X={X.shape}  n={len(y)}  "
        f"CON={int(y.sum())} REJ={int((1-y).sum())}  ({time.time()-t0:.0f}s)")
    if skipped:
        log(f"[dinov2] skipped {len(skipped)}:")
        for sid, why in skipped:
            log(f"   {sid}  {why}")


if __name__ == "__main__":
    main()
