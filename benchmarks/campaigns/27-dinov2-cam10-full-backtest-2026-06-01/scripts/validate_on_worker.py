#!/usr/bin/env python3
"""Camp 27 — valida o pipeline DINOv2 (igual ao detector_dinov2.py) NO worker.

Roda dentro de saira-yolo-worker-prod. Para alguns eventos conhecidos, recorta a
pile-zone dos últimos 3 frames, extrai DINOv2 CLS, e aplica a inferência numpy-pura
do artefato. Compara com os p_con offline (in-sample) esperados.

Não altera nada em prod — só lê frames e roda inferência.
"""
import sys, json, time
from pathlib import Path
import numpy as np
sys.path.insert(0, "/tmp")
from _bench_common import resolve_frame

ART = "/tmp/dinov2_clf_esp32_001.npz"
DEVICE_ID = "esp32_001"
TMP = Path("/tmp/flash_per_camera")
N = 3
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# (id, expected in-sample p_con)
TARGETS = [
    ("2900d8ea-77ee-41a5-894d-1b3863801919", 0.0005),
    ("8bfe0a1f-da31-4ddd-9455-de0d6a5ef652", 0.9715),
    ("218673e1-397c-4293-be2b-0d5e2326334f", 0.9992),
]


def load_frames(det_id):
    sf = Path(f"/app/state/detection_frames/{det_id}.json")
    return json.loads(sf.read_text()).get("frames", []) if sf.exists() else []


def main():
    import torch, cv2
    art = np.load(ART, allow_pickle=True)
    sm, ss = art["scaler_mean"].astype(np.float64), art["scaler_scale"].astype(np.float64)
    coef, b = art["coef"].astype(np.float64), float(art["intercept"])
    thr = float(art["threshold"]); bbox = tuple(int(v) for v in art["bbox"].tolist())
    print(f"artifact thr={thr} bbox={bbox}")

    model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", verbose=False)
    model.eval()

    for det_id, expected in TARGETS:
        frames = load_frames(det_id)
        sel = frames[-N:] if len(frames) >= N else frames
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
            x0 = max(0, min(x0, w-1)); y0 = max(0, min(y0, h-1))
            x1 = max(x0+1, min(x1, w)); y1 = max(y0+1, min(y1, h))
            crop = img[y0:y1, x0:x1]
            crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            crop = cv2.resize(crop, (224, 224), interpolation=cv2.INTER_AREA)
            arr = (crop.astype(np.float32)/255.0 - MEAN)/STD
            crops.append(arr)
        if not crops:
            print(f"{det_id[:8]}  NO CROPS"); continue
        batch = np.stack(crops).transpose(0, 3, 1, 2)
        t0 = time.time()
        with torch.no_grad():
            emb = model(torch.from_numpy(batch).float()).cpu().numpy()
        feat = emb.mean(axis=0)
        z = (feat.astype(np.float64) - sm)/ss
        p_con = 1/(1+np.exp(-(z@coef + b)))
        dt = (time.time()-t0)*1000
        ok = "OK" if abs(p_con - expected) < 0.01 else "MISMATCH"
        print(f"{det_id[:8]}  p_con={p_con:.4f}  expected={expected:.4f}  "
              f"reject={p_con<thr}  {ok}  ({dt:.0f}ms, {len(crops)} crops)")


if __name__ == "__main__":
    main()
