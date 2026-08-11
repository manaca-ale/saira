#!/usr/bin/env python3
"""Pile-zone delta — FULL evaluation on every REJ + CONFIRMADO in the database.

Runs the same first-vs-last-frame delta inside pile_zone_polygon as
pilezone_delta_proto.py, but on all 23 REJ + 30 CONFIRMADO from cam_10 + cam_11
(cam_14/esp32_005 skipped — no polygon yet).

Outputs:
- per-event row with metrics + GT
- decision-rule scoring (accuracy, TP/TN/FP/FN, confusion by camera)
- threshold sweep on edge_delta_pct
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

S3 = boto3.client("s3", region_name="sa-east-1")
TMP = Path("/tmp/pilezone_full")
TMP.mkdir(parents=True, exist_ok=True)

POLYS = {
    "esp32_001": [
        [[40, 280], [560, 280], [560, 720], [40, 720]],
        [[800, 280], [1240, 280], [1240, 720], [800, 720]],
    ],
    "esp32_002": [
        [[480, 60], [920, 60], [920, 340], [480, 340]],
    ],
}
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
    except Exception as exc:
        return None


def load_event(det_id: str) -> dict | None:
    sf = Path(f"/app/state/detection_frames/{det_id}.json")
    if not sf.exists():
        return None
    frames_doc = json.loads(sf.read_text())
    return {
        "id": det_id,
        "device_id": frames_doc.get("device_id"),
        "frames": frames_doc.get("frames", []),
    }


def build_mask(shape, polys) -> np.ndarray:
    mask = np.zeros(shape[:2], dtype=np.uint8)
    for poly in polys:
        pts = np.array(poly, dtype=np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(mask, [pts], 255)
    return mask


def metrics(img_a: np.ndarray, img_b: np.ndarray, mask: np.ndarray) -> dict:
    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray_a, gray_b)
    diff_masked = cv2.bitwise_and(diff, diff, mask=mask)
    mask_area = int(np.count_nonzero(mask))
    changed_pct = float(np.count_nonzero(diff_masked > 25)) / max(mask_area, 1) * 100
    edges_a = cv2.Canny(gray_a, 60, 180)
    edges_b = cv2.Canny(gray_b, 60, 180)
    edges_a_m = cv2.bitwise_and(edges_a, edges_a, mask=mask)
    edges_b_m = cv2.bitwise_and(edges_b, edges_b, mask=mask)
    edge_a_pct = float(np.count_nonzero(edges_a_m)) / mask_area * 100
    edge_b_pct = float(np.count_nonzero(edges_b_m)) / mask_area * 100
    edge_delta_pct = edge_b_pct - edge_a_pct
    hsv_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2HSV)
    hsv_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2HSV)
    sat_a = float(np.mean(hsv_a[..., 1][mask > 0]))
    sat_b = float(np.mean(hsv_b[..., 1][mask > 0]))
    sat_delta = sat_b - sat_a
    a_norm = (gray_a[mask > 0].astype(np.float32) - gray_a[mask > 0].mean())
    b_norm = (gray_b[mask > 0].astype(np.float32) - gray_b[mask > 0].mean())
    denom = float(np.sqrt((a_norm * a_norm).sum() * (b_norm * b_norm).sum()))
    ncc = float((a_norm * b_norm).sum() / denom) if denom > 0 else 1.0
    return {
        "changed_pct": round(changed_pct, 2),
        "edge_a_pct": round(edge_a_pct, 2),
        "edge_b_pct": round(edge_b_pct, 2),
        "edge_delta_pct": round(edge_delta_pct, 2),
        "sat_delta": round(sat_delta, 2),
        "ncc": round(ncc, 4),
    }


def fetch_events() -> list[dict]:
    """All REJ + CONFIRMADO from cam_10 + cam_11."""
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


def night_flag(ts: str) -> bool:
    # Naive: between 17:30 and 06:30 BRT
    try:
        hhmm = ts[11:16]
        h, m = int(hhmm[:2]), int(hhmm[3:5])
        minutes = h * 60 + m
        return minutes >= 17 * 60 + 30 or minutes <= 6 * 60 + 30
    except Exception:
        return False


def main():
    events = fetch_events()
    print(f"[fetch] {len(events)} events from DB", flush=True)
    results = []
    skip_no_frames = 0
    skip_no_resolve = 0
    skip_shape = 0
    t_start = time.monotonic()
    for i, ev in enumerate(events, 1):
        device_id = DEVICE_BY_CAM.get(ev["cam"])
        if not device_id or device_id not in POLYS:
            continue
        det = load_event(ev["id"])
        if not det or not det["frames"]:
            skip_no_frames += 1
            continue
        frames = det["frames"]
        first_path = resolve_path(frames[0]["image_url"], frames[0]["frame_name"], device_id)
        last_path = resolve_path(frames[-1]["image_url"], frames[-1]["frame_name"], device_id)
        if not first_path or not last_path:
            skip_no_resolve += 1
            continue
        img_a = cv2.imread(str(first_path))
        img_b = cv2.imread(str(last_path))
        if img_a is None or img_b is None or img_a.shape != img_b.shape:
            skip_shape += 1
            continue
        t0 = time.monotonic()
        mask = build_mask(img_a.shape, POLYS[device_id])
        m = metrics(img_a, img_b, mask)
        latency_ms = int((time.monotonic() - t0) * 1000)
        gt = "REJ" if ev["status"] == "REJEITADO" else "CON"
        results.append({
            "id": ev["id"], "ts": ev["ts"], "cam": ev["cam"], "device": device_id,
            "gt": gt, "night": night_flag(ev["ts"]), "n_frames": len(frames),
            "latency_ms": latency_ms, **m,
        })
        if i % 10 == 0 or i == len(events):
            print(f"  {i}/{len(events)} (done={len(results)} skip_frames={skip_no_frames} "
                  f"skip_resolve={skip_no_resolve} skip_shape={skip_shape})", flush=True)
    elapsed = time.monotonic() - t_start
    print(f"\n[done] evaluated {len(results)} events in {elapsed:.1f}s "
          f"(skipped: no_frames={skip_no_frames} no_resolve={skip_no_resolve} shape={skip_shape})")

    # threshold sweep on edge_delta_pct
    print("\n=== Threshold sweep on edge_delta_pct ===")
    print(f"{'threshold':<12}{'acc':<8}{'TP':<5}{'TN':<5}{'FP':<5}{'FN':<5}{'precision':<12}{'recall':<10}")
    for th in [-0.5, -0.2, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0]:
        tp = sum(1 for r in results if r["edge_delta_pct"] > th and r["gt"] == "CON")
        tn = sum(1 for r in results if r["edge_delta_pct"] <= th and r["gt"] == "REJ")
        fp = sum(1 for r in results if r["edge_delta_pct"] > th and r["gt"] == "REJ")
        fn = sum(1 for r in results if r["edge_delta_pct"] <= th and r["gt"] == "CON")
        acc = (tp + tn) / max(len(results), 1)
        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        print(f"  {th:>+5.2f}      {acc:>6.2%}  {tp:<5}{tn:<5}{fp:<5}{fn:<5}{prec:>6.2%}    {rec:>6.2%}")

    # composite rules
    print("\n=== Composite rules ===")
    rules = [
        ("edgeΔ > 0.3", lambda r: r["edge_delta_pct"] > 0.3),
        ("edgeΔ > 0.2", lambda r: r["edge_delta_pct"] > 0.2),
        ("edgeΔ > 0.1", lambda r: r["edge_delta_pct"] > 0.1),
        ("edgeΔ > 0 AND chg > 8", lambda r: r["edge_delta_pct"] > 0 and r["changed_pct"] > 8),
        ("edgeΔ > 0.2 AND ncc < 0.95",
         lambda r: r["edge_delta_pct"] > 0.2 and r["ncc"] < 0.95),
        ("edgeΔ > 0 AND satΔ > -1",
         lambda r: r["edge_delta_pct"] > 0 and r["sat_delta"] > -1),
    ]
    for name, rule in rules:
        tp = sum(1 for r in results if rule(r) and r["gt"] == "CON")
        tn = sum(1 for r in results if not rule(r) and r["gt"] == "REJ")
        fp = sum(1 for r in results if rule(r) and r["gt"] == "REJ")
        fn = sum(1 for r in results if not rule(r) and r["gt"] == "CON")
        acc = (tp + tn) / max(len(results), 1)
        print(f"  {name:<32s} acc={acc:.2%}  TP={tp} TN={tn} FP={fp} FN={fn}")

    # day vs night
    print("\n=== Day vs Night (edgeΔ > 0.3) ===")
    for tag, subset in (("day", [r for r in results if not r["night"]]),
                        ("night", [r for r in results if r["night"]])):
        if not subset:
            print(f"  {tag}: n=0")
            continue
        tp = sum(1 for r in subset if r["edge_delta_pct"] > 0.3 and r["gt"] == "CON")
        tn = sum(1 for r in subset if r["edge_delta_pct"] <= 0.3 and r["gt"] == "REJ")
        fp = sum(1 for r in subset if r["edge_delta_pct"] > 0.3 and r["gt"] == "REJ")
        fn = sum(1 for r in subset if r["edge_delta_pct"] <= 0.3 and r["gt"] == "CON")
        n = len(subset)
        print(f"  {tag} n={n:<3} acc={(tp+tn)/n:.2%}  TP={tp} TN={tn} FP={fp} FN={fn}")

    # per-camera
    print("\n=== Per-camera (edgeΔ > 0.3) ===")
    for cam in sorted({r["cam"] for r in results}):
        subset = [r for r in results if r["cam"] == cam]
        tp = sum(1 for r in subset if r["edge_delta_pct"] > 0.3 and r["gt"] == "CON")
        tn = sum(1 for r in subset if r["edge_delta_pct"] <= 0.3 and r["gt"] == "REJ")
        fp = sum(1 for r in subset if r["edge_delta_pct"] > 0.3 and r["gt"] == "REJ")
        fn = sum(1 for r in subset if r["edge_delta_pct"] <= 0.3 and r["gt"] == "CON")
        n = len(subset)
        print(f"  cam_{cam} n={n:<3} acc={(tp+tn)/n:.2%}  TP={tp} TN={tn} FP={fp} FN={fn}")

    # distribution of edge_delta by GT
    print("\n=== edge_delta_pct distribution by GT ===")
    for gt in ("REJ", "CON"):
        vals = sorted(r["edge_delta_pct"] for r in results if r["gt"] == gt)
        if not vals:
            continue
        med = vals[len(vals) // 2]
        p25 = vals[len(vals) // 4]
        p75 = vals[3 * len(vals) // 4]
        print(f"  {gt} n={len(vals):<3} min={vals[0]:+.2f} p25={p25:+.2f} med={med:+.2f} "
              f"p75={p75:+.2f} max={vals[-1]:+.2f}")

    out = Path("/tmp/pilezone_full_results.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nsaved: {out}  ({len(results)} rows)")


if __name__ == "__main__":
    sys.exit(main())
