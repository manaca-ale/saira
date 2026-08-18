#!/usr/bin/env python3
"""Production baseline: Flash 2.5 + V1 prompt for ALL cameras (exact prod behavior).

This replicates what `analyze_with_gemini(prompt_version="current")` does today
in saira-yolo-worker-prod for the detail (Agent-2). Both cam_10 and cam_11
receive the SAME V1 prompt — prod has no per-camera detail routing.

Same N_FRAMES=48 + same 12-frame floor + same Gemini Flash 2.5 model.
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _bench_common import (  # noqa: E402
    DEVICE_BY_CAM, build_intro, fetch_events, jpeg_bytes,
    load_event, print_summary, resolve_frame, sample_n,
)
from _baseline_prompts import SYS_V1_PROD  # noqa: E402
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"
FLASH_IN_PRICE = 0.30 / 1e6
FLASH_OUT_PRICE = 2.50 / 1e6
N_FRAMES = 48
TMP = Path("/tmp/flash_baseline_v1")
TMP.mkdir(parents=True, exist_ok=True)
CACHE_PATH = Path("/tmp/flash_baseline_v1_cache.json")

USE_VERTEX = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
if USE_VERTEX:
    CLIENT = genai.Client()
    print(f"[init] backend=Vertex project={CLIENT._api_client.project} "
          f"location={CLIENT._api_client.location}", flush=True)
else:
    BENCH_KEY = os.environ["GEMINI_TEST_API_KEY"]
    CLIENT = genai.Client(api_key=BENCH_KEY)
    print("[init] backend=AI Studio", flush=True)


def call_flash(paths, frame_names, cam_id):
    intro = build_intro(paths, frame_names, cam_id)
    parts = [types.Part.from_text(text=intro)]
    for p in paths:
        parts.append(types.Part.from_bytes(data=jpeg_bytes(p), mime_type="image/jpeg"))
    t0 = time.monotonic()
    resp = CLIENT.models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=parts, role="user")],
        config=types.GenerateContentConfig(
            system_instruction=SYS_V1_PROD,
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
    events = fetch_events()
    print(f"[fetch] {len(events)} events", flush=True)
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    print(f"[cache] {len(cache)} done", flush=True)

    results = []
    total_in = total_out = 0
    cost = 0.0
    for i, ev in enumerate(events, 1):
        device_id = DEVICE_BY_CAM.get(ev["cam"])
        if not device_id:
            continue
        det = load_event(ev["id"])
        if not det or not det.get("frames"):
            continue
        if ev["id"] in cache:
            results.append(cache[ev["id"]])
            total_in += cache[ev["id"]].get("in_tok", 0)
            total_out += cache[ev["id"]].get("out_tok", 0)
            cost += cache[ev["id"]].get("cost_usd", 0)
            continue

        frames = det["frames"]
        idxs = sample_n(frames, N_FRAMES)
        paths = []
        names = []
        for k in idxs:
            f = frames[k]
            p = resolve_frame(TMP, f["image_url"], f["frame_name"], device_id)
            if p:
                paths.append(p)
                names.append(f["frame_name"])
        if len(paths) < 4:
            print(f"  {ev['id'][:8]}: only {len(paths)} frames", flush=True)
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
        row = {"id": ev["id"], "ts": ev["ts"], "cam": ev["cam"], "gt": gt,
               "pred": pred, "confidence": obj.get("confidence_0_100"),
               "waste_type": obj.get("waste_type"),
               "offender_detected": obj.get("offender_detected"),
               "evidence_summary": (obj.get("evidence_summary") or "")[:200],
               "prompt_version": "V1_PROD",
               "in_tok": in_tok, "out_tok": out_tok, "latency_ms": latency,
               "cost_usd": round(ev_cost, 6),
               "n_frames_used": len(paths)}
        results.append(row)
        cache[ev["id"]] = row
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

        mark = "OK" if pred == gt else "MISS"
        print(f"  {i:>2}/{len(events)} {ev['ts'][:16]} cam_{ev['cam']} [V1_PROD] "
              f"gt={gt} pred={pred} conf={obj.get('confidence_0_100')} {mark} "
              f"({latency}ms in={in_tok} out={out_tok} ${ev_cost:.4f})", flush=True)

    print_summary("Gemini Flash 2.5 + V1 (prod baseline)", results, total_in, total_out, cost)
    out = Path("/tmp/flash_baseline_v1_results.json")
    out.write_text(json.dumps({"model": MODEL, "prompt": "V1_PROD",
                               "results": results, "cost_usd": round(cost, 6)},
                              ensure_ascii=False, indent=2))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    sys.exit(main())
