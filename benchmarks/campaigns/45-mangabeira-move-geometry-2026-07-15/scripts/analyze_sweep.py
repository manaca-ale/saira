#!/usr/bin/env python3
"""Camp 45 — leitura do sweep: trade-off por zona + delay de detecção."""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent.parent
RES = HERE / "results"

agg = json.loads((RES / "sweep_45.json").read_text(encoding="utf-8"))

# 1. melhor config (0 CONF perdidas) por zona, maximizando REJ mortas
print("=== melhor operating point por ARM (0/12 CONF perdidas) ===")
print(f"{'arm':20}{'min_px':>7}{'mf':>6}{'thr':>7}{'REJ†':>10}{'NEG jan':>10}{'TRIG jan':>10}")
best_by_arm = {}
for a in agg:
    if a["conf_det_lost"] != 0 or a["conf_det_n"] == 0:
        continue
    arm = a["arm"]
    key = (a["rej_det_killed"], -a["thr"])  # mais REJ, desempata por thr menor
    if arm not in best_by_arm or key > best_by_arm[arm][0]:
        best_by_arm[arm] = (key, a)
for arm in sorted(best_by_arm):
    a = best_by_arm[arm][1]
    print(f"{arm:20}{a['min_px']:>7}{a['mf']:>6.2f}{a['thr']:>7}"
          f"{a['rej_det_killed']:>4}/{a['rej_det_n']:<4}({a['rej_det_killed']/a['rej_det_n']:>3.0%})"
          f"{a['neg_sup']:>4}/{a['neg_n']:<4}({a['neg_sup']/a['neg_n']:>3.0%})"
          f"{a['trig_nolabel_sup']:>4}/{a['trig_nolabel_n']:<4}")

# 2. a zona proposed no MESMO ponto que a melhor current (comparação justa de NEG)
print("\n=== por que a zona importa: NEG suprimidas (custo) vs REJ mortas no mesmo mf/thr ===")
by_cfg = {(a["arm"], a["min_px"], a["mf"], a["thr"]): a for a in agg}
for mp, mf, thr in [(800, 0.30, 50), (400, 0.20, 400), (200, 0.20, 1000)]:
    print(f"  min_px={mp} mf={mf} thr={thr}:")
    for arm in ("prod/current", "prod/proposed", "prod/proposed_tight",
                "fresh/current", "fresh/proposed"):
        a = by_cfg.get((arm, mp, mf, thr))
        if not a:
            continue
        print(f"    {arm:22} CONF perdidas {a['conf_det_lost']}/{a['conf_det_n']} | "
              f"REJ {a['rej_det_killed']}/{a['rej_det_n']} ({a['rej_det_killed']/max(1,a['rej_det_n']):.0%}) | "
              f"NEG {a['neg_sup']}/{a['neg_n']} ({a['neg_sup']/max(1,a['neg_n']):.0%})")

# 3. custo: qual config maximiza NEG suprimidas (redução de chamadas de gate) com 0 CONF perdidas
print("\n=== top por NEG suprimidas (proxy de reducao de custo do gate), 0 CONF perdidas ===")
safe = [a for a in agg if a["conf_det_lost"] == 0 and a["conf_det_n"] > 0]
safe.sort(key=lambda a: -a["neg_sup"] / max(1, a["neg_n"]))
for a in safe[:8]:
    print(f"  {a['arm']:20} min_px={a['min_px']:>4} mf={a['mf']:.2f} thr={a['thr']:>5} | "
          f"NEG {a['neg_sup']}/{a['neg_n']} ({a['neg_sup']/a['neg_n']:.0%}) | "
          f"REJ {a['rej_det_killed']}/{a['rej_det_n']} ({a['rej_det_killed']/max(1,a['rej_det_n']):.0%})")

# 4. delay: para a config recomendada, quantas janelas até a 1ª que passa (por CONF)
print("\n=== delay de deteccao: janelas suprimidas antes da 1a que passa (por CONF) ===")
import argparse
ap = argparse.ArgumentParser()
ap.add_argument("--arm", default="prod/current")
ap.add_argument("--min_px", type=int, default=800)
ap.add_argument("--mf", type=float, default=0.30)
ap.add_argument("--thr", type=int, default=50)
args, _ = ap.parse_known_args()

rows = list(csv.DictReader((RES / "sweep_windows.csv").open(encoding="utf-8")))
by_det = defaultdict(list)
for r in rows:
    if (r["arm"] == args.arm and int(r["min_px"]) == args.min_px
            and abs(float(r["mf"]) - args.mf) < 1e-9 and r["label"] == "CONF" and r["det_id8"]):
        by_det[r["det_id8"]].append(r)
print(f"config: {args.arm} min_px={args.min_px} mf={args.mf} thr={args.thr}")
for det, items in sorted(by_det.items()):
    items.sort(key=lambda r: r["request_id"])
    supp = [int(r["persistence"]) < args.thr for r in items]
    n_before = 0
    for s in supp:
        if s:
            n_before += 1
        else:
            break
    status = "TODAS suprimidas (PERDE)" if all(supp) else (
        f"{n_before} janela(s) atrasada(s)" if n_before else "passa na 1a")
    print(f"  {det}: {len(items)} janela(s), persist={[int(r['persistence']) for r in items]} -> {status}")
