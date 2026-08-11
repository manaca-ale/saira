#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Campaign 40 Phase D — post-filter + Pareto (corrected).

Base = baseline E+CROPS preds (phase_c). DINOv2 veto (CON->REJ if p_con<thr,
phase_b out-of-fold). CV permanence veto. Variants standalone. Bootstrap CI.
Recall floor 11/13. Reports per-event named TP losses.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(r"c:\saira")
sys.stdout.reconfigure(encoding="utf-8")
RES = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "results"
FLOOR = 11
RNG = np.random.default_rng(7)

pc = json.loads((RES / "phase_c_variant_results.json").read_text(encoding="utf-8"))
base = {p["event_id"]: p for p in pc["baseline"]}
v1 = {p["event_id"]: p["pred"] for p in pc["V1"]}
v2 = {p["event_id"]: p["pred"] for p in pc["V2"]}
dino = {r["event_id"]: float(r["p_con_oof"])
        for r in csv.DictReader((RES / "phase_b_dinov2.csv").open(encoding="utf-8"))}
perm = {r["event_id"]: float(r["permanence"])
        for r in csv.DictReader((RES / "phase_a_signals.csv").open(encoding="utf-8"))}
TP = [e for e in base if base[e]["bucket"] == "TP"]
B3 = [e for e in base if base[e]["bucket"] == "B3"]


def evalrule(pred):
    """pred: event_id -> bool(CON). returns recall, b3fp."""
    return sum(pred(e) for e in TP), sum(pred(e) for e in B3)


def dino_veto(thr):
    return lambda e: base[e]["pred"] == "CON" and dino.get(e, 1.0) >= thr


def perm_veto(thr):
    return lambda e: base[e]["pred"] == "CON" and perm.get(e, 1e9) >= thr


def best_thr(scoremap, mkveto):
    best = None
    for thr in sorted(set(scoremap.values())):
        r, f = evalrule(mkveto(thr))
        if r >= FLOOR and (best is None or f < best[2]):
            best = (thr, r, f)
    return best


def boot(pred):
    s, rc = [], []
    for _ in range(10000):
        bi = RNG.integers(0, len(B3), len(B3))
        ti = RNG.integers(0, len(TP), len(TP))
        s.append(sum(not pred(B3[i]) for i in bi) / len(B3) * 100)
        rc.append(sum(pred(TP[i]) for i in ti))
    return np.percentile(s, [2.5, 50, 97.5]), np.percentile(rc, [2.5, 50, 97.5])


rules = []
rules.append(("baseline E+CROPS", lambda e: base[e]["pred"] == "CON", None))

# DINOv2: recall-safe point (max recall) and floor point
d_safe = best_thr(dino, dino_veto)  # minimizes FP at recall>=11; report also recall-12 pt
# recall-12 point: highest thr keeping recall==max
r12 = None
for thr in sorted(set(dino.values())):
    r, f = evalrule(dino_veto(thr))
    if r >= 12 and (r12 is None or f < r12[2]):
        r12 = (thr, r, f)
if r12:
    rules.append((f"D2 DINOv2 veto (p_con>={r12[0]:.3f}) recall-safe", dino_veto(r12[0]), r12[0]))
if d_safe and (not r12 or d_safe[0] != r12[0]):
    rules.append((f"D2' DINOv2 veto (p_con>={d_safe[0]:.3f}) @floor", dino_veto(d_safe[0]), d_safe[0]))

p_best = best_thr(perm, perm_veto)
if p_best:
    rules.append((f"D1 CV permanence (>={p_best[0]:.0f})", perm_veto(p_best[0]), None))

rules.append(("D5 V1 prompt standalone", lambda e: v1.get(e, base[e]["pred"]) == "CON", None))
rules.append(("D5 V2 prompt standalone", lambda e: v2.get(e, base[e]["pred"]) == "CON", None))
if r12:
    rules.append(("D6 V1 + DINOv2 veto",
                  lambda e: v1.get(e) == "CON" and dino.get(e, 1) >= r12[0], None))

print(f"{'regra':40s} {'recall':>7s} {'B3-FP':>7s} {'B3-supr (95%CI)':>22s} {'rec(CI)':>10s}")
print("-" * 95)
out = []
for name, pred, thr in rules:
    r, f = evalrule(pred)
    supp = len(B3) - f
    ci_s, ci_r = boot(pred)
    ok = "OK" if r >= FLOOR else "FAIL"
    print(f"{name:40s} {r:>3d}/13  {f:>3d}/20  {supp:>3d}/20 {100*supp/len(B3):>3.0f}% "
          f"[{ci_s[0]:.0f},{ci_s[2]:.0f}]  {ci_r[1]:.0f}[{ci_r[0]:.0f},{ci_r[2]:.0f}] {ok}")
    lost = [e[:10] for e in TP if not pred(e)]
    out.append({"rule": name, "recall": r, "b3_fp": f, "b3_supp": supp,
                "supp_pct": round(100 * supp / len(B3)),
                "supp_ci": f"[{ci_s[0]:.0f},{ci_s[2]:.0f}]",
                "recall_ci": f"[{ci_r[0]:.0f},{ci_r[2]:.0f}]",
                "tp_lost": ";".join(lost), "ok": ok})

with (RES / "phase_d_pareto.csv").open("w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
    w.writeheader(); w.writerows(out)
print("\nTP perdido baseline:", [e[:10] for e in TP if base[e]["pred"] != "CON"])
