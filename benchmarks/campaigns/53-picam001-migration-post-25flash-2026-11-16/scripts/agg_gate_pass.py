#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — fracao de eventos que cada gate deixa passar para o detail (sem custo), bloco L.

Compara, nos MESMOS eventos, o gate de producao (`gate__g25l_v1__r<rep>.jsonl`) e o gate
Decisions (`dgate__<tag>__r<rep>.jsonl`, pergunta `deposit`, limiares 0,20 / 0,25 / 0,30),
no total e por estado do operador (sem estado, REJEITADO, CONFIRMADO).

RESSALVA: nao se sabe como os 500 eventos do `pi-avancado-v1` foram escolhidos, e cerca de 24%
deles tem deteccao (a producao tinha ~2%). A fracao absoluta NAO e a de producao. O numero util
e a RAZAO entre os dois gates nos mesmos eventos, que escala a taxa de passagem de producao
(P_PASS_PROD = 3,2%) no lugar da razao das 40 cenas vazias do oficial usada no agg_cascade.py.

Uso: python agg_gate_pass.py [--dataset pi-avancado-v1] [--gate g25l_v1:1] [--tag q1_gate5_low] [--drep 1]
Grava results/<dataset>/gate_pass_summary.json.
"""
from __future__ import annotations

import argparse
import json

import bench53 as b
import bench_decisions as d

THRESHOLDS = (0.20, 0.25, 0.30)
GROUPS = (("indefinido", "sem estado"), ("fp", "REJEITADO"), ("tp", "CONFIRMADO"))
# custo medio por chamada medido no oficial (cascade_summary.json): gate de hoje, Decisions, detail recomendado
C_GATE, C_DGATE, C_DETAIL = 0.00110, 0.00021, 0.0169
C_DETAIL_HOJE = 0.0108      # detail de producao (d25f_v1), para a base "producao de hoje"


def frac(votes: dict[str, int], events) -> dict:
    out = {}
    for key, name in (("total", "total"),) + GROUPS:
        sub = [votes[e["event_id"]] for e in events if e["event_id"] in votes
               and (key == "total" or e["category"] == key)]
        out[name] = {"passa": sum(sub), "n": len(sub), "pct": round(100 * sum(sub) / len(sub), 1) if sub else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="pi-avancado-v1")
    ap.add_argument("--gate", default="g25l_v1:1")
    ap.add_argument("--tag", default="q1_gate5_low")
    ap.add_argument("--drep", type=int, default=1)
    ap.add_argument("--question", default="deposit")
    a = ap.parse_args()
    b.DS["name"] = a.dataset
    events = b.load_events()
    garm, grep_ = b.parse_ref(a.gate)
    gp, dp = b.out_path("gate", garm, grep_), d.dgate_path(a.tag, a.drep)
    gate = {k: int(r.get("fire") == 1) for k, r in b.latest_ok(gp).items()} if gp.exists() else {}
    dg = b.latest_ok(dp) if dp.exists() else {}
    probs = {k: d.prob(r, a.question) for k, r in dg.items()}
    probs = {k: p for k, p in probs.items() if p is not None}

    out = {"dataset": a.dataset, "n_eventos": len(events), "gate_hoje": a.gate, "dgate": f"{a.tag}:{a.drep}",
           "ressalva": "fracao absoluta nao e a de producao (amostra com ~24% de deteccoes); usar a razao entre os gates",
           "gates": {}}
    print(f"{a.dataset}: {len(events)} eventos; gate de hoje em {len(gate)}, Decisions em {len(probs)}")
    print("gate | total | " + " | ".join(n for _, n in GROUPS))
    rows = {}
    if gate:
        rows[a.gate] = gate
    for thr in THRESHOLDS:
        rows[f"decisions_t{int(round(thr * 100)):02d}"] = {k: int(p >= thr) for k, p in probs.items()}
    for name, votes in rows.items():
        f = frac(votes, events)
        out["gates"][name] = f
        print(f"{name} | " + " | ".join(f"{f[n]['passa']}/{f[n]['n']} = {f[n]['pct']}%" for n in ("total",) + tuple(n for _, n in GROUPS)))

    if gate and probs:
        both = [e["event_id"] for e in events if e["event_id"] in gate and e["event_id"] in probs]
        g_pass = sum(gate[k] for k in both)
        base_cost = C_GATE + b.P_PASS_PROD * C_DETAIL
        out["razao"] = {"n_comum": len(both), "gate_hoje_passa": g_pass, "custo_evento_hoje_recomendado": round(base_cost, 6)}
        print(f"\nnos {len(both)} eventos em comum, o gate de hoje passa {g_pass}; projecao de producao = "
              f"{100 * b.P_PASS_PROD:.1f}% x razao; custo por evento com o detail recomendado "
              f"(gate de hoje: US$ {base_cost:.5f}):")
        for thr in THRESHOLDS:
            name = f"decisions_t{int(round(thr * 100)):02d}"
            d_pass = sum(rows[name][k] for k in both)
            so_d = sum(1 for k in both if rows[name][k] and not gate[k])
            so_g = sum(1 for k in both if gate[k] and not rows[name][k])
            ratio = d_pass / g_pass if g_pass else None
            p = b.P_PASS_PROD * ratio if ratio is not None else None
            cost = C_DGATE + p * C_DETAIL if p is not None else None
            out["razao"][name] = {"passa": d_pass, "so_decisions": so_d, "so_gate_hoje": so_g,
                                  "razao": round(ratio, 3) if ratio is not None else None,
                                  "p_prod": round(p, 4) if p is not None else None,
                                  "custo_evento": round(cost, 6) if cost is not None else None,
                                  "vs_gate_hoje_pct": round(100 * (cost / base_cost - 1), 1) if cost is not None else None}
            r = out["razao"][name]
            print(f"  {name}: passa {d_pass} (so ele {so_d}, so o de hoje {so_g}); razao {r['razao']}; "
                  f"p = {100 * p:.1f}%; US$ {cost:.5f} por evento ({r['vs_gate_hoje_pct']:+.0f}%)"
                  if p is not None else f"  {name}: passa {d_pass}")
        # A razao depende do MIX da amostra: aqui ~22% dos eventos tem deteccao (REJEITADO/CONFIRMADO),
        # onde o gate de hoje passa muito; em producao sao ~2%. Por isso a mesma conta so nos eventos
        # "sem estado" (o tipo que domina a producao), e o custo contra a producao de hoje
        # (gate de hoje + detail de hoje, a base do agg_cascade.py).
        prod_today = C_GATE + b.P_PASS_PROD * C_DETAIL_HOJE
        cat = {e["event_id"]: e["category"] for e in events}
        se = [k for k in both if cat[k] == "indefinido"]
        g_se = sum(gate[k] for k in se)
        out["producao_hoje_custo_evento"] = round(prod_today, 6)
        out["razao_sem_estado"] = {"n": len(se), "gate_hoje_passa": g_se}
        print(f"\ncontra a producao de hoje (gate de hoje + detail de hoje, US$ {prod_today:.5f} por evento); "
              f"razao no total da amostra e so nos {len(se)} eventos sem estado (gate de hoje passa {g_se}):")
        for thr in THRESHOLDS:
            name = f"decisions_t{int(round(thr * 100)):02d}"
            r_tot = out["razao"][name]
            cost_tot = r_tot["custo_evento"]
            r_tot["vs_producao_hoje_pct"] = round(100 * (cost_tot / prod_today - 1), 1) if cost_tot is not None else None
            d_se = sum(rows[name][k] for k in se)
            ratio = d_se / g_se if g_se else None
            p = b.P_PASS_PROD * ratio if ratio is not None else None
            cost = C_DGATE + p * C_DETAIL if p is not None else None
            out["razao_sem_estado"][name] = {
                "passa": d_se, "razao": round(ratio, 3) if ratio is not None else None,
                "p_prod": round(p, 4) if p is not None else None,
                "custo_evento": round(cost, 6) if cost is not None else None,
                "vs_producao_hoje_pct": round(100 * (cost / prod_today - 1), 1) if cost is not None else None}
            s = out["razao_sem_estado"][name]
            if p is not None and cost_tot is not None:
                print(f"  {name}: total razao {r_tot['razao']} -> US$ {cost_tot:.5f} ({r_tot['vs_producao_hoje_pct']:+.0f}%)"
                      f" | sem estado: passa {d_se}, razao {s['razao']}, p = {100 * p:.1f}% -> "
                      f"US$ {cost:.5f} ({s['vs_producao_hoje_pct']:+.0f}%)")
        print("  (com so " + str(g_se) + " eventos sem estado passando no gate de hoje, a razao por estrato e grosseira: "
              "serve para mostrar a faixa, nao para fixar um numero)")
    elif not gate:
        print(f"\nfalta o gate de hoje neste conjunto ({gp.name}): a razao entre os gates so fecha quando ele rodar.")
    (b.out_dir() / "gate_pass_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    b.DS["name"] = "official"


if __name__ == "__main__":
    main()
