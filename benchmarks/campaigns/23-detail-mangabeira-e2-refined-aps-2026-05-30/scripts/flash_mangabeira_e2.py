#!/usr/bin/env python3
"""Campanha 23: Flash 2.5 + MANGABEIRA_E2 (APs refinados: per-person, gatilho temporal).

Reusa cache de frames /tmp/flash_per_camera/frames/esp32_002/ (camp 21).
Reusa _bench_common.py já presente em /tmp/.

Vertex AI:
  GOOGLE_GENAI_USE_VERTEXAI=true
  GOOGLE_APPLICATION_CREDENTIALS=/tmp/saira-bench-vertex.json
  GOOGLE_CLOUD_PROJECT=gen-lang-client-0841492152
  GOOGLE_CLOUD_LOCATION=global
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _bench_common import (  # noqa: E402
    DEVICE_BY_CAM, build_intro, fetch_events, jpeg_bytes, load_event,
    resolve_frame, sample_n, score_results,
)
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"
FLASH_IN_PRICE = 0.30 / 1e6
FLASH_OUT_PRICE = 2.50 / 1e6
N_FRAMES = 48
TMP = Path("/tmp/flash_per_camera")
TMP.mkdir(parents=True, exist_ok=True)

PROMPT_FILE = "/tmp/mangabeira-e2-refined-aps.md"
SYSTEM_PROMPT = Path(PROMPT_FILE).read_text(encoding="utf-8")
if SYSTEM_PROMPT.startswith("---"):
    parts = SYSTEM_PROMPT.split("---", 2)
    if len(parts) >= 3:
        SYSTEM_PROMPT = parts[2]
SYSTEM_PROMPT = "\n".join(
    ln for ln in SYSTEM_PROMPT.splitlines() if not ln.startswith("# ")
).strip()

CACHE_PATH = Path("/tmp/flash_mangabeira_E2_cache.json")
RESULTS_PATH = Path("/tmp/flash_mangabeira_E2_results.json")

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


def call_flash(paths, frame_names, cam_id: int):
    intro = build_intro(paths, frame_names, cam_id)
    parts = [types.Part.from_text(text=intro)]
    for p in paths:
        parts.append(types.Part.from_bytes(data=jpeg_bytes(p), mime_type="image/jpeg"))
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
    events = [e for e in fetch_events() if e["cam"] == 11]
    print(f"[fetch] {len(events)} cam_11 events  angle=E2  provider={PROVIDER}",
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
        idxs = sample_n(frames, N_FRAMES)
        paths, names = [], []
        for k in idxs:
            f = frames[k]
            p = resolve_frame(TMP, f["image_url"], f["frame_name"], device_id)
            if p:
                paths.append(p)
                names.append(f["frame_name"])
        if len(paths) < 4:
            print(f"  {ev['id'][:8]}: only {len(paths)} frames, skip", flush=True)
            continue

        try:
            obj, in_tok, out_tok, latency = call_flash(paths, names, ev["cam"])
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
            "evidence_summary": (obj.get("evidence_summary") or "")[:600],
            "prompt_angle": "E2",
            "in_tok": in_tok, "out_tok": out_tok, "latency_ms": latency,
            "cost_usd": round(ev_cost, 6),
            "n_frames_used": len(paths),
        }
        results.append(row)
        cache[ev["id"]] = row
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

        mark = "OK" if pred == gt else "MISS"
        print(f"  {i:>2}/{len(events)} {ev['ts'][:16]} [E2] gt={gt} pred={pred} "
              f"conf={obj.get('confidence_0_100')} {mark} "
              f"({latency}ms in={in_tok} out={out_tok} ${ev_cost:.4f})",
              flush=True)
        smoke_count += 1
        if smoke_only and smoke_count >= 1:
            print("\nSMOKE_ONLY=1 — parando apos 1 evento.")
            break

    s = score_results(results)
    print()
    print(f"=== Flash 2.5 + MANGABEIRA_E2 — n={s['n']} (cam_11) ===")
    print(f"acc={s['acc']:.2%}  TP={s['tp']} TN={s['tn']} FP={s['fp']} FN={s['fn']}")
    print(f"precision={s['precision']:.2%}  recall={s['recall']:.2%}  "
          f"specificity={s['specificity']:.2%}")
    print(f"tokens in={total_in:,} out={total_out:,}  cost=${cost:.4f} "
          f"(avg ${cost / max(s['n'], 1):.4f}/event)")

    RESULTS_PATH.write_text(json.dumps({
        "model": MODEL, "angle": "E2", "provider": PROVIDER,
        "results": results, "cost_usd": round(cost, 6),
    }, ensure_ascii=False, indent=2))
    print(f"\nsaved: {RESULTS_PATH}")


if __name__ == "__main__":
    sys.exit(main())
