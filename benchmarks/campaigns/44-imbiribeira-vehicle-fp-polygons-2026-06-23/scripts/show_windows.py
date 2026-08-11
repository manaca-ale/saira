#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Show the EXACT gate window (first + 3 mid + last) the benchmark fed per event, and the
false negatives (disposals NOT triggered) per arm across the 3 reps.

Mirrors bench_vehicle_gate.load_events + _mid exactly (frames = sorted *.jpg on disk).
"""
import csv
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CAMP = Path(__file__).resolve().parents[1]
DATASET = Path(r"c:\saira\data\datasets\official")


def _mid(frames):
    n = len(frames)
    if n < 5:
        return frames[1:-1]
    picked = []
    for idx in [int(n * 0.25), int(n * 0.5), int(n * 0.75)]:
        idx = max(1, min(n - 2, idx))
        if idx not in picked:
            picked.append(idx)
    return [frames[i] for i in picked]


def window(frames):
    """first + mid(3) + last -> the 5 frames the gate actually saw."""
    if len(frames) < 2:
        return frames
    return [frames[0]] + _mid(frames) + [frames[-1]]


def ts(name):
    import re
    m = re.search(r"(\d{2})-(\d{2})-(\d{2})\.jpg$", name)
    return f"{m[1]}:{m[2]}:{m[3]}" if m else name


# load manifest rows (imbiribeira tp+fp), map to frame dirs
rows = [r for r in csv.DictReader((DATASET / "manifest.csv").open(encoding="utf-8"))
        if r.get("camera") == "cam_imbiribeira" and r.get("category") in ("tp", "fp")]
lab = json.loads((CAMP / "labeling" / "tp_labels.json").read_text(encoding="utf-8"))
veh = {e["event_id"][:8]: e.get("vehicle_present") for e in lab["events"]}

# 3-rep trigger per arm
reps = [json.loads((CAMP / ".tmp" / f"rep{i}.json").read_text(encoding="utf-8")) for i in (1, 2, 3)]
arms = list(reps[0]["results"].keys())


def trig_count(eid8, arm):
    return sum(1 for r in reps if next((x for x in r["results"][arm] if x["id"] == eid8), {}).get("gate", {}).get("triggered"))


out = []
for r in rows:
    fr = sorted((DATASET / r["local_path"] / "frames").glob("*.jpg"))
    if len(fr) < 2:
        continue
    win = window([p.name for p in fr])
    eid8 = r["event_id"][:8]
    rec = {"event_id": eid8, "label": r["category"].upper(),
           "vehicle": veh.get(eid8), "n_frames": len(fr),
           "window": win}
    if r["category"] == "tp":
        rec["catch"] = {a: f"{trig_count(eid8, a)}/3" for a in arms}
    out.append(rec)

(CAMP / "results" / "test_windows.json").write_text(
    json.dumps({"note": "window = first + 3 mid + last (gate input); catch = triggers across 3 reps",
                "arms": arms, "events": out}, ensure_ascii=False, indent=2), encoding="utf-8")

# ---- print TP windows + catch ----
tps = [r for r in out if r["label"] == "TP"]
print(f"=== {len(tps)} DISPARES TP — janela de 5 frames + capturas (3 reps) ===\n")
short = [a.replace("_vehicle", "").replace("A_baseline", "A_base") for a in arms]
print(f"{'event':9s} {'veh':3s} {'nfr':>3s}  {'janela (timestamps: 1º·m·m·m·últ)':38s} " + " ".join(f"{s:>9s}" for s in short))
for r in sorted(tps, key=lambda x: (x["vehicle"] is not True, x["event_id"])):
    wts = "·".join(ts(n) for n in r["window"])
    vh = "V" if r["vehicle"] is True else ("-" if r["vehicle"] is False else "?")
    catches = " ".join(f"{r['catch'][a]:>9s}" for a in arms)
    print(f"{r['event_id']:9s} {vh:^3s} {r['n_frames']:>3d}  {wts:38s} {catches}")

# ---- false negatives ----
print("\n=== FALSOS NEGATIVOS (descartes NÃO identificados) ===")
for a in arms:
    fn = [r["event_id"] for r in tps if r["catch"][a] == "0/3"]
    fn_v = [r["event_id"] for r in tps if r["catch"][a] == "0/3" and r["vehicle"] is True]
    print(f"  {a:20s}: {len(fn)}/20 nunca dispararam (3/3 miss) — veículo: {fn_v}")
never = [r["event_id"] for r in tps if all(r["catch"][a] == "0/3" for a in arms)]
print(f"\n  Inalcançável por QUALQUER arm (0/3 em todos): {never}")
print(f"\n-> janelas completas (todos os 167 eventos, incl. FP) em results/test_windows.json")
