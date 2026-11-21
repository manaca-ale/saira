#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — repetibilidade do gate Decisions (sem custo): a mesma configuracao, os mesmos
eventos, repeticoes em horas/dias diferentes. Compara as probabilidades de cada pergunta
contra a primeira repeticao e conta quantos eventos trocam de lado em cada limiar.

Uso: python agg_dgate_reps.py [--tag q1_gate5_low] [--dataset official]
Grava results/dgate_reps_summary.json.
"""
from __future__ import annotations

import argparse
import json

import bench53 as b
import bench_decisions as d

THRESHOLDS = (0.20, 0.25, 0.30, 0.40, 0.50)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="q1_gate5_low")
    ap.add_argument("--dataset", default="official")
    ap.add_argument("--question", default="deposit")
    a = ap.parse_args()
    b.DS["name"] = a.dataset
    reps = {}
    for p in sorted(b.out_dir().glob(f"dgate__{a.tag}__r*.jsonl")):
        rep = int(p.stem.rsplit("__r", 1)[1])
        if rep:
            reps[rep] = b.latest_ok(p)
    first = min(reps)
    ref = reps[first]
    questions = sorted((next(iter(ref.values())).get("answers") or {}))
    out = {"tag": a.tag, "dataset": a.dataset, "referencia": first,
           "ts": {r: min(x["ts"] for x in g.values()) for r, g in reps.items()}, "contra_referencia": {}}
    print(f"dgate {a.tag} em {a.dataset}: repeticoes {sorted(reps)} (referencia: rep {first}, {out['ts'][first]})")
    for rep, g in reps.items():
        if rep == first:
            continue
        common = [e for e in ref if e in g]
        row = {"eventos": len(common), "max_abs_diff": {}, "eventos_com_diferenca": {}, "trocas_de_lado": {}}
        for q in questions:
            diffs = [abs(d.prob(ref[e], q) - d.prob(g[e], q)) for e in common
                     if d.prob(ref[e], q) is not None and d.prob(g[e], q) is not None]
            row["max_abs_diff"][q] = max(diffs) if diffs else None
            row["eventos_com_diferenca"][q] = sum(1 for x in diffs if x > 0)
        for t in THRESHOLDS:
            flips = [e for e in common
                     if (d.prob(ref[e], a.question) >= t) != (d.prob(g[e], a.question) >= t)]
            row["trocas_de_lado"][f"{t:.2f}"] = flips
        out["contra_referencia"][rep] = row
        worst = max((v or 0) for v in row["max_abs_diff"].values())
        nflip = {t: len(v) for t, v in row["trocas_de_lado"].items()}
        print(f"  rep {rep} ({out['ts'][rep]}): {len(common)} eventos; maior diferenca de probabilidade "
              f"(qualquer pergunta) = {worst:.2e}; eventos com '{a.question}' diferente = "
              f"{row['eventos_com_diferenca'][a.question]}; trocas de lado por limiar = {nflip}")
    b.DS["name"] = "official"
    (b.RESULTS / "dgate_reps_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
