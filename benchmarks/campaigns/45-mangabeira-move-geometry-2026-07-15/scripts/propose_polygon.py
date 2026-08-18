#!/usr/bin/env python3
"""Camp 45 — composição visual p/ proposta do pile_zone_polygon da cena nova.

Sobrepõe num frame atual (1280x720): o polígono ATUAL do DB (vermelho), os
waste_bbox das detecções CONFIRMADAS pós-mudança (verde, normalizados 0-1000
[ymin,xmin,ymax,xmax] — apoio, não fonte, lição camp 44) e o polígono PROPOSTO
de polygons.json quando preenchido (amarelo). O PNG vai para validação do
usuário ANTES de qualquer UPDATE no banco.

Uso: python propose_polygon.py <frame_atual.jpg> [saida.png]
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import cv2
import numpy as np

ROOT = Path(r"c:\saira")
HERE = Path(__file__).resolve().parent.parent
DATA = ROOT / "tmp" / "mangabeira_move"

REF_W, REF_H = 1280, 720


def parse_bbox(raw: str):
    """waste_bbox JSONB: [ymin,xmin,ymax,xmax] normalizado 0-1000 (Gemini)."""
    if not raw or raw in ("", "null"):
        return None
    try:
        v = json.loads(raw)
        if isinstance(v, dict):
            v = [v.get("ymin"), v.get("xmin"), v.get("ymax"), v.get("xmax")]
        ymin, xmin, ymax, xmax = [float(x) for x in v]
        return (int(xmin / 1000 * REF_W), int(ymin / 1000 * REF_H),
                int(xmax / 1000 * REF_W), int(ymax / 1000 * REF_H))
    except Exception:  # noqa: BLE001
        return None


def draw_poly(img, poly, color, thickness=3):
    for p in poly:
        pts = np.array(p, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [pts], isClosed=True, color=color, thickness=thickness)


def main() -> int:
    frame_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "viz" / "polygon_proposal.png"
    out_path.parent.mkdir(exist_ok=True)

    img = cv2.imread(str(frame_path))
    if img is None:
        raise SystemExit(f"frame ilegível: {frame_path}")
    if img.shape[:2] != (REF_H, REF_W):
        img = cv2.resize(img, (REF_W, REF_H))

    polys = json.loads((HERE / "polygons.json").read_text(encoding="utf-8"))
    draw_poly(img, polys["current"], (0, 0, 255))          # ATUAL = vermelho
    if polys.get("proposed"):
        draw_poly(img, polys["proposed"], (0, 255, 255))   # PROPOSTO = amarelo

    n_boxes = 0
    labels_csv = DATA / "labels.csv"
    if labels_csv.exists():
        with labels_csv.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["status"] != "CONFIRMADO":
                    continue
                bb = parse_bbox(row.get("waste_bbox", ""))
                if bb:
                    cv2.rectangle(img, (bb[0], bb[1]), (bb[2], bb[3]), (0, 200, 0), 2)
                    cv2.putText(img, row["id"][:8], (bb[0], max(12, bb[1] - 4)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 0), 1)
                    n_boxes += 1
    else:
        print("AVISO: labels.csv ausente — só polígonos desenhados", flush=True)

    legend = ["vermelho = poligono ATUAL do DB (27/05, pre-mudanca)",
              "verde = waste_bbox das CONFIRMADAS pos-mudanca",
              "amarelo = poligono PROPOSTO"]
    for i, txt in enumerate(legend):
        cv2.putText(img, txt, (10, 690 - 22 * (len(legend) - 1 - i)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    cv2.imwrite(str(out_path), img)
    print(f"{n_boxes} waste_bbox CONF desenhados -> {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
