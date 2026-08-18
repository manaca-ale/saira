#!/usr/bin/env python3
"""Camp 37f — DINOv2 FP-filter offline eval for esp32_005 (Arruda / cam_14).

Prod recipe (retrain_dinov2.py): per detection LAST 3 frames, bbox crop of
pile_zone_polygon, 224², ImageNet norm, dinov2_vits14, mean emb, Scaler+LogReg
(max_iter=2000, balanced, C=1.0). CONFIRMADO=1 vs REJEITADO=0; INDET/COLETA = probe.

Arms:
- bbox: DB polygon (prod) vs WIDE (full chronic strip) — polygon diagnostic
- cohort: ALL vs NEW-ANGLE only (camera repositioned 2026-06-02 ~15:00)
Eval: repeated stratified CV AUC + temporal holdout + threshold curve + probe.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import numpy as np

ROOT = Path(r"c:\saira")
CAMP = Path(__file__).parent
CACHE = ROOT / "tmp" / "dinov2_arruda" / "frames"
sys.stdout.reconfigure(encoding="utf-8")

BBOXES = {
    "db_poly": (585, 320, 874, 470),    # min/max of cameras.pile_zone_polygon
    "wide":    (585, 320, 1230, 560),   # full chronic strip (visual check 06/11)
}
N_FRAMES = 3
INPUT = 224
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
NEW_ANGLE_TS = "2026-06-02_15-00-00"

POS_DIR = ROOT / "tmp" / "det_frames_pos"
REJ_DIR = ROOT / "tmp" / "det_frames_rej"

POS_STATUS = {
    "01c9e4c7": "CONFIRMADO", "6834dad7": "CONFIRMADO", "01e54259": "CONFIRMADO",
    "9085ad0e": "CONFIRMADO", "d7822b53": "CONFIRMADO", "bcb8038c": "CONFIRMADO",
    "a5a72209": "CONFIRMADO", "ce13f76c": "CONFIRMADO", "6328e4e6": "CONFIRMADO",
    "50c32313": "CONFIRMADO",
    "b797daa9": "INDETERMINADO", "95dd7824": "INDETERMINADO", "bd466bda": "INDETERMINADO",
    "6e2e95ce": "INDETERMINADO", "6a126950": "INDETERMINADO", "9e112c6d": "INDETERMINADO",
    "4d51d0a1": "INDETERMINADO", "0c4976c0": "INDETERMINADO", "f7913b02": "INDETERMINADO",
    "0f2e9b60": "INDETERMINADO", "0cb3394b": "INDETERMINADO",
    "8657dafd": "COLETA",
}


def dl(url: str, dest: Path) -> Path | None:
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    if url.startswith("/s3-images/"):
        url = "https://saira-images.s3.sa-east-1.amazonaws.com/" + url[len("/s3-images/"):]
    if not url.startswith("http") or "localhost" in url:
        return None
    try:
        with urlopen(url, timeout=30) as r:
            b = r.read()
        if len(b) > 1000:
            dest.write_bytes(b)
            return dest
    except Exception:
        return None
    return None


def load_events():
    evs = []
    for d, default_status in ((POS_DIR, None), (REJ_DIR, "REJEITADO")):
        for jf in sorted(d.glob("*.json")):
            det8 = jf.name[:8]
            status = default_status or POS_STATUS.get(det8, "?")
            data = json.loads(jf.read_text(encoding="utf-8"))
            frames = sorted(data.get("frames", []), key=lambda x: x["frame_name"])
            if not frames:
                continue
            evs.append({"id": det8, "status": status, "frames": frames[-N_FRAMES:],
                        "ts": frames[-1]["frame_name"][:19]})
    return evs


def main() -> int:
    from PIL import Image
    import torch

    CACHE.mkdir(parents=True, exist_ok=True)
    events = load_events()
    print(f"{len(events)} detecções (CONF={sum(1 for e in events if e['status']=='CONFIRMADO')}, "
          f"REJ={sum(1 for e in events if e['status']=='REJEITADO')}, "
          f"INDET={sum(1 for e in events if e['status']=='INDETERMINADO')}, "
          f"probe={sum(1 for e in events if e['status']=='COLETA')})", flush=True)

    torch.set_num_threads(4)
    model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", verbose=False,
                           skip_validation=True, trust_repo=True)
    model.eval()

    X = {k: [] for k in BBOXES}
    meta = []
    t0 = time.time()
    for ev in events:
        imgs = []
        for f in ev["frames"]:
            p = dl(f["image_url"], CACHE / f["frame_name"])
            if not p:
                continue
            imgs.append(np.asarray(Image.open(p).convert("RGB")))
        if not imgs:
            print(f"  SKIP {ev['id']} ({ev['status']}) — sem frames", flush=True)
            continue
        for key, (x0, y0, x1, y1) in BBOXES.items():
            crops = []
            for img in imgs:
                h, w = img.shape[:2]
                cx0 = max(0, min(x0, w - 1)); cy0 = max(0, min(y0, h - 1))
                cx1 = max(cx0 + 1, min(x1, w)); cy1 = max(cy0 + 1, min(y1, h))
                crop = img[cy0:cy1, cx0:cx1]
                crop = np.asarray(Image.fromarray(crop).resize((INPUT, INPUT), Image.BILINEAR))
                crops.append((crop.astype(np.float32) / 255.0 - _MEAN) / _STD)
            batch = np.stack(crops).transpose(0, 3, 1, 2)
            with torch.no_grad():
                emb = model(torch.from_numpy(batch).float()).cpu().numpy()
            X[key].append(emb.mean(axis=0))
        meta.append(ev)
    X = {k: np.array(v) for k, v in X.items()}
    print(f"embeddings: {X['db_poly'].shape} x {len(BBOXES)} bboxes em {time.time()-t0:.0f}s", flush=True)
    np.savez(CAMP / "dinov2_arruda_emb.npz",
             **{f"X_{k}": v for k, v in X.items()},
             ids=np.array([m["id"] for m in meta]),
             status=np.array([m["status"] for m in meta]),
             ts=np.array([m["ts"] for m in meta]))

    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import RepeatedStratifiedKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    status = np.array([m["status"] for m in meta])
    ts_all = np.array([m["ts"] for m in meta])

    def fit_predict(Xtr, ytr, Xte):
        sc = StandardScaler().fit(Xtr.astype(np.float64))
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
        clf.fit(sc.transform(Xtr.astype(np.float64)), ytr)
        return clf.predict_proba(sc.transform(Xte.astype(np.float64)))[:, 1]

    def run_eval(key, cohort_name, cohort_mask):
        m = cohort_mask & np.isin(status, ["CONFIRMADO", "REJEITADO"])
        Xt = X[key][m]
        yt = (status[m] == "CONFIRMADO").astype(int)
        ts = ts_all[m]
        n_con, n_rej = int(yt.sum()), int(len(yt) - yt.sum())
        print(f"\n--- bbox={key} | cohort={cohort_name}: n={len(yt)} (CON={n_con}, REJ={n_rej})", flush=True)
        if n_con < 3 or n_rej < 3:
            print("    poucos exemplos, pulando", flush=True)
            return
        n_splits = min(5, n_con, n_rej)
        aucs = []
        rskf = RepeatedStratifiedKFold(n_splits=n_splits, n_repeats=10, random_state=42)
        for tr, te in rskf.split(Xt, yt):
            if len(set(yt[te])) < 2 or len(set(yt[tr])) < 2:
                continue
            aucs.append(roc_auc_score(yt[te], fit_predict(Xt[tr], yt[tr], Xt[te])))
        print(f"    (a) CV random {n_splits}-fold x10: AUC = {np.mean(aucs):.3f} ± {np.std(aucs):.3f}", flush=True)

        order = np.argsort(ts)
        cut = int(len(order) * 0.7)
        tr_i, te_i = order[:cut], order[cut:]
        if len(set(yt[tr_i])) > 1 and len(set(yt[te_i])) > 1:
            p_te = fit_predict(Xt[tr_i], yt[tr_i], Xt[te_i])
            print(f"    (b) temporal (train<= {str(ts[tr_i].max())[:10]}, test n={len(te_i)} CON={int(yt[te_i].sum())}): "
                  f"AUC = {roc_auc_score(yt[te_i], p_te):.3f}", flush=True)
            for thr in (0.2, 0.3, 0.5):
                rej = p_te < thr
                print(f"        t={thr:.1f}: FP elim {int((rej & (yt[te_i]==0)).sum())}/{int((yt[te_i]==0).sum())} | "
                      f"TP perdidos {int((rej & (yt[te_i]==1)).sum())}/{int((yt[te_i]==1).sum())}", flush=True)
        else:
            print("    (b) temporal: classe única num dos lados, pulando", flush=True)

        # probe INDET/COLETA dentro do cohort
        probe_m = cohort_mask & np.isin(status, ["INDETERMINADO", "COLETA"])
        if probe_m.sum():
            p_probe = fit_predict(Xt, yt, X[key][probe_m])
            barra = int((p_probe < 0.5).sum())
            print(f"    (c) sonda INDET/COLETA (n={int(probe_m.sum())}): barraria {barra} a t=0.5 "
                  f"(p_con: {' '.join(f'{p:.2f}' for p in sorted(p_probe))})", flush=True)

    all_mask = np.ones(len(meta), dtype=bool)
    new_mask = ts_all >= NEW_ANGLE_TS
    for key in BBOXES:
        run_eval(key, "ALL", all_mask)
        run_eval(key, "NEW_ANGLE(>=02/06 15h)", new_mask)
    return 0


if __name__ == "__main__":
    sys.exit(main())
