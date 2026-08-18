#!/usr/bin/env python3
"""Campanha 26 — DINOv2 embeddings da pile-zone com os POLIGONOS NOVOS.

Roda DENTRO do container (torch + cv2 + frames locais/S3). Para cada evento
rotulado (cam 10, 11), recorta a pile_zone (bbox ATUAL do DB = polígonos
redesenhados em 2026-05-30/31), extrai embedding DINOv2 ViT-S/14 (CLS token),
faz média dos últimos N frames, e salva tudo num .npz.

Depois copie o .npz pra local e rode logreg_eval.py (sklearn) pra o CV.

Reusa _bench_common.resolve_frame (já shipado em /tmp).

Saída: /tmp/dinov2_new/embeddings.npz  (X, y, cams, ids)
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "/tmp")
from _bench_common import resolve_frame  # noqa: E402

CAMS = {10: "esp32_001", 11: "esp32_002", 14: "esp32_005"}
N_FRAMES_PER_EVENT = 3          # last N frames (disposal most visible at the end)
DINO_INPUT = 224                # multiple of 14 for ViT-S/14
OUT = Path("/tmp/dinov2_new/embeddings_all.npz")
OUT.parent.mkdir(parents=True, exist_ok=True)
TMP = Path("/tmp/flash_per_camera")  # reuse frame cache dir


def log(m): print(m, flush=True)


def fetch_events():
    import psycopg2
    conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                            password="postgres", dbname="saira_db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id::text, timestamp::text, camera_id, status::text
        FROM detections
        WHERE status IN ('REJEITADO', 'CONFIRMADO')
          AND camera_id IN (10, 11, 14)
        ORDER BY timestamp DESC
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{"id": r[0], "ts": r[1], "cam": r[2], "status": r[3]} for r in rows]


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

    bboxes = {c: pile_bbox(c) for c in CAMS}
    log(f"[dinov2] NEW bboxes: {bboxes}")

    events = fetch_events()
    log(f"[dinov2] {len(events)} labeled events")

    X, y, cams, ids = [], [], [], []
    skipped = 0
    for i, ev in enumerate(events, 1):
        cam = ev["cam"]
        bbox = bboxes.get(cam)
        if bbox is None:
            skipped += 1
            continue
        device_id = CAMS[cam]
        frames = load_event_frames(ev["id"])
        if not frames:
            skipped += 1
            continue
        # take last N frames
        sel = frames[-N_FRAMES_PER_EVENT:] if len(frames) >= N_FRAMES_PER_EVENT else frames
        crops = []
        for f in sel:
            p = resolve_frame(TMP, f["image_url"], f["frame_name"], device_id)
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
            skipped += 1
            continue
        batch = np.stack(crops).transpose(0, 3, 1, 2)  # N,C,H,W
        with torch.no_grad():
            t = torch.from_numpy(batch).float().to(dev)
            emb = model(t)            # (N, 384) CLS token for ViT-S
            emb = emb.cpu().numpy()
        feat = emb.mean(axis=0)       # average over frames
        X.append(feat)
        y.append(1 if ev["status"] == "CONFIRMADO" else 0)
        cams.append(cam)
        ids.append(ev["id"])
        if i % 10 == 0:
            log(f"  {i}/{len(events)} done (skipped={skipped})")

    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.int64)
    cams = np.array(cams, dtype=np.int64)
    ids = np.array(ids, dtype=object)
    np.savez(OUT, X=X, y=y, cams=cams, ids=ids,
             bbox_10=np.array(bboxes.get(10) or []),
             bbox_11=np.array(bboxes.get(11) or []))
    log(f"[dinov2] saved {OUT}  X={X.shape} y={y.shape} skipped={skipped} "
        f"({time.time()-t0:.0f}s)")
    for c in sorted(set(cams.tolist())):
        m = cams == c
        log(f"  cam_{c}: n={int(m.sum())} CON={int(y[m].sum())} REJ={int((1-y[m]).sum())}")


if __name__ == "__main__":
    main()
