#!/usr/bin/env python3
"""Pile-zone delta filter prototype.

Measures whether the pile actually grew between window_first and selected_frame,
inside the pile_zone_polygon. Zero cost ($/latency negligible), pure OpenCV.

Compares with Agent-3 ground truth on the same 8 events. Hypothesis: simple
pixel/edge/foreground delta inside the pile zone correlates with operator labels.
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

S3 = boto3.client("s3", region_name="sa-east-1")
TMP = Path("/tmp/pilezone_proto")
TMP.mkdir(parents=True, exist_ok=True)

# Pile polygons (pulled from cameras table)
POLYS = {
    "esp32_001": [
        [[40, 280], [560, 280], [560, 720], [40, 720]],
        [[800, 280], [1240, 280], [1240, 720], [800, 720]],
    ],
    "esp32_002": [
        [[480, 60], [920, 60], [920, 340], [480, 340]],
    ],
}

TEST = [
    ("E1", "9e90cc61-5d0d-4d42-b5a2-52a1e92eaa25", "REJ", "14:43 cam10"),
    ("E2", "2900d8ea-77ee-41a5-894d-1b3863801919", "REJ", "11:23 cam10"),
    ("E3", "90c05405-10a3-4d14-923b-3ce8b683eded", "REJ", "13:41 cam11"),
    ("E4", "c4224caf-6cb9-48df-846d-b7ad0ea7d141", "REJ", "13:14 cam11"),
    ("E5", "8bfe0a1f-da31-4ddd-9455-de0d6a5ef652", "CON", "18:45 cam10 (S3)"),
    ("E6", "a447ff19-068a-4460-855c-3f6d02937860", "CON", "02:46 cam10 (S3)"),
    ("E7", "8367f372-247b-42fd-886d-61bfc600b303", "CON", "12:46 cam11"),
    ("E8", "ae3d87cb-189c-4d80-b56e-d202d92b4e59", "CON", "12:03 cam11"),
]


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
    su = Path(f"/app/state/detection_summaries/{det_id}.json")
    if not sf.exists():
        return None
    frames_doc = json.loads(sf.read_text())
    summary_doc = json.loads(su.read_text()) if su.exists() else {}
    return {
        "id": det_id,
        "device_id": frames_doc.get("device_id"),
        "frames": frames_doc.get("frames", []),
        "selected_frame_name": frames_doc.get("selected_frame_name")
        or summary_doc.get("event_frame_name"),
        "evidence_summary": summary_doc.get("evidence_summary"),
    }


def build_mask(shape, polys) -> np.ndarray:
    mask = np.zeros(shape[:2], dtype=np.uint8)
    for poly in polys:
        pts = np.array(poly, dtype=np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(mask, [pts], 255)
    return mask


def metrics(img_a: np.ndarray, img_b: np.ndarray, mask: np.ndarray) -> dict:
    """Compare two frames inside the pile mask. img_a = first (before), img_b = selected (after).

    All metrics designed so positive value = pile likely GREW.
    """
    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)

    # 1. pixel diff inside mask
    diff = cv2.absdiff(gray_a, gray_b)
    diff_masked = cv2.bitwise_and(diff, diff, mask=mask)
    mask_area = int(np.count_nonzero(mask))
    changed_pct = float(np.count_nonzero(diff_masked > 25)) / max(mask_area, 1) * 100

    # 2. edge density delta inside mask
    edges_a = cv2.Canny(gray_a, 60, 180)
    edges_b = cv2.Canny(gray_b, 60, 180)
    edges_a_m = cv2.bitwise_and(edges_a, edges_a, mask=mask)
    edges_b_m = cv2.bitwise_and(edges_b, edges_b, mask=mask)
    edge_a_pct = float(np.count_nonzero(edges_a_m)) / mask_area * 100
    edge_b_pct = float(np.count_nonzero(edges_b_m)) / mask_area * 100
    edge_delta_pct = edge_b_pct - edge_a_pct

    # 3. saturation delta (new objects often saturate more than asphalt)
    hsv_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2HSV)
    hsv_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2HSV)
    sat_a = float(np.mean(hsv_a[..., 1][mask > 0]))
    sat_b = float(np.mean(hsv_b[..., 1][mask > 0]))
    sat_delta = sat_b - sat_a

    # 4. structural similarity inside mask (low = different)
    # cheap proxy: normalized cross-correlation
    a_norm = (gray_a[mask > 0] - gray_a[mask > 0].mean())
    b_norm = (gray_b[mask > 0] - gray_b[mask > 0].mean())
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


def main():
    print("[load] events ...", flush=True)
    results = []
    for label, det_id, gt, descr in TEST:
        ev = load_event(det_id)
        if not ev:
            print(f"  {label}: detection_frames missing", flush=True)
            continue
        if ev["device_id"] not in POLYS:
            print(f"  {label}: no polygon for {ev['device_id']}", flush=True)
            continue
        frames = ev["frames"]
        if not frames:
            continue
        first_path = resolve_path(frames[0]["image_url"], frames[0]["frame_name"],
                                  ev["device_id"])
        # Compare first vs last — widest temporal gap; the deposit happens
        # somewhere mid-window, so the last frame reflects post-deposit state.
        # Detail's selected_frame is often the alert frame (=first), useless here.
        last_frame = frames[-1]
        last_path = resolve_path(last_frame["image_url"], last_frame["frame_name"],
                                 ev["device_id"])
        sel_path = last_path
        sel_frame = last_frame
        if not first_path or not sel_path:
            print(f"  {label}: frames unresolved", flush=True)
            continue

        img_a = cv2.imread(str(first_path))
        img_b = cv2.imread(str(sel_path))
        if img_a is None or img_b is None or img_a.shape != img_b.shape:
            print(f"  {label}: image read fail / shape mismatch", flush=True)
            continue

        t0 = time.monotonic()
        mask = build_mask(img_a.shape, POLYS[ev["device_id"]])
        m = metrics(img_a, img_b, mask)
        latency_ms = int((time.monotonic() - t0) * 1000)
        m["latency_ms"] = latency_ms
        m["first_frame"] = frames[0]["frame_name"]
        m["selected_frame"] = sel_frame["frame_name"]
        m["span_frames"] = len(frames)

        print(f"  {label} {descr:<20s} gt={gt} chg={m['changed_pct']:5.1f}% "
              f"edgeΔ={m['edge_delta_pct']:+5.2f} satΔ={m['sat_delta']:+5.2f} "
              f"ncc={m['ncc']:5.3f} ({latency_ms}ms)", flush=True)
        results.append({"label": label, "id": det_id, "gt": gt, "descr": descr,
                        "device": ev["device_id"], **m})

    # Try a few simple decision rules and score them
    print()
    print("=== Decision rules ===")
    rules = [
        ("changed_pct > 3.0", lambda r: r["changed_pct"] > 3.0),
        ("changed_pct > 5.0", lambda r: r["changed_pct"] > 5.0),
        ("changed_pct > 8.0", lambda r: r["changed_pct"] > 8.0),
        ("edge_delta_pct > 0.5", lambda r: r["edge_delta_pct"] > 0.5),
        ("edge_delta_pct > 1.0", lambda r: r["edge_delta_pct"] > 1.0),
        ("ncc < 0.95", lambda r: r["ncc"] < 0.95),
        ("ncc < 0.90", lambda r: r["ncc"] < 0.90),
        ("changed>3 AND edgeΔ>0.3", lambda r: r["changed_pct"] > 3 and r["edge_delta_pct"] > 0.3),
        ("changed>5 OR edgeΔ>1", lambda r: r["changed_pct"] > 5 or r["edge_delta_pct"] > 1),
    ]
    for name, rule in rules:
        tp = sum(1 for r in results if rule(r) and r["gt"] == "CON")
        tn = sum(1 for r in results if not rule(r) and r["gt"] == "REJ")
        fp = sum(1 for r in results if rule(r) and r["gt"] == "REJ")
        fn = sum(1 for r in results if not rule(r) and r["gt"] == "CON")
        acc = (tp + tn) / max(len(results), 1)
        print(f"  {name:<32s} acc={acc:.2%}  TP={tp} TN={tn} FP={fp} FN={fn}")

    out = Path("/tmp/pilezone_proto_results.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    sys.exit(main())
