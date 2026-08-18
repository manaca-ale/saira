#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build a visual contact-sheet per disposal (TP): the 5 gate-window frames side by side,
captioned with timestamps + the per-arm catch (3 reps). FN sorted first.

Output: results/windows/TP/<rank>_<veh>_<event_id>.png  + _index.md
Reads results/test_windows.json (run show_windows.py first).
"""
import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.stdout.reconfigure(encoding="utf-8")
CAMP = Path(__file__).resolve().parents[1]
DATASET = Path(r"c:\saira\data\datasets\official")
OUT = CAMP / "results" / "windows" / "TP"
OUT.mkdir(parents=True, exist_ok=True)

data = json.loads((CAMP / "results" / "test_windows.json").read_text(encoding="utf-8"))
arms = data["arms"]
short = {a: a.replace("_vehicle", "").replace("A_baseline", "A") for a in arms}
POS = ["1º", "meio", "meio", "meio", "últ"]


def ts(name):
    m = re.search(r"(\d{2})-(\d{2})-(\d{2})\.jpg$", name)
    return f"{m[1]}:{m[2]}:{m[3]}" if m else name


def find_frame(event_id, fname):
    for cat in ("tp", "fp"):
        for d in (DATASET / "cam_imbiribeira" / cat).glob(f"{event_id}*"):
            p = d / "frames" / fname
            if p.exists():
                return p
    return None


def rank(rec):
    caught_any = any(rec["catch"][a] != "0/3" for a in arms)
    b3 = rec["catch"].get("B3_vehicle_stopped", "0/3")
    if not caught_any:
        return "0FN-todos"          # nobody catches
    if b3 == "0/3":
        return "1FN-B3"             # B3 misses
    return "2ok"


index = []
tps = [r for r in data["events"] if r["label"] == "TP"]
for rec in tps:
    eid = rec["event_id"]
    win = rec["window"]
    veh = "VEIC" if rec["vehicle"] is True else ("foot" if rec["vehicle"] is False else "?")
    rk = rank(rec)
    fig, axes = plt.subplots(1, len(win), figsize=(4 * len(win), 3.2), dpi=95)
    if len(win) == 1:
        axes = [axes]
    for ax, fname, pos in zip(axes, win, POS):
        p = find_frame(eid, fname)
        if p:
            ax.imshow(plt.imread(str(p)))
        ax.set_title(f"{pos}  {ts(fname)}", fontsize=11)
        ax.axis("off")
    catch = "  ".join(f"{short[a]}:{rec['catch'][a]}" for a in arms)
    title = (f"{eid}  |  {veh}  |  {rec['n_frames']} frames no evento  |  "
             f"janela {ts(win[0])}–{ts(win[-1])}\nCAPTURA (3 reps):  {catch}")
    fig.suptitle(title, fontsize=12, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.88])
    fname_out = f"{rk}_{veh}_{eid}.png"
    fig.savefig(OUT / fname_out, bbox_inches="tight")
    plt.close(fig)
    index.append((rk, veh, eid, rec, fname_out))

index.sort()
lines = ["# Janelas de teste — descartes (TP)\n",
         "Cada PNG = os 5 frames que o gate viu (1º · 3 meio · último) + placar de captura.",
         "Ordenado: `0FN-todos` (ninguém pega) → `1FN-B3` (B3 erra) → `2ok`.\n",
         "| arquivo | event | veículo | frames | janela | A | B_hard | B2 | B3 |",
         "|---|---|---|---|---|---|---|---|---|"]
for rk, veh, eid, rec, fn in index:
    w = rec["window"]
    lines.append(f"| [{fn}](TP/{fn}) | {eid} | {veh} | {rec['n_frames']} | "
                 f"{ts(w[0])}–{ts(w[-1])} | {rec['catch'][arms[0]]} | {rec['catch'][arms[1]]} "
                 f"| {rec['catch'][arms[2]]} | {rec['catch'][arms[3]]} |")
(CAMP / "results" / "windows" / "_index.md").write_text("\n".join(lines), encoding="utf-8")

print(f"built {len(index)} TP montages -> {OUT}")
print(f"index -> {CAMP / 'results' / 'windows' / '_index.md'}")
fn_all = [eid for rk, veh, eid, *_ in index if rk == "0FN-todos"]
fn_b3 = [eid for rk, veh, eid, *_ in index if rk == "1FN-B3"]
print(f"FN-todos (ninguém pega): {fn_all}")
print(f"FN-B3 (B3 erra): {fn_b3}")
