#!/usr/bin/env python3
"""Camp 49 — importa o controle V1 do Camp 48 sem gastar uma chamada.

Por que não re-rodar: as decisões por evento do braço `current` já existem
(122 eventos, 0 erros, recall 87,5% = idêntico ao Camp 47 e ao Camp 48). A Fase 0
mudou **rótulos**, não decisões do modelo — reavaliar contra os rótulos novos é
aritmética. Economiza ~US$ 0,90 e ~40 min, e evita introduzir ruído estocástico
justamente na linha de base.

As categorias são relidas do DISCO (o `apply_relabel.py` já moveu os diretórios), não
da coluna `category` do CSV do Camp 48, que está congelada nos rótulos antigos.

Uso:
    python scripts/import_control.py            # dry-run: mostra o antes/depois
    python scripts/import_control.py --apply    # grava em results/bench_v4.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
CAMP = Path(__file__).resolve().parents[1]
CAM = ROOT / "data" / "datasets" / "official" / "cam_picam001"
SRC = ROOT / "benchmarks" / "campaigns" / "48-bedrock-oss-vlm-picam001-2026-07-30" / \
    "results" / "bench_bedrock.csv"
DST = CAMP / "results" / "bench_v4.csv"
CATS = ("tp", "fp", "indefinido", "baseline")


def cat_no_disco() -> dict[str, str]:
    return {d.name: c for c in CATS for d in (CAM / c).iterdir()
            if d.is_dir() and (d / "label.json").exists()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--arm", default="current")
    a = ap.parse_args()

    atual = cat_no_disco()
    rows = [r for r in csv.DictReader(SRC.open(encoding="utf-8")) if r["arm"] == a.arm]
    if not rows:
        sys.exit(f"braço '{a.arm}' não encontrado em {SRC}")

    mudou = [(r["event_id"], r["category"], atual[r["event_id"]])
             for r in rows if atual.get(r["event_id"]) != r["category"]]
    print(f"linhas importadas: {len(rows)}   categorias corrigidas: {len(mudou)}")
    for e, de, para in sorted(mudou):
        disp = next(r["disposal"] for r in rows if r["event_id"] == e)
        print(f"  {e:24} {de:>4} -> {para:<4} (o controle disparou? "
              f"{'sim' if disp == '1' else 'NAO'})")

    for r in rows:
        r["category"] = atual.get(r["event_id"], r["category"])
        r["arm"] = "current_v1"       # nome explicito: V1 importado, nao re-rodado
        r["prompt"] = "v1"

    if not a.apply:
        print("\n[DRY-RUN] nada gravado. Rode com --apply.")
        return 0

    # As colunas TÊM que ser as do runner. O CSV do Camp 48 tem 29 e o runner do Camp 49
    # tem 31 (ganhou gate_img/gate_n_images); o guard de cabeçalho do `append_csv` aborta
    # a rodada INTEIRA se divergir — foi exatamente o que matou a 1ª tentativa da Fase 2.
    import os as _os
    _os.environ.setdefault("DATABASE_URL", "postgresql://b:b@localhost/b")
    sys.path.insert(0, str(CAMP / "scripts"))
    from bench_bedrock import COLS as RUNNER_COLS
    cols = list(RUNNER_COLS)
    if DST.exists():
        cols = next(csv.reader(DST.open(encoding="utf-8")))
        existentes = {(r["arm"], r["event_id"])
                      for r in csv.DictReader(DST.open(encoding="utf-8"))}
        rows = [r for r in rows if (r["arm"], r["event_id"]) not in existentes]
        if not rows:
            print("nada novo a gravar (já importado)")
            return 0
        modo = "a"
    else:
        modo = "w"   # cols ja vem do runner — NAO derivar do CSV de origem (Camp 48
                     # tem 29 colunas; o runner do Camp 49 tem 31)

    with DST.open(modo, encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if modo == "w":
            w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    print(f"\ngravadas {len(rows)} linhas em {DST.name} como braço 'current_v1'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
