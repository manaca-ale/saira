#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — a nota do Decisions muda de um dia para o outro? Compara duas repeticoes do mesmo conjunto
de perguntas nos mesmos eventos (mesmos 5 frames): correlacao, diferenca absoluta, trocas de lado no
limiar e deteccoes confirmadas mantidas em cada repeticao.

Uso: python cmp_dgate54.py --qset q5 --q wl_v2 --thr 0.30 [--a 1 --b 2]
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict

from agg_dgate54 import RESULTS, probs


def load(qset, res, rep):
    out = {}
    for line in (RESULTS / f"dgate54__{qset}_gate5_{res}__r{rep}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error") and r.get("answers"):
                out[r["event_id"]] = r
    return out


def sub_of(r):
    if r["estrato"] != "S2":
        return r["estrato"]
    return {"CONFIRMADO": "S2C", "REJEITADO": "S2R"}.get(r["status"], "S2X")


def pearson(x, y):
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sx = sum((a - mx) ** 2 for a in x) ** 0.5
    sy = sum((b - my) ** 2 for b in y) ** 0.5
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qset", default="q5")
    ap.add_argument("--q", default="wl_v2")
    ap.add_argument("--res", default="low")
    ap.add_argument("--thr", type=float, default=0.30)
    ap.add_argument("--a", type=int, default=1)
    ap.add_argument("--b", type=int, default=2)
    a = ap.parse_args()
    A, B = load(a.qset, a.res, a.a), load(a.qset, a.res, a.b)
    ids = [i for i in B if i in A and A[i]["split"] == "dev"]
    rows = [(sub_of(A[i]), A[i]["detection_id"] or i, probs(A[i])[a.q], probs(B[i])[a.q], i) for i in ids]
    x, y = [r[2] for r in rows], [r[3] for r in rows]
    d = sorted(abs(p - q) for p, q in zip(x, y))
    print(f"qset={a.qset} pergunta={a.q} r{a.a} ({A[ids[0]]['ts'][:10]}) x r{a.b} ({B[ids[0]]['ts'][:10]}) "
          f"eventos em comum={len(rows)}")
    print(f"correlacao de Pearson={pearson(x, y):.4f} | |diferenca|: mediana={d[len(d) // 2]:.4f} "
          f"p95={d[int(len(d) * 0.95)]:.4f} max={d[-1]:.4f} | identicas={sum(1 for v in d if v == 0)}")
    print(f"limiar {a.thr}:")
    by = defaultdict(lambda: [0, 0, 0, 0, 0])
    dets = {a.a: defaultdict(bool), a.b: defaultdict(bool)}
    for s, det, p, q, _ in rows:
        c = by[s]
        c[0] += 1
        c[1] += p >= a.thr
        c[2] += q >= a.thr
        c[3] += (p >= a.thr) and (q < a.thr)
        c[4] += (p < a.thr) and (q >= a.thr)
        if s == "S2C":
            dets[a.a][det] |= p >= a.thr
            dets[a.b][det] |= q >= a.thr
    tot = [0, 0, 0, 0, 0]
    for s in sorted(by):
        c = by[s]
        tot = [t + v for t, v in zip(tot, c)]
        print(f"  {s:4s} n={c[0]:4d} passa r{a.a}={c[1]:4d} ({c[1] / c[0]:.1%}) r{a.b}={c[2]:4d} ({c[2] / c[0]:.1%}) "
              f"| saiu={c[3]} entrou={c[4]}")
    print(f"  tudo n={tot[0]} trocaram de lado={tot[3] + tot[4]} ({(tot[3] + tot[4]) / tot[0]:.1%})")
    for rep in (a.a, a.b):
        print(f"  deteccoes confirmadas mantidas r{rep}: {sum(dets[rep].values())}/{len(dets[rep])}")
    worst = sorted(rows, key=lambda r: -abs(r[2] - r[3]))[:8]
    print("maiores diferencas:", "; ".join(f"{r[4]} {r[0]} {r[2]:.3f}->{r[3]:.3f}" for r in worst))


if __name__ == "__main__":
    main()
