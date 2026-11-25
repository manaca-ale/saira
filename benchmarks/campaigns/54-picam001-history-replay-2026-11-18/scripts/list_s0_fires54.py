#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — SEM CUSTO: lista os eventos S0 (o gate de producao nao disparou) em que os candidatos a gate
disparam, para o detail dizer quantos sao descarte de verdade (missao 5).

Um gate que aceita descarte a pe dispara em S0 que o gate de hoje deixou passar em branco. Pelas
justificativas e por frames (secao 12.4 do handoff), parte disso e descarte real que a producao perde, e
parte e catador. So o detail (e depois o operador) separa. Esta lista diz quais eventos rodar e quais ja
tem a janela completa em disco (`amostra/s0_nota_alta_dev_ids.txt`: os 48 de nota >= 0,70 buscados em
18/11; `amostra/s0_fires_pass_ids.txt`: os 79 do `pass` buscados em 19/11); os demais so tem os 5 frames
do gate e pedem busca em producao (sessao interativa, com o ok dele).

Uso: python list_s0_fires54.py [--arms g31l_v1p_min_low,nvl_v1p_low] [--set pass]
Saida: ../results/s0_fires54__<conjunto>.tsv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import run_gate54 as g

RESULTS = Path(__file__).resolve().parent.parent / "results"
CTRL = ("g25l_v1_t2048", "g25l_v1_t1024")
# Listas de eventos S0 com a janela completa em disco (buscas em producao, so leitura, com o ok do Alexandre):
# 18/11 (48 de nota >= 0,70) e 19/11 (79 do `pass` em que os candidatos a gate disparam).
ID_LISTS = ("s0_nota_alta_dev_ids.txt", "s0_fires_pass_ids.txt")


def load(arm: str) -> dict:
    out = {}
    p = RESULTS / f"gate54__{arm}__r1.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if not r.get("error"):
                    out[r["event_id"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="g31l_v1p_min_low,nvl_v1p_low")
    ap.add_argument("--set", default="pass", choices=["tri", "pass"])
    a = ap.parse_args()
    arms = [x for x in a.arms.split(",") if x]
    recs = {x: load(x) for x in arms + list(CTRL)}
    on_disk = set()
    for name in ID_LISTS:
        ids_file = g.ROOT / "amostra" / name
        if ids_file.exists():
            on_disk |= set(ids_file.read_text(encoding="utf-8").split())
    rows = []
    for ev in g.build_set(a.set, 0.30):
        if ev["sub"] != "S0":
            continue
        e = ev["event_id"]
        fires = {x: recs[x].get(e, {}).get("fire") for x in arms}
        if not any(fires.values()):
            continue
        first = next((recs[x][e] for x in arms if fires[x]), {})
        rows.append([e, f"{ev['score']:.3f}", int(e in on_disk)]
                    + [("" if fires[x] is None else int(fires[x])) for x in arms]
                    + [("" if recs[c].get(e) is None else int(recs[c][e]["fire"])) for c in CTRL]
                    + [(first.get("evidence") or "").replace("\t", " ")[:200]])
    rows.sort(key=lambda r: -float(r[1]))
    out = RESULTS / f"s0_fires54__{a.set}.tsv"
    head = ["event_id", "nota_wl_v2", "janela_em_disco"] + arms + list(CTRL) + ["justificativa_do_primeiro_braco"]
    out.write_text("\n".join("\t".join(str(c) for c in r) for r in [head] + rows) + "\n", encoding="utf-8")
    n = len(rows)
    disk = sum(r[2] for r in rows)
    print(f"S0 do conjunto {a.set} em que algum candidato dispara: {n} | com janela completa em disco: {disk} | "
          f"so com os 5 frames do gate: {n - disk}")
    for i, x in enumerate(arms):
        k = sum(1 for r in rows if r[3 + i] == 1)
        kc = sum(1 for r in rows if r[3 + i] == 1 and (r[3 + len(arms)] == 1 or r[4 + len(arms)] == 1))
        print(f"  {x}: dispara em {k}; destes, o gate de hoje repetido (2048 ou 1024) tambem disparou em {kc}")
    both = sum(1 for r in rows if all(r[3 + i] == 1 for i in range(len(arms))))
    print(f"  nos {len(arms)} candidatos ao mesmo tempo: {both}")
    print(f"gravado: {out.name}")


if __name__ == "__main__":
    main()
