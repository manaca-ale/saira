#!/usr/bin/env python3
"""Camp 48 — auditoria de paridade: o braço de controle reproduz produção?

Este é o portão que BLOQUEIA a Fase B. Se o fork do runner quebrou a construção da
janela, o controle Gemini deixa de reproduzir prod — e aí qualquer número dos
candidatos Bedrock estaria medindo o bug, não o modelo.

Fonte de verdade: `label.json.agent1_confidence`, que é a confiança do gate REAL de
produção gravada quando a detecção foi criada. O Camp 47 bateu 15/16 TPs em 95.

Uso:
    python scripts/fidelity_check.py                      # usa results/bench_bedrock.csv
    python scripts/fidelity_check.py --tag screen
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
CAMP = Path(__file__).resolve().parents[1]
CAM = ROOT / "data" / "datasets" / "official" / "cam_picam001"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=None)
    ap.add_argument("--arm", default="current")
    a = ap.parse_args()
    csv_path = CAMP / "results" / (f"bench_bedrock_{a.tag}.csv" if a.tag
                                   else "bench_bedrock.csv")
    if not csv_path.exists():
        sys.exit(f"não achei {csv_path}")

    prod = {}
    for lab in (CAM / "tp").glob("*/label.json"):
        L = json.loads(lab.read_text(encoding="utf-8"))
        try:
            prod[L["event_id"]] = int(L.get("agent1_confidence") or -1)
        except (TypeError, ValueError):
            prod[L["event_id"]] = -1

    rows = [r for r in csv.DictReader(csv_path.open(encoding="utf-8"))
            if r["arm"] == a.arm and r["category"] == "tp" and not r["error"]]
    if not rows:
        sys.exit(f"sem linhas TP sem erro para o braço '{a.arm}' em {csv_path.name}")

    # A unidade é a DETECÇÃO, não o evento — como no Camp 47 (fidelity_check.py:16).
    # 30 eventos TP colapsam em 16 detecções por coalescência, e os eventos-cauda
    # HERDAM o agent1_confidence da detecção-pai (o rótulo veio do pai). Comparar
    # por evento penaliza justamente as caudas, que em prod também não disparam:
    # uma primeira versão deste script mediu 79% por evento e "reprovou" um harness
    # que estava correto.
    bydet: dict[str, list[dict]] = {}
    for r in rows:
        bydet.setdefault(r["det_id"], []).append(r)

    print(f"{'det_id':14}{'ev':>4}{'prod a1conf':>12}{'bench gate max':>15}"
          f"{'bate':>7}{'fire':>6}{'disposal':>10}")
    match = disp_ok = 0
    for det, rs in sorted(bydet.items()):
        p = max((prod.get(r["event_id"], -1) for r in rs), default=-1)
        gates = [int(r["gate_conf"]) for r in rs
                 if str(r["gate_conf"]).lstrip("-").isdigit()]
        b = max(gates) if gates else -1
        same = (p == b)
        match += int(same)
        disp = any(str(r["disposal"]) == "1" for r in rs)
        disp_ok += int(disp)
        print(f"{det[:12]:14}{len(rs):>4}{p:>12}{b:>15}"
              f"{('sim' if same else 'NAO'):>7}"
              f"{str(any(str(r['gate_fire']) == '1' for r in rs)):>6}{str(disp):>10}")

    n = len(bydet)
    print(f"\ngate igual ao de prod: {match}/{n} detecções TP "
          f"({100*match/n:.0f}%)  — Camp 47 bateu 15/16 (94%)")
    print(f"disposal confirmado:   {disp_ok}/{n} detecções "
          f"({100*disp_ok/n:.0f}%)  — Camp 47: 87,5%")
    print(f"(eventos TP sem erro: {len(rows)})")
    # Critério: a paridade é sobre a JANELA, então aceito 85% de igualdade exata.
    # O modelo é estocástico mesmo com seed=42; o que não pode variar é o input.
    if match / n < 0.85:
        print("\nFALHA: o controle não reproduz o gate de produção. NÃO rode a Fase B — "
              "revise build_window()/gate_mids() antes de gastar com os candidatos.")
        return 1
    print("\nOK: o harness reproduz o input de produção. Liberado para a Fase B.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
