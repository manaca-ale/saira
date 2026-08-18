#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Auditoria de fidelidade: prod real (DB) vs benchmark (braço current), por TP."""
import csv, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
CAMP = Path(__file__).resolve().parents[1]

corpus = {r["id"][:8]: r for r in csv.DictReader((CAMP/".tmp"/"corpus_picam001.csv").open(encoding="utf-8"))
          if r["status"] == "CONFIRMADO"}
bench = [r for r in csv.DictReader((CAMP/"results"/"bench_picam_g3.csv").open(encoding="utf-8"))
         if r["arm"] == "current" and r["category"] == "tp"]

bydet = {}
for r in bench:
    bydet.setdefault(r["det_id"][:8], []).append(r)

print(f"{'det':10}{'prod_a1conf':>12}{'prod_a2disp':>12}{'bench_gmax':>11}{'bench_fired':>12}{'bench_disp':>11}")
mism = 0
for d, rows in sorted(bydet.items()):
    c = corpus.get(d, {})
    gmax = max((int(r["gate_conf"]) for r in rows if r["gate_conf"] not in ("", "None")), default=-1)
    fired = any(str(r["gate_fire"]) == "1" for r in rows)
    disp = any(str(r["disposal"]) == "1" for r in rows)
    prod_disp = c.get("agent2_disposal", "?")
    flag = "" if disp else "  <-- bench MISS"
    if not disp:
        mism += 1
    print(f"{d:10}{str(c.get('agent1_confidence','?')):>12}{str(prod_disp):>12}{gmax:>11}{str(fired):>12}{str(disp):>11}{flag}")
print(f"\nprod: TODOS são CONFIRMADO (viraram detecção => gate disparou + detail confirmou em prod).")
print(f"bench current reproduz disposal em {len(bydet)-mism}/{len(bydet)} detecções TP.")
