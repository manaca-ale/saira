#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Clean before/after visualization of the polygon proposal over a daytime frame."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CAMP = Path(__file__).resolve().parents[1]
OFFICIAL = Path(r"c:\saira\data\datasets\official")
REF_W, REF_H = 1280, 720

current = json.loads((CAMP / "data" / "current_polygons_live.json").read_text(encoding="utf-8"))
proposed = json.loads((CAMP / "results" / "proposed_polygons.json").read_text(encoding="utf-8"))["esp32_001_Imbiribeira"]["proposed"]
lab = json.loads((CAMP / "labeling" / "tp_labels.json").read_text(encoding="utf-8"))
tp = [(e["x"], e["y"], e.get("vehicle_present")) for e in lab["events"] if e.get("x") is not None]

frames = sorted((OFFICIAL / "cam_imbiribeira" / "baseline" / "day").glob("*.jpg"))
img = plt.imread(str(frames[0])) if frames else None


def panel(ax, polys, title, color):
    if img is not None:
        ax.imshow(img, extent=[0, REF_W, REF_H, 0])
    ax.set_xlim(0, REF_W); ax.set_ylim(REF_H, 0)
    for i, poly in enumerate(polys):
        p = np.array(poly + [poly[0]])
        ax.plot(p[:, 0], p[:, 1], color=color, lw=2.2)
        ax.fill(p[:, 0], p[:, 1], color=color, alpha=0.18)
        cx, cy = np.mean([v[0] for v in poly]), np.mean([v[1] for v in poly])
        ax.text(cx, cy, f"#{i+1}", color="white", fontsize=11, fontweight="bold",
                ha="center", va="center", bbox=dict(boxstyle="round,pad=0.2", fc=color, ec="none", alpha=0.8))
    for x, y, veh in tp:
        c = "#19d36b" if veh is True else "#33d6ff"
        ax.scatter(x, y, c=c, s=120, edgecolors="black", linewidths=1.4, zorder=5)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xticks([]); ax.set_yticks([])


fig, (a1, a2) = plt.subplots(1, 2, figsize=(24, 7), dpi=130)
panel(a1, current, "ATUAL — 4 polígonos (cobrem 55% dos TPs · 9 caem nas lacunas)", "#4ea1ff")
panel(a2, proposed, "PROPOSTA recall-safe — 4 polígonos (cobrem 100% dos TPs)", "#36d399")
from matplotlib.lines import Line2D
leg = [Line2D([0], [0], marker="o", color="w", markerfacecolor="#19d36b", markeredgecolor="k", markersize=11, label="TP com veículo (12)"),
       Line2D([0], [0], marker="o", color="w", markerfacecolor="#33d6ff", markeredgecolor="k", markersize=11, label="TP sem veículo (8)")]
fig.legend(handles=leg, loc="lower center", ncol=2, fontsize=12, frameon=False)
fig.suptitle("Imbiribeira (esp32_001) — pile_zone_polygon: atual vs proposta (20 TPs marcados manualmente)", fontsize=15, fontweight="bold")
fig.tight_layout(rect=[0, 0.04, 1, 0.96])
out = CAMP / "results" / "proposal_before_after.png"
fig.savefig(out, bbox_inches="tight")
print(f"-> {out}")
