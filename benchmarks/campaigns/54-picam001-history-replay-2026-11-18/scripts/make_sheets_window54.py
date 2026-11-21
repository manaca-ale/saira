#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — folha de contato da janela inteira, para conferir a olho um "sim" do detail (missao 6).

Por evento: primeiro e ultimo frame da janela, o recorte ampliado da regiao que o detail apontou como
residuo (raw_waste_bbox, [ymin, xmin, ymax, xmax] em milesimos) nesses dois frames, e os 6 frames com mais
movimento (diferenca para a mediana da janela), em ordem de tempo.
So le C:\\Saira\\data e o resultado do braco; as paginas vao para --out (fora do git). So eventos do dev.

Uso: python make_sheets_window54.py --arm d25f_v1 --file lista.txt --out C:/tmp/sheets6 --name s0sim
     (lista: um evento por linha, opcionalmente <TAB>legenda)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(r"C:\Saira\data\historico-picam")
RESULTS = Path(__file__).resolve().parent.parent / "results"
FW, CW, MW = 400, 380, 260  # larguras: frame inteiro, recorte, frame de movimento


def find(name):
    for d in ("janela", "gate5"):
        p = ROOT / "frames" / d / name
        if p.is_file():
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="d25f_v1")
    ap.add_argument("--file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--per-page", type=int, default=3)
    a = ap.parse_args()
    items = []
    for line in Path(a.file).read_text(encoding="utf-8").splitlines():
        if line.strip():
            ev, _, cap = line.partition("\t")
            items.append((ev.strip(), cap.strip()))
    sample = {r["event_id"]: r for r in csv.DictReader((ROOT / "amostra" / "sample.csv").open(encoding="utf-8", newline=""))}
    det = {}
    split = os.environ.get("CAMP54_SPLIT", "dev")   # aval so na medicao final (missao 10), depois de rodar
    sfx = "" if split == "dev" else f"__{split}"
    for line in (RESULTS / f"detail54__{a.arm}{sfx}__r1.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error"):
                det[r["event_id"]] = r
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for ev, cap in items:
        r = sample[ev]
        if r["split"] != split:
            raise SystemExit(f"{ev} nao e do conjunto {split}; nao olhar")
        paths = [p for p in (find(n) for n in r["window"].split("|") if n) if p]
        if len(paths) < 2:
            print(f"{ev}: janela fora do disco")
            continue
        ims = [Image.open(p).convert("RGB") for p in paths]
        small = np.stack([np.asarray(im.convert("L").resize((160, 90)), dtype=np.int16) for im in ims])
        motion = np.abs(small - np.median(small, axis=0)).mean(axis=(1, 2))
        mids = sorted(sorted(range(1, len(ims) - 1), key=lambda i: -motion[i])[:6])
        W, H = ims[0].size
        fh, mh = int(H * FW / W), int(H * MW / W)
        box = (det.get(ev) or {}).get("raw_waste_bbox")
        row = Image.new("RGB", (2 * FW + 2 * CW, 16 + fh + mh), "white")
        d = ImageDraw.Draw(row)
        d.text((4, 2), f"{ev} [{len(ims)} frames] {cap}"[:250], fill="black")
        for k, im in enumerate((ims[0], ims[-1])):
            full = im.resize((FW, fh))
            if box and len(box) == 4:
                y0, x0, y1, x1 = (v / 1000 for v in box)
                ImageDraw.Draw(full).rectangle((x0 * FW, y0 * fh, x1 * FW, y1 * fh), outline="red", width=2)
                cx, cy, bw, bh = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, 0.12) * 2.0, max(y1 - y0, 0.12) * 2.0
                bw = max(bw, bh * (CW / fh) * H / W)
                bh = bw * (fh / CW) * W / H
                l, t = max(0.0, min(1 - bw, cx - bw / 2)), max(0.0, min(1 - bh, cy - bh / 2))
                crop = im.crop((int(l * W), int(t * H), int(min(1.0, l + bw) * W), int(min(1.0, t + bh) * H)))
                row.paste(crop.resize((CW, fh)), (2 * FW + k * CW, 16))
            row.paste(full, (k * FW, 16))
        for k, i in enumerate(mids):
            row.paste(ims[i].resize((MW, mh)), (k * MW, 16 + fh))
        rows.append(row)
    for p in range(0, len(rows), a.per_page):
        chunk = rows[p:p + a.per_page]
        page = Image.new("RGB", (chunk[0].width, sum(r.height for r in chunk)), "white")
        y = 0
        for row in chunk:
            page.paste(row, (0, y))
            y += row.height
        dst = out / f"{a.name}_{p // a.per_page + 1:02d}.jpg"
        page.save(dst, quality=82)
        print(dst)


if __name__ == "__main__":
    main()
