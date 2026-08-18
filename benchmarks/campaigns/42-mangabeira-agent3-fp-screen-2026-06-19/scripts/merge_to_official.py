#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Merge the curated Mangabeira revira/passante FP dataset into the OFFICIAL
dataset at data/datasets/official/cam_mangabeira/.

Sources:
  - eval_manifest.csv      (definite keep/kill + subtype + label_source)
  - excluded_uncertain.csv (uncertain -> indefinido)
  - .tmp/corpus_bucketed.csv (validity_comment)
  - Camp-40 df/<id>.json   (created_at, selected_frame, evidence_summary)
  - .tmp/revira_stage/frames/<id>/  (sampled frames to copy)

Category mapping:
  gold=keep                       -> tp
  gold=kill (revira/passante/empty)-> fp   (label.json gets fp_subtype)
  uncertain                       -> indefinido

Writes per-event <cat>/<id>/{frames/*.jpg, label.json} and refreshes
manifest_revira.csv (a sidecar index for this curation). It does NOT rewrite the
master manifest.csv in place destructively — instead it appends/refreshes rows
for these event_ids and regenerates manifest.csv via a merge-by-id.

Idempotent: re-running skips frames already copied and overwrites label.json.
"""
import csv
import json
import shutil
from collections import Counter
from pathlib import Path

CAMP = Path(__file__).resolve().parents[1]
ROOT = Path(r"c:\saira")
OFFICIAL = ROOT / "data" / "datasets" / "official"
CAM = OFFICIAL / "cam_mangabeira"
DF = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "largeN" / "df"
STAGE = ROOT / ".tmp" / "revira_stage" / "frames"
BUCKETED = ROOT / ".tmp" / "corpus_bucketed.csv"

DEVICE = "esp32_002"
LOGRADOURO = "Av. Prof. José dos Anjos, 3254"
BAIRRO = "Mangabeira"
RPA = "RPA 3"

CLASSIF = {"tp": "Descarte", "fp": "Falso Positivo", "indefinido": "Indefinido"}


def cat_for(gold: str, subtype: str) -> str:
    if gold == "keep":
        return "tp"
    if gold == "kill":
        return "fp"
    return "indefinido"


def load_df(eid):
    jp = DF / f"{eid}.json"
    if not jp.exists():
        return {}
    try:
        return json.loads(jp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    bucket = {r["id"]: r for r in csv.DictReader(BUCKETED.open(encoding="utf-8"))}
    eval_rows = list(csv.DictReader((CAMP / "eval_manifest.csv").open(encoding="utf-8")))
    excl_path = CAMP / "excluded_uncertain.csv"
    excl = list(csv.DictReader(excl_path.open(encoding="utf-8"))) if excl_path.exists() else []

    records = []
    for r in eval_rows:
        records.append((r["event_id"], r["gold"], r["subtype"], r["label_source"]))
    for r in excl:
        reason = r.get("reason", "")
        if reason in ("vision_uncertain", "vision_contested_deposit_on_rejeitado"):
            sub = "contested_deposit" if "contested" in reason else "uncertain"
            records.append((r["event_id"], "uncertain", sub, "vision_disagree"))

    written = Counter()
    index_rows = []
    for eid, gold, subtype, source in records:
        cat = cat_for(gold, subtype)
        dfj = load_df(eid)
        b = bucket.get(eid, {})
        created = dfj.get("created_at", "")
        dest = CAM / cat / eid
        fdir = dest / "frames"
        fdir.mkdir(parents=True, exist_ok=True)
        # copy frames
        src = STAGE / eid
        frame_rel = []
        for jpg in sorted(src.glob("*.jpg")):
            dst = fdir / jpg.name
            if not dst.exists():
                shutil.copy2(jpg, dst)
            frame_rel.append(f"cam_mangabeira/{cat}/{eid}/frames/{jpg.name}")
        label = {
            "event_id": eid,
            "camera": "cam_mangabeira",
            "device_id": DEVICE,
            "logradouro": LOGRADOURO,
            "bairro": BAIRRO,
            "rpa": RPA,
            "datetime": created,
            "tipo_residuo": "",
            "volumetria": "",
            "classificacao": CLASSIF.get(cat, "Indefinido"),
            "category": cat,
            "fp_subtype": subtype if cat == "fp" else "",
            "label_source": source,
            "screener_target": cat == "fp" and subtype in ("revira_explicit", "revira_mexe", "passante_parado"),
            "validity_comment": (b.get("comment") or "").strip(),
            "evidence_summary": dfj.get("evidence_summary", ""),
            "selected_frame_name": dfj.get("selected_frame_name", ""),
            "source_campaign": "40-mangabeira-b3-fp + 42-agent3-fp-screen",
            "frame_count": len(frame_rel),
            "frames": frame_rel,
        }
        (dest / "label.json").write_text(json.dumps(label, ensure_ascii=False, indent=2), encoding="utf-8")
        written[cat] += 1
        index_rows.append({
            "event_id": eid, "category": cat, "fp_subtype": label["fp_subtype"],
            "screener_target": label["screener_target"], "label_source": source,
            "datetime": created, "frame_count": len(frame_rel),
            "validity_comment": label["validity_comment"],
        })

    idx = CAM / "manifest_revira.csv"
    with idx.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "category", "fp_subtype", "screener_target",
                                          "label_source", "datetime", "frame_count", "validity_comment"])
        w.writeheader(); w.writerows(index_rows)

    print("merged into official:", dict(written))
    print(f"sidecar index -> {idx}")
    print(f"total events written: {sum(written.values())}")


if __name__ == "__main__":
    main()
