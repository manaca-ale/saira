#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — o que o Decisions faria na producao real da pi-cam-001 (sem custo de API).

Le os resultados de run_dgate54.py e projeta para a populacao com os pesos REAIS dos estratos
(decisao gravada em producao, 14/07 a 08/09/2026):
  S0 gate nao disparou | S1 disparou, detail nao | S2C/S2R/S2X detail sim (confirmada/rejeitada/outras).

Estruturas (nota = expressao sobre as probabilidades das perguntas; passa se nota >= limiar):
  A  Decisions NO LUGAR do gate:       custo = cD + P(D) * cDetail          (alertas mudam)
  B  Decisions ANTES do gate de hoje:  custo = cD + P(D) * cGate + P(D e G) * cDetail
  C  Decisions DEPOIS do gate de hoje: custo = cGate + P(G) * cD + P(D e G) * cDetail
Em B e C o gate de hoje (decisao gravada) continua decidindo; so se perde o que o Decisions barrar.

Uso:
  python agg_dgate54.py --qset q1 --split dev
  python agg_dgate54.py --qset q1 --split dev --expr "max(deposit, carrying_in)"
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = Path(r"C:\Saira\data\historico-picam\base")
RESULTS = HERE.parent / "results"
# custos REAIS, gemini_call_log da pi-cam-001, 14/07 a 08/09/2026
N_EVT = 31976
C_GATE = 32.8770 / N_EVT
C_DET_OLD = 9.5424 / 1023
C_DET_NEW = C_DET_OLD * (0.016923 / 0.010813)
C_D = 0.00021
TODAY = (32.8770 + 9.5424) / N_EVT
GRID = (0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25, 0.30, 0.35, 0.40, 0.50)


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def auc(pos, neg):
    if not pos or not neg:
        return None
    neg_sorted = sorted(neg)
    import bisect
    wins = 0.0
    for p in pos:
        lo = bisect.bisect_left(neg_sorted, p)
        hi = bisect.bisect_right(neg_sorted, p)
        wins += lo + 0.5 * (hi - lo)
    return wins / (len(pos) * len(neg))


def probs(rec) -> dict:
    out = {}
    for q, ans in (rec.get("answers") or {}).items():
        if not isinstance(ans, dict):
            continue
        if "noul" in ans:
            out[q] = float(ans["noul"])
        elif "score" in ans and isinstance(ans.get("score"), (int, float)):
            out[q] = float(ans["score"])
        if isinstance(ans.get("probabilities"), dict):
            for k, v in ans["probabilities"].items():
                out[f"{q}_{k}"] = float(v)
            if "DUMPING" in ans["probabilities"]:
                out[q] = float(ans["probabilities"]["DUMPING"])
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--qset", default="q1")
    ap.add_argument("--res", default="low")
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--split", default="dev", choices=["dev", "aval", "all"])
    ap.add_argument("--expr", default="deposit", help="nota: expressao Python sobre as perguntas")
    ap.add_argument("--from-day", default="2026-07-14", help="so eventos a partir deste dia (ex.: 2026-08-02)")
    a = ap.parse_args()

    # pesos da populacao
    W = defaultdict(int)
    for r in csv.DictReader((BASE / "base_eventos.csv").open(encoding="utf-8", newline="")):
        if r["dia"] < a.from_day or r["gate_avaliou"] != "1":
            continue
        if r["gate_disparou"] != "1":
            W["S0"] += 1
        elif r["detail_sim"] != "1":
            W["S1"] += 1
        else:
            W[{"CONFIRMADO": "S2C", "REJEITADO": "S2R"}.get(r["status"], "S2X")] += 1
    n_pop = sum(W.values())
    p_gate = (n_pop - W["S0"]) / n_pop

    path = RESULTS / f"dgate54__{a.qset}_gate5_{a.res}__r{a.rep}.jsonl"
    recs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("error") or not r.get("answers"):
            continue
        recs[r["event_id"]] = r
    rows = []
    for r in recs.values():
        if a.split != "all" and r["split"] != a.split:
            continue
        if r["event_id"][4:8] + "-" + r["event_id"][8:10] + "-" + r["event_id"][10:12] < a.from_day:
            continue
        p = probs(r)
        try:
            score = float(eval(a.expr, {"__builtins__": {}, "max": max, "min": min, "abs": abs}, dict(p)))
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"expressao invalida para {r['event_id']}: {exc}; perguntas: {sorted(p)}")
        s = r["estrato"]
        if s == "S2":
            s = {"CONFIRMADO": "S2C", "REJEITADO": "S2R"}.get(r["status"], "S2X")
        rows.append({"id": r["event_id"], "s": s, "det": r.get("detection_id") or r["event_id"], "score": score, "p": p})
    n_s = defaultdict(int)
    for r in rows:
        n_s[r["s"]] += 1
    print(f"qset={a.qset} split={a.split} nota = {a.expr} | desde {a.from_day}")
    print(f"populacao: {n_pop} eventos | " + ", ".join(f"{k} {W[k]} ({100 * W[k] / n_pop:.2f}%)" for k in sorted(W)))
    print(f"amostra medida: {len(rows)} | " + ", ".join(f"{k} {n_s[k]}" for k in sorted(n_s)))
    print(f"custo real de hoje US$ {TODAY:.6f}; gate de hoje + detail recomendado "
          f"{100 * ((C_GATE + p_gate * C_DET_NEW) / TODAY - 1):+.1f}%")

    def rate(s, t):
        sub = [r for r in rows if r["s"] == s]
        return sum(1 for r in sub if r["score"] >= t), len(sub)

    def dets(s, t):
        byd = defaultdict(list)
        for r in rows:
            if r["s"] == s:
                byd[r["det"]].append(r["score"] >= t)
        return sum(1 for v in byd.values() if any(v)), len(byd)

    f = lambda kn: kn[0] / kn[1] if kn[1] else 0.0
    out = {"expr": a.expr, "split": a.split, "n": dict(n_s), "limiares": {}}
    print("\nlimiar | S0 passa [IC95] | S1 passa | confirmadas mantidas: eventos, deteccoes | rejeitadas mantidas: "
          "deteccoes | P(passa) | A custo | B custo [faixa] | C custo")
    for t in GRID:
        r0, r1, rc, rr, rx = (rate(s, t) for s in ("S0", "S1", "S2C", "S2R", "S2X"))
        dc, dr = dets("S2C", t), dets("S2R", t)
        w = {k: W[k] / n_pop for k in ("S0", "S1", "S2C", "S2R", "S2X")}
        lo, hi = wilson(*r0)
        p_fired = w["S1"] * f(r1) + w["S2C"] * f(rc) + w["S2R"] * f(rr) + w["S2X"] * f(rx)
        p_d = w["S0"] * f(r0) + p_fired
        A = C_D + p_d * C_DET_NEW
        B = C_D + p_d * C_GATE + p_fired * C_DET_NEW
        B_lo = C_D + (w["S0"] * lo + p_fired) * C_GATE + p_fired * C_DET_NEW
        B_hi = C_D + (w["S0"] * hi + p_fired) * C_GATE + p_fired * C_DET_NEW
        C = C_GATE + p_gate * C_D + p_fired * C_DET_NEW
        out["limiares"][f"{t:.2f}"] = {"S0": r0, "S1": r1, "S2C_evt": rc, "S2C_det": dc, "S2R_det": dr,
                                       "p_passa": p_d, "A": A / TODAY - 1, "B": B / TODAY - 1,
                                       "B_faixa": [B_lo / TODAY - 1, B_hi / TODAY - 1], "C": C / TODAY - 1}
        print(f"{t:.2f} | {r0[0]}/{r0[1]} = {100 * f(r0):.1f}% [{100 * lo:.1f}-{100 * hi:.1f}] | "
              f"{r1[0]}/{r1[1]} = {100 * f(r1):.0f}% | {rc[0]}/{rc[1]} = {100 * f(rc):.0f}%, {dc[0]}/{dc[1]} = "
              f"{100 * f(dc):.0f}% | {dr[0]}/{dr[1]} = {100 * f(dr):.0f}% | {100 * p_d:.1f}% | "
              f"{100 * (A / TODAY - 1):+.0f}% | {100 * (B / TODAY - 1):+.0f}% [{100 * (B_lo / TODAY - 1):+.0f} a "
              f"{100 * (B_hi / TODAY - 1):+.0f}] | {100 * (C / TODAY - 1):+.0f}%")

    qs = sorted({q for r in rows for q in r["p"]})
    pos = [r for r in rows if r["s"] == "S2C"]
    print("\nAUC por pergunta (0,5 = nao separa):")
    for name, neg in (("confirmados x S0", [r for r in rows if r["s"] == "S0"]),
                      ("confirmados x S1", [r for r in rows if r["s"] == "S1"]),
                      ("confirmados x rejeitados", [r for r in rows if r["s"] == "S2R"])):
        vals = []
        for q in qs:
            v = auc([r["p"][q] for r in pos if q in r["p"]], [r["p"][q] for r in neg if q in r["p"]])
            if v is not None:
                vals.append((v, q))
        vals.sort(reverse=True)
        print(f"  {name}: " + " | ".join(f"{q} {v:.3f}" for v, q in vals[:12]))
    (RESULTS / f"agg_dgate54__{a.qset}__{a.split}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                                                    encoding="utf-8")


if __name__ == "__main__":
    main()
