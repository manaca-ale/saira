#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase A — merge the pulled esp32_001 corpus into the OFFICIAL dataset.

Reads largeN/manifest.csv (from largeN_fetch.py) and writes, per NEW event,
  data/datasets/official/cam_imbiribeira/<cat>/<event_id>/{frames/*.jpg, label.json}

DEDUP: event_ids already present on disk (any of tp/fp/indefinido) are SKIPPED so the
55 curated events (incl. human indefinido calls) are preserved verbatim. Idempotent.

label.json mirrors the existing imbiribeira schema + new prod-pull fields:
  agent1_confidence, offender_present, waste_bbox, confidence_score, label_source.
`vehicle_present` is intentionally left absent (filled by Phase B manual labeling).

Adapted from benchmarks/campaigns/42-mangabeira-agent3-fp-screen-2026-06-19/scripts/merge_to_official.py
(rewritten for the imbiribeira FLAT layout; status-based category; dedup by folder).
"""
import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CAMP = Path(__file__).resolve().parents[1]
ROOT = Path(r"c:\saira")
OFFICIAL = ROOT / "data" / "datasets" / "official"
CAM = OFFICIAL / "cam_imbiribeira"

CAMERA = "cam_imbiribeira"
DEVICE = "esp32_001"
BAIRRO = "Imbiribeira"
RPA = "RPA 2"
LOGRADOURO_DEFAULT = "Rua Professor Pedro Augusto Carneiro Leão"
CLASSIF = {"tp": "Descarte", "fp": "Falso Positivo", "indefinido": "Indefinido"}
CATS = ("tp", "fp", "indefinido")


def existing_event_ids() -> set[str]:
    ids = set()
    for cat in CATS:
        d = CAM / cat
        if d.exists():
            ids.update(p.name for p in d.iterdir() if p.is_dir())
    return ids


def main():
    apply = "--apply" in sys.argv
    rows = list(csv.DictReader((CAMP / "largeN" / "manifest.csv").open(encoding="utf-8")))
    existing = existing_event_ids()
    print(f"existing official events: {len(existing)} | corpus rows: {len(rows)}")

    written, skipped = Counter(), 0
    for r in rows:
        eid = r["id"]
        cat = r["category"]
        if eid in existing:
            skipped += 1
            continue
        if cat not in CATS:
            continue
        dest = CAM / cat / eid
        fdir = dest / "frames"
        frame_paths = [Path(p) for p in (r.get("frames") or "").split("|") if p.strip()]
        frame_rel = []
        if apply:
            fdir.mkdir(parents=True, exist_ok=True)
        for src in frame_paths:
            if not src.exists() or src.stat().st_size < 1000:
                continue
            rel = f"{CAMERA}/{cat}/{eid}/frames/{src.name}"
            frame_rel.append(rel)
            if apply:
                dst = fdir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
        if not frame_rel:
            continue
        label = {
            "event_id": eid,
            "camera": CAMERA,
            "device_id": DEVICE,
            "logradouro": (r.get("logradouro") or "").strip() or LOGRADOURO_DEFAULT,
            "bairro": BAIRRO,
            "rpa": RPA,
            "datetime": r.get("created_at", ""),
            "tipo_residuo": (r.get("waste_type") or "").strip(),
            "volumetria": (r.get("volume_m3") or "").strip(),
            "classificacao": CLASSIF[cat],
            "category": cat,
            "justificativa": (r.get("validity_comment") or "").strip()
                             or (r.get("evidence_summary") or "").strip(),
            "agent1_confidence": (r.get("agent1_confidence") or "").strip(),
            "offender_present": (r.get("offender_present") or "").strip(),
            "confidence_score": (r.get("confidence_score") or "").strip(),
            "waste_bbox": (r.get("waste_bbox") or "").strip(),
            "selected_frame_name": (r.get("selected_frame_name") or "").strip(),
            "label_source": "prod_pull_44",
            "source_campaign": "44-imbiribeira-vehicle-fp-polygons",
            "frame_count": len(frame_rel),
            "frames": frame_rel,
        }
        if apply:
            (dest / "label.json").write_text(
                json.dumps(label, ensure_ascii=False, indent=2), encoding="utf-8")
        written[cat] += 1

    mode = "APPLIED" if apply else "DRY-RUN (use --apply to write)"
    print(f"[{mode}] new events written: {dict(written)} (total {sum(written.values())}) | skipped existing: {skipped}")
    print(f"projected official total: {len(existing) + sum(written.values())}")


if __name__ == "__main__":
    main()
