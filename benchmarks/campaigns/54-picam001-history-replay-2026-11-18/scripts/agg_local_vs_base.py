#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — o que os eventos JA rodados (camp 53: oficial, pi-inicial-v1, pi-avancado-v1) dizem quando
pesados pela proporcao REAL de producao (sem custo de API).

Cada evento local e procurado na base de producao (build_base.py) e cai num estrato:
  S0  gate de producao NAO disparou                  (maioria dos eventos)
  S1  gate disparou, detail disse nao
  S2  detail disse sim (virou deteccao): CONFIRMADO / REJEITADO / outros
As fracoes de cada estrato na producao vem da base inteira (31,7 mil eventos).

Estruturas avaliadas com o Decisions (pergunta `deposit`, limiar t):
  A  Decisions NO LUGAR do gate:        custo = cD + P(D) * cDetail
  B  Decisions ANTES do gate de hoje:   custo = cD + P(D) * cGate + P(D e G) * cDetail
  C  Decisions DEPOIS do gate de hoje:  custo = cGate + P(G) * cD + P(D e G) * cDetail
Em B e C quem decide ir ao detail continua sendo o gate de hoje (decisao GRAVADA em producao), entao o
numero de alertas nao aumenta; o risco e perder descartes confirmados com probabilidade abaixo de t.

Uso: python agg_local_vs_base.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

C53 = Path(__file__).resolve().parents[2] / "53-picam001-migration-post-25flash-2026-11-16" / "scripts"
sys.path.insert(0, str(C53))
import bench53 as b          # noqa: E402
import bench_decisions as d  # noqa: E402

BASE = Path(r"C:\Saira\data\historico-picam\base")
# custos REAIS de producao, gemini_call_log da pi-cam-001, 14/07 a 08/09/2026
N_EVT = 31976                     # eventos avaliados com sucesso pelo gate
C_GATE = 32.8770 / N_EVT          # gate por evento (inclui chamadas com erro)
C_DET_OLD = 9.5424 / 1023         # detail de hoje por evento que passa (inclui erros)
C_DET_NEW = C_DET_OLD * (0.016923 / 0.010813)   # detail recomendado: razao medida no oficial (camp 53)
C_D = 0.00021                     # Decisions por chamada (camp 53)
TODAY = (32.8770 + 9.5424) / N_EVT
GRID = (0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40)
QUESTIONS = ("deposit", "actor_at_pile", "removal", "pile_grew", "carrying_in", "scene")


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
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    base = {}
    with (BASE / "base_eventos.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            base[r["event_id"]] = r
    pop = [r for r in base.values() if r["dia"] >= "2026-07-14" and r["gate_avaliou"] == "1"]

    def stratum(r):
        if r["gate_disparou"] != "1":
            return "S0"
        if r["detail_sim"] != "1":
            return "S1"
        return {"CONFIRMADO": "S2C", "REJEITADO": "S2R"}.get(r["status"], "S2X")

    n_pop = len(pop)
    W = {}
    for r in pop:
        W[stratum(r)] = W.get(stratum(r), 0) + 1
    print(f"producao, 14/07 a 08/09: {n_pop} eventos avaliados | custo real US$ {TODAY:.6f} por evento "
          f"(gate {C_GATE:.6f}; detail de hoje {C_DET_OLD:.6f} por evento que passa; recomendado {C_DET_NEW:.6f})")
    print("estratos na producao:", ", ".join(f"{k} {v} ({100 * v / n_pop:.2f}%)" for k, v in sorted(W.items())))
    p_gate = (n_pop - W["S0"]) / n_pop
    rec = C_GATE + p_gate * C_DET_NEW
    print(f"gate de hoje + detail recomendado: US$ {rec:.6f} por evento ({100 * (rec / TODAY - 1):+.1f}%)")

    # eventos locais com resposta do Decisions
    loc = []
    for ds in ("official", "pi-inicial-v1", "pi-avancado-v1"):
        b.DS["name"] = ds
        dg = b.latest_ok(d.dgate_path("q1_gate5_low", 1))
        gp = b.out_path("gate", "g25l_v1", 1)
        og = b.latest_ok(gp) if gp.exists() else {}
        for ev in b.load_events():
            rec_d = dg.get(ev["event_id"])
            br = base.get(ev["event_id"])
            if rec_d is None or br is None or br["gate_avaliou"] != "1":
                continue
            row = {"event_id": ev["event_id"], "ds": ds, "cat": ev["category"], "s": stratum(br),
                   "dia": br["dia"], "og": (og.get(ev["event_id"]) or {}).get("fire")}
            for q in QUESTIONS:
                row[q] = d.prob(rec_d, q)
            loc.append(row)
    b.DS["name"] = "official"
    seen, uniq = set(), []
    for r in loc:
        if r["event_id"] not in seen:
            seen.add(r["event_id"])
            uniq.append(r)
    loc = uniq
    n_loc = {}
    for r in loc:
        n_loc[r["s"]] = n_loc.get(r["s"], 0) + 1
    print(f"\neventos locais com Decisions e presentes na base: {len(loc)} | por estrato: "
          + ", ".join(f"{k} {v}" for k, v in sorted(n_loc.items())))
    print("  (S0 e S1 locais vem quase todos da amostra do Gabriel, de criterio desconhecido, e das 40 cenas do oficial)")

    # paridade do gate offline com o de producao
    print("\ngate de hoje rodado aqui (g25l_v1:1) x decisao gravada em producao:")
    for s in ("S0", "S1", "S2C", "S2R", "S2X"):
        sub = [r for r in loc if r["s"] == s and r["og"] is not None]
        k = sum(1 for r in sub if r["og"] == 1)
        print(f"  {s}: aqui passa {k}/{len(sub)}" + (f" = {100 * k / len(sub):.0f}%" if sub else "")
              + ("  (producao: 0%)" if s == "S0" else "  (producao: 100%)"))

    # taxas do Decisions por estrato e projecao
    def rate(s, t, q="deposit"):
        sub = [r for r in loc if r["s"] == s and r[q] is not None]
        k = sum(1 for r in sub if r[q] >= t)
        return k, len(sub)

    out = {"pesos": {k: v / n_pop for k, v in W.items()}, "n_local": n_loc, "custo_hoje": TODAY, "limiares": {}}
    print("\nlimiar | passa em S0 [IC95] | S1 | confirmados (S2C) | rejeitados (S2R) | "
          "A: P(passa), custo | B: custo | C: custo | confirmados mantidos")
    for t in GRID:
        r0, r1, rc, rr, rx = (rate(s, t) for s in ("S0", "S1", "S2C", "S2R", "S2X"))
        f = lambda kn: kn[0] / kn[1] if kn[1] else 0.0
        w = {k: W.get(k, 0) / n_pop for k in ("S0", "S1", "S2C", "S2R", "S2X")}
        p_d = w["S0"] * f(r0) + w["S1"] * f(r1) + w["S2C"] * f(rc) + w["S2R"] * f(rr) + w["S2X"] * f(rx)
        p_dg = w["S1"] * f(r1) + w["S2C"] * f(rc) + w["S2R"] * f(rr) + w["S2X"] * f(rx)
        lo, hi = wilson(*r0)
        p_d_hi = p_d + w["S0"] * (hi - f(r0))
        a = C_D + p_d * C_DET_NEW
        a_hi = C_D + p_d_hi * C_DET_NEW
        bb = C_D + p_d * C_GATE + p_dg * C_DET_NEW
        cc = C_GATE + p_gate * C_D + p_dg * C_DET_NEW
        out["limiares"][f"{t:.2f}"] = {
            "S0": r0, "S1": r1, "S2C": rc, "S2R": rr, "p_passa": p_d, "A": a, "A_sup": a_hi, "B": bb, "C": cc,
            "A_vs_hoje": a / TODAY - 1, "B_vs_hoje": bb / TODAY - 1, "C_vs_hoje": cc / TODAY - 1}
        print(f"{t:.2f} | {r0[0]}/{r0[1]} = {100 * f(r0):.1f}% [{100 * lo:.1f} a {100 * hi:.1f}] | "
              f"{r1[0]}/{r1[1]} | {rc[0]}/{rc[1]} = {100 * f(rc):.0f}% | {rr[0]}/{rr[1]} = {100 * f(rr):.0f}% | "
              f"{100 * p_d:.1f}%, {100 * (a / TODAY - 1):+.0f}% (ate {100 * (a_hi / TODAY - 1):+.0f}%) | "
              f"{100 * (bb / TODAY - 1):+.0f}% | {100 * (cc / TODAY - 1):+.0f}% | {100 * f(rc):.0f}%")

    # que pergunta separa o que
    print("\nAUC de cada pergunta (0,5 = nao separa; 1,0 = separa tudo):")
    pos = [r for r in loc if r["s"] == "S2C"]
    for name, neg in (("confirmados x eventos sem disparo (S0)", [r for r in loc if r["s"] == "S0"]),
                      ("confirmados x rejeitados pelo operador (S2R)", [r for r in loc if r["s"] == "S2R"])):
        vals = []
        for q in QUESTIONS:
            a_ = auc([r[q] for r in pos if r[q] is not None], [r[q] for r in neg if r[q] is not None])
            vals.append(f"{q} {a_:.3f}" if a_ is not None else f"{q} -")
        print(f"  {name}: " + " | ".join(vals))
    a_rm = auc([-(r["removal"] or 0) for r in pos], [-(r["removal"] or 0) for r in [x for x in loc if x["s"] == "S2R"]])
    print(f"  confirmados x rejeitados com (1 - removal): {a_rm:.3f}" if a_rm is not None else "")
    (BASE / "local_vs_base.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
