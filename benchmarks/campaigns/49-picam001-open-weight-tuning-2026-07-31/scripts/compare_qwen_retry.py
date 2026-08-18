#!/usr/bin/env python3
"""Camp 49 / Tema 1 — Camp 49 (amostra enviesada) vs re-teste (amostra completa).

Comparar as duas rodadas braço a braço só é honesto se as duas colunas deixarem claro
QUANTOS eventos entraram em cada uma. No Camp 49 o qwen perdeu 13%/13%/66% dos eventos
por erro de endpoint, e a perda não foi aleatória: no `v4_single` sobreviveram 6 de 40
baselines e 10 de 35 tp. Toda métrica de precisão/baseline dele veio desse resíduo.

Uso:
    python scripts/compare_qwen_retry.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CAMP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bedrock_client as bc   # noqa: E402

OLD = CAMP / "results" / "bench_v4.csv"
NEW = CAMP / "results" / "bench_v4_qwen_retry.csv"
ARMS = ["qwen3-vl-235b:v4_single", "qwen3-vl-235b:v4_casc", "qwen3-vl-235b:v4_casc_5f"]


def metrics(rows: list[dict], arm: str) -> dict | None:
    allr = [r for r in rows if r["arm"] == arm]
    if not allr:
        return None
    ar = [r for r in allr if not r["error"]]
    if not ar:
        return {"n": 0, "err": len(allr)}

    def det(cat):
        byd: dict[str, list[bool]] = {}
        for r in ar:
            if r["category"] == cat:
                byd.setdefault(r["det_id"], []).append(str(r["disposal"]) == "1")
        return sum(1 for v in byd.values() if any(v)), len(byd)

    def evt(cat):
        sub = [r for r in ar if r["category"] == cat]
        return sum(1 for r in sub if r["disposal"] == "1"), len(sub)

    tp, tpn = det("tp")
    fp, fpn = det("fp")
    bl, bln = evt("baseline")
    pin, pout = bc.MODELS[arm.split(":")[0]].price
    costs = [int(r["tok_in"] or 0) / 1e6 * pin + int(r["tok_out"] or 0) / 1e6 * pout
             for r in ar]
    lat = sorted(int(r["latency_ms"]) for r in ar if str(r["latency_ms"]).isdigit())
    # Precisão como o report.md calcula: TP detecções / (TP + FP detecções + disparos
    # de BASELINE). Conferido contra três braços publicados — current_v4 18/(18+8)=69,2%,
    # kimi:v4_single 19/(19+12+2)=57,6%, magistral:v4_single 7/(7+2)=77,8%. Omitir o
    # baseline daria 61,3% para o kimi e a tabela deixaria de fechar.
    den = tp + fp + bl
    prec = 100 * tp / den if den else None
    return {"n": len(ar), "err": len(allr) - len(ar),
            "recall": 100 * tp / tpn if tpn else None, "tp": f"{tp}/{tpn}",
            "prec": prec, "fp": f"{fp}/{fpn}",
            "fp_rate": 100 * fp / fpn if fpn else None,
            "bl": f"{bl}/{bln}", "bl_rate": 100 * bl / bln if bln else None,
            "cost": sum(costs) / len(costs), "tot": sum(costs),
            "p50": lat[len(lat) // 2] / 1000 if lat else None,
            "p90": lat[int(0.9 * (len(lat) - 1))] / 1000 if lat else None}


def fmt(m: dict | None) -> str:
    if not m:
        return f"{'—':>52}"
    if not m.get("n"):
        return f"{0:>4}{m['err']:>5}{'(nenhuma chamada válida)':>43}"
    rec = "{:.1f}% {}".format(m["recall"], m["tp"]) if m["recall"] is not None else "—"
    pre = "{:.1f}%".format(m["prec"]) if m["prec"] is not None else "—"
    fpc = "{:.0f}% {}".format(m["fp_rate"], m["fp"]) if m["fp_rate"] is not None else "—"
    blc = "{:.0f}% {}".format(m["bl_rate"], m["bl"]) if m["bl_rate"] is not None else "—"
    return (f"{m['n']:>4}{m['err']:>5}{rec:>14}{pre:>9}{fpc:>12}{blc:>11}"
            f"{m['cost']:>9.5f}{(m['p50'] or 0):>7.1f}{(m['p90'] or 0):>7.1f}")


def main() -> int:
    old = list(csv.DictReader(OLD.open(encoding="utf-8")))
    if not NEW.exists():
        sys.exit(f"não achei {NEW} — rode a Fase B primeiro")
    new = list(csv.DictReader(NEW.open(encoding="utf-8")))

    hdr = (f"{'braço / rodada':38}{'n':>4}{'err':>5}{'recall det':>14}{'prec':>9}"
           f"{'fp det':>12}{'baseline':>11}{'$/ev':>9}{'p50':>7}{'p90':>7}")
    print(hdr)
    print("-" * len(hdr))
    tot_new = 0.0
    for arm in ARMS:
        mo, mn = metrics(old, arm), metrics(new, arm)
        print(f"{arm + '  · Camp 49':38}{fmt(mo)}")
        print(f"{'    · re-teste':38}{fmt(mn)}")
        if mn and mn.get("n"):
            tot_new += mn["tot"]
        print()
    print(f"custo do re-teste (tokens crus): US$ {tot_new:.4f}")
    print("\nATENÇÃO: as colunas do Camp 49 vêm de amostra INCOMPLETA (perda de 13-66% por "
          "erro de endpoint, e não aleatória). Só a linha do re-teste é comparável com os "
          "demais braços do report.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
