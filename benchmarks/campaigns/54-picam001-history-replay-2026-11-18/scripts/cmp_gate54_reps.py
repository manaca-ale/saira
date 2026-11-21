#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — SEM CUSTO: compara duas repeticoes do mesmo braco do gate (r1 e r2) evento a evento.

Para que serve: (1) saber quanto o "sim" do gate se repete (a campanha 51 mediu que, ao longo de dias,
os "sim" de um gate Gemini so se repetem cerca de metade das vezes; os "nao", quase todos);
(2) comparar a latencia quando uma repeticao rodou em Flex e a outra em modo padrao.

Uso: python cmp_gate54_reps.py --arm g31l_v1p_min_low [--a 1 --b 2]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"


def load(arm: str, rep: int) -> dict:
    out = {}
    for line in (RESULTS / f"gate54__{arm}__r{rep}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error"):
                out[r["event_id"]] = r
    return out


def pct(lat, q):
    return lat[min(len(lat) - 1, int(len(lat) * q))] / 1000 if lat else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--a", type=int, default=1)
    ap.add_argument("--b", type=int, default=2)
    a = ap.parse_args()
    A, B = load(a.arm, a.a), load(a.arm, a.b)
    common = sorted(set(A) & set(B))
    print(f"{a.arm}: r{a.a} = {len(A)} eventos, r{a.b} = {len(B)}, em comum = {len(common)}")
    for name, recs in ((f"r{a.a}", A), (f"r{a.b}", B)):
        mine = [recs[e] for e in common]
        lat = sorted(r["latency_ms"] for r in mine)
        flex = sum(1 for r in mine if r.get("flex_requested"))
        print(f"  {name}: Flex pedido em {flex}/{len(mine)} | latencia p50 {pct(lat, 0.5):.1f} s, p90 {pct(lat, 0.9):.1f} s, "
              f"p99 {pct(lat, 0.99):.1f} s, maxima {lat[-1] / 1000:.1f} s | acima de 15 s: {sum(1 for x in lat if x > 15000)}")
    by = defaultdict(lambda: [0, 0, 0, 0])   # sub -> [n, sim em A, sim em B, sim nos dois]
    dets = defaultdict(lambda: [False, False])
    for e in common:
        s = A[e]["sub"]
        fa, fb = bool(A[e]["fire"]), bool(B[e]["fire"])
        row = by[s]
        row[0] += 1
        row[1] += fa
        row[2] += fb
        row[3] += fa and fb
        if s == "S2C":
            d = dets[A[e]["detection_id"] or e]
            d[0] |= fa
            d[1] |= fb
    for s in ("S2C", "S2R", "S1", "S0"):
        n, fa, fb, both = by[s]
        if n:
            agree = sum(1 for e in common if A[e]["sub"] == s and bool(A[e]["fire"]) == bool(B[e]["fire"]))
            print(f"  {s}: n={n} | dispara r{a.a} {fa}, r{a.b} {fb}, nos dois {both} | mesma resposta em {agree}/{n} "
                  f"({agree / n:.0%}) | dos sim de r{a.a}, repetem {both}/{fa}" + (f" ({both / fa:.0%})" if fa else ""))
    ka = sum(1 for d in dets.values() if d[0])
    kb = sum(1 for d in dets.values() if d[1])
    kab = sum(1 for d in dets.values() if d[0] and d[1])
    kor = sum(1 for d in dets.values() if d[0] or d[1])
    print(f"  deteccoes confirmadas mantidas: r{a.a} {ka}/{len(dets)}, r{a.b} {kb}/{len(dets)}, nas duas {kab}, em alguma {kor}")


if __name__ == "__main__":
    main()
