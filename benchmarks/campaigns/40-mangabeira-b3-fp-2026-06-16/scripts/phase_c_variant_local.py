#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Campaign 40 Phase C — detail prompt variants on the local official dataset.

Baseline = deployed DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS (imported verbatim).
V1 = transient-return crop-grounded hard anti-pattern. V2 = evidence-required CON
for INTERAGENTE_CURTA only. Runs on 13 TP + 20 B3, caches by event_id+prompt_hash.
Bench Gemini key only (gen-lang-client-0841492152). ~$1.
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
sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
sys.stdout.reconfigure(encoding="utf-8")

# bench auth (AI Studio test project)
for line in (ROOT / "services" / ".env.benchmark").read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from worker._prompts_v3 import DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS as BASE  # noqa: E402
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

DATASET = ROOT / "data" / "datasets" / "official"
RES = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "results"
CACHE = RES / "phase_c_cache.json"
MODEL = "gemini-2.5-flash"
BBOX = (480, 60, 920, 340)
N_GLOBAL, N_CROP, UP = 48, 12, 2
IN_P, OUT_P = 0.30 / 1e6, 2.50 / 1e6

V1_PATCH = """

=============================================================================
PATCH V1 — ANTI-PADRAO DURO DE PASSANTE (crop-grounded)
=============================================================================
AP8 — PASSANTE CONFIRMADO POR CROP: Se uma pessoa muda de posicao em TODOS os
frames (trajetoria linear, SEM dwell de 4+ frames consecutivos na frente da pilha)
E os CROPS da pile-zone NAO mostram nenhum objeto novo no fim vs inicio, entao ela
e PASSANTE -> infraction_confirmed=false, MESMO que carregue uma sacola momentanea
em um ou dois frames. Esta regra TEM PRECEDENCIA sobre "delta nao exigido" quando a
pessoa nunca para na pilha. Inclua no JSON o campo booleano crop_new_object.
"""

V2_PATCH = """

=============================================================================
PATCH V2 — EVIDENCIA EXIGIDA SO PARA INTERAGENTE_CURTA
=============================================================================
OVERRIDE DO PASSO 4: para pessoas classificadas INTERAGENTE_CURTA (3-30s sem
postura especial), exija PELO MENOS UMA evidencia concreta de transferencia para
infraction_confirmed=true: (a) maos cheias -> vazias junto a pilha, OU (b) objeto
novo visivel nos CROPS fim-vs-inicio, OU (c) mudanca de carga de carrinho/veiculo.
Se NENHUMA das tres -> infraction_confirmed=false para esse caso. AGACHADA_LONGA e
PAUSADA seguem DEFAULT-CON normalmente (casos tiny-bag criticos p/ recall). Inclua
no JSON o campo booleano crop_new_object.
"""

PROMPTS = {"baseline": BASE, "V1": BASE + V1_PATCH, "V2": BASE + V2_PATCH}

CLIENT = genai.Client(api_key=os.environ["GEMINI_TEST_API_KEY"])


def jpeg_global(path: Path) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return buf.getvalue()


def crop_pile(path: Path) -> bytes | None:
    img = cv2.imread(str(path))
    if img is None:
        return None
    h, w = img.shape[:2]
    x0, y0, x1, y1 = BBOX
    cx0, cy0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
    cx1, cy1 = max(cx0 + 1, min(x1, w)), max(cy0 + 1, min(y1, h))
    c = img[cy0:cy1, cx0:cx1]
    if c.size == 0:
        return None
    c = cv2.resize(c, (c.shape[1] * UP, c.shape[0] * UP), interpolation=cv2.INTER_LANCZOS4)
    ok, b = cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return b.tobytes() if ok else None


def sample(frames, n):
    if len(frames) <= n:
        return frames
    idx = [round(i * (len(frames) - 1) / (n - 1)) for i in range(n)]
    return [frames[i] for i in sorted(set(idx))]


def call(prompt: str, globals_, crops):
    parts = [types.Part.from_text(text="SEQ1 globais cronologicos; SEQ2 crops hi-res da "
             "pile-zone (upscale 2x). Retorne APENAS JSON com infraction_confirmed.")]
    parts.append(types.Part.from_text(text="=== SEQ1 GLOBAIS ==="))
    for g in globals_:
        parts.append(types.Part.from_bytes(data=jpeg_global(g), mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text="=== SEQ2 CROPS PILE-ZONE ==="))
    for cp in crops:
        parts.append(types.Part.from_bytes(data=cp, mime_type="image/jpeg"))
    r = None
    for attempt in range(6):
        try:
            r = CLIENT.models.generate_content(
                model=MODEL, contents=[types.Content(parts=parts, role="user")],
                config=types.GenerateContentConfig(system_instruction=prompt,
                    response_mime_type="application/json", temperature=0.0))
            break
        except Exception as e:  # noqa: BLE001
            if "503" in str(e) or "UNAVAILABLE" in str(e) or "429" in str(e):
                time.sleep(5 * (attempt + 1))
                continue
            raise
    if r is None:
        raise RuntimeError("503/429 persistente após 6 tentativas")
    u = r.usage_metadata
    it = u.prompt_token_count or 0
    ot = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
    try:
        obj = json.loads(r.text)
    except Exception:
        obj = {"raw": (r.text or "")[:200]}
    return obj, it, ot


def main() -> int:
    rows = [r for r in csv.DictReader((RES / "b3_split.csv").open(encoding="utf-8"))
            if r["bucket"] in ("TP", "B3")]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    smoke = os.environ.get("SMOKE_ONLY") == "1"
    cost = 0.0
    out = {}
    for name, prompt in PROMPTS.items():
        phash = hashlib.md5(prompt.encode()).hexdigest()[:8]
        preds = []
        for r in rows:
            key = f"{r['event_id']}:{phash}"
            fdir = DATASET / r["local_path"] / "frames"
            frames = sorted(fdir.glob("*.jpg"))
            if len(frames) < 2:
                continue
            if key in cache:
                row = cache[key]
            else:
                g = sample(frames, N_GLOBAL)
                cps = [c for c in (crop_pile(p) for p in sample(frames, N_CROP)) if c]
                obj, it, ot = call(prompt, g, cps)
                con = bool(obj.get("infraction_confirmed"))
                c = it * IN_P + ot * OUT_P
                cost += c
                row = {"event_id": r["event_id"], "bucket": r["bucket"], "gt": r["bucket"],
                       "pred": "CON" if con else "REJ", "crop_new_object": obj.get("crop_new_object"),
                       "in_tok": it, "out_tok": ot, "cost": c}
                cache[key] = row
                CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                time.sleep(0.3)
            preds.append(row)
            if smoke and len(preds) >= 2:
                break
        out[name] = preds
        tp = [p for p in preds if p["bucket"] == "TP"]
        b3 = [p for p in preds if p["bucket"] == "B3"]
        tp_recall = sum(1 for p in tp if p["pred"] == "CON")
        b3_fp = sum(1 for p in b3 if p["pred"] == "CON")
        print(f"{name:9s} [{phash}]  TP recall={tp_recall}/{len(tp)}  "
              f"B3 FP={b3_fp}/{len(b3)} (supr {len(b3)-b3_fp})  cost_acum=${cost:.3f}")
        if smoke:
            break
    (RES / "phase_c_variant_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTotal novo: ${cost:.3f}")
    assert cost < 2.0, "custo estourou $2"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
