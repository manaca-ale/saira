#!/usr/bin/env python3
"""Campanha 24: Flash 2.5 + MANGABEIRA_E + pile-zone hi-res crops (esp32_002).

Envia AMBAS sequências ao Flash:
- 48 frames globais (production parity)
- 12 crops alta-res da pile_zone (upscale 2x), amostrados uniformemente

Reusa cache de frames /tmp/flash_per_camera/frames/esp32_002/ (camp 21).
Reusa _bench_common.py + DB connection (fetch pile_zone_polygon).

Vertex AI:
  GOOGLE_GENAI_USE_VERTEXAI=true
  GOOGLE_APPLICATION_CREDENTIALS=/tmp/saira-bench-vertex.json
  GOOGLE_CLOUD_PROJECT=gen-lang-client-0841492152
  GOOGLE_CLOUD_LOCATION=global
"""
from __future__ import annotations
import io
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import psycopg2
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))

from _bench_common import (  # noqa: E402
    DEVICE_BY_CAM, fetch_events, load_event, resolve_frame, sample_n,
    score_results,
)
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"
FLASH_IN_PRICE = 0.30 / 1e6
FLASH_OUT_PRICE = 2.50 / 1e6
N_GLOBAL_FRAMES = 48  # production parity
N_CROP_FRAMES = 12    # subset of globals to crop
CROP_UPSCALE = 2      # match GEMINI_GATE_PILECROP_UPSCALE in prod
TMP = Path("/tmp/flash_per_camera")
TMP.mkdir(parents=True, exist_ok=True)

PROMPT_FILE = "/tmp/mangabeira-e-with-pilecrops.md"
SYSTEM_PROMPT = Path(PROMPT_FILE).read_text(encoding="utf-8")
if SYSTEM_PROMPT.startswith("---"):
    parts = SYSTEM_PROMPT.split("---", 2)
    if len(parts) >= 3:
        SYSTEM_PROMPT = parts[2]
SYSTEM_PROMPT = "\n".join(
    ln for ln in SYSTEM_PROMPT.splitlines() if not ln.startswith("# ")
).strip()

CACHE_PATH = Path("/tmp/flash_mangabeira_E_CROPS_cache.json")
RESULTS_PATH = Path("/tmp/flash_mangabeira_E_CROPS_results.json")

if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
    CLIENT = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
    )
    PROVIDER = "vertex"
else:
    CLIENT = genai.Client(api_key=os.environ["GEMINI_TEST_API_KEY"])
    PROVIDER = "ai_studio"


def pile_bbox(polygon) -> tuple[int, int, int, int] | None:
    """Bounding box (x0, y0, x1, y1) of pile_zone_polygon JSON column."""
    try:
        pts = [pt for poly in polygon for pt in poly]
        xs = [int(p[0]) for p in pts]
        ys = [int(p[1]) for p in pts]
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)
    except Exception:
        return None


def fetch_pile_bbox(camera_id: int) -> tuple[int, int, int, int] | None:
    conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                            password="postgres", dbname="saira_db")
    cur = conn.cursor()
    cur.execute("SELECT pile_zone_polygon FROM cameras WHERE id = %s", (camera_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or not row[0]:
        return None
    return pile_bbox(row[0])


def crop_pile(img_path: Path, bbox: tuple[int, int, int, int],
              upscale: int = 2) -> bytes | None:
    """Crop image to bbox + upscale, return JPEG bytes."""
    img = cv2.imread(str(img_path))
    if img is None:
        return None
    h, w = img.shape[:2]
    x0, y0, x1, y1 = bbox
    cx0, cy0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
    cx1, cy1 = max(cx0 + 1, min(x1, w)), max(cy0 + 1, min(y1, h))
    crop = img[cy0:cy1, cx0:cx1]
    if crop.size == 0:
        return None
    if upscale != 1:
        crop = cv2.resize(
            crop, (crop.shape[1] * upscale, crop.shape[0] * upscale),
            interpolation=cv2.INTER_LANCZOS4,
        )
    # Encode as JPEG
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return None
    return buf.tobytes()


def jpeg_bytes_resized(path: Path, max_edge: int = 1280, quality: int = 85) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_edge, max_edge))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


def build_intro(global_count: int, crop_count: int,
                global_names: list[str], crop_names: list[str]) -> str:
    return (
        f"Voce recebe DUAS sequencias de imagens em ordem cronologica de uma "
        f"camera fixa em Mangabeira, Recife (cam_11 / esp32_002).\n\n"
        f"SEQUENCIA 1 — FRAMES GLOBAIS ({global_count} imagens, ordem cronologica, "
        f"primeiro=earliest):\n"
        f"  Frame names: {', '.join(global_names)}\n\n"
        f"SEQUENCIA 2 — CROPS ALTA-RES DA PILE-ZONE ({crop_count} imagens, upscale 2x, "
        f"amostrados uniformemente da mesma janela temporal):\n"
        f"  Crop frame names: {', '.join(crop_names)}\n\n"
        "Analise AMBAS sequencias e retorne JSON estruturado conforme o schema "
        "(apenas JSON, sem texto antes ou depois)."
    )


def call_flash_with_crops(global_paths: list[Path], global_names: list[str],
                          crop_payloads: list[tuple[str, bytes]]):
    parts = [types.Part.from_text(text=build_intro(
        len(global_paths), len(crop_payloads), global_names,
        [n for n, _ in crop_payloads],
    ))]
    # Section delimiter for globals
    parts.append(types.Part.from_text(text="=== SEQUENCIA 1: FRAMES GLOBAIS ==="))
    for p in global_paths:
        parts.append(types.Part.from_bytes(
            data=jpeg_bytes_resized(p), mime_type="image/jpeg"))
    # Section delimiter for crops
    parts.append(types.Part.from_text(text="=== SEQUENCIA 2: CROPS ALTA-RES DA PILE-ZONE ==="))
    for _, jpg in crop_payloads:
        parts.append(types.Part.from_bytes(data=jpg, mime_type="image/jpeg"))

    t0 = time.monotonic()
    resp = CLIENT.models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=parts, role="user")],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )
    latency = int((time.monotonic() - t0) * 1000)
    u = resp.usage_metadata
    in_tok = u.prompt_token_count or 0
    out_tok = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
    try:
        obj = json.loads(resp.text)
    except Exception:
        obj = {"raw": (resp.text or "")[:400]}
    return obj, in_tok, out_tok, latency


def main():
    bbox = fetch_pile_bbox(11)
    if bbox is None:
        print("ERROR: no pile_zone_polygon for cam_11", flush=True)
        return 2
    print(f"[bbox] esp32_002 pile_zone bbox={bbox} (w={bbox[2]-bbox[0]}, h={bbox[3]-bbox[1]})",
          flush=True)

    events = [e for e in fetch_events() if e["cam"] == 11]
    print(f"[fetch] {len(events)} cam_11 events  angle=E+CROPS  provider={PROVIDER}",
          flush=True)
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    print(f"[cache] {len(cache)} already done", flush=True)

    results = []
    total_in = total_out = 0
    cost = 0.0
    smoke_only = os.environ.get("SMOKE_ONLY") == "1"
    smoke_count = 0

    for i, ev in enumerate(events, 1):
        device_id = DEVICE_BY_CAM.get(ev["cam"])
        det = load_event(ev["id"])
        if not det or not det.get("frames"):
            continue
        if ev["id"] in cache:
            row = cache[ev["id"]]
            results.append(row)
            total_in += row.get("in_tok", 0)
            total_out += row.get("out_tok", 0)
            cost += row.get("cost_usd", 0)
            continue

        frames = det["frames"]
        # Sample 48 globals
        g_idxs = sample_n(frames, N_GLOBAL_FRAMES)
        g_paths, g_names = [], []
        for k in g_idxs:
            f = frames[k]
            p = resolve_frame(TMP, f["image_url"], f["frame_name"], device_id)
            if p:
                g_paths.append(p)
                g_names.append(f["frame_name"])
        if len(g_paths) < 4:
            print(f"  {ev['id'][:8]}: only {len(g_paths)} global frames, skip",
                  flush=True)
            continue

        # Crops: subsample 12 from the same 48 (uniform indices into g_paths)
        c_idxs = sample_n(g_paths, N_CROP_FRAMES)
        crop_payloads = []
        for k in c_idxs:
            p = g_paths[k]
            jpg = crop_pile(p, bbox, upscale=CROP_UPSCALE)
            if jpg is not None:
                crop_payloads.append((g_names[k], jpg))
        if len(crop_payloads) < 4:
            print(f"  {ev['id'][:8]}: only {len(crop_payloads)} crops, skip",
                  flush=True)
            continue

        try:
            obj, in_tok, out_tok, latency = call_flash_with_crops(
                g_paths, g_names, crop_payloads)
        except Exception as exc:
            print(f"  {ev['id'][:8]} ERROR: {exc}", flush=True)
            continue

        ev_cost = in_tok * FLASH_IN_PRICE + out_tok * FLASH_OUT_PRICE
        total_in += in_tok
        total_out += out_tok
        cost += ev_cost
        gt = "CON" if ev["status"] == "CONFIRMADO" else "REJ"
        pred = "CON" if obj.get("infraction_confirmed") else "REJ"
        row = {
            "id": ev["id"], "ts": ev["ts"], "cam": ev["cam"], "gt": gt,
            "pred": pred, "confidence": obj.get("confidence_0_100"),
            "waste_type": obj.get("waste_type"),
            "offender_detected": obj.get("offender_detected"),
            "evidence_summary": (obj.get("evidence_summary") or "")[:700],
            "prompt_angle": "E+CROPS",
            "in_tok": in_tok, "out_tok": out_tok, "latency_ms": latency,
            "cost_usd": round(ev_cost, 6),
            "n_global_frames": len(g_paths),
            "n_crops": len(crop_payloads),
        }
        results.append(row)
        cache[ev["id"]] = row
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

        mark = "OK" if pred == gt else "MISS"
        print(f"  {i:>2}/{len(events)} {ev['ts'][:16]} [E+CROPS] gt={gt} "
              f"pred={pred} conf={obj.get('confidence_0_100')} {mark} "
              f"({latency}ms in={in_tok} out={out_tok} ${ev_cost:.4f} "
              f"g={len(g_paths)} c={len(crop_payloads)})",
              flush=True)
        smoke_count += 1
        if smoke_only and smoke_count >= 1:
            print("\nSMOKE_ONLY=1 — parando apos 1 evento.")
            break

    s = score_results(results)
    print()
    print(f"=== Flash 2.5 + MANGABEIRA_E + PILECROPS — n={s['n']} (cam_11) ===")
    print(f"acc={s['acc']:.2%}  TP={s['tp']} TN={s['tn']} FP={s['fp']} FN={s['fn']}")
    print(f"precision={s['precision']:.2%}  recall={s['recall']:.2%}  "
          f"specificity={s['specificity']:.2%}")
    print(f"tokens in={total_in:,} out={total_out:,}  cost=${cost:.4f} "
          f"(avg ${cost / max(s['n'], 1):.4f}/event)")

    RESULTS_PATH.write_text(json.dumps({
        "model": MODEL, "angle": "E+CROPS", "provider": PROVIDER,
        "pile_bbox": list(bbox), "results": results,
        "cost_usd": round(cost, 6),
    }, ensure_ascii=False, indent=2))
    print(f"\nsaved: {RESULTS_PATH}")


if __name__ == "__main__":
    sys.exit(main() or 0)
