#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Large-N high-bar flagrante gate: only CON for ATTRIBUTABLE+SIGNIFICANT disposal.

Runs on 216 events (72 TP + 144 B3). Baseline (deployed) = 100% CON by construction
(all are persisted detections). Measures B3 suppression + TP retention, stratified by
offender_type/volume. Bench Gemini only. ~$3.
"""
import csv
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

import cv2
from PIL import Image

ROOT = Path(r"c:\saira")
sys.stdout.reconfigure(encoding="utf-8")
for line in (ROOT / "services" / ".env.benchmark").read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
from google import genai
from google.genai import types

LN = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "largeN"
RES = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "results"
CACHE = LN / "highbar_cache.json"
MODEL = "gemini-2.5-flash"
BBOX = (480, 60, 920, 340)
IN_P, OUT_P = 0.30 / 1e6, 2.50 / 1e6

HIGHBAR = """Voce decide se deve EMITIR FLAGRANTE de descarte irregular num ponto cronico
de Mangabeira, Recife, que tem uma PILHA DE LIXO PERMANENTE (sempre presente; nao e
infracao). Pessoas e veiculos passam o tempo todo perto dela.

REGRA DE BARRA ALTA (flagrante e acao de fiscalizacao, nao contagem):
Emita CONFIRMA (alert=true) SOMENTE se houver evidencia ATRIBUIVEL e SIGNIFICATIVA:
  (A) veiculo / carroca / carrinho PARADO junto a pilha COM material sendo descarregado
      em direcao ao chao/pilha; OU
  (B) pessoa AGACHADA ou PARADA LONGA (>=20s, mesma posicao em varios frames) claramente
      depositando uma carga VISIVEL (saco grande, entulho, volumoso); OU
  (C) um objeto NOVO e VOLUMOSO aparece sobre/junto a pilha entre o inicio e o fim.

REJEITE (alert=false) TODO o resto, MESMO que um descarte minusculo POSSA ter ocorrido:
  - pedestre passando / atravessando, com ou sem sacola pequena momentanea;
  - interacao curta/ambigua sem deposito de carga visivel;
  - pessoa parada olhando, mexendo no lixo existente, catador;
  - veiculo so estacionado sem descarregar.
Descartes minusculos de pedestre NAO sao flagrante aqui (sao medidos por volume ao longo
do tempo, nao por evento) e NAO devem gerar alerta.

Responda APENAS JSON: {"alert": true|false, "basis": "A|B|C|none", "offender_type":
"Carro|Carroca|Carrinho|Pessoa|Outro|Nenhum", "reason": "<=160 chars"}"""


def jpeg_global(p):
    with Image.open(p) as im:
        im = im.convert("RGB"); im.thumbnail((1280, 1280))
        b = io.BytesIO(); im.save(b, "JPEG", quality=85); return b.getvalue()


def crop_pile(p):
    img = cv2.imread(str(p))
    if img is None:
        return None
    h, w = img.shape[:2]; x0, y0, x1, y1 = BBOX
    cx0, cy0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
    cx1, cy1 = max(cx0 + 1, min(x1, w)), max(cy0 + 1, min(y1, h))
    c = img[cy0:cy1, cx0:cx1]
    if c.size == 0:
        return None
    c = cv2.resize(c, (c.shape[1] * 2, c.shape[0] * 2), interpolation=cv2.INTER_LANCZOS4)
    ok, bb = cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return bb.tobytes() if ok else None


def sample(lst, n):
    return lst if len(lst) <= n else [lst[round(i * (len(lst) - 1) / (n - 1))] for i in range(n)]


_VCRED = r"C:\secrets\saira-bench-vertex.json"
if os.path.exists(_VCRED):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _VCRED
    CLIENT = genai.Client(vertexai=True, project="gen-lang-client-0841492152", location="global")
    print("[auth] Vertex AI (bench project)")
else:
    CLIENT = genai.Client(api_key=os.environ["GEMINI_TEST_API_KEY"])
    print("[auth] AI Studio")


def call(globs, crops):
    parts = [types.Part.from_text(text="SEQ1 globais cronologicos; SEQ2 crops hi-res da pile-zone.")]
    parts.append(types.Part.from_text(text="=== SEQ1 ==="))
    for g in globs:
        parts.append(types.Part.from_bytes(data=jpeg_global(g), mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text="=== SEQ2 CROPS ==="))
    for c in crops:
        parts.append(types.Part.from_bytes(data=c, mime_type="image/jpeg"))
    for att in range(6):
        try:
            r = CLIENT.models.generate_content(
                model=MODEL, contents=[types.Content(parts=parts, role="user")],
                config=types.GenerateContentConfig(system_instruction=HIGHBAR,
                    response_mime_type="application/json", temperature=0.0))
            break
        except Exception as e:
            if any(x in str(e) for x in ("503", "UNAVAILABLE", "429")):
                time.sleep(5 * (att + 1)); continue
            raise
    else:
        raise RuntimeError("503/429 persistente")
    u = r.usage_metadata
    it, ot = u.prompt_token_count or 0, (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
    try:
        o = json.loads(r.text)
    except Exception:
        o = {"alert": True, "basis": "parse_err"}
    return o, it, ot


def main():
    rows = list(csv.DictReader((LN / "manifest24.csv").open(encoding="utf-8")))
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    smoke = os.environ.get("SMOKE_ONLY") == "1"
    cost = 0.0
    out = {}
    for i, r in enumerate(rows, 1):
        if r["id"] in cache:
            out[r["id"]] = cache[r["id"]]; continue
        frames = [Path(p) for p in r["frames"].split("|") if Path(p).exists()]
        if len(frames) < 2:
            continue
        crops = [c for c in (crop_pile(p) for p in sample(frames, 12)) if c]
        o, it, ot = call(sample(frames, 24), crops)
        c = it * IN_P + ot * OUT_P; cost += c
        out[r["id"]] = {"bucket": r["bucket"], "alert": bool(o.get("alert")),
                        "basis": o.get("basis"), "offender_type": o.get("offender_type"),
                        "reason": o.get("reason", "")[:160]}
        cache[r["id"]] = out[r["id"]]
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        if i % 20 == 0:
            print(f"  {i}/{len(rows)}  cost=${cost:.2f}", flush=True)
        if smoke and len(out) >= 3:
            break
    (RES / "highbar_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    tp = [v for v in out.values() if v["bucket"] == "TP"]
    b3 = [v for v in out.values() if v["bucket"] == "B3"]
    tp_keep = sum(v["alert"] for v in tp)
    b3_fp = sum(v["alert"] for v in b3)
    print(f"\n=== HIGH-BAR (n TP={len(tp)} B3={len(b3)}) ===")
    print(f"TP mantidos (alert): {tp_keep}/{len(tp)} ({100*tp_keep/len(tp):.0f}%)")
    print(f"B3 ainda FP (alert): {b3_fp}/{len(b3)} -> suprimidos {len(b3)-b3_fp} ({100*(len(b3)-b3_fp)/len(b3):.0f}%)")
    print(f"custo novo: ${cost:.2f}")
    import collections
    print("basis dos TP mantidos:", collections.Counter(v["basis"] for v in tp if v["alert"]))
    print("basis dos B3 que viraram FP:", collections.Counter(v["basis"] for v in b3 if v["alert"]))


if __name__ == "__main__":
    main()
