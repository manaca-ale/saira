#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — bloco M: escolha do prompt do detail no gemini-3.8-flash (sem custo).

Compara, por deteccao e pela RESPOSTA CRUA do modelo (o rollout usa GEMINI_REQUIRE_BBOX=false),
os prompts v4 e v1 contra o g3 (o recomendado), todos com thinking low e resolucao low, nos
eventos que passam no gate de producao (`g25l_v1:1`).

Regra fixada ANTES de rodar (handoff, secao 6, correcao de rotulos de 17/11): um prompt so
substitui o g3 se, no oficial, mantiver pelo menos 16/18 deteccoes reais e confirmar MENOS
falsas que o g3 (6/26). Nesse caso roda no holdout `pi-inicial-v1` e precisa reter pelo menos
25 dos 27 confirmados que passam no gate. Com 18 reais e 26 falsas, diferenca de 1 ou 2 e ruido.

Uso: python agg_block_m.py
Grava results/block_m_summary.json.
"""
from __future__ import annotations

import json
import sys

import bench53 as b
from agg_grounding import vetoed

GATE = "g25l_v1:1"
BASE_ARM = "d38f_g3_low_low"
BASE_REPS = (1, 2, 3)
CANDS = ("d38f_v4_low_low", "d38f_v1_low_low")
MIN_TP_OFFICIAL = 16      # de 18
MIN_KEEP_HOLDOUT = 25     # dos 27 confirmados que passam no gate


def raw_yes(rec) -> int:
    """Resposta do modelo antes do veto do bbox."""
    if rec.get("raw_disposal") is not None:
        return int(rec["raw_disposal"] == 1)
    return int(rec.get("disposal") == 1 or vetoed(rec))


def _label(event_id: str) -> dict:
    if b.DS["name"] != "official":
        return {}
    for folder in ("tp", "fp", "indefinido", "baseline"):
        p = b.CAM / folder / event_id / "label.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {}


def table(detail_arm: str, rep: int, cats):
    """Por evento que passa no gate: voto cru e voto com o veto. Devolve None se faltar detail."""
    garm, grep_ = b.parse_ref(GATE)
    gp, dp = b.out_path("gate", garm, grep_), b.out_path("detail", detail_arm, rep)
    if not (gp.exists() and dp.exists()):
        return None
    gate, detail = b.latest_ok(gp), b.latest_ok(dp)
    rows, missing = [], 0
    for ev in b.load_events(cats):
        g = gate.get(ev["event_id"])
        fired = bool(g and g.get("fire") == 1)
        d = detail.get(ev["event_id"]) if fired else None
        if fired and d is None:
            missing += 1
            continue
        rows.append({"event_id": ev["event_id"], "det_id": ev["det_id"], "category": ev["category"],
                     "gate": int(fired),
                     "raw": raw_yes(d) if d else 0,
                     "veto": int(d.get("disposal") == 1) if d else 0,
                     "conf": (d or {}).get("raw_conf", (d or {}).get("conf")),
                     "evidence": ((d or {}).get("evidence") or "")[:300]})
    return rows, missing


def by_det(rows, cat, field):
    byd: dict[str, list[int]] = {}
    for r in rows:
        if r["category"] == cat:
            byd.setdefault(r["det_id"], []).append(r[field])
    return {k: int(any(v)) for k, v in byd.items()}


def summarize(rows, missing):
    out = {"missing_detail": missing}
    for name, field in (("cru", "raw"), ("com_veto", "veto")):
        tp, fp = by_det(rows, "tp", field), by_det(rows, "fp", field)
        bl = [r[field] for r in rows if r["category"] == "baseline"]
        out[name] = {"reais": f"{sum(tp.values())}/{len(tp)}", "falsos": f"{sum(fp.values())}/{len(fp)}",
                     "vazias": f"{sum(bl)}/{len(bl)}",
                     "n_reais": sum(tp.values()), "n_falsos": sum(fp.values())}
    out["falsos_confirmados_cru"] = sorted(k for k, v in by_det(rows, "fp", "raw").items() if v)
    out["reais_perdidas_cru"] = sorted(k for k, v in by_det(rows, "tp", "raw").items() if not v)
    out["vazias_confirmadas_cru"] = sorted(r["event_id"] for r in rows if r["category"] == "baseline" and r["raw"])
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    out = {"gate": GATE, "regra": {"oficial_min_reais": MIN_TP_OFFICIAL, "oficial_falsos_menos_que_o_g3": True,
                                   "holdout_min_retidos_dos_que_passam_no_gate": MIN_KEEP_HOLDOUT},
           "official": {}, "pi-inicial-v1": {}}

    # ── oficial
    b.DS["name"] = "official"
    cats = ["tp", "fp", "baseline"]
    print("=== oficial (por deteccao; resposta crua / com o veto do bbox) ===")
    base_fp = None
    tables = {}
    for rep in BASE_REPS:
        t = table(BASE_ARM, rep, cats)
        if t is None:
            continue
        s = summarize(*t)
        out["official"][f"{BASE_ARM}:{rep}"] = s
        tables[f"{BASE_ARM}:{rep}"] = t[0]
        base_fp = s["cru"]["n_falsos"] if base_fp is None else max(base_fp, s["cru"]["n_falsos"])
        print(f"  {BASE_ARM}:{rep} | cru: reais {s['cru']['reais']} falsos {s['cru']['falsos']} vazias {s['cru']['vazias']}"
              f" | com veto: reais {s['com_veto']['reais']} falsos {s['com_veto']['falsos']} vazias {s['com_veto']['vazias']}")
    base_fp_min = min((out["official"][k]["cru"]["n_falsos"] for k in out["official"]), default=None)
    verdict = {}
    for arm in CANDS:
        t = table(arm, 1, cats)
        if t is None:
            print(f"  {arm}:1 | sem resultado em disco")
            continue
        s = summarize(*t)
        tables[f"{arm}:1"] = t[0]
        ok_tp = s["cru"]["n_reais"] >= MIN_TP_OFFICIAL
        # "menos falsos que o g3": exige ficar abaixo da MENOR contagem do g3 entre as repeticoes
        ok_fp = base_fp_min is not None and s["cru"]["n_falsos"] < base_fp_min
        s["passa_regra_oficial"] = bool(ok_tp and ok_fp and s["missing_detail"] == 0)
        verdict[arm] = s["passa_regra_oficial"]
        out["official"][f"{arm}:1"] = s
        print(f"  {arm}:1 | cru: reais {s['cru']['reais']} falsos {s['cru']['falsos']} vazias {s['cru']['vazias']}"
              f" | com veto: reais {s['com_veto']['reais']} falsos {s['com_veto']['falsos']} vazias {s['com_veto']['vazias']}"
              f" | faltam {s['missing_detail']} | passa na regra: {'SIM' if s['passa_regra_oficial'] else 'nao'}")
    out["official"]["g3_falsos_cru_min_max"] = [base_fp_min, base_fp]

    # ── falsos, deteccao a deteccao: quem confirma o que, com a justificativa do operador
    ref = f"{BASE_ARM}:3" if f"{BASE_ARM}:3" in tables else next(iter(tables), None)
    cols = [k for k in tables]
    fp_dets: dict[str, dict] = {}
    for k, rows in tables.items():
        for r in rows:
            if r["category"] != "fp":
                continue
            d = fp_dets.setdefault(r["det_id"], {"eventos": set(), "votos": {}})
            d["eventos"].add(r["event_id"])
            d["votos"][k] = max(d["votos"].get(k, 0), r["raw"])
    lista = []
    for det_id, d in sorted(fp_dets.items()):
        if not any(d["votos"].values()):
            continue
        just = sorted({(_label(e).get("justificativa") or "").strip() for e in d["eventos"]} - {""})
        lista.append({"det_id": det_id, "eventos": sorted(d["eventos"]), "justificativa_operador": just,
                      "confirmam_cru": {k: d["votos"].get(k, 0) for k in cols}})
    out["official"]["falsos_confirmados_por_alguem"] = lista
    print(f"\n=== oficial: deteccoes falsas que algum prompt confirma (resposta crua); colunas: {', '.join(cols)} ===")
    for it in lista:
        votos = " ".join(str(it["confirmam_cru"][k]) for k in cols)
        print(f"  {it['det_id'][:8]} | {votos} | {'; '.join(it['justificativa_operador'])[:110]}")

    # ── reais: quem perde o que
    tp_dets: dict[str, dict] = {}
    for k, rows in tables.items():
        for r in rows:
            if r["category"] == "tp":
                tp_dets.setdefault(r["det_id"], {})[k] = max(tp_dets.get(r["det_id"], {}).get(k, 0), r["raw"])
    perdidas = [{"det_id": d, "confirmam_cru": {k: v.get(k, 0) for k in cols}}
                for d, v in sorted(tp_dets.items()) if not all(v.get(k, 0) for k in cols)]
    out["official"]["reais_perdidas_por_alguem"] = perdidas
    print("\n=== oficial: deteccoes reais que algum prompt perde (resposta crua) ===")
    for it in perdidas:
        print(f"  {it['det_id'][:8]} | " + " ".join(str(it["confirmam_cru"][k]) for k in cols))
    if not perdidas:
        print("  nenhuma")

    # ── holdout (so se o braco rodou la)
    b.DS["name"] = "pi-inicial-v1"
    print("\n=== holdout pi-inicial-v1 (cada evento e uma deteccao; resposta crua / com veto) ===")
    for arm, rep in [(BASE_ARM, 1), (BASE_ARM, 2)] + [(c, 1) for c in CANDS]:
        t = table(arm, rep, ["tp", "fp"])
        if t is None:
            print(f"  {arm}:{rep} | nao rodou no holdout")
            continue
        rows, missing = t
        passed_tp = [r for r in rows if r["category"] == "tp" and r["gate"]]
        all_tp = [r for r in rows if r["category"] == "tp"]
        all_fp = [r for r in rows if r["category"] == "fp"]
        s = {"missing_detail": missing,
             "confirmados_que_passam_no_gate": len(passed_tp),
             "retidos_cru": sum(r["raw"] for r in passed_tp), "retidos_com_veto": sum(r["veto"] for r in passed_tp),
             "cascata_cru": {"confirmados": f"{sum(r['raw'] for r in all_tp)}/{len(all_tp)}",
                             "rejeitados": f"{sum(r['raw'] for r in all_fp)}/{len(all_fp)}"},
             "cascata_com_veto": {"confirmados": f"{sum(r['veto'] for r in all_tp)}/{len(all_tp)}",
                                  "rejeitados": f"{sum(r['veto'] for r in all_fp)}/{len(all_fp)}"}}
        if arm in CANDS:
            s["passa_regra_holdout"] = bool(missing == 0 and s["retidos_cru"] >= MIN_KEEP_HOLDOUT)
        out["pi-inicial-v1"][f"{arm}:{rep}"] = s
        print(f"  {arm}:{rep} | retidos dos {len(passed_tp)} que passam no gate: cru {s['retidos_cru']}, com veto "
              f"{s['retidos_com_veto']} | cascata crua: {s['cascata_cru']['confirmados']} confirmados, "
              f"{s['cascata_cru']['rejeitados']} rejeitados | com veto: {s['cascata_com_veto']['confirmados']} e "
              f"{s['cascata_com_veto']['rejeitados']} | faltam {missing}"
              + (f" | passa na regra: {'SIM' if s['passa_regra_holdout'] else 'nao'}" if arm in CANDS else ""))
    b.DS["name"] = "official"
    out["veredito_oficial"] = verdict
    (b.RESULTS / "block_m_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
