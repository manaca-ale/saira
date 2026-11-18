#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — folha de contato dos 5 frames do gate de cada evento, para olhar os erros de um filtro.

Monta paginas com um evento por linha (5 frames lado a lado) e uma legenda com o que for passado.
So le C:\\Saira\\data; as paginas vao para a pasta indicada em --out (fora do git).

Uso: python make_sheets54.py --out C:/tmp/sheets --name bloqueadas --events "evt-a=legenda;evt-b=legenda"
     python make_sheets54.py --out C:/tmp/sheets --name s0 --file lista.txt   (uma linha: evento<TAB>legenda)
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(r"C:\Saira\data\historico-picam")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--events", default="")
    ap.add_argument("--file", default="")
    ap.add_argument("--per-page", type=int, default=2)
    ap.add_argument("--width", type=int, default=520, help="largura de cada frame na folha")
    a = ap.parse_args()
    items = []
    if a.events:
        for part in a.events.split(";"):
            ev, _, cap = part.partition("=")
            items.append((ev.strip(), cap.strip()))
    if a.file:
        for line in Path(a.file).read_text(encoding="utf-8").splitlines():
            if line.strip():
                ev, _, cap = line.partition("\t")
                items.append((ev.strip(), cap.strip()))
    sample = {r["event_id"]: r for r in csv.DictReader((ROOT / "amostra" / "sample.csv").open(encoding="utf-8", newline=""))}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for p in range(0, len(items), a.per_page):
        rows = []
        for ev, cap in items[p:p + a.per_page]:
            r = sample[ev]
            if r["split"] != "dev":
                raise SystemExit(f"{ev} nao e do conjunto de desenvolvimento; nao olhar")
            frames = [Image.open(ROOT / "frames" / "gate5" / n).convert("RGB") for n in r["gate5"].split("|") if n]
            h = int(frames[0].height * a.width / frames[0].width)
            # grade 3 x 2 (ordem de leitura: primeiro, tres do meio, ultimo), para cada frame ficar legivel
            row = Image.new("RGB", (a.width * 3, 2 * h + 18), "white")
            for i, im in enumerate(frames[:5]):
                row.paste(im.resize((a.width, h)), ((i % 3) * a.width, 18 + (i // 3) * h))
            ImageDraw.Draw(row).text((4, 3), f"{ev} [{r['estrato']} {r['status']}] {cap}", fill="black")
            rows.append(row)
        page = Image.new("RGB", (a.width * 3, sum(r.height for r in rows)), "white")
        y = 0
        for row in rows:
            page.paste(row, (0, y))
            y += row.height
        dst = out / f"{a.name}_{p // a.per_page + 1:02d}.jpg"
        page.save(dst, quality=80)
        print(dst)


if __name__ == "__main__":
    main()
