#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — quanto do "nao" do detail e veto do worker, e nao resposta do modelo (sem custo).

O worker (`_sanitize_report`, com GEMINI_REQUIRE_BBOX=true, o padrao) troca um "sim" do modelo
por "nao" com confianca 0 quando nenhum bbox passa em `_validate_bbox` (que recusa caixa com
menos de 1% ou mais de 60% da imagem). Nos registros da campanha isso aparece como
`disposal=0, conf=0`; os registros novos trazem tambem `grounding_rejected` e os bboxes crus.

Para cada cascata (gate + detail), compara por deteccao:
  - como medido (com o veto, que e o que a producao faz hoje);
  - sem o veto (todo "nao" com confianca 0 volta a ser "sim").
"Sem o veto" e um teto: equivale a aceitar qualquer caixa, por menor que seja.

Uso: python agg_grounding.py
Grava results/grounding_summary.json.
"""
from __future__ import annotations

import json

import bench53 as b

GATES = ["g25l_v1:1", "gdec_q1_gate5_low_deposit_t30:1", "gdec_q1_gate5_low_deposit_t25:1",
         "gdec_q1_gate5_low_deposit_t20:1"]
DETAILS = ["d25f_v1:1", "d25f_v1:2", "d38f_g3_low_low:1", "d38f_g3_low_low:2", "d38f_g3_low_low:3",
           "d38f_g3_low_med:1",
           "d35l_g3_low_high:1", "d35l_g3_low_high:2", "d35l_v1_low_high:1", "d35l_v1_low_high:2"]


def vetoed(rec) -> bool:
    if "grounding_rejected" in rec:
        return rec["grounding_rejected"] == 1
    return rec.get("disposal") == 0 and rec.get("conf") == 0


def score(gate_ref, detail_ref):
    garm, grep_ = b.parse_ref(gate_ref)
    darm, drep = b.parse_ref(detail_ref)
    gp, dp = b.out_path("gate", garm, grep_), b.out_path("detail", darm, drep)
    if not (gp.exists() and dp.exists()):
        return None
    gate, detail = b.latest_ok(gp), b.latest_ok(dp)
    rows, missing = [], 0
    for ev in b.load_events(["tp", "fp", "baseline"]):
        g = gate.get(ev["event_id"])
        if g is None or g.get("fire") != 1:
            rows.append((ev, 0, 0))
            continue
        d = detail.get(ev["event_id"])
        if d is None:
            missing += 1
            continue
        yes = int(d.get("disposal") == 1)
        rows.append((ev, yes, int(yes or vetoed(d))))

    def det(cat, i):
        byd: dict[str, list[int]] = {}
        for r in rows:
            if r[0]["category"] == cat:
                byd.setdefault(r[0]["det_id"], []).append(r[i])
        return sum(1 for v in byd.values() if any(v)), len(byd)

    def evt(cat, i):
        sub = [r for r in rows if r[0]["category"] == cat]
        return sum(r[i] for r in sub), len(sub)

    out = {"gate": gate_ref, "detail": detail_ref, "missing_detail": missing}
    for name, i in (("medido", 1), ("sem_veto", 2)):
        out[name] = {"tp_det": "%d/%d" % det("tp", i), "fp_det": "%d/%d" % det("fp", i),
                     "baseline": "%d/%d" % evt("baseline", i),
                     "tp_evt": "%d/%d" % evt("tp", i), "fp_evt": "%d/%d" % evt("fp", i)}
    out["vetos_evt"] = {c: evt(c, 2)[0] - evt(c, 1)[0] for c in ("tp", "fp", "baseline")}
    return out


def main():
    out = {}
    for ds in ("official", "pi-inicial-v1"):
        b.DS["name"] = ds
        print(f"\n=== {ds} ===")
        print("gate | detail | medido: reais / falsos / vazias | sem veto: reais / falsos / vazias | "
              "vetos em eventos (tp/fp/baseline) | faltam")
        for g in GATES:
            for d in DETAILS:
                s = score(g, d)
                # par incompleto (detail nao rodou em parte dos eventos que este gate passa): nao lista
                if s is None or s["missing_detail"] > 0:
                    continue
                out.setdefault(ds, []).append(s)
                m, w, v = s["medido"], s["sem_veto"], s["vetos_evt"]
                print(f"{g} | {d} | {m['tp_det']} / {m['fp_det']} / {m['baseline']} | "
                      f"{w['tp_det']} / {w['fp_det']} / {w['baseline']} | "
                      f"{v['tp']}/{v['fp']}/{v['baseline']} | {s['missing_detail']}")
    b.DS["name"] = "official"
    (b.RESULTS / "grounding_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
