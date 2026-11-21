#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54, missao 9 — o detail de hoje repetido no VERTEX contra o AI Studio e contra a producao.

Sem custo: le results/detail54__d25f_v1_vtx__r1.jsonl (Vertex), detail54__d25f_v1__r1/r2.jsonl (AI Studio)
e o registro de chamadas de producao (copia local em C:\\Saira\\data\\historico-picam). Nos S1 a producao
disse "nao" por definicao. A chamada de detail de producao e achada pelo horario: a primeira chamada
`detail` com sucesso ate 180 s depois da chamada do gate do evento.

Uso: python cmp_detail54_vtx.py > ../results/cmp_detail54_vtx__s1.txt
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from bisect import bisect_right
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"C:\Saira\data\historico-picam")
RES = Path(__file__).resolve().parent.parent / "results"


def read_ok(name):
    out = {}
    for line in (RES / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error"):
                out[r["event_id"]] = r
    return out


def ts(s):
    return dt.datetime.fromisoformat(s[:19])


def main():
    vx = read_ok("detail54__d25f_v1_vtx__r1.jsonl")
    a1 = read_ok("detail54__d25f_v1__r1.jsonl")
    a2 = read_ok("detail54__d25f_v1__r2.jsonl")
    base = {}
    with (ROOT / "base" / "base_eventos.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["event_id"] in vx:
                base[r["event_id"]] = r
    gate_at, details = {}, []
    want = {b["agent1_request_id"]: e for e, b in base.items()}
    with (ROOT / "raw" / "gemini_call_log_picam.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["agent"] == "gate" and r["request_id"] in want:
                gate_at[want[r["request_id"]]] = ts(r["called_at"])
            elif r["agent"] == "detail" and r["success"] == "t" and r["input_tokens"]:
                details.append((ts(r["called_at"]), int(r["input_tokens"]), int(r["output_tokens"]),
                                int(r["total_tokens"])))
    details.sort()
    keys = [d[0] for d in details]
    prod = {}
    for e, t in gate_at.items():
        i = bisect_right(keys, t)
        if i < len(details) and (details[i][0] - t).total_seconds() <= 180:
            prod[e] = details[i]

    evs = sorted(vx)
    print(f"eventos S1 no Vertex: {len(evs)} | com chamada de detail de producao achada: {len(prod)}")
    print(f"sim: Vertex {sum(vx[e]['disposal'] for e in evs)} | AI Studio r1 {sum(a1[e]['disposal'] for e in evs)} "
          f"| AI Studio r2 {sum(a2[e]['disposal'] for e in evs)} | producao 0 (definicao de S1)")
    print(f"sim BRUTO (antes do veto do bbox): Vertex {sum(vx[e]['raw_disposal'] for e in evs)} | r1 "
          f"{sum(a1[e]['raw_disposal'] for e in evs)} | r2 {sum(a2[e]['raw_disposal'] for e in evs)}")
    tab = Counter((a1[e]["disposal"], a2[e]["disposal"], vx[e]["disposal"]) for e in evs)
    print("\n(AI Studio r1, AI Studio r2, Vertex) -> eventos")
    for k, v in sorted(tab.items(), reverse=True):
        print(f"  {k}: {v}")
    stable_yes = [e for e in evs if a1[e]["disposal"] and a2[e]["disposal"]]
    stable_no = [e for e in evs if not a1[e]["disposal"] and not a2[e]["disposal"]]
    print(f"\nnos {len(stable_yes)} 'sim' estaveis do AI Studio: Vertex sim {sum(vx[e]['disposal'] for e in stable_yes)}, "
          f"nao {sum(1 - vx[e]['disposal'] for e in stable_yes)}")
    print(f"nos {len(stable_no)} 'nao' estaveis do AI Studio: Vertex sim {sum(vx[e]['disposal'] for e in stable_no)}, "
          f"nao {sum(1 - vx[e]['disposal'] for e in stable_no)}")
    agree = lambda x, y: sum(x[e]["disposal"] == y[e]["disposal"] for e in evs)  # noqa: E731
    print(f"concordancia: Vertex x r1 {agree(vx, a1)}/30 | Vertex x r2 {agree(vx, a2)}/30 | r1 x r2 {agree(a1, a2)}/30 "
          f"| Vertex x producao {sum(1 - vx[e]['disposal'] for e in evs)}/30 | r1 x producao "
          f"{sum(1 - a1[e]['disposal'] for e in evs)}/30 | r2 x producao {sum(1 - a2[e]['disposal'] for e in evs)}/30")

    print("\ntokens de entrada (mesmo evento): Vertex - producao, e Vertex - AI Studio")
    d_prod = Counter(vx[e]["tok_in"] - prod[e][1] for e in evs if e in prod)
    d_ais = Counter(vx[e]["tok_in"] - a2[e]["tok_in"] for e in evs)
    print(f"  Vertex - producao: {dict(sorted(d_prod.items()))}")
    print(f"  Vertex - AI Studio r2: {dict(sorted(d_ais.items()))}")
    th_prod = [prod[e][3] - prod[e][1] - prod[e][2] for e in evs if e in prod]
    th_vx = [vx[e]["tok_think"] for e in evs]
    th_a2 = [a2[e]["tok_think"] for e in evs]
    out_prod = [prod[e][2] for e in evs if e in prod]
    mean = lambda xs: sum(xs) / len(xs) if xs else float("nan")  # noqa: E731
    print(f"  pensamento medio: producao {mean(th_prod):.0f} | Vertex {mean(th_vx):.0f} | AI Studio r2 {mean(th_a2):.0f}")
    print(f"  saida media: producao {mean(out_prod):.0f} | Vertex {mean([vx[e]['tok_out'] for e in evs]):.0f} | "
          f"AI Studio r2 {mean([a2[e]['tok_out'] for e in evs]):.0f}")
    print(f"  custo medio por chamada: Vertex US$ {mean([vx[e]['cost_usd'] for e in evs]):.5f} | AI Studio r2 "
          f"US$ {mean([a2[e]['cost_usd'] for e in evs]):.5f}")
    lat = sorted(vx[e]["latency_ms"] for e in evs)
    print(f"  latencia no Vertex, modo padrao: p50 {lat[len(lat) // 2] / 1000:.1f} s, p90 "
          f"{lat[int(0.9 * len(lat))] / 1000:.1f} s, max {lat[-1] / 1000:.1f} s")

    print("\nevento | quadros | producao | r1 | r2 | Vertex (bruto, conf) | tok_in prod / Vertex | dia")
    for e in evs:
        p = prod.get(e)
        print(f"  {e} | {vx[e]['n_sent']:>2} | nao | {'SIM' if a1[e]['disposal'] else 'nao'} | "
              f"{'SIM' if a2[e]['disposal'] else 'nao'} | {'SIM' if vx[e]['disposal'] else 'nao'} "
              f"({vx[e]['raw_disposal']}, {vx[e]['conf']}) | {p[1] if p else '-'} / {vx[e]['tok_in']}")


if __name__ == "__main__":
    main()
