"""Retreino semanal do classificador DINOv2 (filtro de FP).

Run dentro do worker:  python -m worker.retrain_dinov2

Pipeline:
  FETCH  eventos rotulados (CON/REJ) do device no DB
  EXTRACT embeddings DINOv2 da pile-zone (torch)  — mesmo pré-proc do detector_dinov2
  FIT    LogReg + StandardScaler (sklearn, dep só-de-treino)
  VALIDATE 5-fold CV AUC  — GATE: só promove se AUC >= min E n não encolheu
  EXPORT artefato numpy (scaler/coef/intercept/threshold/bbox/metadados)
  SWAP   backup do atual (.bak) + rename atômico (.tmp -> final)
  LOG    métricas em {MODELS_DIR}/retrain_log.jsonl

Self-contained: sem dependência do scaffold de bench. Resolução de frame = local
/app/uploads -> fallback S3 (igual resolve_frame do bench). Idempotente e fail-safe:
qualquer erro/gate reprovado NÃO toca o artefato em produção.

O worker faz hot-reload do artefato via mtime (detector_dinov2._DinoCache), então
não precisa de restart após o retreino.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from . import config

logger = logging.getLogger("worker.retrain_dinov2")

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_FRAME_CACHE = Path("/tmp/dinov2_retrain_frames")


def _log(msg: str) -> None:
    print(f"[retrain] {msg}", flush=True)


# --------------------------------------------------------------------------- DB
def _db():
    import psycopg2
    return psycopg2.connect(config.DATABASE_URL)


def _camera_row(device_id: str):
    """Return (camera_id, pile_zone_polygon) for a device_id."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT id, pile_zone_polygon FROM cameras WHERE device_id = %s",
                (device_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return (row[0], row[1]) if row else (None, None)


def _fetch_labeled(camera_id: int):
    conn = _db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id::text, timestamp::text, status::text
        FROM detections
        WHERE status IN ('REJEITADO', 'CONFIRMADO') AND camera_id = %s
        ORDER BY timestamp ASC
    """, (camera_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{"id": r[0], "ts": r[1], "status": r[2]} for r in rows]


def _bbox_from_polygon(polygon):
    try:
        polys = polygon
        if isinstance(polys, str):
            polys = json.loads(polys)
        pts = [pt for poly in polys for pt in poly]
        xs = [int(p[0]) for p in pts]; ys = [int(p[1]) for p in pts]
        return (min(xs), min(ys), max(xs), max(ys)) if xs and ys else None
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------------ frames
_S3 = None


def _s3():
    global _S3
    if _S3 is None:
        import boto3
        _S3 = boto3.client("s3", region_name=config.S3_REGION)
    return _S3


def _resolve_frame(image_url: str, frame_name: str, device_id: str):
    """Local /app/uploads first, S3 fallback. Mirrors bench resolve_frame."""
    target = _FRAME_CACHE / device_id / frame_name
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
        _s3().download_file(config.S3_BUCKET_NAME or "saira-images", s3_key, str(target))
        return target if target.stat().st_size > 1000 else None
    except Exception:  # noqa: BLE001
        return None


def _load_frames(det_id: str):
    sf = Path(f"/app/state/detection_frames/{det_id}.json")
    if not sf.exists():
        return []
    try:
        return json.loads(sf.read_text()).get("frames", [])
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------- embeddings
def _extract(events, device_id, bbox, n_frames, input_size):
    import torch
    import cv2
    torch.set_num_threads(int(config.DINOV2_TORCH_THREADS))
    model = torch.hub.load("facebookresearch/dinov2", config.DINOV2_VARIANT, verbose=False)
    model.eval()
    X, y, ids, ts = [], [], [], []
    skipped = 0
    x0, y0, x1, y1 = bbox
    for ev in events:
        frames = _load_frames(ev["id"])
        if not frames:
            skipped += 1
            continue
        sel = frames[-n_frames:] if len(frames) >= n_frames else frames
        crops = []
        for f in sel:
            p = _resolve_frame(f.get("image_url", ""), f.get("frame_name", ""), device_id)
            if not p:
                continue
            img = cv2.imread(str(p))
            if img is None:
                continue
            h, w = img.shape[:2]
            cx0 = max(0, min(x0, w - 1)); cy0 = max(0, min(y0, h - 1))
            cx1 = max(cx0 + 1, min(x1, w)); cy1 = max(cy0 + 1, min(y1, h))
            crop = img[cy0:cy1, cx0:cx1]
            if crop.size == 0:
                continue
            crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            crop = cv2.resize(crop, (input_size, input_size), interpolation=cv2.INTER_AREA)
            arr = (crop.astype(np.float32) / 255.0 - _MEAN) / _STD
            crops.append(arr)
        if not crops:
            skipped += 1
            continue
        batch = np.stack(crops).transpose(0, 3, 1, 2)
        with torch.no_grad():
            emb = model(torch.from_numpy(batch).float()).cpu().numpy()
        X.append(emb.mean(axis=0))
        y.append(1 if ev["status"] == "CONFIRMADO" else 0)
        ids.append(ev["id"]); ts.append(ev["ts"])
    return (np.array(X, dtype=np.float32), np.array(y, dtype=np.int64),
            np.array(ids, dtype=object), np.array(ts, dtype=object), skipped)


# ------------------------------------------------------------------------- fit/cv
def _cv_auc(X, y, n_splits=5):
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score
    n_con = int(y.sum()); n_rej = int(len(y) - n_con)
    if n_con < n_splits or n_rej < n_splits:
        return None  # poucos exemplos p/ CV confiável
    proba = np.zeros(len(y))
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    for tr, te in skf.split(X, y):
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
        clf.fit(sc.transform(X[tr]), y[tr])
        proba[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
    try:
        return float(roc_auc_score(y, proba))
    except ValueError:
        return None


def _fit_export(X, y, bbox, device_id, threshold):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    sc = StandardScaler().fit(X.astype(np.float64))
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(sc.transform(X.astype(np.float64)), y)
    sign = 1.0 if clf.classes_[1] == 1 else -1.0
    return {
        "scaler_mean": sc.mean_.astype(np.float64),
        "scaler_scale": sc.scale_.astype(np.float64),
        "coef": (sign * clf.coef_[0]).astype(np.float64),
        "intercept": np.array(float(sign * clf.intercept_[0])),
        "threshold": np.array(float(threshold)),
        "con_class_index": np.array(int(np.where(clf.classes_ == 1)[0][0])),
        "device_id": np.array(device_id),
        "dino_variant": np.array(config.DINOV2_VARIANT),
        "dino_input": np.array(int(config.DINOV2_INPUT_SIZE)),
        "n_frames": np.array(int(config.DINOV2_N_FRAMES)),
        "bbox": np.array(bbox),
        "n_train": np.array(int(len(y))),
        "n_con": np.array(int(y.sum())),
        "n_rej": np.array(int(len(y) - y.sum())),
        "trained_at": np.array(datetime.now(timezone.utc).isoformat()),
    }


# ----------------------------------------------------------------------- promote
def _current_n_train(path: Path):
    if not path.exists():
        return -1
    try:
        return int(np.load(str(path), allow_pickle=True)["n_train"])
    except Exception:  # noqa: BLE001
        return -1


def _append_log(models_dir: Path, record: dict):
    try:
        with (models_dir / "retrain_log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        _log(f"WARN: failed to append retrain_log: {exc}")


def retrain_device(device_id: str) -> dict:
    t0 = time.time()
    models_dir = Path(config.DINOV2_MODELS_DIR)
    models_dir.mkdir(parents=True, exist_ok=True)
    final = models_dir / f"dinov2_clf_{device_id}.npz"
    rec = {"device_id": device_id,
           "ts": datetime.now(timezone.utc).isoformat(), "promoted": False}

    camera_id, polygon = _camera_row(device_id)
    if camera_id is None:
        rec["reason"] = "no_camera_row"; _log(rec["reason"]); _append_log(models_dir, rec); return rec
    bbox = _bbox_from_polygon(polygon)
    if bbox is None:
        rec["reason"] = "no_polygon"; _log(rec["reason"]); _append_log(models_dir, rec); return rec

    events = _fetch_labeled(camera_id)
    _log(f"{device_id} cam_id={camera_id} bbox={bbox} labeled_events={len(events)}")
    X, y, ids, ts, skipped = _extract(
        events, device_id, bbox, int(config.DINOV2_N_FRAMES), int(config.DINOV2_INPUT_SIZE))
    n = len(y); n_con = int(y.sum()); n_rej = n - n_con
    rec.update({"n": n, "n_con": n_con, "n_rej": n_rej, "skipped": skipped})
    _log(f"extracted n={n} (CON={n_con} REJ={n_rej}, skipped={skipped})")
    if n_con < 2 or n_rej < 2:
        rec["reason"] = "too_few_per_class"; _log(rec["reason"]); _append_log(models_dir, rec); return rec

    auc = _cv_auc(X, y)
    rec["cv_auc"] = auc
    prev_n = _current_n_train(final)
    min_auc = float(config.DINOV2_RETRAIN_MIN_AUC)
    _log(f"cv_auc={auc} prev_n_train={prev_n} min_auc={min_auc}")

    # GATE: AUC suficiente E não encolher o conjunto de treino.
    if auc is None or auc < min_auc:
        rec["reason"] = f"auc_below_gate({auc})"; _log("GATE FAIL: " + rec["reason"])
        _append_log(models_dir, rec); return rec
    if n < prev_n:
        rec["reason"] = f"n_shrank({n}<{prev_n})"; _log("GATE FAIL: " + rec["reason"])
        _append_log(models_dir, rec); return rec

    threshold = config.DINOV2_THRESHOLD if config.DINOV2_THRESHOLD is not None else 0.5
    payload = _fit_export(X, y, bbox, device_id, threshold)

    tmp = models_dir / f"dinov2_clf_{device_id}.tmp.npz"
    np.savez(str(tmp), **payload)
    if final.exists():
        bak = models_dir / f"dinov2_clf_{device_id}.npz.bak"
        try:
            bak.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        final.replace(bak)
    tmp.replace(final)  # swap atômico
    rec.update({"promoted": True, "threshold": float(threshold),
                "elapsed_s": round(time.time() - t0, 1)})
    _log(f"PROMOTED {final.name} (n={n}, auc={auc:.3f}, thr={threshold})")
    _append_log(models_dir, rec)
    return rec


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    devices = sorted(config.DINOV2_RETRAIN_DEVICES)
    if not devices:
        _log("no DINOV2_RETRAIN_DEVICES configured"); return 1
    _log(f"retrain devices: {devices}")
    any_promoted = False
    for d in devices:
        try:
            r = retrain_device(d)
            any_promoted = any_promoted or r.get("promoted", False)
        except Exception as exc:  # noqa: BLE001
            _log(f"ERROR retraining {d}: {exc}")
    return 0 if any_promoted else 0  # nunca falha o cron por gate reprovado


if __name__ == "__main__":
    sys.exit(main())
