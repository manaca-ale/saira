#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — exploracao sem custo dos bracos do gate no conjunto tri (so dev). Nada aqui e validado:
serve para decidir o que vale uma rodada paga.

1) regra de disparo alternativa: dispara se "sim", ou se "nao" com confianca abaixo de T
2) deteccoes confirmadas: quais cada braco perde, sobreposicao com o controle e unioes de dois bracos
3) o Decisions sozinho como gate (sem o gate LLM): limiar alto direto para o detail

Uso: python explore_gate54.py
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from agg_dgate54 import C_DET_NEW, C_GATE, RESULTS, TODAY
from agg_gate54 import C_D, SUBS, load_arm, weights
import run_gate54 as g

CTRL = "g25l_v1_t2048"


def main():
    rows = g.load_dev()
    w = weights()
    tri = {r["event_id"]: r for r in g.build_set("tri", 0.30, rows)}
    arms = {}
    for p in sorted(RESULTS.glob("gate54__*__r1.jsonl")):
        recs = {i: r for i, r in load_arm(p).items() if i in tri}
        if len(recs) >= 200:
            arms[p.name.split("__")[1]] = recs
    dets = defaultdict(set)
    for i, r in tri.items():
        if r["sub"] == "S2C":
            dets[r["detection_id"] or i].add(i)
    print(f"tri={len(tri)} deteccoes confirmadas={len(dets)} | detail novo US$ {C_DET_NEW:.6f}, gate de hoje US$ {C_GATE:.6f}, "
          f"hoje US$ {TODAY:.6f}/evento\n")

    print("1) regra alternativa: dispara se sim (conf >= 85), ou se nao com confianca < T   [confirmadas | S0 | S1 | S2R]")
    for a, recs in arms.items():
        out = []
        for T in (0, 80, 90, 95, 100, 101):
            def fire(r, T=T):
                return (bool(r["new_litter"]) and r["conf"] >= 85) or (not r["new_litter"] and r["conf"] < T)
            k = sum(any(fire(recs[e]) for e in evs if e in recs) for evs in dets.values())
            c = defaultdict(lambda: [0, 0])
            for i, r in recs.items():
                c[tri[i]["sub"]][0] += fire(r)
                c[tri[i]["sub"]][1] += 1
            out.append(f"T={T}: {k}/{len(dets)} | " + " | ".join(f"{c[s][0]}/{c[s][1]}" for s in ("S0", "S1", "S2R")))
        print(f"  {a}\n    " + "\n    ".join(out))

    def fire0(r):
        return bool(r["new_litter"]) and r["conf"] >= 85
    kept = {a: {d for d, evs in dets.items() if any(fire0(recs[e]) for e in evs if e in recs)} for a, recs in arms.items()}
    s0 = {a: {i for i, r in recs.items() if tri[i]["sub"] == "S0" and fire0(r)} for a, recs in arms.items()}
    print("\n2) deteccoes confirmadas mantidas e sobreposicao com o controle")
    for a in arms:
        print(f"  {a}: mantem {len(kept[a])}; em comum com o controle {len(kept[a] & kept[CTRL])}; "
              f"so este {len(kept[a] - kept[CTRL])}; S0 em comum com o controle {len(s0[a] & s0[CTRL])}/{len(s0[a])}")
    g3 = [a for a in arms if not a.startswith("g25l")]
    allg3 = set().union(*(kept[a] for a in g3)) if g3 else set()
    print(f"  mantidas por pelo menos um Gemini 3: {len(allg3)}/{len(dets)}; por nenhum: {len(dets) - len(allg3)}; "
          f"perdidas pelo controle: {len(dets) - len(kept[CTRL])}")
    best = sorted(((len(kept[a] | kept[b]), -len(s0[a] | s0[b]), a, b) for a, b in combinations(g3, 2)), reverse=True)[:4]
    for k, ns0, a, b in best:
        print(f"  uniao {a} OU {b}: {k}/{len(dets)} confirmadas, S0 {-ns0}/60")

    print("\n3) Decisions sozinho como gate: wl_v2 >= t vai direto ao detail (dev inteiro, pesos reais)")
    ok = [r for r in rows if r["score"] is not None]
    n_s = defaultdict(int)
    for r in ok:
        n_s[r["sub"]] += 1
    for t in (0.30, 0.50, 0.70, 0.80, 0.90, 0.95):
        ps = {s: sum(1 for r in ok if r["sub"] == s and r["score"] >= t) / n_s[s] for s in SUBS}
        p = sum(w[s] * ps[s] for s in SUBS)
        d = defaultdict(bool)
        for r in ok:
            if r["sub"] == "S2C":
                d[r["detection_id"] or r["event_id"]] |= r["score"] >= t
        cost = C_D + p * C_DET_NEW
        print(f"  t={t:.2f}: vai ao detail {p:.2%} dos eventos (S0 {ps['S0']:.1%}); confirmadas {sum(d.values())}/{len(d)}; "
              f"custo/evento US$ {cost:.6f} ({cost / TODAY - 1:+.0%})")


if __name__ == "__main__":
    main()
