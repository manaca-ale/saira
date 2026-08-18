#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase D.1 — vehicle split: how many TPs really have a vehicle, and what a
vehicle-required gate would cost/save.

Ground truth for TP vehicle presence = manual labels (labeling/tp_labels.json, Phase B).
For FP vehicle presence we only have the MODEL's `vehicle_stopped` (no manual FP labels),
read from the benchmark results.json (arm A_baseline) — flagged model-derived.

Reports:
  - TP: with-vehicle vs without (manual)  -> hard bound: a vehicle-REQUIRED gate loses
    every no-vehicle TP. recall_ceiling_hard = tp_with_vehicle / tp_total.
  - FP: with-vehicle vs without (model)    -> fp_without_vehicle ≈ FP avoidable.
  - reliability: manual vs model vehicle_stopped on the TP set.
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CAMP = Path(__file__).resolve().parents[1]
RES = CAMP / "results"
RES.mkdir(parents=True, exist_ok=True)


def short(eid):
    return eid[:8]


def main():
    tp_lab_path = CAMP / "labeling" / "tp_labels.json"
    res_path = CAMP / "results.json"
    if not res_path.exists():
        print("ERR results.json not found — run bench_vehicle_gate.py first.")
        return 1
    res = json.loads(res_path.read_text(encoding="utf-8"))
    base = res.get("results", {}).get("A_baseline", [])
    model_veh = {short(r["id"]): r["gate"].get("vehicle_stopped") for r in base}
    model_label = {short(r["id"]): r["label"] for r in base}

    manual = {}
    if tp_lab_path.exists():
        d = json.loads(tp_lab_path.read_text(encoding="utf-8"))
        for e in d.get("events", []):
            manual[short(e["event_id"])] = e.get("vehicle_present")
    else:
        print("WARN labeling/tp_labels.json not found — TP vehicle GT missing; "
              "reporting MODEL vehicle_stopped only.")

    tp_ids = [i for i, l in model_label.items() if l == "TP"]
    fp_ids = [i for i, l in model_label.items() if l == "FP"]

    # TP vehicle (manual GT, fallback to model if unlabeled)
    tp_manual = [v for i in tp_ids if (v := manual.get(i)) is not None]
    tp_with = sum(1 for v in tp_manual if v is True)
    tp_without = sum(1 for v in tp_manual if v is False)
    tp_unlabeled = len(tp_ids) - len(tp_manual)
    recall_ceiling = (tp_with / len(tp_manual)) if tp_manual else None

    # FP vehicle (model-derived)
    fp_veh_model = [model_veh.get(i) for i in fp_ids]
    fp_with = sum(1 for v in fp_veh_model if v is True)
    fp_without = sum(1 for v in fp_veh_model if v is False)

    # reliability: manual vs model on TPs
    agree = sum(1 for i in tp_ids if manual.get(i) is not None and manual.get(i) == model_veh.get(i))
    comparable = sum(1 for i in tp_ids if manual.get(i) is not None and model_veh.get(i) is not None)

    out = {
        "tp_total": len(tp_ids),
        "tp_labeled_manual": len(tp_manual), "tp_unlabeled": tp_unlabeled,
        "tp_with_vehicle_manual": tp_with, "tp_without_vehicle_manual": tp_without,
        "recall_ceiling_hard_gate": recall_ceiling,
        "fp_total": len(fp_ids),
        "fp_with_vehicle_model": fp_with, "fp_without_vehicle_model": fp_without,
        "fp_avoidable_no_vehicle_approx": fp_without,
        "model_vs_manual_agree_tp": f"{agree}/{comparable}",
        "note": "TP vehicle = MANUAL GT (Phase B). FP vehicle = MODEL vehicle_stopped (no manual FP labels).",
    }
    (RES / "vehicle_split.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== VEHICLE SPLIT (esp32_001 Imbiribeira) ===")
    print(f"TPs total {len(tp_ids)} | labeled manual {len(tp_manual)} (unlabeled {tp_unlabeled})")
    if tp_manual:
        print(f"  with vehicle:    {tp_with}/{len(tp_manual)}")
        print(f"  without vehicle: {tp_without}/{len(tp_manual)}  <- LOST by a vehicle-required gate")
        print(f"  => recall ceiling of HARD gate: {recall_ceiling*100:.0f}%")
    print(f"FPs total {len(fp_ids)} (vehicle via MODEL):")
    print(f"  with vehicle:    {fp_with}/{len(fp_ids)}")
    print(f"  without vehicle: {fp_without}/{len(fp_ids)}  <- FP avoidable by requiring a vehicle (approx)")
    print(f"model vs manual vehicle agreement on TPs: {agree}/{comparable}")
    print(f"-> {RES/'vehicle_split.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
