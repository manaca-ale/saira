#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — filtro barato antes do gate: regra gratuita (frames no evento) x Decisions (sem custo de API).

Junta, por evento da amostra, o numero de frames (base_eventos.csv) e as respostas do Decisions
(run_dgate54.py) e projeta para a populacao com os pesos reais dos estratos, como em agg_dgate54.py.

Funil avaliado (o gate e o detail de hoje continuam decidindo; so se perde o que o filtro barrar):
  regra (frames >= K)  ->  Decisions (nota >= limiar)  ->  gate de hoje  ->  detail recomendado
  custo = P(regra) * cD + P(regra e D) * cGate + P(regra e D e disparo) * cDetail
Confirmada mantida = deteccao com pelo menos um evento que passa pela regra e pelo Decisions.

Secoes:
  varredura   para cada pergunta (e pares, com --pairs): AUC, limiar que mantem todas as confirmadas e
              limiar que perde uma, com a passagem de S0 e o custo; e a mesma conta com o limiar
              escolhido numa metade do desenvolvimento e aplicado na outra (metades A/B por hash).
  funil       para cada --expr: tabela K x limiar.

Uso:
  python agg_funnel54.py --qset q2
  python agg_funnel54.py --qset q2 --pairs 6
  python agg_funnel54.py --qset q2 --expr person_near_pile --expr "max(person_near_pile, carrying)" --frames 0,8,10,12
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from agg_dgate54 import BASE, C_DET_NEW, C_GATE, RESULTS, TODAY, auc, probs, wilson

SAFE = {"__builtins__": {}, "max": max, "min": min, "abs": abs}
STRATA = ("S0", "S1", "S2C", "S2R", "S2X")


def half(key: str) -> str:
    return "A" if int(hashlib.sha256(("half54|" + key).encode()).hexdigest(), 16) % 2 == 0 else "B"


def stratum(r) -> str:
    if r["gate_disparou"] != "1":
        return "S0"
    if r["detail_sim"] != "1":
        return "S1"
    return {"CONFIRMADO": "S2C", "REJEITADO": "S2R"}.get(r["status"], "S2X")


def load(a):
    base, W = {}, defaultdict(int)
    for r in csv.DictReader((BASE / "base_eventos.csv").open(encoding="utf-8", newline="")):
        if r["gate_avaliou"] != "1" or not (a.from_day <= r["dia"] <= a.to_day):
            continue
        s = stratum(r)
        W[s] += 1
        base[r["event_id"]] = {"s": s, "n": int(r["n_frames"] or 0), "dia": r["dia"],
                               "det": r["detection_id"] or r["event_id"]}
    rows, toks = [], []
    path = RESULTS / f"dgate54__{a.qset}_gate5_{a.res}__r{a.rep}.jsonl"
    seen = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error") and r.get("answers"):
                seen[r["event_id"]] = r
    for r in seen.values():
        b = base.get(r["event_id"])
        if b is None or (a.split != "all" and r["split"] != a.split):
            continue
        toks.append(r.get("tok_in") or 0)
        rows.append({"id": r["event_id"], "s": b["s"], "det": b["det"], "n": b["n"], "dia": b["dia"],
                     "p": probs(r), "half": half(b["det"])})
    return base, W, rows, (statistics.median(toks) if toks else 0)


def score_all(rows, expr):
    code = compile(expr, "<expr>", "eval")
    out = []
    for r in rows:
        try:
            out.append(float(eval(code, SAFE, dict(r["p"]))))
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"expressao invalida ({expr}) em {r['id']}: {exc}; perguntas: {sorted(r['p'])}")
    return out


class Funnel:
    def __init__(self, rows, W, cd):
        self.rows, self.W, self.cd = rows, W, cd
        self.n_pop = sum(W.values())
        self.n_s = defaultdict(int)
        for r in rows:
            self.n_s[r["s"]] += 1

    def run(self, sc, k, t, sub=None):
        """sc: nota por evento (ou None = sem Decisions); k: minimo de frames; t: limiar; sub: metade A/B."""
        rule, both = defaultdict(int), defaultdict(int)
        n_s = defaultdict(int)
        dets = {"S2C": defaultdict(bool), "S2R": defaultdict(bool)}
        for i, r in enumerate(self.rows):
            if sub and r["half"] != sub:
                continue
            n_s[r["s"]] += 1
            a = r["n"] >= k
            b = a and (sc is None or sc[i] >= t)
            rule[r["s"]] += a
            both[r["s"]] += b
            if r["s"] in dets:
                dets[r["s"]][r["det"]] |= b
        w = {s: self.W[s] / self.n_pop for s in STRATA}
        fr = lambda d, s: d[s] / n_s[s] if n_s[s] else 0.0  # noqa: E731
        p_rule = sum(w[s] * fr(rule, s) for s in STRATA)
        p_fired = sum(w[s] * fr(both, s) for s in STRATA if s != "S0")

        def cost(p0):
            p_pass = w["S0"] * p0 + p_fired
            if sc is None:
                return p_pass * C_GATE + p_fired * C_DET_NEW
            return p_rule * self.cd + p_pass * C_GATE + p_fired * C_DET_NEW

        lo, hi = wilson(both["S0"], n_s["S0"])
        return {"s0": (both["S0"], n_s["S0"]), "s1": (both["S1"], n_s["S1"]),
                "c_evt": (both["S2C"], n_s["S2C"]),
                "c_det": (sum(dets["S2C"].values()), len(dets["S2C"])),
                "r_det": (sum(dets["S2R"].values()), len(dets["S2R"])),
                "p_rule": p_rule, "p_gate": w["S0"] * fr(both, "S0") + p_fired,
                "cost": cost(fr(both, "S0")) / TODAY - 1, "cost_lo": cost(lo) / TODAY - 1,
                "cost_hi": cost(hi) / TODAY - 1}

    def det_max(self, sc, k=0, sub=None):
        """maior nota entre os eventos de cada deteccao confirmada (so eventos que passam na regra)."""
        m = {}
        for i, r in enumerate(self.rows):
            if r["s"] != "S2C" or (sub and r["half"] != sub):
                continue
            v = sc[i] if r["n"] >= k else float("-inf")
            m[r["det"]] = max(m.get(r["det"], float("-inf")), v)
        return m


def pct(kn):
    return f"{kn[0]}/{kn[1]} = {100 * kn[0] / kn[1]:.1f}%" if kn[1] else "0/0"


def fmt(x, k, t):
    return (f"frames>={k:<2} limiar {t if isinstance(t, str) else format(t, '.3f')} | S0 passa {pct(x['s0'])} | S1 {pct(x['s1'])} | "
            f"confirmadas: eventos {pct(x['c_evt'])}, deteccoes {x['c_det'][0]}/{x['c_det'][1]} | rejeitadas "
            f"deteccoes {x['r_det'][0]}/{x['r_det'][1]} | vai ao gate {100 * x['p_gate']:.1f}% | custo "
            f"{100 * x['cost']:+.0f}% [{100 * x['cost_lo']:+.0f} a {100 * x['cost_hi']:+.0f}]")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--qset", default="q2")
    ap.add_argument("--res", default="low")
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--split", default="dev", choices=["dev", "aval", "all"])
    ap.add_argument("--from-day", default="2026-07-14")
    ap.add_argument("--to-day", default="2026-12-31")
    ap.add_argument("--tok", type=float, default=0, help="tokens de entrada por chamada (padrao: mediana medida)")
    ap.add_argument("--expr", action="append", default=[], help="nota para a secao funil (pode repetir)")
    ap.add_argument("--frames", default="0,8,10,12")
    ap.add_argument("--grid", default="")
    ap.add_argument("--pairs", type=int, default=0, help="testa max() e media dos pares entre as N melhores")
    ap.add_argument("--k-scan", type=int, default=0, help="regra de frames aplicada na varredura")
    a = ap.parse_args()

    base, W, rows, tok_med = load(a)
    tok = a.tok or tok_med
    cd = tok * 0.10 / 1e6
    fu = Funnel(rows, W, cd)
    print(f"qset={a.qset} split={a.split} dias {a.from_day} a {a.to_day} | populacao {fu.n_pop}: "
          + ", ".join(f"{s} {W[s]}" for s in STRATA))
    print("amostra: " + ", ".join(f"{s} {fu.n_s[s]}" for s in STRATA)
          + f" | Decisions: {tok:.0f} tokens = US$ {cd:.6f} por chamada ({100 * cd / TODAY:.1f}% do custo de hoje)")
    ks = [int(x) for x in a.frames.split(",")]
    print("\nso a regra gratuita (sem Decisions), nesta amostra:")
    for k in ks:
        print("  " + fmt(fu.run(None, k, 0), k, "  -  "))

    names = sorted({q for r in rows for q in r["p"]})
    if not a.expr:
        print(f"\nvarredura (frames >= {a.k_scan}): limiar T = mantem todas as confirmadas; U = perde uma; "
              "AB = limiar T de uma metade aplicado na outra")
        pos = [i for i, r in enumerate(rows) if r["s"] == "S2C"]
        table = []

        def scan(expr):
            sc = score_all(rows, expr)
            au = [auc([sc[i] for i in pos], [sc[i] for i, r in enumerate(rows) if r["s"] == s])
                  for s in ("S0", "S1", "S2R")]
            dm = sorted(fu.det_max(sc, a.k_scan).values())
            if len(dm) < 2 or dm[0] == float("-inf"):
                dm = [v for v in dm if v != float("-inf")]
            t_all, t_one = dm[0], dm[1]
            xa, xo = fu.run(sc, a.k_scan, t_all), fu.run(sc, a.k_scan, t_one)
            kept, tot, s0p, s0n = 0, 0, 0, 0
            for fit, app in (("A", "B"), ("B", "A")):
                dmf = [v for v in fu.det_max(sc, a.k_scan, fit).values() if v != float("-inf")]
                x = fu.run(sc, a.k_scan, min(dmf), app)
                kept += x["c_det"][0]
                tot += x["c_det"][1]
                s0p += x["s0"][0]
                s0n += x["s0"][1]
            table.append((xa["cost"], expr, au, t_all, xa, t_one, xo, (kept, tot), (s0p, s0n)))

        for q in names:
            scan(q)
        table.sort(key=lambda z: z[0])
        if a.pairs:
            top = [z[1] for z in table[:a.pairs]]
            for x, y in itertools.combinations(top, 2):
                scan(f"max({x}, {y})")
                scan(f"({x} + {y}) / 2")
            table.sort(key=lambda z: z[0])
        for cost, expr, au, t_all, xa, t_one, xo, kd, s0 in table[:60 if a.pairs else 200]:
            print(f"  {expr}: AUC S0 {au[0]:.3f} S1 {au[1]:.3f} rej {au[2]:.3f} | T {t_all:.3f}: S0 "
                  f"{100 * xa['s0'][0] / xa['s0'][1]:.1f}%, S1 {100 * xa['s1'][0] / max(1, xa['s1'][1]):.0f}%, rej "
                  f"{xa['r_det'][0]}/{xa['r_det'][1]}, custo {100 * cost:+.0f}% | U {t_one:.3f}: S0 "
                  f"{100 * xo['s0'][0] / xo['s0'][1]:.1f}%, {xo['c_det'][0]}/{xo['c_det'][1]}, custo "
                  f"{100 * xo['cost']:+.0f}% | AB: {kd[0]}/{kd[1]} confirmadas, S0 {100 * s0[0] / s0[1]:.1f}%")
        return

    for expr in a.expr:
        sc = score_all(rows, expr)
        print(f"\nfunil com nota = {expr}")
        for k in ks:
            dm = sorted(v for v in fu.det_max(sc, k).values() if v != float("-inf"))
            grid = [float(x) for x in a.grid.split(",")] if a.grid else sorted(set(dm[:4]))
            for t in grid:
                print("  " + fmt(fu.run(sc, k, t), k, t))


if __name__ == "__main__":
    main()
