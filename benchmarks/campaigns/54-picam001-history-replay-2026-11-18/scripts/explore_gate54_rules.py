#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — exploracao SEM CUSTO da regra de disparo do gate nos bracos que gravaram os 3 sinais
(veh_stopped, person_handling, new_ground; run_gate54.py desde 19/11).

O worker dispara quando: cena == DUMPING e pelo menos 2 dos 3 sinais (e confianca >= 85). Essa regra foi
escrita para o prompt V1 (veiculo parado + pessoa depositando) e pune o descarte a pe, em que nao ha
veiculo. Aqui cada regra alternativa e reaplicada as respostas ja gravadas.

Nada aqui e validado: e exploracao no conjunto de desenvolvimento, com muitas regras no mesmo conjunto
(o melhor numero e otimista). Serve para escolher o que medir de verdade.

Uso: python explore_gate54_rules.py [--set tri|pass] [--thr 0.30]
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from agg_dgate54 import C_DET_NEW, RESULTS, TODAY, wilson
from agg_gate54 import C_D, SUBS, load_arm, weights
import run_gate54 as g


def n_sig(r):
    return int(bool(r.get("veh_stopped"))) + int(bool(r.get("person_handling"))) + int(bool(r.get("new_ground")))


def scene(r):
    return (r.get("scene_type") or "").upper().strip()


RULES = {
    "worker (DUMPING e 2 de 3, conf>=85)": lambda r: bool(r["new_litter"]) and r["conf"] >= 85,
    "DUMPING e 2 de 3 (sem conf)": lambda r: scene(r) == "DUMPING" and n_sig(r) >= 2,
    "DUMPING e 1 de 3": lambda r: scene(r) == "DUMPING" and n_sig(r) >= 1,
    "so cena DUMPING": lambda r: scene(r) == "DUMPING",
    "DUMPING ou (pessoa e chao novo)": lambda r: scene(r) == "DUMPING" or (
        bool(r.get("person_handling")) and bool(r.get("new_ground"))),
    "DUMPING ou pessoa manuseando": lambda r: scene(r) == "DUMPING" or bool(r.get("person_handling")),
    "DUMPING ou chao novo": lambda r: scene(r) == "DUMPING" or bool(r.get("new_ground")),
    "pessoa manuseando (qualquer cena)": lambda r: bool(r.get("person_handling")),
    # regras MAIS estritas que a do worker (para bracos que disparam demais, como o prompt g3)
    "worker e conf>=90": lambda r: bool(r["new_litter"]) and r["conf"] >= 90,
    "worker e conf>=95": lambda r: bool(r["new_litter"]) and r["conf"] >= 95,
    "worker e chao novo": lambda r: bool(r["new_litter"]) and r["conf"] >= 85 and bool(r.get("new_ground")),
    "worker e pessoa manuseando": lambda r: bool(r["new_litter"]) and r["conf"] >= 85 and bool(
        r.get("person_handling")),
    "worker e pessoa e chao novo": lambda r: bool(r["new_litter"]) and r["conf"] >= 85 and bool(
        r.get("person_handling")) and bool(r.get("new_ground")),
    "worker e 3 de 3": lambda r: bool(r["new_litter"]) and r["conf"] >= 85 and n_sig(r) == 3,
    # regra conjunta com a nota do filtro Decisions (wl_v2), que o funil ja tem de graca
    "worker e nota>=0,40": lambda r: bool(r["new_litter"]) and r["conf"] >= 85 and (r.get("score") or 0) >= 0.40,
    "worker e nota>=0,50": lambda r: bool(r["new_litter"]) and r["conf"] >= 85 and (r.get("score") or 0) >= 0.50,
    "worker e (nota>=0,50 ou conf>=95)": lambda r: bool(r["new_litter"]) and r["conf"] >= 85 and (
        (r.get("score") or 0) >= 0.50 or r["conf"] >= 95),
    "worker e (nota>=0,50 ou 3 de 3)": lambda r: bool(r["new_litter"]) and r["conf"] >= 85 and (
        (r.get("score") or 0) >= 0.50 or n_sig(r) == 3),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="tri", choices=["tri", "pass"])
    ap.add_argument("--thr", type=float, default=0.30)
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
    ids = {r["event_id"]: r for r in g.build_set(a.set, a.thr, rows)}
    print(f"conjunto={a.set} limiar do filtro={a.thr} eventos={len(ids)} | hoje US$ {TODAY:.6f}/evento | "
          f"vai ao gate {p_gate:.1%}\n")

    for path in sorted(RESULTS.glob("gate54__*__r1.jsonl")):
        arm = path.name.split("__")[1]
        recs = load_arm(path)
        mine = [r for i, r in recs.items() if i in ids]
        if not mine or "person_handling" not in mine[0]:
            continue
        c_call = sum(r["cost_usd"] for r in mine) / len(mine)
        print(f"{arm}  n={len(mine)}/{len(ids)}  US$ {c_call:.6f}/chamada")
        sc = defaultdict(lambda: defaultdict(int))
        for r in mine:
            sc[ids[r["event_id"]]["sub"]][f"{scene(r)}/{n_sig(r)}"] += 1
        for s in ("S2C", "S2R", "S1", "S0"):
            print(f"  cena/sinais em {s}: " + ", ".join(f"{k} {v}" for k, v in sorted(sc[s].items(), key=lambda kv: -kv[1])))
        for name, rule in RULES.items():
            cnt, fr = defaultdict(int), defaultdict(int)
            dets = {"S2C": defaultdict(bool), "S2R": defaultdict(bool)}
            for r in mine:
                s = ids[r["event_id"]]["sub"]
                cnt[s] += 1
                fr[s] += rule(r)
                if s in dets:
                    dets[s][r["detection_id"] or r["event_id"]] |= rule(r)
            f2 = (fr["S2C"] + fr["S2R"]) / max(1, cnt["S2C"] + cnt["S2R"])
            fx = {s: (fr[s] / cnt[s] if cnt[s] else f2) for s in SUBS}

            def cost(f0):
                p_fire = w["S0"] * pf["S0"] * f0 + sum(w[s] * pf[s] * fx[s] for s in SUBS if s != "S0")
                return C_D + p_gate * c_call + p_fire * C_DET_NEW, p_fire
            lo, hi = wilson(fr["S0"], cnt["S0"]) if cnt["S0"] else (0.0, 0.0)
            full, p_fire = cost(fx["S0"])
            print(f"  {name:<38} confirmadas {sum(dets['S2C'].values()):>2}/{len(dets['S2C'])} | "
                  f"rejeitadas {sum(dets['S2R'].values()):>2}/{len(dets['S2R'])} | S1 {fr['S1']:>2}/{cnt['S1']} | "
                  f"S0 {fr['S0']:>2}/{cnt['S0']} | dispara {p_fire:.2%} | custo {full / TODAY - 1:+.0%} "
                  f"[{cost(lo)[0] / TODAY - 1:+.0%} a {cost(hi)[0] / TODAY - 1:+.0%}]")
        print()


if __name__ == "__main__":
    main()
