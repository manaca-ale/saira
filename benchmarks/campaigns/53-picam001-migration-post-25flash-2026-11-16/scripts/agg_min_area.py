#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — o que muda se a area minima do bbox do worker (1% da imagem) fosse outra (sem custo).

Usa os campos crus gravados pelo runner (raw_disposal, raw_waste_bbox, raw_offender_bbox) em uma
repeticao do detail. Para cada area minima, conta deteccoes confirmadas: o modelo disse "sim" e
pelo menos uma caixa tem area entre o minimo e 60% da imagem (a regra de `_validate_bbox`).
Com o minimo em 1% o resultado tem de bater com o `disposal` gravado (conferencia impressa).

Uso: python agg_min_area.py [--gate g25l_v1:1] [--detail d38f_g3_low_low:3] [--dataset official]
Grava results/min_area_summary.json.
"""
from __future__ import annotations

import argparse
import json

import bench53 as b

THRESHOLDS = [0.01, 0.0075, 0.005, 0.0025, 0.0]


def area(bb):
    if isinstance(bb, dict):
        bb = bb.get("box_2d") or [bb.get(k) for k in ("y_min", "x_min", "y_max", "x_max")]
    if not isinstance(bb, (list, tuple)) or len(bb) != 4:
        return None
    try:
        y0, x0, y1, x1 = [float(v) for v in bb]
    except (TypeError, ValueError):
        return None
    if y1 <= y0 or x1 <= x0:
        return None
    return (y1 - y0) * (x1 - x0) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", default="g25l_v1:1")
    ap.add_argument("--detail", default="d38f_g3_low_low:3")
    ap.add_argument("--dataset", default="official")
    a = ap.parse_args()
    b.DS["name"] = a.dataset
    garm, grep_ = b.parse_ref(a.gate)
    darm, drep = b.parse_ref(a.detail)
    gate = b.latest_ok(b.out_path("gate", garm, grep_))
    detail = b.latest_ok(b.out_path("detail", darm, drep))
    events = b.load_events(["tp", "fp", "baseline"])
    rows, raw_yes, agree, total = [], [], 0, 0
    for ev in events:
        g = gate.get(ev["event_id"])
        d = detail.get(ev["event_id"]) if g is not None and g.get("fire") == 1 else None
        if d is None or "raw_disposal" not in d:
            rows.append((ev, None, []))
            continue
        areas = [x for x in (area(d.get("raw_waste_bbox")), area(d.get("raw_offender_bbox"))) if x is not None]
        yes = d.get("raw_disposal") == 1
        rows.append((ev, yes, areas))
        total += 1
        sim = int(yes and any(0.01 <= x <= 0.60 for x in areas))
        agree += int(sim == int(d.get("disposal") == 1))
        if yes:
            raw_yes.append({"event_id": ev["event_id"], "cat": ev["category"], "det": ev["det_id"][:8],
                            "raw_conf": d.get("raw_conf"), "areas_pct": [round(x * 100, 2) for x in areas],
                            "vetado": int(d.get("grounding_rejected") == 1)})
    print(f"{a.gate} + {a.detail} em {a.dataset}: {total} eventos com campos crus; "
          f"simulacao a 1% bate com o gravado em {agree}/{total}")
    out = {"gate": a.gate, "detail": a.detail, "dataset": a.dataset, "confere_1pct": f"{agree}/{total}",
           "por_area_minima": {}, "sins_crus": raw_yes}
    for thr in THRESHOLDS:
        def det(cat):
            byd: dict[str, list[int]] = {}
            for ev, yes, areas in rows:
                if ev["category"] == cat:
                    byd.setdefault(ev["det_id"], []).append(int(bool(yes) and any(thr <= x <= 0.60 for x in areas)))
            return sum(1 for v in byd.values() if any(v)), len(byd)

        def evt(cat):
            sub = [int(bool(yes) and any(thr <= x <= 0.60 for x in areas)) for ev, yes, areas in rows
                   if ev["category"] == cat]
            return sum(sub), len(sub)

        row = {"tp_det": "%d/%d" % det("tp"), "fp_det": "%d/%d" % det("fp"), "baseline": "%d/%d" % evt("baseline")}
        out["por_area_minima"][f"{thr * 100:.2f}%"] = row
        print(f"  area minima {thr * 100:.2f}%: reais {row['tp_det']} | falsos {row['fp_det']} | vazias {row['baseline']}")
    print("  'sim' cru do modelo (areas em % da imagem; vetado=1 e o que o worker derruba):")
    for r in sorted(raw_yes, key=lambda r: (r["cat"], max(r["areas_pct"] or [0]))):
        print(f"    {r['cat']:8} {r['event_id']} det {r['det']} conf {r['raw_conf']} areas {r['areas_pct']} vetado={r['vetado']}")
    b.DS["name"] = "official"
    (b.RESULTS / "min_area_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
