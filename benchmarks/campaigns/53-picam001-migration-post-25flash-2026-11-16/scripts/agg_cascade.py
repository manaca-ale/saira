#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — cascatas completas lado a lado (sem custo): gate de producao x gate Decisions,
detail atual x detail recomendado, nos dois conjuntos.

Custo por evento no mix de producao = custo_gate + p_passa * custo_detail. A taxa de passagem
de producao do gate ATUAL e 2,2% (derivada do custo medido; ver bench53.P_PASS_PROD). Para
outro gate ela e escalada pela razao de passagem nas cenas VAZIAS do dataset oficial (40
eventos `baseline`), que sao o tipo de evento que domina a producao:

    p(gate) = 2,2% * vazias_que_passam(gate) / vazias_que_passam(gate atual)

E uma projecao, nao uma medida: so um shadow em producao da o numero real.

Uso: python agg_cascade.py
"""
from __future__ import annotations

import json

import bench53 as b

GATES = ["g25l_v1:1", "gdec_q1_gate5_low_deposit_t20:1", "gdec_q1_gate5_low_deposit_t25:1",
         "gdec_q1_gate5_low_deposit_t30:1", "gdec_q1_gate5_low_deposit_t40:1"]
DETAILS = ["d25f_v1:1", "d38f_g3_low_low:1"]
# Sem coluna de 2027: no Vertex o 3.8-flash ja custa 1,50 / 7,50 (catalogo de cobranca de
# 2026-11-17), que e o valor que a pagina do AI Studio anuncia para 2027. Nao ha aumento
# conhecido adiante.


def exists(stage, ref):
    arm, rep = b.parse_ref(ref)
    return b.out_path(stage, arm, rep).exists()


def baseline_pass(gate_ref):
    arm, rep = b.parse_ref(gate_ref)
    g = b.latest_ok(b.out_path("gate", arm, rep))
    bl = [r for r in g.values() if r["category"] == "baseline"]
    return (sum(r["fire"] for r in bl), len(bl)) if bl else (None, 0)


def main():
    out = {}
    # 1) taxa de passagem projetada, pelo dataset oficial
    b.DS["name"] = "official"
    ref_pass, n_bl = baseline_pass("g25l_v1:1")
    p_prod = {}
    for g in GATES:
        if exists("gate", g):
            k, n = baseline_pass(g)
            p_prod[g] = b.P_PASS_PROD * (k / ref_pass) if ref_pass else b.P_PASS_PROD
    print("taxa de passagem projetada em producao (escala pelas cenas vazias do oficial):")
    for g, p in p_prod.items():
        k, n = baseline_pass(g)
        print(f"  {g}: vazias {k}/{n} -> p = {100 * p:.1f}%")
    base_cost = None
    for ds in ("official", "pi-inicial-v1"):
        b.DS["name"] = ds
        print(f"\n=== {ds} ===")
        print("gate | detail | recall (det.) | IC95 | falsos (det.) | vazias | gate passa reais / falsos | "
              "US$ gate | US$ detail | US$ evento | vs atual | faltam")
        rows = []
        for g in GATES:
            for d in DETAILS:
                if not (exists("gate", g) and exists("detail", d)):
                    continue
                s = b.score_pair(g, d, quiet=True)
                if not s["n_events"]:
                    continue
                p = p_prod.get(g, b.P_PASS_PROD)
                ev = s["cost_gate_per_call"] + p * s["cost_detail_per_call"]
                if ds == "official" and g == "g25l_v1:1" and d == "d25f_v1:1":
                    base_cost = ev
                rows.append((g, d, s, ev))
        for g, d, s, ev in rows:
            rel = f"{100 * (ev / base_cost - 1):+.0f}%" if base_cost else "?"
            # tp/fp/baseline que disparam o gate mas nao tem detail: o par esta incompleto
            flag = f"{s['missing_detail']}" if s["missing_detail"] else "0"
            print(f"{g} | {d} | {s['tp_det']} = {s['recall_det']}% | {s['recall_det_ci95']} | "
                  f"{s['fp_det']} | {s['baseline']} | {s['gate_pass_tp_det']} / {s['gate_pass_fp_det']} | "
                  f"{s['cost_gate_per_call']:.5f} | {s['cost_detail_per_call']:.4f} | {ev:.5f} | {rel} | "
                  f"{flag}")
            out.setdefault(ds, []).append({
                "gate": g, "detail": d, "tp_det": s["tp_det"], "recall_det": s["recall_det"],
                "recall_ci95": s["recall_det_ci95"], "fp_det": s["fp_det"], "baseline": s["baseline"],
                "gate_pass_tp_det": s["gate_pass_tp_det"], "gate_pass_fp_det": s["gate_pass_fp_det"],
                "cost_gate": s["cost_gate_per_call"], "cost_detail": s["cost_detail_per_call"],
                "p_pass_prod": round(p_prod.get(g, b.P_PASS_PROD), 4),
                "cost_event": round(ev, 6), "vs_current": rel,
                "missing_detail": s["missing_detail"]})
    b.DS["name"] = "official"
    (b.RESULTS / "cascade_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n'faltam' = eventos que disparam o gate e nao tem detail (inclui `indefinido`, que nao "
          "pontua); se algum tp/fp/baseline faltar, rodar o detail com --events-from <gate>.")


if __name__ == "__main__":
    main()
