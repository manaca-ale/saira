#!/usr/bin/env python3
"""Pile-zone delta v2 — multi-anchor + control-zone subtraction.

v1 (first vs last, pile only) got 60% acc on 52 events because:
- 4-min window dilutes the deposit moment (multi-anchor fixes)
- scene-global motion (sun, shadows, vehicles) confounds pile delta (control fixes)

Strategy:
- Sample 5 frames evenly from each window.
- Per frame, compute edge density inside pile_mask and inside control_mask (=
  frame minus pile).
- For each pair (i, j>i): lift_ij = (pile_b - pile_a) - (control_b - control_a).
  Captures pile-specific edge gain, subtracting global scene motion.
- Signals tested: max_lift over all pairs, max_lift vs first-frame anchor,
  and the v1 first-vs-last metric for comparison.
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
TMP = Path("/tmp/pilezone_v2")
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
N_ANCHORS = 5


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


def build_masks(shape, polys) -> tuple[np.ndarray, np.ndarray]:
    """Return (pile_mask, control_mask) where control = frame minus pile."""
    h, w = shape[:2]
    pile = np.zeros((h, w), dtype=np.uint8)
    for poly in polys:
        pts = np.array(poly, dtype=np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(pile, [pts], 255)
    full = np.full((h, w), 255, dtype=np.uint8)
    control = cv2.bitwise_and(full, cv2.bitwise_not(pile))
    return pile, control


def edge_pct(gray: np.ndarray, mask: np.ndarray, mask_area: int) -> float:
    edges = cv2.Canny(gray, 60, 180)
    return float(np.count_nonzero(cv2.bitwise_and(edges, edges, mask=mask))) / max(mask_area, 1) * 100


def night_flag(ts: str) -> bool:
    try:
        hhmm = ts[11:16]
        h, m = int(hhmm[:2]), int(hhmm[3:5])
        mins = h * 60 + m
        return mins >= 17 * 60 + 30 or mins <= 6 * 60 + 30
    except Exception:
        return False


def sample_indices(n: int, k: int) -> list[int]:
    if n <= k:
        return list(range(n))
    return [int(round(i * (n - 1) / (k - 1))) for i in range(k)]


def evaluate_event(det: dict, polys: list) -> dict | None:
    frames = det.get("frames", [])
    if len(frames) < 2:
        return None
    device_id = det["device_id"]
    idxs = sample_indices(len(frames), N_ANCHORS)
    paths = []
    for i in idxs:
        p = resolve_path(frames[i]["image_url"], frames[i]["frame_name"], device_id)
        if p:
            paths.append((i, p))
    if len(paths) < 2:
        return None

    # load first image to get shape -> masks
    img0 = cv2.imread(str(paths[0][1]))
    if img0 is None:
        return None
    pile_mask, control_mask = build_masks(img0.shape, polys)
    pile_area = int(np.count_nonzero(pile_mask))
    ctrl_area = int(np.count_nonzero(control_mask))

    pile_pcts = []
    ctrl_pcts = []
    for _, p in paths:
        img = cv2.imread(str(p))
        if img is None or img.shape != img0.shape:
            pile_pcts.append(None)
            ctrl_pcts.append(None)
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        pile_pcts.append(edge_pct(gray, pile_mask, pile_area))
        ctrl_pcts.append(edge_pct(gray, control_mask, ctrl_area))

    valid = [(p, c) for p, c in zip(pile_pcts, ctrl_pcts) if p is not None and c is not None]
    if len(valid) < 2:
        return None

    # v1 first-vs-last (for comparison)
    v1_pile_delta = valid[-1][0] - valid[0][0]
    v1_ctrl_delta = valid[-1][1] - valid[0][1]
    v1_lift = v1_pile_delta - v1_ctrl_delta

    # max lift across all pairs (j > i)
    n = len(valid)
    max_lift_any = -1e9
    max_pile_any = -1e9
    for i in range(n):
        for j in range(i + 1, n):
            pile_d = valid[j][0] - valid[i][0]
            ctrl_d = valid[j][1] - valid[i][1]
            lift = pile_d - ctrl_d
            if lift > max_lift_any:
                max_lift_any = lift
            if pile_d > max_pile_any:
                max_pile_any = pile_d

    # max lift vs first-anchor (i=0)
    max_lift_anchor0 = -1e9
    for j in range(1, n):
        pile_d = valid[j][0] - valid[0][0]
        ctrl_d = valid[j][1] - valid[0][1]
        if (pile_d - ctrl_d) > max_lift_anchor0:
            max_lift_anchor0 = pile_d - ctrl_d

    # final delta (last vs first, just pile)
    return {
        "v1_pile_delta": round(v1_pile_delta, 3),
        "v1_ctrl_delta": round(v1_ctrl_delta, 3),
        "v1_lift": round(v1_lift, 3),
        "max_lift_any": round(max_lift_any, 3),
        "max_lift_anchor0": round(max_lift_anchor0, 3),
        "max_pile_any": round(max_pile_any, 3),
        "pile_first": round(valid[0][0], 3),
        "pile_last": round(valid[-1][0], 3),
        "n_anchors": n,
    }


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


def score(results: list[dict], key: str, ths: list[float]) -> None:
    print(f"\n=== {key} sweep ===")
    print(f"{'th':<8}{'acc':<8}{'TP':<5}{'TN':<5}{'FP':<5}{'FN':<5}{'prec':<8}{'recall':<8}")
    for th in ths:
        tp = sum(1 for r in results if r[key] > th and r["gt"] == "CON")
        tn = sum(1 for r in results if r[key] <= th and r["gt"] == "REJ")
        fp = sum(1 for r in results if r[key] > th and r["gt"] == "REJ")
        fn = sum(1 for r in results if r[key] <= th and r["gt"] == "CON")
        acc = (tp + tn) / max(len(results), 1)
        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        print(f"  {th:>+5.2f}  {acc:>6.2%}  {tp:<5}{tn:<5}{fp:<5}{fn:<5}{prec:>6.2%}  {rec:>6.2%}")


def distribution(results: list[dict], key: str) -> None:
    print(f"\n=== {key} distribution by GT ===")
    for gt in ("REJ", "CON"):
        vals = sorted(r[key] for r in results if r["gt"] == gt)
        if not vals:
            continue
        med = vals[len(vals) // 2]
        p25 = vals[len(vals) // 4]
        p75 = vals[3 * len(vals) // 4]
        print(f"  {gt} n={len(vals):<3} min={vals[0]:+.2f} p25={p25:+.2f} "
              f"med={med:+.2f} p75={p75:+.2f} max={vals[-1]:+.2f}")


def main():
    events = fetch_events()
    print(f"[fetch] {len(events)} events", flush=True)
    results = []
    t0 = time.monotonic()
    for i, ev in enumerate(events, 1):
        device_id = DEVICE_BY_CAM.get(ev["cam"])
        if not device_id or device_id not in POLYS:
            continue
        det = load_event(ev["id"])
        if not det:
            continue
        m = evaluate_event(det, POLYS[device_id])
        if not m:
            continue
        gt = "REJ" if ev["status"] == "REJEITADO" else "CON"
        results.append({"id": ev["id"], "ts": ev["ts"], "cam": ev["cam"],
                        "gt": gt, "night": night_flag(ev["ts"]), **m})
        if i % 10 == 0 or i == len(events):
            print(f"  {i}/{len(events)} (done={len(results)})", flush=True)
    print(f"[done] {len(results)} events in {time.monotonic()-t0:.1f}s", flush=True)

    distribution(results, "v1_pile_delta")
    distribution(results, "v1_lift")
    distribution(results, "max_lift_any")
    distribution(results, "max_lift_anchor0")
    distribution(results, "max_pile_any")

    score(results, "v1_lift", [-0.2, 0.0, 0.1, 0.2, 0.3, 0.5])
    score(results, "max_lift_anchor0", [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    score(results, "max_lift_any", [0.0, 0.3, 0.5, 0.8, 1.0, 1.5])

    # composite: max_lift_anchor0 AND v1_pile_delta
    print("\n=== Composite rules ===")
    rules = [
        ("max_lift_anchor0 > 0.4", lambda r: r["max_lift_anchor0"] > 0.4),
        ("max_lift_anchor0 > 0.6", lambda r: r["max_lift_anchor0"] > 0.6),
        ("v1_lift > 0.2", lambda r: r["v1_lift"] > 0.2),
        ("max_lift_anchor0>0.4 AND v1_pile_delta>0",
         lambda r: r["max_lift_anchor0"] > 0.4 and r["v1_pile_delta"] > 0),
        ("v1_lift > 0 AND v1_pile_delta > 0.2",
         lambda r: r["v1_lift"] > 0 and r["v1_pile_delta"] > 0.2),
    ]
    for name, rule in rules:
        tp = sum(1 for r in results if rule(r) and r["gt"] == "CON")
        tn = sum(1 for r in results if not rule(r) and r["gt"] == "REJ")
        fp = sum(1 for r in results if rule(r) and r["gt"] == "REJ")
        fn = sum(1 for r in results if not rule(r) and r["gt"] == "CON")
        acc = (tp + tn) / max(len(results), 1)
        print(f"  {name:<48s} acc={acc:.2%}  TP={tp} TN={tn} FP={fp} FN={fn}")

    # day vs night
    print("\n=== max_lift_anchor0 > 0.4 by period/camera ===")
    for tag, subset in (
        ("day", [r for r in results if not r["night"]]),
        ("night", [r for r in results if r["night"]]),
        ("cam_10", [r for r in results if r["cam"] == 10]),
        ("cam_11", [r for r in results if r["cam"] == 11]),
    ):
        if not subset:
            continue
        rule = lambda r: r["max_lift_anchor0"] > 0.4
        tp = sum(1 for r in subset if rule(r) and r["gt"] == "CON")
        tn = sum(1 for r in subset if not rule(r) and r["gt"] == "REJ")
        fp = sum(1 for r in subset if rule(r) and r["gt"] == "REJ")
        fn = sum(1 for r in subset if not rule(r) and r["gt"] == "CON")
        n = len(subset)
        print(f"  {tag:<8s} n={n:<3} acc={(tp+tn)/n:.2%} TP={tp} TN={tn} FP={fp} FN={fn}")

    out = Path("/tmp/pilezone_v2_results.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    sys.exit(main())
