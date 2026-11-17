#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — repetibilidade do gate de producao (sem custo): o mesmo gate, os mesmos eventos,
repeticoes em dias/horas diferentes. Mostra, por repeticao, quantas deteccoes reais e falsas e
quantas cenas vazias passam, e quantos eventos mudam de voto entre repeticoes.

Uso: python agg_gate_reps.py [--arm g25l_v1] [--dataset official]
Grava results/gate_reps_summary.json.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

import bench53 as b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="g25l_v1")
    ap.add_argument("--dataset", default="official")
    a = ap.parse_args()
    b.DS["name"] = a.dataset
    reps = {}
    for p in sorted(b.out_dir().glob(f"gate__{a.arm}__r*.jsonl")):
        rep = int(p.stem.rsplit("__r", 1)[1])
        if rep:
            reps[rep] = b.latest_ok(p)
    events = b.load_events()
    out = {"arm": a.arm, "dataset": a.dataset, "reps": {}, "flips": {}}
    print(f"gate {a.arm} em {a.dataset}: repeticoes {sorted(reps)}")
    for rep, g in reps.items():
        def det(cat):
            byd: dict[str, list[int]] = {}
            for ev in events:
                if ev["category"] == cat and ev["event_id"] in g:
                    byd.setdefault(ev["det_id"], []).append(int(g[ev["event_id"]].get("fire") == 1))
            return sum(1 for v in byd.values() if any(v)), len(byd)

        def evt(cat):
            sub = [g[ev["event_id"]] for ev in events if ev["category"] == cat and ev["event_id"] in g]
            return sum(1 for r in sub if r.get("fire") == 1), len(sub)

        row = {"tp_det": "%d/%d" % det("tp"), "fp_det": "%d/%d" % det("fp"),
               "tp_evt": "%d/%d" % evt("tp"), "fp_evt": "%d/%d" % evt("fp"),
               "indefinido_evt": "%d/%d" % evt("indefinido"), "baseline_evt": "%d/%d" % evt("baseline"),
               "ts": min(r["ts"] for r in g.values()),
               "cost_per_call": round(sum(r.get("cost_usd") or 0 for r in g.values()) / len(g), 6)}
        out["reps"][rep] = row
        print(f"  rep {rep} ({row['ts']}): reais {row['tp_det']} det. ({row['tp_evt']} eventos) | "
              f"falsos {row['fp_det']} det. ({row['fp_evt']} eventos) | indefinidos {row['indefinido_evt']} | "
              f"vazias {row['baseline_evt']} | US$ {row['cost_per_call']:.5f} por chamada")
    # eventos que mudam de voto
    n = len(reps)
    for cat in ("tp", "fp", "indefinido", "baseline"):
        votes = Counter()
        unstable = []
        for ev in events:
            if ev["category"] != cat:
                continue
            v = [int(g[ev["event_id"]].get("fire") == 1) for g in reps.values() if ev["event_id"] in g]
            if len(v) != n:
                continue
            votes[sum(v)] += 1
            if 0 < sum(v) < n:
                unstable.append({"event_id": ev["event_id"], "det_id": ev["det_id"][:8], "votos": v})
        out["flips"][cat] = {"por_numero_de_sins": dict(sorted(votes.items())), "instaveis": unstable}
        tot = sum(votes.values())
        print(f"  {cat}: {len(unstable)}/{tot} eventos mudam de voto entre as {n} repeticoes; "
              f"eventos por numero de 'sim': {dict(sorted(votes.items()))}")
    # deteccoes reais que algum rep perde
    lost = {}
    for rep, g in reps.items():
        byd: dict[str, list[int]] = {}
        for ev in events:
            if ev["category"] == "tp" and ev["event_id"] in g:
                byd.setdefault(ev["det_id"][:8], []).append(int(g[ev["event_id"]].get("fire") == 1))
        lost[rep] = sorted(d for d, v in byd.items() if not any(v))
    out["tp_det_perdidas"] = lost
    print(f"  deteccoes reais que o gate nao passa, por repeticao: {lost}")
    b.DS["name"] = "official"
    (b.RESULTS / "gate_reps_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
