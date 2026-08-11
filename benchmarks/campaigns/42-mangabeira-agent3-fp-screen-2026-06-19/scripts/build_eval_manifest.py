#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build the screener eval manifest by combining:
  - GOLD labels (human validity_comment buckets) from corpus_bucketed.csv
  - SILVER labels (2-vote vision workflow) from vision_labels.json

Mapping to gold decision:
  real_deposit                 -> keep   (true positive, recall guard)
  revira_explicit / revira_mexe-> kill   (PRIMARY false-positive target)
  passante_parado              -> kill   (secondary target)
  empty_other                  -> kill   (false positive, non-focus)
  generic_no_disposal/no_comment with vision label -> use vision label
  uncertain                    -> EXCLUDED from metrics (written to a side file)

Output: eval_manifest.csv (event_id, gold, subtype, label_source, frames_dir)
        excluded_uncertain.csv
"""
import csv
import json
from pathlib import Path

CAMP = Path(__file__).resolve().parents[1]
ROOT = Path(r"c:\saira")
BUCKETED = ROOT / ".tmp" / "corpus_bucketed.csv"
VISION = CAMP / "vision_labels.json"          # workflow result {results:[{id, final_label,...}]}
FRAMES = ROOT / ".tmp" / "revira_stage" / "frames"

KILL = {"revira_explicit", "revira_mexe", "passante_parado", "empty_other"}
KEEP = {"real_deposit"}


def gold_from_label(label: str):
    if label in KEEP:
        return "keep"
    if label in KILL:
        return "kill"
    return None  # uncertain / unknown


def main():
    bucket = {r["id"]: r for r in csv.DictReader(BUCKETED.open(encoding="utf-8"))}

    vision = {}
    if VISION.exists():
        data = json.loads(VISION.read_text(encoding="utf-8"))
        for r in data.get("results", []):
            vision[r["id"]] = r

    rows, excluded = [], []
    for eid, b in bucket.items():
        bkt = b["bucket"]
        if bkt in ("generic_no_disposal", "no_comment"):
            v = vision.get(eid)
            if not v:
                excluded.append({"event_id": eid, "reason": "no_vision_label", "bucket": bkt})
                continue
            label = v["final_label"]
            # These events were REJEITADO by the human operator (authority). Vision
            # is used ONLY to assign the FP subtype. If vision instead claims a real
            # deposit, that contradicts the human reject -> contested, exclude it
            # (don't let 4 disputed events skew TP-preservation either way).
            if label == "real_deposit":
                excluded.append({"event_id": eid, "reason": "vision_contested_deposit_on_rejeitado", "bucket": bkt})
                continue
            if label == "uncertain":
                excluded.append({"event_id": eid, "reason": "vision_uncertain", "bucket": bkt})
                continue
            subtype = label  # revira_mexe | passante_parado | empty_other
            source = "vision_2vote" if v.get("agree") else "vision_disagree"
            gold = "kill"
        else:
            # gold human-comment bucket
            label = bkt
            subtype = bkt
            source = "comment"
            gold = gold_from_label(label)
            if gold is None:
                excluded.append({"event_id": eid, "reason": f"bucket_{bkt}", "bucket": bkt})
                continue
        fdir = FRAMES / eid
        if not fdir.exists() or not any(fdir.glob("*.jpg")):
            excluded.append({"event_id": eid, "reason": "no_frames", "bucket": bkt})
            continue
        rows.append({"event_id": eid, "gold": gold, "subtype": subtype,
                     "label_source": source, "frames_dir": str(fdir).replace("\\", "/")})

    out = CAMP / "eval_manifest.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "gold", "subtype", "label_source", "frames_dir"])
        w.writeheader(); w.writerows(rows)
    exc = CAMP / "excluded_uncertain.csv"
    with exc.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "reason", "bucket"])
        w.writeheader(); w.writerows(excluded)

    from collections import Counter
    print(f"eval events: {len(rows)} | excluded: {len(excluded)}")
    print("gold:", Counter(r["gold"] for r in rows))
    print("subtype:", Counter(r["subtype"] for r in rows))
    print("source:", Counter(r["label_source"] for r in rows))
    print("excluded reasons:", Counter(e["reason"] for e in excluded))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
