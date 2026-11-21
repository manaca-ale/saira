#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — olhar por dentro de um braco de gate (missao 4b): o modelo le as imagens?

Complementa o agg_gate54.py (que da disparo por estrato e funil). Aqui: respostas invalidas, latencia
(com o corte de 15 s do worker), distribuicao da confianca crua, resposta crua x pos-regra, cena e sinais,
quantos textos de `evidence` sao distintos e uma amostra deles por estrato.

Uso: python inspect_gate54_arm.py --arm dsf_v1p_low_ctx [--rep 1] [--show 3]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from agg_dgate54 import RESULTS

SUBS = ("S2C", "S2R", "S1", "S0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--show", type=int, default=3)
    a = ap.parse_args()

    last = {}
    for line in (RESULTS / f"gate54__{a.arm}__r{a.rep}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            last[r["event_id"]] = r
    recs = list(last.values())
    ok = [r for r in recs if not r.get("error")]
    bad = [r for r in recs if r.get("error")]
    print(f"{a.arm} r{a.rep}: {len(recs)} eventos, {len(ok)} validos, {len(bad)} com erro")
    for k, n in Counter(r["error"][:60] for r in bad).most_common(5):
        print(f"  erro x{n}: {k}")
    lat = sorted(r["latency_ms"] for r in ok)
    q = lambda p: lat[min(len(lat) - 1, int(len(lat) * p))] / 1000  # noqa: E731
    print(f"latencia: p50 {q(0.5):.1f} s, p90 {q(0.9):.1f} s, p99 {q(0.99):.1f} s, maxima {lat[-1] / 1000:.1f} s; "
          f"acima de 15 s: {sum(x > 15000 for x in lat)}/{len(lat)}")
    print(f"tokens de entrada: {sorted(Counter(r['tok_in'] for r in ok).items())[:6]} | "
          f"saida media {sum(r['tok_out'] for r in ok) / len(ok):.0f}")
    print("confianca crua (valor: n): " + ", ".join(f"{k}: {n}" for k, n in sorted(Counter(r["conf_raw"] for r in ok).items())))

    by = defaultdict(list)
    for r in ok:
        by[r["sub"]].append(r)
    print("\nestrato | n | sim cru | dispara (pos-regra, conf>=85) | cena | veiculo parado | pessoa manuseia | material novo")
    for s in SUBS:
        rs = by[s]
        if not rs:
            continue
        sc = Counter(r["scene_type"] for r in rs).most_common(4)
        print(f"  {s} | {len(rs)} | {sum(r['new_litter_raw'] for r in rs)} | {sum(r['fire'] for r in rs)} | "
              f"{', '.join(f'{k} {n}' for k, n in sc)} | {sum(r['veh_stopped'] for r in rs)} | "
              f"{sum(r['person_handling'] for r in rs)} | {sum(r['new_ground'] for r in rs)}")
    ev = Counter(r["evidence"] for r in ok)
    print(f"\ntextos de evidence distintos: {len(ev)} de {len(ok)}; o mais repetido aparece {ev.most_common(1)[0][1]} vez(es)")
    for s in SUBS:
        for fire in (1, 0):
            rs = sorted((r for r in by[s] if r["fire"] == fire), key=lambda r: r["event_id"])[: a.show]
            for r in rs:
                print(f"  [{s} dispara={fire} conf={r['conf_raw']} cena={r['scene_type']}] {r['event_id'][:40]}: {r['evidence']}")


if __name__ == "__main__":
    main()
