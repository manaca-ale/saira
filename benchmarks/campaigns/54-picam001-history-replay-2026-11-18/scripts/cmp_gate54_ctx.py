"""Efeito do contexto da janela anterior no gate (missao 4): braco sem contexto x braco _ctx.

Teste de fidelidade: o gate de controle reexecutado tem de disparar, no total dos eventos
que passam no filtro, a mesma fracao que a producao disparou (a estratificacao e pela
decisao gravada, mas a taxa marginal de uma reexecucao fiel e a mesma da original).

  python cmp_gate54_ctx.py [--pairs g25l_v1_t2048:g25l_v1_t2048_ctx ...] [--reps 1 1]
"""
import argparse
import json
import os
import random
from collections import Counter

RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
# pesos dos estratos na populacao e fracao que passa no filtro (cabecalho do agg_gate54.py)
W = {"S0": 0.9676, "S1": 0.0188, "S2C": 0.0045, "S2R": 0.0079, "S2X": 0.0013}
PASS = {"S0": 304 / 1623, "S1": 131 / 246, "S2C": 61 / 61, "S2R": 73 / 88, "S2X": 8 / 9}
PROD = sum(W[s] * PASS[s] for s in W if s != "S0")   # producao disparou em todo S1 e S2


def load(arm, rep=1):
    out = {}
    with open(os.path.join(RESULTS, f"gate54__{arm}__r{rep}.jsonl"), encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            if not r.get("error"):
                r["st"] = r.get("sub") or r["estrato"]
                out[r["event_id"]] = r
    return out


def rate(recs):
    tot = 0.0
    for s in W:
        v = [r["fire"] for r in recs if r["st"] == s]
        if v:
            tot += W[s] * PASS[s] * sum(v) / len(v)
    return tot


def boot(recs, n=2000, seed=54):
    rnd = random.Random(seed)
    by = {s: [r for r in recs if r["st"] == s] for s in W}
    v = sorted(rate([x for s in W if by[s] for x in rnd.choices(by[s], k=len(by[s]))]) for _ in range(n))
    return v[int(0.025 * n)], v[int(0.975 * n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="*", default=["g25l_v1_t2048:g25l_v1_t2048_ctx",
                                                   "g31l_v1p_min_low:g31l_v1p_min_low_ctx"])
    ap.add_argument("--reps", nargs=2, type=int, default=[1, 1])
    a = ap.parse_args()
    print(f"producao: dispara e passa no filtro em {PROD:.2%} dos eventos")
    for pair in a.pairs:
        x, y = pair.split(":")
        A, B = load(x, a.reps[0]), load(y, a.reps[1])
        ids = sorted(set(A) & set(B))
        print(f"\n{x} (r{a.reps[0]}) x {y} (r{a.reps[1]})  pares={len(ids)}")
        for name, d in ((x, A), (y, B)):
            recs = [d[i] for i in ids]
            lo, hi = boot(recs)
            print(f"  {name:28s} dispara {rate(recs):.2%} dos eventos [{lo:.2%} a {hi:.2%}] "
                  f"= {rate(recs) / PROD:.2f}x a producao")
        for s in W:
            c = Counter((A[i]["fire"], B[i]["fire"]) for i in ids if A[i]["st"] == s)
            n = sum(c.values())
            if n:
                print(f"  {s:4s} n={n:3d}  os dois {c[(True, True)]:3d} | so o 1o {c[(True, False)]:3d} | "
                      f"so o 2o {c[(False, True)]:3d} | nenhum {c[(False, False)]:3d}")
        if any("prior_type" in B[i] for i in ids):
            for lab, fn in (("sem contexto", lambda t: t is None), ("contexto sem tipo", lambda t: t == ""),
                            ("contexto com tipo", lambda t: bool(t))):
                sel = [i for i in ids if fn(B[i].get("prior_type"))]
                if sel:
                    print(f"  {lab:18s} n={len(sel):3d}  dispara: 1o {sum(A[i]['fire'] for i in sel):3d}, "
                          f"2o {sum(B[i]['fire'] for i in sel):3d}")


if __name__ == "__main__":
    main()
