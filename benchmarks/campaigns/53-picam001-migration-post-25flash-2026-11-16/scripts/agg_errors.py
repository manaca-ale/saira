#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — lista de erros por deteccao da cascata recomendada (sem custo), para a
analise visual dos frames.

Para cada conjunto, com o gate e o detail escolhidos:
  - deteccoes reais perdidas (e em que estagio: gate ou detail);
  - deteccoes falsas confirmadas, e as que o detail atual confirma e o novo nao;
  - eventos `baseline` (sem ocorrencia) confirmados.
Cada evento sai com a probabilidade `deposit` do Decisions, o voto dos gates, o veredito do
detail novo (todas as repeticoes em disco) e do detail atual, e a pasta dos frames.

Uso: python agg_errors.py [--gate gdec_q1_gate5_low_deposit_t20:1] [--detail d38f_g3_low_low]
Grava results/errors_summary.json.
"""
from __future__ import annotations

import argparse
import json

import bench53 as b

BASE_GATE = "g25l_v1:1"
BASE_DETAIL = "d25f_v1"
DGATE_TAG = "q1_gate5_low"


def _load(stage, arm, rep):
    p = b.out_path(stage, arm, rep)
    return b.latest_ok(p) if p.exists() else {}


def _reps(stage, arm):
    out = {}
    for p in sorted(b.out_dir().glob(f"{stage}__{arm}__r*.jsonl")):
        rep = int(p.stem.rsplit("__r", 1)[1])
        if rep:
            out[rep] = b.latest_ok(p)
    return out


def _verdict(rec):
    if rec is None:
        return "-"
    return f"{'SIM' if rec.get('disposal') == 1 else 'nao'}({rec.get('conf')})"


def collect(ds, gate_ref, detail_arm):
    b.DS["name"] = ds
    garm, grep_ = b.parse_ref(gate_ref)
    gate = _load("gate", garm, grep_)
    bgate = _reps("gate", b.parse_ref(BASE_GATE)[0])
    dgate = _load("dgate", DGATE_TAG, 1)
    new = _reps("detail", detail_arm)
    old = _reps("detail", BASE_DETAIL)
    dets: dict[str, list[dict]] = {}
    for ev in b.load_events(["tp", "fp", "baseline"]):
        eid = ev["event_id"]
        g = gate.get(eid)
        dg = dgate.get(eid, {}).get("answers", {})
        p_dep = dg.get("deposit", {}).get("noul")      # probabilidade de "sim"
        n1 = new.get(1, {}).get(eid)
        row = {
            "event_id": eid, "category": ev["category"], "det_id": ev["det_id"],
            "frames_dir": str(ev["frames"][0].parent), "n_frames": len(ev["frames"]),
            "gate_fire": int(bool(g and g.get("fire") == 1)),
            "p_deposit": round(p_dep, 3) if p_dep is not None else None,
            "scene": dg.get("scene", {}).get("choice"),
            "gate_today": {r: int(v.get(eid, {}).get("fire") == 1) for r, v in bgate.items() if eid in v},
            "new": {r: _verdict(v.get(eid)) for r, v in new.items() if eid in v},
            "old": {r: _verdict(v.get(eid)) for r, v in old.items() if eid in v},
            "new_yes": int(bool(n1 and n1.get("disposal") == 1)),
            "old_yes_any": int(any(v.get(eid, {}).get("disposal") == 1 for v in old.values())),
            "evidence_new": (n1 or {}).get("evidence", "")[:400],
        }
        row["cascade_yes"] = int(row["gate_fire"] and row["new_yes"])
        dets.setdefault(ev["det_id"], []).append(row)
    return dets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", default="gdec_q1_gate5_low_deposit_t20:1")
    ap.add_argument("--detail", default="d38f_g3_low_low")
    a = ap.parse_args()
    out = {}
    for ds in ("official", "pi-inicial-v1"):
        dets = collect(ds, a.gate, a.detail)
        groups = {"tp_perdida": [], "fp_confirmada": [], "fp_so_o_atual_confirma": [],
                  "baseline_confirmada": []}
        for det_id, rows in dets.items():
            cat = rows[0]["category"]
            hit = any(r["cascade_yes"] for r in rows)
            if cat == "tp" and not hit:
                stage = "gate" if not any(r["gate_fire"] for r in rows) else "detail"
                groups["tp_perdida"].append({"det_id": det_id, "perdida_no": stage, "eventos": rows})
            elif cat == "fp" and hit:
                groups["fp_confirmada"].append({"det_id": det_id, "eventos": rows})
            elif cat == "fp" and any(r["old_yes_any"] for r in rows):
                groups["fp_so_o_atual_confirma"].append({"det_id": det_id, "eventos": rows})
            elif cat == "baseline" and hit:
                groups["baseline_confirmada"].append({"det_id": det_id, "eventos": rows})
        out[ds] = groups
        print(f"\n=== {ds} | gate {a.gate} | detail {a.detail} ===")
        for name, items in groups.items():
            print(f"\n-- {name}: {len(items)}")
            for it in items:
                extra = f" (perdida no {it['perdida_no']})" if "perdida_no" in it else ""
                print(f"  det {it['det_id'][:8]}{extra}")
                for r in it["eventos"]:
                    print(f"    {r['event_id']} gate={r['gate_fire']} p_dep={r['p_deposit']} "
                          f"cena={r['scene']} gate_hoje={r['gate_today']} novo={r['new']} "
                          f"atual={r['old']} frames={r['n_frames']}")
    b.DS["name"] = "official"
    (b.RESULTS / "errors_summary.json").write_text(
        json.dumps({"gate": a.gate, "detail": a.detail, **out}, ensure_ascii=False, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    main()
