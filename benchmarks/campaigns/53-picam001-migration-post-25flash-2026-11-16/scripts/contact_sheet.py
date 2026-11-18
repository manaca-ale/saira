#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — folha de contato de um evento, para conferir os frames a olho (sem custo).

Monta grades 2x2 com frames espalhados pela janela do evento (um por rajada, quando da),
cada um com o horario no canto. As folhas saem FORA do repositorio (sao imagens de camera).

Uso: python contact_sheet.py [--dataset pi-inicial-v1] [--k 8] [--crop x0,y0,x1,y1] evt-... [evt-...]
     --k     quantos frames (multiplo de 4; cada 4 viram uma folha)
     --crop  recorte em fracoes do frame (ex.: 0.3,0.3,1,1), para ampliar uma regiao
     --bbox  caixa do modelo [y_min,x_min,y_max,x_max] em 0-1000, desenhada em todos os frames
             (pode repetir: a primeira sai em vermelho, a segunda em ciano)
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

import bench53 as b

OUT = Path.home() / ".saira-bench" / "sheets"
TILE = (784, 441)


def pick(frames, k, dedupe=True):
    """Um frame por rajada (mesmo segundo no nome), espalhados; sempre inclui o primeiro e o
    ultimo. O nome do arquivo traz a hora da GRAVACAO: frames de pre-rolagem saem no mesmo
    segundo com horas de camera diferentes; `dedupe=False` (--no-dedupe) usa todos."""
    by_sec: dict[str, Path] = {}
    for f in frames:
        by_sec.setdefault(f.name[:19], f)
    uniq = list(by_sec.values()) if dedupe else list(frames)
    if frames[-1] not in uniq:
        uniq[-1] = frames[-1]
    if len(uniq) <= k:
        return uniq
    idx = sorted({round(i * (len(uniq) - 1) / (k - 1)) for i in range(k)})
    return [uniq[i] for i in idx]


def sheet(paths, crop, out, bboxes=()):
    img = Image.new("RGB", (TILE[0] * 2, TILE[1] * 2), "black")
    for i, p in enumerate(paths):
        im = Image.open(p).convert("RGB")
        for (y0, x0, y1, x1), color in zip(bboxes, ("red", "cyan", "magenta")):
            w, h = im.size
            ImageDraw.Draw(im).rectangle((x0 * w / 1000, y0 * h / 1000, x1 * w / 1000, y1 * h / 1000),
                                         outline=color, width=max(2, w // 400))
        if crop:
            w, h = im.size
            im = im.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h)))
        im.thumbnail(TILE, Image.LANCZOS)
        x, y = (i % 2) * TILE[0], (i // 2) * TILE[1]
        img.paste(im, (x, y))
        d = ImageDraw.Draw(img)
        d.rectangle((x, y, x + 150, y + 16), fill="black")
        d.text((x + 3, y + 2), p.name[11:19] + " #" + p.stem[-3:], fill="yellow")
    img.save(out, quality=88)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="official")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--crop", default=None)
    ap.add_argument("--all-frames", action="store_true", help="usa todos os frames, nao so a janela")
    ap.add_argument("--bbox", action="append", default=[])
    ap.add_argument("--no-dedupe", action="store_true", help="nao junta frames do mesmo segundo")
    ap.add_argument("events", nargs="+")
    a = ap.parse_args()
    crop = [float(v) for v in a.crop.split(",")] if a.crop else None
    bboxes = [[float(v) for v in s.split(",")] for s in a.bbox]
    b.DS["name"] = a.dataset
    OUT.mkdir(parents=True, exist_ok=True)
    evs = {e["event_id"]: e for e in b.load_events(only=set(a.events))}
    for eid in a.events:
        ev = evs.get(eid)
        if ev is None:
            print(f"{eid}: nao encontrado em {a.dataset}")
            continue
        frames = ev["frames"] if a.all_frames else b.build_window(ev["frames"])
        chosen = pick(frames, a.k, dedupe=not a.no_dedupe)
        tag = ("_crop" if crop else "") + ("_bbox" if bboxes else "")
        for n in range(0, len(chosen), 4):
            out = OUT / f"{eid}{tag}_{n // 4 + 1}.jpg"
            sheet(chosen[n:n + 4], crop, out, bboxes)
            print(f"{eid} [{ev['category']}] frames={len(ev['frames'])} janela={len(frames)} -> {out}")


if __name__ == "__main__":
    main()
