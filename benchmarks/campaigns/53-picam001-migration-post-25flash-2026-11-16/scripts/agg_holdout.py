#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — agregacao do segundo conjunto (pi-inicial-v1, holdout temporal), sem custo.

O conjunto so tem eventos em que a PRODUCAO criou deteccao. O gate de producao, rodado
de novo, so reproduz parte deles (camp 51), entao a cascata medida hoje fica limitada pelo
gate. Como a migracao troca so o DETAIL, a comparacao que interessa aqui e a do detail
sozinho:

  A) todos os eventos (sem gate): taxa de confirmacao nos CONFIRMADO (retencao) e nos
     REJEITADO (quanto do falso positivo de producao o detail repete);
  B) so os eventos que passaram no gate rodado nesta campanha: os mesmos numeros, lado a
     lado com a linha de base (o 2.5-flash so rodou nesse subconjunto, por custo).

Uso: python agg_holdout.py [--gate g25l_v1:1]
"""
from __future__ import annotations

import argparse
import json

import bench53 as b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="pi-inicial-v1")
    ap.add_argument("--gate", default="g25l_v1:1")
    a = ap.parse_args()
    b.DS["name"] = a.dataset
    events = {e["event_id"]: e for e in b.load_events()}
    garm, grep_ = b.parse_ref(a.gate)
    gate = b.latest_ok(b.out_path("gate", garm, grep_))
    passed = {e for e, r in gate.items() if r.get("fire") == 1}
    n_tp = sum(1 for e in events.values() if e["category"] == "tp")
    n_fp = sum(1 for e in events.values() if e["category"] == "fp")
    g_tp = sum(1 for e in passed if events[e]["category"] == "tp")
    g_fp = sum(1 for e in passed if events[e]["category"] == "fp")
    print(f"dataset={a.dataset} eventos={len(events)} (confirmados {n_tp}, rejeitados {n_fp})")
    print(f"gate {a.gate}: passou {g_tp}/{n_tp} confirmados ({b._rate(g_tp, n_tp)}%, IC {b._wilson(g_tp, n_tp)}) "
          f"e {g_fp}/{n_fp} rejeitados ({b._rate(g_fp, n_fp)}%)")
    out = {"dataset": a.dataset, "gate": a.gate, "gate_pass_tp": f"{g_tp}/{n_tp}",
           "gate_pass_fp": f"{g_fp}/{n_fp}", "arms": []}
    print("\nbraco | escopo | confirmados: detail diz sim | rejeitados: detail diz sim | "
          "US$/chamada | lat. mediana (s)")
    for path in sorted(b.out_dir().glob("detail__*__r*.jsonl")):
        arm = path.name[len("detail__"):-len(".jsonl")].replace("__r", ":")
        det = b.latest_ok(path)
        for scope, ids in (("todos", set(events)), ("passou no gate", passed)):
            sub = [det[e] for e in ids if e in det]
            tp = [r for r in sub if r["category"] == "tp"]
            fp = [r for r in sub if r["category"] == "fp"]
            if not tp and not fp:
                continue
            need_tp = sum(1 for e in ids if events[e]["category"] == "tp")
            need_fp = sum(1 for e in ids if events[e]["category"] == "fp")
            complete = len(tp) == need_tp and len(fp) == need_fp
            tp_yes, fp_yes = sum(r["disposal"] for r in tp), sum(r["disposal"] for r in fp)
            costs = [r["cost_usd"] for r in sub]
            lats = sorted(r["latency_ms"] for r in sub)
            row = {"arm": arm, "scope": scope, "complete": complete,
                   "tp_yes": f"{tp_yes}/{len(tp)}", "tp_rate": b._rate(tp_yes, len(tp)),
                   "tp_ci95": b._wilson(tp_yes, len(tp)),
                   "fp_yes": f"{fp_yes}/{len(fp)}", "fp_rate": b._rate(fp_yes, len(fp)),
                   "fp_ci95": b._wilson(fp_yes, len(fp)),
                   "cost_per_call": round(sum(costs) / len(costs), 6),
                   "latency_p50_s": round(lats[len(lats) // 2] / 1000, 1),
                   "flex": bool(sub[0].get("flex"))}
            out["arms"].append(row)
            flag = "" if complete else " (INCOMPLETO)"
            print(f"{arm} | {scope}{flag} | {row['tp_yes']} = {row['tp_rate']}% ({row['tp_ci95']}) | "
                  f"{row['fp_yes']} = {row['fp_rate']}% ({row['fp_ci95']}) | {row['cost_per_call']} | "
                  f"{row['latency_p50_s']}{' flex' if row['flex'] else ''}")
    (b.out_dir() / "holdout_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
