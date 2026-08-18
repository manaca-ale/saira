#!/usr/bin/env python3
"""Camp 48 — agregação final, recomputando custo a partir dos tokens crus.

Por que recomputar em vez de somar a coluna `cost_usd`: a tabela de preço mudou no
meio da campanha. O runner começou com a tabela do Camp 47 para o Gemini
((0.15, 0.60) para o 2.5-flash) e ela SUBESTIMA o output em ~4x — a de produção
(`detector_gemini._MODEL_PRICES`:676) é (0.30, 2.50). Como as colunas `tok_in` /
`tok_out` / `tok_think` estão gravadas, dá para corrigir sem re-rodar nada.

Uso:
    python scripts/agg_all.py
    python scripts/agg_all.py --csv results/bench_bedrock_screen.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bedrock_client as bc   # noqa: E402

CAMP = Path(__file__).resolve().parents[1]

# USD por 1M tokens (input, output). Gemini = tabela de PRODUÇÃO.
# thinking é cobrado como OUTPUT nos dois fornecedores.
GEMINI_PRICE = {"gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-flash": (0.30, 2.50)}


def price_for(row) -> tuple[float, float] | None:
    if row["provider"] == "gemini":
        # cascade: o custo real mistura gate (lite) e detail (flash). Sem separação
        # por estágio no CSV, uso o preço do DETAIL quando ele rodou (disposal
        # preenchido pelo detail) e o do GATE quando parou no gate.
        model = row["detail_model"] if str(row.get("detail_conf") or "").strip() \
            else row["gate_model"]
        return GEMINI_PRICE.get(model)
    alias = row["arm"].split(":", 1)[0]
    spec = bc.MODELS.get(alias)
    return spec.price if spec else None


def recompute_cost(row) -> float:
    p = price_for(row)
    if not p:
        return float(row["cost_usd"] or 0)
    ti = int(row["tok_in"] or 0)
    to = int(row["tok_out"] or 0)
    tt = int(row["tok_think"] or 0)
    return ti / 1e6 * p[0] + (to + tt) / 1e6 * p[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(CAMP / "results" / "bench_bedrock.csv"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    path = Path(a.csv)
    if not path.exists():
        sys.exit(f"não achei {path}")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))

    out = {}
    for arm in sorted({r["arm"] for r in rows}):
        allr = [r for r in rows if r["arm"] == arm]
        ar = [r for r in allr if not r["error"]]
        if not ar:
            out[arm] = {"n": 0, "n_errors": len(allr)}
            continue

        def det_frac(cat):
            byd = {}
            for r in ar:
                if r["category"] == cat:
                    byd.setdefault(r["det_id"], []).append(str(r["disposal"]) == "1")
            return sum(1 for v in byd.values() if any(v)), len(byd)

        def evt_frac(cat):
            sub = [r for r in ar if r["category"] == cat]
            return sum(1 for r in sub if r["disposal"] == "1"), len(sub)

        tpd, tpdn = det_frac("tp")
        fpd, fpdn = det_frac("fp")
        ble, blen = evt_frac("baseline")
        costs = [recompute_cost(r) for r in ar]
        lats = sorted(int(r["latency_ms"]) for r in ar if str(r["latency_ms"]).isdigit())
        jv = [r for r in allr if str(r.get("json_valid")) in ("0", "1")]
        out[arm] = {
            "n": len(ar), "n_errors": len(allr) - len(ar),
            "json_valid_rate": (round(100 * sum(1 for r in jv if r["json_valid"] == "1")
                                      / len(jv), 1) if jv else None),
            "tp_recall_det": round(100 * tpd / tpdn, 1) if tpdn else None,
            "tp_det": f"{tpd}/{tpdn}",
            "fp_rate_det": round(100 * fpd / fpdn, 1) if fpdn else None,
            "fp_det": f"{fpd}/{fpdn}",
            "baseline_fire_rate": round(100 * ble / blen, 1) if blen else None,
            "baseline": f"{ble}/{blen}",
            "cost_per_event_usd": round(sum(costs) / len(costs), 6),
            "total_cost_usd": round(sum(costs), 4),
            "latency_p50_ms": lats[len(lats) // 2] if lats else None,
            "img_mode": next((r["img_mode"] for r in ar if r["img_mode"]), ""),
        }

    dest = Path(a.out) if a.out else path.with_name(path.stem + "_agg.json")
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    hdr = (f"{'braço':34}{'n':>5}{'err':>5}{'json':>6}{'recall det':>12}"
           f"{'fp det':>12}{'baseline':>11}{'$/ev':>10}{'p50 s':>7}")
    print(hdr)
    print("-" * len(hdr))
    for arm, m in sorted(out.items(), key=lambda kv: -(kv[1].get("tp_recall_det") or -1)):
        if not m.get("n"):
            print(f"{arm:34}{0:>5}{m.get('n_errors', 0):>5}   —  (nenhuma chamada válida)")
            continue
        print(f"{arm:34}{m['n']:>5}{m['n_errors']:>5}{(m['json_valid_rate'] or 0):>5.0f}%"
              f"{(str(m['tp_recall_det'])+'% '+m['tp_det']):>12}"
              f"{(str(m['fp_rate_det'])+'% '+m['fp_det']):>12}"
              f"{(str(m['baseline_fire_rate'])+'% '):>11}"
              f"{m['cost_per_event_usd']:>10.5f}"
              f"{(m['latency_p50_ms'] or 0)/1000:>7.1f}")
    print(f"\nagregado em {dest.name}   custo total recomputado: "
          f"${sum(m.get('total_cost_usd', 0) for m in out.values()):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
