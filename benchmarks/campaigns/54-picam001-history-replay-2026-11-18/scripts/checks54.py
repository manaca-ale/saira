#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — conferencias de uma pergunta do Decisions usada como filtro (sem custo de API).

Para --qset e --key imprime, no conjunto de desenvolvimento:
  1. as deteccoes confirmadas de nota mais baixa (nota da deteccao = maior nota entre os eventos dela);
  2. limiares fixos aplicados a cada metade do desenvolvimento (mesma divisao A/B do agg_funnel54);
  3. a parcela dos eventos sem disparo (S0) com nota alta (candidatos a despejo que o gate de hoje nao viu);
  4. com --other, a mesma pergunta medida em outro pedido (a resposta depende das vizinhas do pedido).

Uso: python checks54.py --qset q5 --key wl_v2 --grid 0.30,0.35 --other q4
"""
from __future__ import annotations

import argparse
import statistics
from collections import defaultdict

from agg_dgate54 import wilson
from agg_funnel54 import load


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qset", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--grid", default="0.22,0.25")
    ap.add_argument("--other", default="")
    ap.add_argument("--res", default="low")
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--from-day", default="2026-07-14")
    ap.add_argument("--to-day", default="2026-12-31")
    a = ap.parse_args()
    _, _, rows, _ = load(a)
    sc = {r["id"]: r["p"][a.key] for r in rows}

    best = {}
    for r in rows:
        if r["s"] == "S2C" and (r["det"] not in best or sc[r["id"]] > best[r["det"]][0]):
            best[r["det"]] = (sc[r["id"]], r["id"], r["n"], r["half"])
    print(f"qset={a.qset} pergunta={a.key} | {len(best)} deteccoes confirmadas; as 8 de nota mais baixa:")
    for det, (s, ev, n, h) in sorted(best.items(), key=lambda kv: kv[1][0])[:8]:
        print(f"  {s:.3f}  {ev}  frames={n}  metade={h}")

    print("\nlimiar fixo por metade (S0 que passa; deteccoes confirmadas mantidas):")
    for t in [float(x) for x in a.grid.split(",")]:
        parts = []
        for h in ("A", "B"):
            s0 = [r for r in rows if r["s"] == "S0" and r["half"] == h]
            k = sum(sc[r["id"]] >= t for r in s0)
            dets = [v for v in best.values() if v[3] == h]
            parts.append(f"{h}: S0 {k}/{len(s0)} = {100 * k / len(s0):.1f}%, confirmadas "
                         f"{sum(v[0] >= t for v in dets)}/{len(dets)}")
        print(f"  limiar {t:.2f} | " + " | ".join(parts))

    s0 = [sc[r["id"]] for r in rows if r["s"] == "S0"]
    print("\neventos sem disparo (S0) com nota alta:")
    for t in (0.7, 0.8, 0.9):
        k = sum(x >= t for x in s0)
        lo, hi = wilson(k, len(s0))
        print(f"  nota >= {t}: {k}/{len(s0)} = {100 * k / len(s0):.2f}% [{100 * lo:.2f} a {100 * hi:.2f}]")

    if a.other:
        b = argparse.Namespace(**{**vars(a), "qset": a.other})
        _, _, rows2, _ = load(b)
        sc2 = {r["id"]: r["p"][a.key] for r in rows2 if a.key in r["p"]}
        d = sorted(abs(sc[i] - sc2[i]) for i in sc if i in sc2)
        by = defaultdict(list)
        for r in rows:
            if r["id"] in sc2:
                by[r["s"]].append(sc[r["id"]] - sc2[r["id"]])
        print(f"\nmesma pergunta em {a.qset} e em {a.other} ({len(d)} eventos): |diferenca| mediana "
              f"{statistics.median(d):.3f}, p90 {d[int(0.9 * len(d))]:.3f}, maxima {d[-1]:.3f}")
        print("  diferenca media por estrato: " + ", ".join(f"{s} {statistics.mean(v):+.3f}" for s, v in sorted(by.items())))


if __name__ == "__main__":
    main()
