#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — funis completos no desenvolvimento (missao 7). Sem custo: so le arquivos de resultado.

Para cada par gate x detail medido do jeito da producao:
  filtro Decisions (wl_v2 >= 0,30) -> gate (new_litter e conf >= 85) -> detail (veredito final, com o veto)
  custo/evento = cD + P(passa no filtro) * cGate + P(passa e dispara) * cDetail      (modo padrao)
  deteccoes confirmadas mantidas, rejeitadas que sobrevivem, alertas por 1.000 eventos e a parte S0 dos
  alertas dividida pela leitura a olho da missao 6 (results/s0_sim_*__revisao.tsv).
O detail entra com dois precos: o do AI Studio (o que foi cobrado) e o do Vertex (cost_usd do executor).
A margem do custo e so a do disparo em S0 (Wilson 95%), como em agg_gate54.

Uso: python funnels54.py
"""
from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict

import run_gate54 as g54
from agg_dgate54 import C_DET_OLD, C_GATE, TODAY
from agg_gate54 import C_D, weights
from review_m6_54 import DETAILS, GATES, read_jsonl, wilson
from run_detail54 import RESULTS, cost_usd

SUBS = ("S2C", "S2R", "S2X", "S1", "S0")
KINDS = ("descarte_provavel", "falso_provavel", "indeterminado")


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")


def main():
    pass_rows = g54.build_set("pass", 0.30)
    sub = {r["event_id"]: r["sub"] for r in pass_rows}
    det_of = {r["event_id"]: r["detection_id"] for r in pass_rows}
    n_det = {s: len({r["detection_id"] for r in pass_rows if r["sub"] == s}) for s in ("S2C", "S2R")}
    w = weights()
    n_all, n_ok = Counter(), Counter()
    for r in g54.load_dev():
        if r["score"] is not None:
            n_all[r["sub"]] += 1
            n_ok[r["sub"]] += r["score"] >= 0.30
    pf = {s: n_ok[s] / n_all[s] for s in SUBS}
    p_gate = sum(w[s] * pf[s] for s in SUBS)
    leit = {}
    for name in ("s0_sim_controle54__revisao.tsv", "s0_sim_so_g3_54__revisao.tsv"):
        with (RESULTS / name).open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                leit[r["event_id"]] = r["leitura"]

    gate, det = {}, {}
    for g in GATES:
        recs = {e: r for e, r in read_jsonl(RESULTS / f"gate54__{g}__r1.jsonl")[0].items() if e in sub}
        gate[g] = {"fire": {e for e, r in recs.items() if r.get("fire")},
                   "n": Counter(sub[e] for e in recs),
                   "c": statistics.fmean(r["cost_usd"] for r in recs.values()),
                   # latencia so de chamadas em modo padrao (as rodadas r1 dos gates Gemini foram em Flex)
                   "p90": pct([r["latency_ms"] for r in recs.values() if not r.get("flex_requested")], 0.9) / 1000}
    for d in DETAILS:
        recs = read_jsonl(RESULTS / f"detail54__{d}__r1.jsonl")[0]
        std = [r["latency_ms"] for r in recs.values() if not r.get("flex_requested")]
        det[d] = {"recs": recs,
                  "c_ai": statistics.fmean(r["cost_usd"] for r in recs.values()),
                  "c_vx": statistics.fmean(cost_usd(r["model"], r["tok_in"], r["tok_out"], r["tok_think"])
                                           for r in recs.values()),
                  "p90": pct(std, 0.9) / 1000 if std else float("nan")}

    print(f"desenvolvimento, conjunto pass: confirmadas {n_det['S2C']}, rejeitadas {n_det['S2R']} | passam no filtro "
          f"{p_gate:.1%} dos eventos | hoje (producao medida) US$ {TODAY:.6f}/evento = gate US$ {C_GATE:.6f} em "
          f"todo evento + detail US$ {C_DET_OLD:.6f} por disparo | Decisions US$ {C_D:.6f}/evento")
    for g in GATES:
        print(f"  gate {g:<22} US$ {gate[g]['c']:.6f}/chamada, p90 em modo padrao {gate[g]['p90']:.1f} s "
              "(nan = so chamadas Flex neste arquivo)")
    for d in DETAILS:
        print(f"  detail {d:<18} AI Studio US$ {det[d]['c_ai']:.5f}/chamada, Vertex US$ {det[d]['c_vx']:.5f}, "
              f"p90 em modo padrao {det[d]['p90']:.1f} s")

    print("\nfunil | confirmadas | rejeitadas | alertas por 1.000 (S0: descarte provavel / falso / indeterminado) | "
          "dispara | custo/evento com o detail no AI Studio | no Vertex")
    for d in DETAILS:
        for g in GATES:
            fire, recs = gate[g]["fire"], det[d]["recs"]
            kept = defaultdict(set)
            alerts, s0 = 0.0, Counter()
            p_fire = {}
            for s in SUBS:
                fired = [e for e in fire if sub[e] == s]
                cov = [e for e in fired if e in recs]
                yes = [e for e in cov if recs[e].get("disposal")]
                for e in yes:
                    kept[s].add(det_of[e])
                rate = w[s] * pf[s] * len(fired) / gate[g]["n"][s]
                p_fire[s] = rate
                a = 1000 * rate * len(yes) / len(cov) if cov else 0.0
                alerts += a
                if s == "S0":
                    for e in yes:
                        s0[leit.get(e, "sem leitura")] += a / len(yes)
            lo, hi = wilson(len([e for e in fire if sub[e] == "S0"]), gate[g]["n"]["S0"])
            rest = sum(v for s, v in p_fire.items() if s != "S0")

            def cost(c_det, f0=None):
                pfire = rest + (p_fire["S0"] if f0 is None else w["S0"] * pf["S0"] * f0)
                return (C_D + p_gate * gate[g]["c"] + pfire * c_det) / TODAY - 1

            ai, vx = det[d]["c_ai"], det[d]["c_vx"]
            print(f"  {g.split('_')[0]:<5}+ {d.split('_')[0]:<5} | {len(kept['S2C']):>2}/{n_det['S2C']} | "
                  f"{len(kept['S2R']):>2}/{n_det['S2R']} | {alerts:5.2f} (S0 "
                  + " / ".join(f"{s0[k]:.1f}" for k in KINDS) + (f"; sem leitura {s0['sem leitura']:.1f}"
                                                                 if s0["sem leitura"] else "")
                  + f") | {sum(p_fire.values()):.2%} | {cost(ai):+.0%} [{cost(ai, lo):+.0%} a {cost(ai, hi):+.0%}] | "
                  f"{cost(vx):+.0%} [{cost(vx, lo):+.0%} a {cost(vx, hi):+.0%}]")
    print("\nreferencia: producao no mesmo conjunto = 32 confirmadas, 61 rejeitadas, alerta em 3,20% dos eventos. "
          "O replay do gate de hoje (g25l) e a regua justa das confirmadas.")


if __name__ == "__main__":
    main()
