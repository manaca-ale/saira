#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Protótipo: volume longitudinal da pilha (cam_11) ao longo do dia.

Mede a persistência de foreground na pile-zone (material que FICA, ignora transeunte)
por bucket de 15 min, relativo ao baseline da manhã. Sobrepõe os eventos reais do dia.
Mostra que descarte real = degrau pra cima; FP transeunte não move a curva.
"""
import csv
import re
import sys
from pathlib import Path

import numpy as np
import cv2

ROOT = Path(r"c:\saira")
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import spike_bgsub_filter as spk  # noqa: E402
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

VP = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "volume_proto"
FR = VP / "frames"
# pile_zone_polygon REAL do esp32_002 (banco) — quad inclinado, justo na pilha
# (≠ retângulo axis-aligned do spike, que pegava via/calçada e poluía o sinal).
PILE_POLY = np.array([[461, 154], [704, 66], [939, 299], [617, 416]], np.int32)
ZONE = np.zeros((720, 1280), np.uint8)
cv2.fillPoly(ZONE, [PILE_POLY], 255)
KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))


def tmin(fname):
    m = re.search(r"_(\d\d)-(\d\d)-(\d\d)", fname)
    return int(m.group(1)) * 60 + int(m.group(2))


def fg_mask(img, bg):
    m = bg.apply(img, learningRate=0)
    m = (m > 200).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, KERNEL)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, KERNEL)
    return cv2.bitwise_and(m, ZONE) > 0


def main():
    frames = sorted(FR.glob("*.jpg"))
    buckets = {}
    for f in frames:
        buckets.setdefault((tmin(f.name) // 15) * 15, []).append(f)
    keys = sorted(buckets)

    # baseline MOG2: treina nos 3 primeiros buckets (manhã) — pilha de início = background
    bg = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=40, detectShadows=True)
    for k in keys[:3]:
        for f in buckets[k]:
            img = cv2.imread(str(f))
            if img is not None:
                bg.apply(img, learningRate=0.3)

    # A pilha = PISO do sinal (cena vazia). Por bucket pega o frame MAIS VAZIO
    # (menos FG = sem gente) → leitura limpa da pilha estática.
    series = []
    for k in keys:
        fgs = []
        for f in buckets[k]:
            img = cv2.imread(str(f))
            if img is None:
                continue
            fgs.append(int(np.count_nonzero(fg_mask(img, bg))))
        if fgs:
            series.append((k, min(fgs)))   # emptiest-frame = pile floor

    xs = [k / 60 for k, _ in series]
    raw = [p for _, p in series]
    # envelope de mínimo móvel (janela 1h=4 buckets) = piso da pilha (só sobe entre coletas)
    ys = []
    for i in range(len(raw)):
        lo = max(0, i - 3)
        ys.append(min(raw[lo:i + 1]))

    # eventos
    ev = list(csv.DictReader((VP / "events_today.csv").open(encoding="utf-8")))
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(xs, raw, "-", lw=0.8, color="#bbbbbb", label="frame mais vazio/bucket (cru)")
    ax.plot(xs, ys, "-o", ms=4, color="#1f77b4", lw=2, label="PISO da pilha (mín. móvel 1h)")
    for e in ev:
        h, m, s = map(int, e["t"].split(":"))
        x = h + m / 60
        if x < 6 or x > 18:
            continue
        conf = e["status"] == "CONFIRMADO"
        ax.axvline(x, color="green" if conf else "red", ls="-" if conf else ":",
                   alpha=0.8 if conf else 0.35, lw=2 if conf else 1)
    ax.axvline(-1, color="green", lw=2, label="CONFIRMADO (descarte real)")
    ax.axvline(-1, color="red", ls=":", label="REJEITADO (FP transeunte)")
    ax.set_xlim(6, 18); ax.set_xlabel("hora do dia (BRT)")
    ax.set_ylabel("persistência FG na pile-zone (px)")
    ax.set_title("Protótipo volume longitudinal — pilha cam_11 (Mangabeira) 2026-06-16\n"
                 "descarte real = degrau; transeunte (FP) não move a curva")
    ax.legend(loc="upper left", fontsize=8); ax.grid(alpha=0.3)
    out = VP / "volume_timeseries.png"
    fig.tight_layout(); fig.savefig(out, dpi=110)
    print(f"-> {out}")

    # resumo numérico
    print("\nbucket(h)  persist_px  delta")
    prev = ys[0]
    for x, y in zip(xs, ys):
        d = y - prev
        flag = " <== DEGRAU+" if d > 1500 else ""
        print(f"  {x:5.2f}    {y:7d}   {d:+6d}{flag}")
        prev = y
    csv.writer((VP / "series.csv").open("w", newline="")).writerows([("hour", "persist_px"), *zip(xs, ys)])


if __name__ == "__main__":
    main()
