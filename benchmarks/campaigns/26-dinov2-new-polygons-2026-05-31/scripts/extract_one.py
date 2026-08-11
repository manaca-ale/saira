#!/usr/bin/env python3
"""Extrai embedding DINOv2 (mesma config da camp 26) de UM evento por id.
Salva /tmp/dinov2_new/one_<id8>.npz com X (1,384)."""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, "/tmp")
from _bench_common import resolve_frame  # noqa: E402

DET_ID = sys.argv[1]
CAM = int(sys.argv[2])           # 11
DEVICE = {10: "esp32_001", 11: "esp32_002"}[CAM]
N = 3
DINO = 224
TMP = Path("/tmp/flash_per_camera")


def bbox(cam):
    import psycopg2
    c = psycopg2.connect(host="saira-db-prod", user="postgres", password="postgres", dbname="saira_db")
    cur = c.cursor(); cur.execute("SELECT pile_zone_polygon FROM cameras WHERE id=%s", (cam,))
    poly = cur.fetchone()[0]; cur.close(); c.close()
    pts = [pt for p in poly for pt in p]
    xs = [int(p[0]) for p in pts]; ys = [int(p[1]) for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def main():
    import torch, cv2
    m = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14"); m.eval()
    mean = np.array([0.485,0.456,0.406],dtype=np.float32); std=np.array([0.229,0.224,0.225],dtype=np.float32)
    bb = bbox(CAM)
    frames = json.loads(Path(f"/app/state/detection_frames/{DET_ID}.json").read_text())["frames"]
    sel = frames[-N:] if len(frames) >= N else frames
    crops = []
    for f in sel:
        p = resolve_frame(TMP, f["image_url"], f["frame_name"], DEVICE)
        if not p: continue
        img = cv2.imread(str(p))
        if img is None: continue
        h,w=img.shape[:2]; x0,y0,x1,y1=bb
        x0=max(0,min(x0,w-1));y0=max(0,min(y0,h-1));x1=max(x0+1,min(x1,w));y1=max(y0+1,min(y1,h))
        cr=img[y0:y1,x0:x1]
        if cr.size==0: continue
        cr=cv2.cvtColor(cr,cv2.COLOR_BGR2RGB); cr=cv2.resize(cr,(DINO,DINO),interpolation=cv2.INTER_AREA)
        a=(cr.astype(np.float32)/255.0-mean)/std; crops.append(a)
    batch=np.stack(crops).transpose(0,3,1,2)
    with torch.no_grad():
        emb=m(torch.from_numpy(batch).float()).cpu().numpy().mean(axis=0)
    out=Path(f"/tmp/dinov2_new/one_{DET_ID[:8]}.npz"); out.parent.mkdir(parents=True,exist_ok=True)
    np.savez(out, X=emb.astype(np.float32), bbox=np.array(bb))
    print(f"saved {out} dim={emb.shape} n_crops={len(crops)} bbox={bb}")


if __name__ == "__main__":
    main()
