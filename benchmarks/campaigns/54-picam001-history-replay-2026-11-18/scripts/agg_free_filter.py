#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — existe filtro GRATUITO (sem chamada de modelo) antes do gate? (sem custo de API)

Usa so o que o receptor ja grava no manifesto de cada evento: numero de frames, duracao, estatisticas do
gate de movimento da Pi (gate_fg_px, gate_delta_px), hora do dia e intervalo desde o evento anterior.
Compara os eventos em que o gate de producao NAO disparou (S0) com os eventos de deteccoes CONFIRMADAS
(S2C) e mostra, para cada regra simples, que fracao de S0 ela descartaria e quantos confirmados perderia.

Populacao inteira (base_eventos.csv), sem amostragem. Por padrao so a configuracao atual da Pi (de 02/08).
Uso: python agg_free_filter.py [--from-day 2026-08-02]
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Saira\data\historico-picam")


def q(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(p * len(vals)))] if vals else None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-day", default="2026-08-02")
    a = ap.parse_args()
    base = [r for r in csv.DictReader((ROOT / "base" / "base_eventos.csv").open(encoding="utf-8", newline=""))
            if r["dia"] >= a.from_day and r["gate_avaliou"] == "1"]
    base.sort(key=lambda r: r["event_id"])
    rows, prev_end = [], None
    for r in base:
        m = json.loads((ROOT / "extraido" / "events" / f"{r['event_id']}.json").read_text(encoding="utf-8"))
        try:
            t0 = datetime.fromisoformat(m["started_at"])
            t1 = datetime.fromisoformat(m.get("closed_at") or m.get("updated_at") or m["started_at"])
            dur = (t1 - t0).total_seconds()
        except Exception:  # noqa: BLE001
            t0 = t1 = None
            dur = None
        gap = (t0 - prev_end).total_seconds() if (t0 and prev_end) else None
        prev_end = t1 or prev_end
        s = "S0" if r["gate_disparou"] != "1" else ("S1" if r["detail_sim"] != "1" else
                                                    {"CONFIRMADO": "S2C", "REJEITADO": "S2R"}.get(r["status"], "S2X"))
        rows.append({"s": s, "det": r["detection_id"], "n": int(r["n_frames"]), "dur": dur, "gap": gap,
                     "fg": m.get("gate_fg_px"), "delta": m.get("gate_delta_px"), "hora": int(r["hora"] or 0)})
    n = defaultdict(int)
    for r in rows:
        n[r["s"]] += 1
    print(f"eventos avaliados desde {a.from_day}: {len(rows)} | " + ", ".join(f"{k} {n[k]}" for k in sorted(n)))
    print("\nmedianas [p10 - p90] por estrato:")
    for feat, name in (("n", "frames no evento"), ("dur", "duracao (s)"), ("fg", "gate_fg_px"),
                       ("delta", "gate_delta_px"), ("gap", "intervalo desde o evento anterior (s)")):
        line = f"  {name}: "
        for s in ("S0", "S1", "S2C", "S2R"):
            v = [r[feat] for r in rows if r["s"] == s and isinstance(r[feat], (int, float))]
            if v:
                line += f"{s} {statistics.median(v):.0f} [{q(v, 0.1):.0f} - {q(v, 0.9):.0f}] (n={len(v)}) | "
        print(line)

    def rule(name, keep):
        """keep(r) -> True se o evento SEGUE para o gate."""
        s0 = [r for r in rows if r["s"] == "S0"]
        s1 = [r for r in rows if r["s"] == "S1"]
        c = [r for r in rows if r["s"] == "S2C"]
        rj = [r for r in rows if r["s"] == "S2R"]
        byd = defaultdict(list)
        for r in c:
            byd[r["det"]].append(keep(r))
        allr = len(rows)
        drop = sum(1 for r in rows if not keep(r))
        print(f"  {name}: descarta {100 * drop / allr:.1f}% dos eventos | S0 descartados {100 * sum(not keep(r) for r in s0) / len(s0):.1f}% | "
              f"S1 {100 * sum(not keep(r) for r in s1) / max(1, len(s1)):.0f}% | confirmados perdidos: eventos "
              f"{sum(not keep(r) for r in c)}/{len(c)}, deteccoes {sum(1 for v in byd.values() if not any(v))}/{len(byd)} | "
              f"rejeitados descartados {100 * sum(not keep(r) for r in rj) / max(1, len(rj)):.0f}%")

    print("\nregras simples (o evento so vai ao gate se...):")
    for k in (4, 6, 8, 10, 12, 15):
        rule(f"frames >= {k}", lambda r, k=k: r["n"] >= k)
    for k in (10, 15, 20, 30, 40):
        rule(f"duracao >= {k} s", lambda r, k=k: r["dur"] is None or r["dur"] >= k)
    fgv = [r["fg"] for r in rows if isinstance(r["fg"], (int, float))]
    if fgv:
        for p in (0.2, 0.3, 0.4, 0.5):
            thr = q(fgv, p)
            rule(f"gate_fg_px >= {thr:.0f} (percentil {int(p * 100)})",
                 lambda r, thr=thr: not isinstance(r["fg"], (int, float)) or r["fg"] >= thr)
    dv = [r["delta"] for r in rows if isinstance(r["delta"], (int, float))]
    if dv:
        for p in (0.2, 0.3, 0.4, 0.5):
            thr = q(dv, p)
            rule(f"gate_delta_px >= {thr:.0f} (percentil {int(p * 100)})",
                 lambda r, thr=thr: not isinstance(r["delta"], (int, float)) or r["delta"] >= thr)

    print("\npor hora do dia: eventos | confirmados (eventos)")
    byh = defaultdict(lambda: [0, 0])
    for r in rows:
        byh[r["hora"]][0] += 1
        byh[r["hora"]][1] += int(r["s"] == "S2C")
    print("  " + " ".join(f"{h:02d}h:{v[0]}|{v[1]}" for h, v in sorted(byh.items())))
    night = [h for h, v in byh.items() if v[1] == 0]
    print(f"  horas sem nenhum confirmado: {sorted(night)} = {100 * sum(byh[h][0] for h in night) / len(rows):.1f}% dos eventos")


if __name__ == "__main__":
    main()
