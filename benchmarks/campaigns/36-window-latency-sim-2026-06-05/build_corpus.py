#!/usr/bin/env python3
"""Camp 36 Phase 0a — assemble positive replay corpus from prod S3 timelines.

Reads the 21 detection_frames JSONs (already fetched to .tmp/corpus_jsons/) plus the
DB metadata dump, downloads every frame from S3 into the campaign corpus dir, writes a
per-event meta.json, and renders a contact sheet for disposal_start labeling.

Run from repo root:  python -X utf8 benchmarks/campaigns/36-window-latency-sim-2026-06-05/build_corpus.py
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

REPO = Path(__file__).resolve().parents[3]
CAMPAIGN = Path(__file__).resolve().parent
JSON_DIR = REPO / ".tmp" / "corpus_jsons"
DB_META = REPO / ".tmp" / "corpus_db_meta.txt"
CORPUS = CAMPAIGN / "corpus" / "positives"
SHEETS = CAMPAIGN / "corpus" / "contact_sheets"

CAMERA_BAIRRO = {10: "Imbiribeira", 11: "Mangabeira", 14: "Arruda"}


def parse_ts(frame_name: str) -> datetime:
    # 2026-06-04_20-44-23.jpg
    stem = frame_name.replace(".jpg", "")
    return datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S")


def load_db_meta() -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for line in DB_META.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 7:
            continue
        eid, cam, ts, created, status, conf, waste = parts[:7]
        meta[eid] = {
            "camera_id": int(cam),
            "db_timestamp": ts,
            "db_created_at": created,
            "status": status,
            "confidence": float(conf),
            "waste_type": waste,
        }
    return meta


def download_one(url: str, dest: Path) -> tuple[Path, bool, str]:
    if dest.exists() and dest.stat().st_size > 1000:
        return dest, True, "cached"
    try:
        with urlopen(url, timeout=30) as r:
            data = r.read()
        if len(data) < 500:
            return dest, False, f"too_small({len(data)})"
        dest.write_bytes(data)
        return dest, True, "ok"
    except (HTTPError, URLError, TimeoutError) as e:  # noqa
        return dest, False, str(e)


def build_event(eid: str, db_meta: dict) -> dict:
    j = json.loads((JSON_DIR / f"{eid}.json").read_text(encoding="utf-8"))
    device_id = j.get("device_id")
    frames = j.get("frames") or []
    # de-dup + sort by timestamp
    seen, rows = set(), []
    for f in frames:
        name = f.get("frame_name")
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append((parse_ts(name), name, f.get("image_url")))
    rows.sort(key=lambda r: r[0])

    ev_dir = CORPUS / eid
    fr_dir = ev_dir / "frames"
    fr_dir.mkdir(parents=True, exist_ok=True)

    # download all frames in parallel
    results = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = {pool.submit(download_one, url, fr_dir / name): name
                for _, name, url in rows}
        for fut in as_completed(futs):
            results.append(fut.result())
    ok = sum(1 for _, good, _ in results if good)
    fails = [(p.name, msg) for p, good, msg in results if not good]

    dbm = db_meta.get(eid, {})
    cam = dbm.get("camera_id")
    frame_meta = [{"frame_name": name, "ts": ts.strftime("%H:%M:%S"),
                   "epoch": ts.timestamp(), "idx": i}
                  for i, (ts, name, _url) in enumerate(rows)]
    span = (rows[-1][0] - rows[0][0]).total_seconds() if len(rows) > 1 else 0
    meta = {
        "event_id": eid,
        "device_id": device_id,
        "camera_id": cam,
        "bairro": CAMERA_BAIRRO.get(cam, "?"),
        "status": dbm.get("status"),
        "waste_type": dbm.get("waste_type"),
        "confidence": dbm.get("confidence"),
        "db_timestamp": dbm.get("db_timestamp"),
        "db_created_at": dbm.get("db_created_at"),
        "n_frames": len(rows),
        "first_frame": rows[0][1] if rows else None,
        "last_frame": rows[-1][1] if rows else None,
        "span_seconds": round(span, 1),
        "median_cadence_s": _median_cadence(rows),
        "frames": frame_meta,
        # to be filled by operator confirmation:
        "disposal_start_frame": None,
        "disposal_start_ts": None,
        "disposal_start_source": None,
    }
    (ev_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    return {"event_id": eid, "device_id": device_id, "bairro": meta["bairro"],
            "n_frames": len(rows), "downloaded_ok": ok, "fails": fails,
            "span_s": round(span, 1)}


def _median_cadence(rows) -> float:
    if len(rows) < 2:
        return 0.0
    deltas = sorted((rows[i + 1][0] - rows[i][0]).total_seconds()
                    for i in range(len(rows) - 1))
    return round(deltas[len(deltas) // 2], 1)


def main() -> int:
    db_meta = load_db_meta()
    ids = sorted(p.stem for p in JSON_DIR.glob("*.json"))
    print(f"Building corpus for {len(ids)} events -> {CORPUS}")
    summary = []
    for i, eid in enumerate(ids, 1):
        r = build_event(eid, db_meta)
        summary.append(r)
        flag = "OK" if not r["fails"] else f"!! {len(r['fails'])} FAILS"
        print(f"[{i:2}/{len(ids)}] {eid[:8]} {r['bairro']:12} "
              f"frames={r['n_frames']:3} dl={r['downloaded_ok']:3} span={r['span_s']:5.0f}s {flag}")
        for name, msg in r["fails"][:3]:
            print(f"        FAIL {name}: {msg}")
    SHEETS.mkdir(parents=True, exist_ok=True)
    (CAMPAIGN / "corpus" / "build_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    total_ok = sum(r["downloaded_ok"] for r in summary)
    total_fail = sum(len(r["fails"]) for r in summary)
    print(f"\nDONE: {len(ids)} events, {total_ok} frames downloaded, {total_fail} fails")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
