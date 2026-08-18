#!/usr/bin/env python3
"""Camp 48 — Fase A: screen de capacidade dos candidatos antes da rodada cheia.

Roda o perfil `casc_v1_low` (paridade de prompt com prod) num subconjunto pequeno e
aplica quatro portas eliminatórias. O objetivo NÃO é medir recall com precisão — é
gastar US$ 4-6 para não gastar US$ 50 num modelo que nem devolve JSON.

    A1 JSON      >=80% de respostas válidas no schema
    A2 payload   a janela cabe no teto de corpo do Bedrock (~2,7 MB)
    A3 recall    dispara em >=1 dos TPs
    A4 pt-BR     evidence_summary do DETAIL em português — INFORMATIVO, não elimina:
                 o prompt V1 de detail é escrito em pt-BR mas nunca PEDE o idioma
                 (o Gemini infere, os open-weight não). É uma linha de prompt de
                 distância, então cortar por isso enviesaria a campanha.

Uso:
    python scripts/screen_bedrock.py                     # 8 candidatos
    python scripts/screen_bedrock.py --models gemma-3-27b,qwen3-vl-235b
    python scripts/screen_bedrock.py --report-only
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAMPAIGN = HERE.parent
CSV_PATH = CAMPAIGN / "results" / "bench_bedrock_screen.csv"

# Ordem = da mais promissora (custo x capacidade) para a menos.
# llama4-* fora: teto de 3 imagens, eliminado pelo probe (ver _bedrock_client).
CANDIDATES = ["gemma-3-27b", "qwen3-vl-235b", "nemotron-nano-12b", "magistral-small",
              "gemma-3-12b", "kimi-k2.5", "ministral-3-14b", "palmyra-vision-7b"]
PROFILE = "casc_v1_low"
# palmyra tem teto de 5 imagens -> só consegue rodar em mosaico
PROFILE_OVERRIDE = {"palmyra-vision-7b": "single_g3_mosaic"}

# 6 tp + 5 fp + 4 baseline: --limit é por categoria, então peço 6 e corto depois
LIMIT_PER_CAT = 6
CATS = "tp,fp,baseline"

A1_MIN_JSON = 80.0
A3_MIN_TP_FIRES = 1

# Marcadores de português que praticamente não aparecem em inglês.
_PT = re.compile(r"[ãõçáéíóúâêô]|\b(uma|não|está|veículo|pilha|entulho|calçada|"
                 r"descarte|pessoa|frente|lixo|rua|material|caminhão)\b", re.I)


def run_candidate(alias: str, workers: int) -> None:
    prof = PROFILE_OVERRIDE.get(alias, PROFILE)
    cmd = [sys.executable, "-X", "utf8", "-u", str(HERE / "bench_bedrock.py"),
           "--arms", f"{alias}:{prof}", "--limit", str(LIMIT_PER_CAT),
           "--cats", CATS, "--tag", "screen", "--workers", str(workers)]
    print(f"\n>>> {alias} ({prof})", flush=True)
    subprocess.run(cmd, cwd=CAMPAIGN, check=False)


def report(models: list[str]) -> int:
    if not CSV_PATH.exists():
        print(f"sem resultados em {CSV_PATH}")
        return 1
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    print(f"\n{'='*104}\nFase A — portas de capacidade  (n={len(rows)} chamadas)\n{'='*104}")
    hdr = (f"{'modelo':20} {'A1 json':>8} {'A2 payload':>11} {'A3 tp':>7} {'A4 ptBR':>8} "
           f"{'fp':>5} {'base':>5} {'$/ev':>9} {'p50 s':>6}  veredicto")
    print(hdr)
    print("-" * 104)
    survivors = []
    for alias in models:
        sub = [r for r in rows if r["arm"].startswith(alias + ":")]
        if not sub:
            print(f"{alias:20} {'—':>8} {'—':>11} {'—':>7} {'—':>8} "
                  f"{'—':>5} {'—':>5} {'—':>9} {'—':>6}  SEM DADOS")
            continue
        jv = [r for r in sub if str(r.get("json_valid")) in ("0", "1")]
        a1 = 100 * sum(1 for r in jv if r["json_valid"] == "1") / len(jv) if jv else 0.0
        pay_err = sum(1 for r in sub if "payload:" in (r["error"] or ""))
        a2 = pay_err == 0
        ok = [r for r in sub if not r["error"]]
        tp = [r for r in ok if r["category"] == "tp"]
        tp_fire = sum(1 for r in tp if r["disposal"] == "1")
        fp = [r for r in ok if r["category"] == "fp"]
        fp_fire = sum(1 for r in fp if r["disposal"] == "1")
        bl = [r for r in ok if r["category"] == "baseline"]
        bl_fire = sum(1 for r in bl if r["disposal"] == "1")
        # só o estágio de detail conta para pt-BR: o prompt do GATE é em inglês
        # (NEW_LITTER_SYSTEM_PROMPT), então evidência em inglês ali é o esperado.
        eviz = [r["evidence"] for r in sub
                if (r["evidence"] or "").strip() and str(r.get("detail_conf") or "").strip()]
        a4 = 100 * sum(1 for e in eviz if _PT.search(e)) / len(eviz) if eviz else 0.0
        costs = [float(r["cost_usd"]) for r in ok if r["cost_usd"]]
        lats = sorted(int(r["latency_ms"]) for r in ok if str(r["latency_ms"]).isdigit())

        fails = []
        if a1 < A1_MIN_JSON:
            fails.append("A1")
        if not a2:
            fails.append("A2")
        if tp_fire < A3_MIN_TP_FIRES:
            fails.append("A3")
        # Guarda de degenerescencia: um modelo que dispara em quase TODO negativo
        # nao tem recall, tem viés de "sim". Com N=6 o A3 sozinho nao ve isso —
        # gemma-3-12b marcou tp 5/5 e tambem fp 5/5 + baseline 2/6.
        degenerate = (len(fp) >= 3 and fp_fire / len(fp) >= 0.8)
        verdict = "PASSA" if not fails else "CORTA (" + ",".join(fails) + ")"
        if not fails and degenerate:
            verdict = "PASSA (degenerado: dispara em quase tudo)"
        elif not fails and eviz and a4 < 50:
            verdict = "PASSA (avisa: detail em ingles)"
        if not fails:
            survivors.append({"alias": alias, "tp": tp_fire, "tp_n": len(tp),
                              "fp": fp_fire, "fp_n": len(fp), "bl": bl_fire,
                              "degenerate": degenerate,
                              "cost": sum(costs) / len(costs) if costs else 0})
        print(f"{alias:20} {a1:7.0f}% {('ok' if a2 else f'{pay_err} err'):>11} "
              f"{f'{tp_fire}/{len(tp)}':>7} {a4:7.0f}% "
              f"{f'{fp_fire}/{len(fp)}':>5} {f'{bl_fire}/{len(bl)}':>5} "
              f"{(sum(costs)/len(costs) if costs else 0):9.5f} "
              f"{(lats[len(lats)//2]/1000 if lats else 0):6.1f}  {verdict}")

    print("-" * 104)
    if not survivors:
        print("nenhum candidato passou — nada a levar para a Fase B")
        return 1
    # Ranking: recall primeiro; disparos indevidos (fp + baseline) DEPOIS; custo
    # desempata. Ignorar o fp — como a 1a versao fazia — colocava na frente modelos
    # que disparam em tudo: gemma-3-27b acerta 5/6 TP mas tambem 6/6 FP.
    for s in survivors:
        s["false_fires"] = s["fp"] + s["bl"]
    # degenerados vao para o fim da fila, independente do recall aparente
    survivors.sort(key=lambda s: (s["degenerate"], -s["tp"], s["false_fires"], s["cost"]))
    print("Finalistas para a Fase B (recall > disparos indevidos > custo):")
    for i, s in enumerate(survivors[:3], 1):
        print(f"  {i}. {s['alias']:20} tp {s['tp']}/{s['tp_n']}  "
              f"fp {s['fp']}/{s['fp_n']}  baseline-fire {s['bl']}  ${s['cost']:.5f}/ev")
    resto = survivors[3:]
    if resto:
        print("  fora do top-3: " + ", ".join(
            f"{s['alias']} (tp {s['tp']}/{s['tp_n']}, disparos indevidos {s['false_fires']})"
            for s in resto))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(CANDIDATES))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    if not a.report_only:
        for alias in models:
            run_candidate(alias, a.workers)
    return report(models)


if __name__ == "__main__":
    sys.exit(main())
