#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — agrega os bracos de detail (run_detail54.py) e cruza com os gates de referencia (missao 5).

Sem custo: so le results/detail54__<braco>__r<rep>.jsonl e results/gate54__<gate>__r1.jsonl.

Por braco de detail:
  por estrato   eventos com "sim" (veredito final, com o veto de grounding do worker) e "sim" cru do modelo
  por gate      funil gate -> detail: deteccoes confirmadas mantidas (pelo menos um evento em que o gate
                dispara E o detail diz sim), deteccoes rejeitadas que sobrevivem, eventos S1 e S0 que viram
                ocorrencia
  producao      concordancia com o que o detail de producao respondeu no mesmo evento (base_eventos)
  alertas       ocorrencias por 1.000 eventos da camera (pesos reais dos estratos, so eventos que passam no
                filtro Decisions), por origem: confirmadas, rejeitadas, S1 e S0 (estes dois sem rotulo)
  custo         US$ por chamada em modo padrao (AI Studio e Vertex) e latencia (so vale a de modo padrao)
Com --ref, pareia cada braco com o braco de referencia (controle) evento a evento.

Uso:
  python agg_detail54.py d25f_v1 d38f_g3_low_low --ref d25f_v1
"""
from __future__ import annotations

import argparse
import csv
import statistics as st
import sys
from collections import Counter, defaultdict

import run_gate54 as g54
from agg_gate54 import weights
from run_detail54 import GATE_REFS, RESULTS, b, cost_usd

sys.stdout.reconfigure(encoding="utf-8")
SUBS = ("S2C", "S2R", "S2X", "S1", "S0")


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load_detail(arm, rep):
    p = RESULTS / f"detail54__{arm}__r{rep}.jsonl"
    return b.latest_ok(p) if p.exists() else {}


def load_gate(arm):
    return {e: r for e, r in b.latest_ok(RESULTS / f"gate54__{arm}__r1.jsonl").items()}


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arms", nargs="+")
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--ref", default="")
    ap.add_argument("--raw", action="store_true", help="usa o sim cru do modelo (sem o veto de grounding)")
    a = ap.parse_args()

    pass_rows = g54.build_set("pass", 0.30)
    sub = {r["event_id"]: r["sub"] for r in pass_rows}
    det_of = {r["event_id"]: r["detection_id"] for r in pass_rows}
    n_det = {s: len({r["detection_id"] for r in pass_rows if r["sub"] == s}) for s in ("S2C", "S2R", "S2X")}
    n_evt = Counter(sub.values())
    gates = {g: load_gate(g) for g in GATE_REFS}
    base = {}
    with (g54.ROOT / "base" / "base_eventos.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["event_id"] in sub:
                base[r["event_id"]] = r
    key = "raw_disposal" if a.raw else "disposal"
    w = weights()
    dev = g54.load_dev()
    n_all, n_ok = Counter(), Counter()
    for r in dev:
        if r["score"] is not None:
            n_all[r["sub"]] += 1
            n_ok[r["sub"]] += r["score"] >= 0.30
    pf = {s: n_ok[s] / n_all[s] if n_all[s] else 0.0 for s in SUBS}
    passed = {r["event_id"] for r in dev if r["score"] is not None and r["score"] >= 0.30}
    yes = lambda r: int(bool(r.get(key)))  # noqa: E731
    print(f"conjunto pass (dev): eventos {dict(n_evt)} | deteccoes confirmadas {n_det['S2C']}, "
          f"rejeitadas {n_det['S2R']}, sem rotulo {n_det['S2X']} | veredito = "
          f"{'cru do modelo' if a.raw else 'final (com veto de grounding)'}")
    ref = load_detail(a.ref, a.rep) if a.ref else {}

    for arm in a.arms:
        rows = load_detail(arm, a.rep)
        rows = {e: r for e, r in rows.items() if e in sub}
        if not rows:
            print(f"\n== {arm}: sem registros")
            continue
        model = next(iter(rows.values()))["model"]
        print(f"\n== {arm} ({model}) eventos={len(rows)}")
        print("  por estrato (eventos):  sim final / n   | sim cru | vetados por grounding")
        for s in SUBS:
            rs = [r for r in rows.values() if r["sub"] == s]
            if rs:
                k = sum(r["disposal"] for r in rs)
                lo, hi = wilson(k, len(rs))
                print(f"    {s:<4} {k:>3}/{len(rs):<3} = {k / len(rs):5.1%} [{lo:.0%} a {hi:.0%}] | "
                      f"{sum(int(bool(r.get('raw_disposal'))) for r in rs):>3} | "
                      f"{sum(int(bool(r.get('grounding_rejected'))) for r in rs):>2}")
        # concordancia com a producao (so eventos em que o detail de producao rodou)
        ag = defaultdict(Counter)
        for e, r in rows.items():
            bp = base.get(e, {})
            if bp.get("detail_rodou") == "1" and bp.get("detail_ok", "1") != "0":
                ag[r["sub"]][(int(bp.get("detail_sim") == "1"), r["disposal"])] += 1
        tot = Counter()
        for c in ag.values():
            tot.update(c)
        if tot:
            n = sum(tot.values())
            same = tot[(1, 1)] + tot[(0, 0)]
            print(f"  producao x replay (detail rodou em producao, n={n}): iguais {same} = {same / n:.1%} | "
                  f"prod sim/replay nao {tot[(1, 0)]} | prod nao/replay sim {tot[(0, 1)]}")
        print("  funil por gate (r1):   confirmadas mantidas | rejeitadas que sobrevivem | S2X | S1 sim/disparos | S0 sim/disparos")
        for g, gr in gates.items():
            fire = {e for e, r in gr.items() if r.get("fire") and e in sub}
            miss = [e for e in fire if e not in rows]
            dets = {s: set() for s in ("S2C", "S2R", "S2X")}
            gdets = {s: set() for s in ("S2C", "S2R", "S2X")}
            ev = {s: [0, 0] for s in ("S1", "S0")}
            for e in fire:
                s = sub[e]
                r = rows.get(e)
                if s in dets:
                    gdets[s].add(det_of[e])
                    if r and yes(r):
                        dets[s].add(det_of[e])
                elif s in ev:
                    ev[s][1] += 1
                    if r and yes(r):
                        ev[s][0] += 1
            print(f"    {g:<22} {len(dets['S2C']):>2}/{n_det['S2C']} (gate {len(gdets['S2C'])}) | "
                  f"{len(dets['S2R']):>2}/{n_det['S2R']} (gate {len(gdets['S2R'])}) | "
                  f"{len(dets['S2X'])}/{n_det['S2X']} | {ev['S1'][0]:>2}/{ev['S1'][1]:<3} | "
                  f"{ev['S0'][0]:>2}/{ev['S0'][1]:<3} | disparos sem detail: {len(miss)}")
        print("  alertas por 1.000 eventos (gate r1 -> este detail; S1 e S0 nao tem rotulo): total | de confirmadas | de rejeitadas | S2X | S1 | S0")
        for g, gr in gates.items():
            per = {}
            for s in SUBS:
                fired = [e for e, r in gr.items() if r.get("fire") and e in passed and sub.get(e) == s]
                cov = [e for e in fired if e in rows]
                k = sum(yes(rows[e]) for e in cov)
                # braco rodado em amostra: a taxa de sim dos disparos cobertos vale para todos os disparos
                per[s] = (1000 * w[s] * pf[s] * (k / len(cov)) * len(fired) / n_ok[s]) if cov and n_ok[s] else 0.0
            print(f"    {g:<22} {sum(per.values()):5.2f} | {per['S2C']:.2f} | {per['S2R']:.2f} | {per['S2X']:.2f} | "
                  f"{per['S1']:.2f} | {per['S0']:.2f}")
        cs = [r["cost_usd"] for r in rows.values()]
        cv = [cost_usd(r["model"], r["tok_in"], r["tok_out"], r["tok_think"]) for r in rows.values()]
        std = [r["latency_ms"] / 1000 for r in rows.values() if not r.get("flex_requested")]
        allm = [r["latency_ms"] / 1000 for r in rows.values()]
        print(f"  custo por chamada, modo padrao: AI Studio US$ {st.mean(cs):.5f} | Vertex (sem os tokens do "
              f"esquema) US$ {st.mean(cv):.5f} | entrada media {st.mean(r['tok_in'] for r in rows.values()):.0f}, "
              f"saida {st.mean(r['tok_out'] for r in rows.values()):.0f}, pensamento "
              f"{st.mean(r['tok_think'] for r in rows.values()):.0f} | quadros enviados: mediana "
              f"{st.median(r['n_sent'] for r in rows.values())}, max {max(r['n_sent'] for r in rows.values())}")
        if std:
            print(f"  latencia em modo padrao (n={len(std)}): p50 {pct(std, 0.5):.1f} s, p90 {pct(std, 0.9):.1f} s")
        else:
            print(f"  latencia: so chamadas Flex (p50 {pct(allm, 0.5):.0f} s); nao vale para producao")
        if ref and arm != a.ref:
            print(f"  pareado com {a.ref} (eventos em comum):")
            for s in SUBS:
                c = Counter()
                for e, r in rows.items():
                    if r["sub"] == s and e in ref:
                        c[(yes(ref[e]), yes(r))] += 1
                if c:
                    print(f"    {s:<4} n={sum(c.values()):>3}  os dois {c[(1, 1)]:>3} | so {a.ref} {c[(1, 0)]:>3} | "
                          f"so {arm} {c[(0, 1)]:>3} | nenhum {c[(0, 0)]:>3}")


if __name__ == "__main__":
    main()
