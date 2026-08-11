#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase A — download ALL esp32_001 (Imbiribeira) detection frames from S3.

Reads (produced by the prod pull, see README):
  .tmp/corpus_esp32_001.csv   (one row per detection; cols from sql/pull_esp32_001.sql)
  .tmp/df/<id>.json           (detection_frames JSON: frames[{frame_name,image_url}])

Buckets purely by operator status: CONFIRMADO->tp, REJEITADO->fp, INDETERMINADO->indefinido.
Downloads ALL frames per event (Phases B/C/D need the full window). Writes
largeN/manifest.csv with one row per event + the local frame paths.

Adapted from benchmarks/campaigns/40-mangabeira-b3-fp-2026-06-16/scripts/largeN_fetch.py
(dropped the B1/B2/B3 regex bucketing; status-only here).
"""
import collections
import csv
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CAMP = Path(__file__).resolve().parents[1]
TMP = CAMP / ".tmp"
LN = CAMP / "largeN"
FR = LN / "frames"
FR.mkdir(parents=True, exist_ok=True)

STATUS_TO_CAT = {"CONFIRMADO": "tp", "REJEITADO": "fp", "INDETERMINADO": "indefinido"}
N_SUBSET = 12  # frames per event: even-spaced incl. endpoints (supports gate first+3mid+last)


def even_spaced(frames, k):
    """Pick up to k frames evenly spaced across the list, always incl. first & last."""
    n = len(frames)
    if n <= k:
        return frames
    idxs = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
    return [frames[i] for i in idxs]


def dl(args):
    url, dst = args
    if dst.exists() and dst.stat().st_size > 1000:
        return True
    try:
        urllib.request.urlretrieve(url, dst)
        return dst.stat().st_size > 1000
    except Exception:
        return False


def main():
    corpus = TMP / "corpus_esp32_001.csv"
    rows = list(csv.DictReader(corpus.open(encoding="utf-8")))
    print(f"corpus: {len(rows)} detections")

    jobs, manifest, missing_df = [], [], 0
    for r in rows:
        eid = r["id"]
        cat = STATUS_TO_CAT.get((r.get("status") or "").strip().upper())
        if not cat:
            continue
        jp = TMP / "df" / f"{eid}.json"
        if not jp.exists() or jp.stat().st_size < 10:
            missing_df += 1
            continue
        try:
            dfj = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            missing_df += 1
            continue
        frames = dfj.get("frames", []) or []
        if not frames:
            continue
        frames = even_spaced(frames, N_SUBSET)
        edir = FR / eid
        edir.mkdir(parents=True, exist_ok=True)
        local = []
        for f in frames:
            u = (f.get("image_url") or "").strip()
            name = (f.get("frame_name") or "").strip()
            if not u.startswith("http") or not name:
                continue
            dst = edir / name
            jobs.append((u, dst))
            local.append(str(dst))
        if not local:
            continue
        manifest.append({
            "id": eid,
            "status": r.get("status", ""),
            "category": cat,
            "created_at": r.get("created_at", ""),
            "validity_comment": r.get("validity_comment", ""),
            "waste_bbox": r.get("waste_bbox", ""),
            "confidence_score": r.get("confidence_score", ""),
            "agent1_confidence": r.get("agent1_confidence", ""),
            "offender_present": r.get("offender_present", ""),
            "waste_type": r.get("waste_type", ""),
            "volume_m3": r.get("volume_m3", ""),
            "logradouro": r.get("logradouro", ""),
            "selected_frame_name": dfj.get("selected_frame_name", ""),
            "evidence_summary": dfj.get("evidence_summary", ""),
            "n_frames": len(local),
            "frames": "|".join(local),
        })

    print(f"events with frames: {len(manifest)} | missing df json: {missing_df}")
    print(f"downloading {len(jobs)} frames (16 threads)...")
    with ThreadPoolExecutor(max_workers=16) as ex:
        ok = sum(ex.map(dl, jobs))
    print(f"frames downloaded OK: {ok}/{len(jobs)} (miss rate {100*(len(jobs)-ok)/max(1,len(jobs)):.1f}%)")

    print("buckets:", dict(collections.Counter(m["category"] for m in manifest)))
    LN.mkdir(parents=True, exist_ok=True)
    out = LN / "manifest.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0].keys()) if manifest else ["id"])
        w.writeheader()
        w.writerows(manifest)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
