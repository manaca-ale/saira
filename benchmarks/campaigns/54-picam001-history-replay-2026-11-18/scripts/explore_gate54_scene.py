#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — SEM CUSTO: o que cada braco do gate respondeu (cena e justificativa) nos eventos do `tri`.

Serve para achar a CAUSA de um numero, em cima das respostas ja gravadas (gate54__<braco>__r1.jsonl):

  1) cena (scene_type) por braco nos eventos de deteccoes confirmadas e nos S0;
  2) --never: as confirmadas que NENHUM dos bracos escolhidos dispara, com a justificativa de cada um
     e a do controle (g25l_v1_t2048);
  3) --arm X: os S0 em que o braco X dispara e as confirmadas que ele perde, com a justificativa.

Achado de 19/11/2026 que motivou o script: com o prompt V1, os Gemini 3 nao disparam nas confirmadas a
pe, de carrinho de mao e de carroca porque leem ao pe da letra "A vehicle is STOPPED and a person is
ACTIVELY depositing" ("no vehicle is stopped for illegal dumping"). Ver prompts54.py (v1p).

Uso:
  python explore_gate54_scene.py --never g31l_v1_low_low,g35l_v1_min_low,g38f_v1_low_low
  python explore_gate54_scene.py --arm g31l_v1p_min_low
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
CTRL = "g25l_v1_t2048"


def load(arm: str) -> dict:
    out = {}
    path = RESULTS / f"gate54__{arm}__r1.jsonl"
    if not path.exists():
        raise SystemExit(f"sem resultado para o braco {arm}: {path.name}")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error"):
                out[r["event_id"]] = r
    return out


def fmt(r: dict | None, n: int = 200) -> str:
    if not r:
        return "(sem registro)"
    return (f"{r.get('scene_type')} dispara={r.get('fire')} conf={r.get('conf')} :: "
            f"{(r.get('evidence') or '')[:n]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--never", default="", help="bracos separados por virgula")
    ap.add_argument("--arm", default="")
    a = ap.parse_args()

    ctrl = load(CTRL)
    dets = collections.defaultdict(list)
    for e, r in ctrl.items():
        if r["sub"] == "S2C":
            dets[r["detection_id"]].append(e)

    if a.never:
        arms = {x: load(x) for x in a.never.split(",") if x}
        for name, recs in arms.items():
            c, c0 = collections.Counter(), collections.Counter()
            for r in recs.values():
                key = (r.get("scene_type") or "?").upper() + ("/dispara" if r["fire"] else "")
                if r["sub"] == "S2C":
                    c[key] += 1
                elif r["sub"] == "S0":
                    c0[key] += 1
            print(f"{name}\n  confirmadas (eventos): {dict(c.most_common())}\n  S0: {dict(c0.most_common())}")
        never = [d for d, evs in dets.items()
                 if not any(recs.get(e, {}).get("fire") for recs in arms.values() for e in evs)]
        print(f"\nconfirmadas que nenhum destes bracos dispara: {len(never)} de {len(dets)}")
        for d in never:
            print(f"\n== deteccao {d[:8]}")
            for e in dets[d]:
                print(f"  {e} nota do filtro {ctrl[e]['score']:.2f}\n     controle: {fmt(ctrl.get(e))}")
                for name, recs in arms.items():
                    print(f"     {name}: {fmt(recs.get(e))}")

    if a.arm:
        recs = load(a.arm)
        print(f"\n== S0 em que {a.arm} dispara (nota do filtro; o controle disparou?; sinais veiculo/pessoa/chao)")
        for e, r in sorted(recs.items(), key=lambda kv: -(kv[1]["score"] or 0)):
            if r["sub"] == "S0" and r["fire"]:
                sig = "".join(str(int(bool(r.get(k)))) for k in ("veh_stopped", "person_handling", "new_ground"))
                print(f"  {e} nota={r['score']:.2f} controle={ctrl.get(e, {}).get('fire')} sinais={sig} :: "
                      f"{(r.get('evidence') or '')[:220]}")
        print(f"\n== confirmadas que {a.arm} perde")
        for d, evs in dets.items():
            if not any(recs.get(e, {}).get("fire") for e in evs):
                for e in evs:
                    print(f"  {d[:8]} {e} nota={ctrl[e]['score']:.2f} controle={ctrl[e]['fire']} | {fmt(recs.get(e), 220)}")


if __name__ == "__main__":
    main()
