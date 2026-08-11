#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Agrega TODOS os braços (g3 high-res + g3low low-res) numa tabela.
Custo: recomputa do zero com PRICE + tokens reais (tok_in/out/think) quando
disponíveis (arquivos low), senão usa cost_usd gravado (arquivos high, já corrigido? não —
os high foram gravados com o cost BUGADO sem thinking). Para justiça, marca a fonte."""
import csv, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
CAMP = Path(__file__).resolve().parents[1]
PRICE = {"gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-flash": (0.15, 0.60),
         "gemini-3.1-flash-lite": (0.125, 0.75), "gemini-3.6-flash": (1.50, 7.00),
         "gemini-3.5-flash-lite": (0.30, 2.50), "gemini-3.5-flash": (0.50, 4.00)}

def load(path):
    p = CAMP / "results" / path
    return list(csv.DictReader(p.open(encoding="utf-8"))) if p.exists() else []

rows = load("bench_picam_g3.csv") + load("bench_picam_g3low.csv")

def det_rate(ar, cat):
    byd = {}
    for r in ar:
        if r["category"] == cat:
            byd.setdefault(r["det_id"], []).append(str(r.get("disposal")) == "1")
    fired = sum(1 for v in byd.values() if any(v))
    return fired, len(byd)

def evt_rate(ar, cat):
    sub = [r for r in ar if r["category"] == cat]
    return sum(1 for r in sub if str(r.get("disposal")) == "1"), len(sub)

ORDER = ["current", "g3_v1", "g3_new", "g3_unified", "unified_single",
         "unified_low", "unified_low_8f", "unified_low_2s",
         "unified_low_spec", "unified_low_2s_spec"]
LABEL = {
 "current": "2.5-lite+2.5-flash V1 (prod hoje)",
 "g3_v1": "3.1-lite+3.5-flash V1+think",
 "g3_new": "3.1-lite+3.5-flash promptG3+think",
 "g3_unified": "só 3.1-lite 2-estágios (high-res)",
 "unified_single": "1 chamada 3.1-lite (high-res)",
 "unified_low": "1 chamada 3.1-lite (LOW-res)",
 "unified_low_8f": "1 chamada 3.1-lite (LOW-res, 8 frames)",
 "unified_low_2s": "2-estágios 3.1-lite (LOW-res)",
 "unified_low_spec": "1 chamada 3.1-lite (LOW, prompt ESPEC-first)",
 "unified_low_2s_spec": "2-estágios 3.1-lite (LOW, prompt ESPEC-first)",
}
print(f"{'arm':16}{'recall/det':>11}{'FP-rate':>9}{'base':>7}{'$/ev(medido)':>13}{'tokIn/ev':>10}{'think/ev':>9}")
for arm in ORDER:
    ar = [r for r in rows if r["arm"] == arm and not r["error"]]
    if not ar:
        continue
    tf, tn = det_rate(ar, "tp"); ff, fn = det_rate(ar, "fp"); bf, bn = evt_rate(ar, "baseline")
    # custo real: se tiver tok_in, recomputa com thinking; senão usa cost_usd gravado
    costs, tins, thinks = [], [], []
    for r in ar:
        if r.get("tok_in") not in (None, "", "None"):
            ti, to, tt = int(r["tok_in"]), int(r["tok_out"]), int(r["tok_think"])
            model = r["detail_model"]
            p = PRICE.get(model, (0, 0))
            costs.append((ti * p[0] + (to + tt) * p[1]) / 1e6)
            tins.append(ti); thinks.append(tt)
        elif r.get("cost_usd"):
            costs.append(float(r["cost_usd"]))
    cpe = sum(costs) / len(costs) if costs else 0
    src = "*" if tins else "~"   # * = recomputado c/ thinking real ; ~ = cost gravado (SEM thinking, subestimado)
    ti_avg = sum(tins) // len(tins) if tins else 0
    th_avg = sum(thinks) // len(thinks) if thinks else 0
    rec = f"{tf}/{tn}={100*tf//max(1,tn)}%"
    fpr = f"{ff}/{fn}={100*ff//max(1,fn)}%"
    bas = f"{bf}/{bn}={100*bf//max(1,bn)}%"
    print(f"{arm:16}{rec:>11}{fpr:>9}{bas:>7}{('$%.5f%s'%(cpe,src)):>13}{ti_avg:>10}{th_avg:>9}   {LABEL[arm]}")
print("\n* = custo recomputado com thinking real (tok_in/out/think medidos)")
print("~ = custo gravado SEM thinking (SUBESTIMADO ~2x p/ os braços high-res antigos)")
print("Nota: preço 3.5-flash é estimativa ($0.50/$4.00).")
