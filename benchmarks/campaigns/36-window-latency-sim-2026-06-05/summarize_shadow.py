#!/usr/bin/env python3
"""Camp 36 — summarize the live sliding-window SHADOW audit (FP/h, cost, suppression).

Pull the jsonl first, e.g.:
  scp -r saira-prod:/tmp/sliding_shadow_audit ./shadow_pull   # (docker cp from worker first)
then:
  python -X utf8 summarize_shadow.py ./shadow_pull

Compares the sliding arm against the live fixed pipeline (cascade_audit) when both dirs
are given:  python summarize_shadow.py ./shadow_pull --cascade ./cascade_pull
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def _read_jsonl(root: Path):
    for p in sorted(root.rglob("*.jsonl")):
        device = p.stem
        day = p.parent.name
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield day, device, json.loads(line)
            except Exception:
                continue


def summarize_sliding(root: Path):
    by = defaultdict(lambda: {"n": 0, "suppressed": 0, "gate_ran": 0, "gate_trig": 0,
                              "confirm": 0, "coalesced_fp": 0, "cost": 0.0})
    for day, device, r in _read_jsonl(root):
        k = (day, device)
        s = by[k]
        s["n"] += 1
        s["suppressed"] += int(r.get("bgsub_suppressed", False))
        s["gate_ran"] += int(r.get("gate_ran", False))
        s["gate_trig"] += int(r.get("gate_triggered", False))
        s["confirm"] += int(r.get("would_confirm", False))
        s["coalesced_fp"] += int(r.get("is_coalesced_new_fp", False))
        s["cost"] += float(r.get("gate_cost_usd", 0.0)) + float(r.get("detail_cost_usd", 0.0))
    print(f"{'day/device':22} {'wins':6} {'suppr%':7} {'gTrig':6} {'confirm':8} {'coalFP':7} {'cost$':8}")
    for (day, device), s in sorted(by.items()):
        sup = 100 * s["suppressed"] / s["n"] if s["n"] else 0
        print(f"{day+'/'+device:22} {s['n']:<6} {sup:<7.0f} {s['gate_trig']:<6} "
              f"{s['confirm']:<8} {s['coalesced_fp']:<7} {round(s['cost'],4)}")
    return by


def summarize_cascade(root: Path):
    """Fixed-pipeline confirmations from cascade_audit (FP if no real disposal)."""
    by = defaultdict(lambda: {"windows": 0, "disposal": 0})
    for day, device, r in _read_jsonl(root):
        s = by[(day, device)]
        s["windows"] += 1
        s["disposal"] += int(r.get("agent2_disposal") is True)
    print(f"\n{'[FIXED] day/device':22} {'windows':8} {'disposal(confirm)':18}")
    for (day, device), s in sorted(by.items()):
        print(f"{day+'/'+device:22} {s['windows']:<8} {s['disposal']}")
    return by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sliding_dir")
    ap.add_argument("--cascade", default=None)
    args = ap.parse_args()
    print("=== SLIDING SHADOW (arm B) ===")
    summarize_sliding(Path(args.sliding_dir))
    if args.cascade:
        print("\n=== FIXED PIPELINE (arm A, live) ===")
        summarize_cascade(Path(args.cascade))
    print("\nNote: a 'confirm' on a no-disposal period = FP. Real disposals are the CONFIRMADO "
          "rows in the DB — join with detections to separate TP from FP per arm.")


if __name__ == "__main__":
    main()
