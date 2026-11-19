#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — candidatos a gate (run_gate54.py): disparo por estrato, deteccoes confirmadas mantidas,
custo por chamada e custo por evento no funil  filtro (wl_v2 >= limiar) -> gate candidato -> detail novo.

Referencia: a decisao gravada em producao (S1 e S2 dispararam, S0 nao). Um gate repetido aqui nao repete
todos os "sim" de producao; compare cada braco com o controle do mesmo dia (g25l_v1_t2048).

  custo/evento = cD + P(passa no filtro) * cGate + P(passa e dispara) * cDetail
  P(passa e dispara) = soma_s peso_s * passa_filtro_s * disparo_s   (pesos reais dos estratos)

Uso: python agg_gate54.py [--set tri|pass] [--thr 0.30] [--conf 85]
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict

from agg_dgate54 import BASE, C_DET_NEW, C_GATE, RESULTS, TODAY, wilson
from agg_funnel54 import stratum
import run_gate54 as g

C_D = 0.000169          # Decisions, 1 pergunta, 5 frames low (medido, 1.691 tokens)
SUBS = ("S0", "S1", "S2C", "S2R", "S2X")


def weights():
    W = defaultdict(int)
    for r in csv.DictReader((BASE / "base_eventos.csv").open(encoding="utf-8", newline="")):
        if r["gate_avaliou"] == "1":
            W[stratum(r)] += 1
    n = sum(W.values())
    return {s: W[s] / n for s in SUBS}


def load_arm(path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error"):
                out[r["event_id"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="tri", choices=["tri", "pass"])
    ap.add_argument("--thr", type=float, default=0.30)
    ap.add_argument("--conf", type=int, default=85)
    a = ap.parse_args()

    rows = g.load_dev()
    w = weights()
    n_s, pass_s = defaultdict(int), defaultdict(int)
    for r in rows:
        if r["score"] is not None:
            n_s[r["sub"]] += 1
            pass_s[r["sub"]] += r["score"] >= a.thr
    pf = {s: pass_s[s] / n_s[s] if n_s[s] else 0.0 for s in SUBS}
    p_gate = sum(w[s] * pf[s] for s in SUBS)
    p_fire_prod = sum(w[s] * pf[s] for s in SUBS if s != "S0")
    ref = C_D + p_gate * C_GATE + p_fire_prod * C_DET_NEW
    ids = {r["event_id"]: r for r in g.build_set(a.set, a.thr, rows)}
    s0f = {r["event_id"] for r in g.build_set("s0fail", a.thr, rows)}
    print(f"conjunto={a.set} limiar do filtro={a.thr} disparo: new_litter e conf >= {a.conf} | eventos={len(ids)}")
    print(f"pesos: " + ", ".join(f"{s} {w[s]:.4f}" for s in SUBS) + " | passa no filtro: "
          + ", ".join(f"{s} {pass_s[s]}/{n_s[s]}" for s in SUBS) + f" | vai ao gate {p_gate:.1%}")
    print(f"hoje US$ {TODAY:.6f}/evento | filtro + gate de producao (decisao gravada) + detail novo: "
          f"US$ {ref:.6f} ({ref / TODAY - 1:+.0%}); gate de producao US$ {C_GATE:.6f}/chamada\n")

    for path in sorted(RESULTS.glob("gate54__*__r1.jsonl")):
        arm = path.name.split("__")[1]
        recs = load_arm(path)
        mine = [r for i, r in recs.items() if i in ids]
        if not mine:
            continue
        fire = lambda r: bool(r["new_litter"]) and r["conf"] >= a.conf  # noqa: E731
        cnt, fr = defaultdict(int), defaultdict(int)
        dets = {"S2C": defaultdict(bool), "S2R": defaultdict(bool)}
        for r in mine:
            s = ids[r["event_id"]]["sub"]
            cnt[s] += 1
            fr[s] += fire(r)
            if s in dets:
                dets[s][r["detection_id"] or r["event_id"]] |= fire(r)
        f = {s: fr[s] / cnt[s] if cnt[s] else None for s in SUBS}
        # S2X (poucos eventos) usa a taxa conjunta de S2C e S2R quando nao foi medido
        f2 = (fr["S2C"] + fr["S2R"]) / max(1, cnt["S2C"] + cnt["S2R"])
        fx = {s: (f[s] if f[s] is not None else f2) for s in SUBS}
        c_call = statistics.fmean(r["cost_usd"] for r in mine)
        lat = sorted(r["latency_ms"] for r in mine)
        tin, tout, tth = (statistics.fmean(r[k] for r in mine) for k in ("tok_in", "tok_out", "tok_think"))
        flex_n = sum(1 for r in mine if r.get("flex_requested"))

        def cost(f0, c):
            p_fire = w["S0"] * pf["S0"] * f0 + sum(w[s] * pf[s] * fx[s] for s in SUBS if s != "S0")
            return C_D + p_gate * c + p_fire * C_DET_NEW, p_fire
        lo, hi = wilson(fr["S0"], cnt["S0"]) if cnt["S0"] else (0.0, 0.0)
        full, p_fire = cost(fx["S0"], c_call)
        print(f"{arm}  n={len(mine)}/{len(ids)}  (flex pedido em {flex_n})")
        print("  disparo: " + " | ".join(f"{s} {fr[s]}/{cnt[s]}" + (f" = {f[s]:.0%}" if cnt[s] else "") for s in SUBS))
        print(f"  deteccoes confirmadas mantidas {sum(dets['S2C'].values())}/{len(dets['S2C'])} | "
              f"rejeitadas que disparam {sum(dets['S2R'].values())}/{len(dets['S2R'])}")
        print(f"  tokens: entrada {tin:.0f}, saida {tout:.0f}, thinking {tth:.0f} | US$ {c_call:.6f}/chamada padrao "
              f"({c_call / C_GATE:.2f}x o gate de hoje), Flex US$ {c_call / 2:.6f} | latencia p50 {lat[len(lat) // 2] / 1000:.1f} s, "
              f"p90 {lat[int(len(lat) * 0.9)] / 1000:.1f} s")
        print(f"  funil: dispara {p_fire:.2%} dos eventos (producao 3,20%) | custo/evento padrao US$ {full:.6f} "
              f"({full / TODAY - 1:+.0%} [{cost(lo, c_call)[0] / TODAY - 1:+.0%} a {cost(hi, c_call)[0] / TODAY - 1:+.0%}]) | "
              f"Flex US$ {cost(fx['S0'], c_call / 2)[0]:.6f} ({cost(fx['S0'], c_call / 2)[0] / TODAY - 1:+.0%})")
        sf = [r for i, r in recs.items() if i in s0f]
        if sf:
            k = sum(fire(r) for r in sf)
            f0_all = pf["S0"] * fx["S0"] + (1 - pf["S0"]) * k / len(sf)
            p_all = w["S0"] * f0_all + sum(w[s] * fx[s] for s in SUBS if s != "S0")
            c_all = c_call + p_all * C_DET_NEW
            print(f"  sem filtro: S0 abaixo do limiar dispara {k}/{len(sf)}; dispara {p_all:.2%} dos eventos; "
                  f"custo/evento US$ {c_all:.6f} ({c_all / TODAY - 1:+.0%}), Flex ({(c_call / 2 + p_all * C_DET_NEW) / TODAY - 1:+.0%})")
        print()


if __name__ == "__main__":
    main()
