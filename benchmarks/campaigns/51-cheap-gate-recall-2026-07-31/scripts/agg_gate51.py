#!/usr/bin/env python3
"""Camp 51 — agregação da Fase A e veredito contra os 4 critérios de aceite.

Lê `results/gate51_faseA.csv` e produz a tabela recall-do-gate x taxa-de-disparo por
braço, nas duas regras de decisão (`raw` = a do próprio prompt, `v1` = com o pós-gate
determinístico de produção por cima).

Critérios (HANDOFF_CHEAP_GATE.md, "Critério de aceite"), na ordem que importa:
  1. recall do gate >= o do gate de produção      -> ELIMINATÓRIO
  2. disparo em fp/baseline <= o de produção
  3. taxa de passagem  (aqui: no dataset; a de tráfego sai na Fase B)
  4. disponibilidade: 0 erro

⚠️ A taxa de passagem NO DATASET não é a de tráfego: o dataset é construído com
35/32/40/15 por categoria, proporção que não existe na rua. Ela serve para ORDENAR
candidatos, não para estimar custo. O custo/evento honesto sai da Fase B, onde o
denominador é a distribuição real do ledger (11,2% dos eventos com gate g3 positivo).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent.parent
RESULTS = HERE / "results"
# Vários CSV porque a Fase A pode ser rodada em processos paralelos (`--out`).
CSV_GLOB = "gate51_faseA*.csv"
OUT_JSON = RESULTS / "gate51_faseA_summary.json"
PROD_ARM = "gemini-2.5-flash-lite:v1"     # gate de produção hoje; regra `v1`


def pct(num, den):
    return 100.0 * num / den if den else 0.0


def main():
    files = sorted(RESULTS.glob(CSV_GLOB))
    if not files:
        raise SystemExit(f"nenhum {CSV_GLOB} em {RESULTS} — rode bench_gate51.py primeiro")
    rows = [r for f in files for r in csv.DictReader(f.open(encoding="utf-8", newline=""))]
    print(f"lidos {len(rows)} registros de {', '.join(f.name for f in files)}")
    # Resumabilidade grava append-only: se um evento foi re-rodado depois de um erro,
    # vale a ÚLTIMA linha sem erro.
    latest: dict[tuple[str, str], dict] = {}
    errors: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        key = (r["arm"], r["event_id"])
        if r.get("error"):
            errors[r["arm"]].append(f"{r['event_id']}: {r['error'][:80]}")
            latest.setdefault(key, r)
        else:
            latest[key] = r

    by_arm: dict[str, list[dict]] = defaultdict(list)
    for r in latest.values():
        by_arm[r["arm"]].append(r)

    summary = {}
    for arm, rs in by_arm.items():
        ok = [r for r in rs if not r.get("error")]
        ent = {"n": len(rs), "n_ok": len(ok), "n_erro": len(rs) - len(ok),
               "erros": errors.get(arm, [])[:5]}
        for rule in ("raw", "v1"):
            per_cat = {}
            for cat in ("tp", "fp", "baseline", "indefinido"):
                sub = [r for r in ok if r["category"] == cat]
                fired = sum(int(r[f"fire_{rule}"] or 0) for r in sub)
                per_cat[cat] = {"n": len(sub), "fire": fired,
                                "taxa": round(pct(fired, len(sub)), 1)}
            decisivos = [r for r in ok if r["category"] in ("tp", "fp", "baseline")]
            ent[rule] = {
                "recall_tp": per_cat["tp"]["taxa"],
                "tp_perdidos": per_cat["tp"]["n"] - per_cat["tp"]["fire"],
                "disparo_fp": per_cat["fp"]["taxa"],
                "disparo_baseline": per_cat["baseline"]["taxa"],
                "passagem_dataset": round(pct(sum(int(r[f"fire_{rule}"] or 0)
                                                  for r in decisivos), len(decisivos)), 1),
                "por_categoria": per_cat,
            }
        custo = [float(r["cost_usd"] or 0) for r in ok]
        lat = sorted(int(r["latency_ms"] or 0) for r in ok)
        ent["custo_usd_por_chamada"] = round(sum(custo) / len(custo), 8) if custo else 0.0
        ent["latencia_p50_ms"] = lat[len(lat) // 2] if lat else 0
        ent["tok_in_medio"] = round(sum(int(r["tok_in"] or 0) for r in ok) / len(ok)) if ok else 0
        summary[arm] = ent

    prod = summary.get(PROD_ARM)
    ref_recall = prod["v1"]["recall_tp"] if prod else None
    ref_fp = prod["v1"]["disparo_fp"] if prod else None
    ref_base = prod["v1"]["disparo_baseline"] if prod else None
    ref_pass = prod["v1"]["passagem_dataset"] if prod else None

    print(f"\nreferência de produção ({PROD_ARM}, regra v1): ", end="")
    print(f"recall {ref_recall}% · fp {ref_fp}% · baseline {ref_base}%"
          if prod else "AUSENTE — rode o braço, sem ele não há critério 1")

    hdr = (f"\n{'braço':<30} {'regra':<5} {'recall tp':>10} {'perdidos':>9} "
           f"{'fp':>7} {'baseline':>9} {'passa':>7} {'US$/ch':>10} {'p50 ms':>8} {'err':>4}")
    print(hdr)
    print("-" * len(hdr))
    for arm in sorted(summary):
        e = summary[arm]
        for rule in ("raw", "v1"):
            d = e[rule]
            print(f"{arm:<30} {rule:<5} {d['recall_tp']:>9.1f}% {d['tp_perdidos']:>9} "
                  f"{d['disparo_fp']:>6.1f}% {d['disparo_baseline']:>8.1f}% "
                  f"{d['passagem_dataset']:>6.1f}% {e['custo_usd_por_chamada']:>10.6f} "
                  f"{e['latencia_p50_ms']:>8} {e['n_erro']:>4}")

    # Um braço a meio caminho gera percentual que parece medição e não é (n=4 vira
    # "100% de disparo em baseline" com um único evento). Só entra no veredito quem
    # cobriu o dataset inteiro; o resto sai rotulado como PARCIAL.
    # `n` = eventos TENTADOS, `n_ok` = respondidos. A distinção importa: um braço que
    # tentou os 122 e falhou em 4 está COMPLETO e reprova no critério 4 — chamá-lo de
    # "parcial" esconderia exatamente a indisponibilidade que o critério existe para pegar.
    n_total = max(e["n"] for e in summary.values())
    if prod and prod["n"] < n_total:
        print(f"⚠️  referência de produção incompleta ({prod['n_ok']}/{n_total}) — "
              f"veredito suspenso até ela fechar")
        prod = None

    if prod:
        # Dos 4 critérios de aceite, a Fase A decide 3. O critério 2 ("FP de ponta a
        # ponta <= o de hoje") NÃO é decidível aqui: ele é medido DEPOIS do detail, e
        # um gate que dispara mais não gera mais FP se o detail rejeitar o excedente
        # (~63% de rejeição medidos em project_detail_rejection_rate). Disparo em fp e
        # em baseline entra como DIAGNÓSTICO, não como reprovação — reprovar por ele
        # seria cobrar do gate uma seletividade que o desenho não lhe pede.
        # Reprovam aqui: recall abaixo do gate atual (1), passagem >= 25% (3) e
        # qualquer erro de disponibilidade (4).
        # ⚠️ O teto de 25% do critério 3 é taxa de passagem em TRÁFEGO. Não se aplica a
        # este dataset, que é montado 35/32/40/15 por categoria — proporção que não
        # existe na rua e onde ~33% dos eventos DEVEM disparar (a própria produção
        # passa 48,6% aqui). Em Fase A o proxy honesto é "passa no máximo o que a
        # produção passa"; o número absoluto contra os 25% só sai na Fase B.
        print("\nVEREDITO (melhor regra de cada braço)")
        print(f"  c1 recall >= produção (ELIMINATÓRIO) · c3' passagem <= produção "
              f"({ref_pass:.1f}%, proxy) · c4 zero erro")
        print("  c2 (FP fim-a-fim) exige o detail; c3 absoluto exige tráfego — Fase B")
        print("-" * 100)
        for arm in sorted(summary):
            if arm == PROD_ARM:
                continue
            e = summary[arm]
            if e["n"] < n_total:
                print(f"{'PARCIAL':<10} {arm:<30} {e['n']}/{n_total} eventos — sem veredito")
                continue
            best = max(("raw", "v1"), key=lambda k: (e[k]["recall_tp"],
                                                     -e[k]["passagem_dataset"]))
            d = e[best]
            c1 = d["recall_tp"] >= ref_recall
            c3 = d["passagem_dataset"] <= ref_pass
            c4 = e["n_erro"] == 0
            marca = "APROVADO" if (c1 and c3 and c4) else "REPROVADO"
            motivos = []
            if not c1:
                motivos.append(f"c1 recall {d['recall_tp']:.1f}% < {ref_recall:.1f}% "
                               f"({d['tp_perdidos']} TP perdidos)")
            if not c3:
                motivos.append(f"c3' passagem {d['passagem_dataset']:.1f}% > "
                               f"{ref_pass:.1f}% da produção")
            if not c4:
                motivos.append(f"c4 {e['n_erro']} erro(s)")
            diag = (f"[diag: fp {d['disparo_fp']:.0f}% vs {ref_fp:.0f}%, "
                    f"baseline {d['disparo_baseline']:.0f}% vs {ref_base:.0f}%]")
            print(f"{marca:<10} {arm:<30} (regra {best}) "
                  f"{'; '.join(motivos) if motivos else 'passa em c1/c3/c4'} {diag}")
            summary[arm]["veredito"] = {"resultado": marca, "regra": best, "motivos": motivos}

    OUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {OUT_JSON}")


if __name__ == "__main__":
    main()
