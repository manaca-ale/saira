#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — deteccoes confirmadas que um braco de gate perde, e o que os bracos de referencia fizeram nelas.

Uma linha por deteccao confirmada (S2C) que o braco NAO mantem (nenhum evento dela dispara no limiar dado):
os eventos, a resposta do braco (cena, confianca crua, evidence) e se cada referencia disparou.
Com --sheet grava a lista no formato do make_sheets54.py (evento<TAB>legenda) para olhar os frames.

Uso: python misses_gate54.py --arm dsf_v1p_low_ctx [--conf 0] [--refs g25l_v1_t2048_ctx,nvl_v1p_low_ctx] [--sheet lista.txt]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from agg_dgate54 import RESULTS


def load(arm, rep=1):
    out = {}
    for line in (RESULTS / f"gate54__{arm}__r{rep}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error"):
                out[r["event_id"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--conf", type=int, default=85)
    ap.add_argument("--refs", default="g25l_v1_t2048_ctx,g31l_v1p_min_low_ctx,nvl_v1p_low_ctx")
    ap.add_argument("--sheet", default="")
    a = ap.parse_args()

    fire = lambda r, c: bool(r["new_litter"]) and r["conf"] >= c  # noqa: E731
    mine = load(a.arm)
    refs = {k: load(k) for k in a.refs.split(",") if k}
    dets = defaultdict(list)
    for r in mine.values():
        if r["sub"] == "S2C":
            dets[r["detection_id"] or r["event_id"]].append(r)
    lost = {d: rs for d, rs in dets.items() if not any(fire(r, a.conf) for r in rs)}
    print(f"{a.arm} (limiar {a.conf}): {len(dets) - len(lost)}/{len(dets)} confirmadas mantidas; perdidas: {len(lost)}")
    rows = []
    for d, rs in sorted(lost.items(), key=lambda kv: kv[1][0]["event_id"]):
        kept = {k: any(e["event_id"] in v and fire(v[e["event_id"]], 85) for e in rs) for k, v in refs.items()}
        print(f"\ndeteccao {str(d)[:12]} ({len(rs)} evento(s)) | " + ", ".join(f"{k}: {'sim' if x else 'nao'}" for k, x in kept.items()))
        for r in sorted(rs, key=lambda r: r["event_id"]):
            print(f"  {r['event_id']} cena={r['scene_type']} sim_cru={int(r['new_litter_raw'])} conf={r['conf_raw']} "
                  f"aviso={r.get('prior_type')}: {r['evidence']}")
            rows.append(f"{r['event_id']}\t{a.arm} {r['scene_type']} conf {r['conf_raw']} | "
                        + " ".join(f"{k.split('_')[0]}={'S' if x else 'N'}" for k, x in kept.items()))
    if a.sheet:
        with open(a.sheet, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(rows) + "\n")
        print(f"\nlista para o make_sheets54.py: {a.sheet} ({len(rows)} eventos)")


if __name__ == "__main__":
    main()
