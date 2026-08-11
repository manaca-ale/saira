#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Rebuild the master manifest.csv of the OFFICIAL dataset from the per-event
label.json files on disk.

Why: campaign merges (e.g. Camp 42 merge_to_official.py) write per-event folders
+ label.json + a sidecar manifest, but never regenerate the master manifest.csv.
This leaves curated events invisible to the benchmark skill (which uses
manifest.csv as ground truth). This script reconciles disk -> manifest.

Behaviour (additive, non-destructive):
  - For every event folder under official/<cam>/<category>/<id>/ that has a
    label.json, derive a manifest row from it (label.json is source of truth).
  - For overlap events also present in the OLD manifest, backfill columns the
    label.json lacks (notably drive_url) from the old row.
  - Events in the OLD manifest but NOT on disk (or in folders without label.json,
    e.g. baseline) are PRESERVED verbatim.
  - Adds two columns: label_source, fp_subtype (empty for legacy rows -> tagged
    'official_v1' so the human-only subset = label_source in {comment, official_v1}).

Usage:
  python rebuild_official_manifest.py --dry-run      # writes manifest.rebuilt.csv, no overwrite
  python rebuild_official_manifest.py --apply        # backs up + overwrites manifest.csv
"""
import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(r"c:\saira")
OFFICIAL = ROOT / "data" / "datasets" / "official"
MANIFEST = OFFICIAL / "manifest.csv"

BASE_COLS = ["event_id", "camera", "device_id", "category", "classificacao",
             "datetime", "logradouro", "bairro", "rpa", "tipo_residuo",
             "volumetria", "justificativa", "frame_count", "drive_url", "local_path"]
NEW_COLS = ["label_source", "fp_subtype"]
OUT_COLS = BASE_COLS + NEW_COLS

# NOTE: the ESP32 baseline (cam_*/baseline/{day,night}/*.jpg) has no per-event label.json
# and is intentionally skipped. Event-driven cameras (pi-cam-001) DO carry a per-event
# baseline/<event_ref>/label.json (sem-ocorrência true negatives), so "baseline" is scanned
# and only folders that actually contain a label.json are picked up.
DISK_CATEGORIES = ["tp", "fp", "indefinido", "missed", "baseline"]


def row_from_label(cam_dir: Path, cat: str, ev_dir: Path, old: dict | None) -> dict:
    lj = json.loads((ev_dir / "label.json").read_text(encoding="utf-8"))
    frames_dir = ev_dir / "frames"
    n_frames = len(list(frames_dir.glob("*.jpg"))) if frames_dir.is_dir() else lj.get("frame_count", 0)
    cam = cam_dir.name
    r = {
        "event_id": lj.get("event_id", ev_dir.name),
        "camera": lj.get("camera", cam),
        "device_id": lj.get("device_id", ""),
        "category": lj.get("category", cat),
        "classificacao": lj.get("classificacao", ""),
        "datetime": lj.get("datetime", ""),
        "logradouro": lj.get("logradouro", ""),
        "bairro": lj.get("bairro", ""),
        "rpa": lj.get("rpa", ""),
        "tipo_residuo": lj.get("tipo_residuo", ""),
        "volumetria": lj.get("volumetria", ""),
        "justificativa": lj.get("validity_comment", "") or (old or {}).get("justificativa", ""),
        "frame_count": n_frames,
        "drive_url": (old or {}).get("drive_url", ""),  # label.json has no drive_url; keep legacy link
        "local_path": f"{cam}/{cat}/{ev_dir.name}",
        "label_source": lj.get("label_source", "") or "official_v1",
        "fp_subtype": lj.get("fp_subtype", ""),
    }
    return r


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    old_rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    old_by_id = {r["event_id"]: r for r in old_rows}

    disk_rows = {}
    for cam_dir in sorted(OFFICIAL.glob("cam_*")):
        for cat in DISK_CATEGORIES:
            cdir = cam_dir / cat
            if not cdir.is_dir():
                continue
            for ev_dir in sorted(p for p in cdir.iterdir() if p.is_dir()):
                if (ev_dir / "label.json").is_file():
                    r = row_from_label(cam_dir, cat, ev_dir, old_by_id.get(ev_dir.name))
                    disk_rows[r["event_id"]] = r

    # Merge: disk wins; preserve legacy rows not derivable from disk
    out = dict(disk_rows)
    preserved = 0
    for eid, r in old_by_id.items():
        if eid not in out:
            legacy = {c: r.get(c, "") for c in BASE_COLS}
            legacy["label_source"] = r.get("label_source", "") or "official_v1"
            legacy["fp_subtype"] = r.get("fp_subtype", "")
            out[eid] = legacy
            preserved += 1

    out_rows = sorted(out.values(), key=lambda r: (r["camera"], r["category"], r["event_id"]))

    # Report
    def breakdown(rows):
        d = {}
        for r in rows:
            d.setdefault(r["camera"], Counter())[r["category"]] += 1
        return d

    print("=== BEFORE (old manifest.csv) ===")
    for cam, c in breakdown(old_rows).items():
        print(f"  {cam}: {dict(c)}  (total {sum(c.values())})")
    print(f"  TOTAL rows: {len(old_rows)}")
    print("\n=== AFTER (rebuilt) ===")
    for cam, c in breakdown(out_rows).items():
        print(f"  {cam}: {dict(c)}  (total {sum(c.values())})")
    print(f"  TOTAL rows: {len(out_rows)}  | from disk: {len(disk_rows)} | legacy preserved: {preserved}")
    print("\n=== label_source distribution (rebuilt) ===")
    print(" ", dict(Counter(r["label_source"] for r in out_rows)))
    print("=== mangabeira fp_subtype (rebuilt) ===")
    print(" ", dict(Counter(r["fp_subtype"] for r in out_rows
                            if r["camera"] == "cam_mangabeira" and r["category"] == "fp")))

    target = (OFFICIAL / "manifest.rebuilt.csv") if args.dry_run else MANIFEST
    if args.apply:
        from datetime import datetime
        bak = MANIFEST.with_suffix(f".csv.bak-{datetime.now():%Y%m%d}")
        shutil.copy2(MANIFEST, bak)
        print(f"\nBackup -> {bak}")
    with target.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        w.writerows(out_rows)
    print(f"WROTE -> {target}  ({'dry-run, master untouched' if args.dry_run else 'MASTER OVERWRITTEN'})")


if __name__ == "__main__":
    main()
