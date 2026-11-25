#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — quantos tokens de ENTRADA cada modelo cobra pelos mesmos frames.

Usa countTokens do Vertex (gratuito). Responde, sem gastar, a pergunta de custo do
roteamento de 01/12: a mesma janela de 48 frames custa quantos tokens no 2.5-flash e no
3.5-flash-lite, e quanto muda com media_resolution.

Uso: python probe_tokens.py [--frames 48] [--event evt-...]
"""
from __future__ import annotations

import argparse
import json
import sys

import bench53 as b
from google.genai import types

MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3.1-flash-lite",
          "gemini-3.5-flash-lite", "gemini-3.6-flash"]
RESOLUTIONS = [None, "low", "medium", "high"]


def count(client, model, parts, res):
    cfg = None
    if res:
        cfg = types.CountTokensConfig(generation_config=types.GenerationConfig(
            media_resolution=getattr(types.MediaResolution, f"MEDIA_RESOLUTION_{res.upper()}")))
    r = client.models.count_tokens(model=model, contents=parts, config=cfg)
    return int(r.total_tokens)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=48)
    ap.add_argument("--event", default=None)
    a = ap.parse_args()
    events = b.load_events(["tp", "fp"])
    if a.event:
        ev = next(e for e in events if e["event_id"] == a.event)
    else:
        ev = max(events, key=lambda e: len(b.build_window(e["frames"])))
    win = b.even_subsample(b.build_window(ev["frames"]), a.frames)
    client = b.get_client()
    text = [b.dg.SYSTEM_PROMPT, "contexto"]
    imgs = [types.Part.from_bytes(data=p.read_bytes(), mime_type="image/jpeg") for p in win]
    from PIL import Image
    w, h = Image.open(win[0]).size
    kb = sum(p.stat().st_size for p in win) // 1024
    print(f"evento={ev['event_id']} frames={len(win)} resolucao={w}x{h} payload={kb} KB")
    out = []
    for m in MODELS:
        row = {"model": m}
        try:
            base = count(client, m, text, None)
            row["texto"] = base
            for res in RESOLUTIONS:
                key = res or "padrao"
                try:
                    tot = count(client, m, text + imgs, res)
                    row[key] = tot
                    row[key + "_por_frame"] = round((tot - base) / len(win), 1)
                except Exception as exc:  # noqa: BLE001
                    row[key] = f"erro: {str(exc)[:90]}"
        except Exception as exc:  # noqa: BLE001
            row["erro"] = str(exc)[:160]
        out.append(row)
        print(json.dumps(row, ensure_ascii=False))
    (b.RESULTS / "probe_tokens.json").write_text(
        json.dumps({"event": ev["event_id"], "frames": len(win), "size": [w, h], "rows": out},
                   ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
