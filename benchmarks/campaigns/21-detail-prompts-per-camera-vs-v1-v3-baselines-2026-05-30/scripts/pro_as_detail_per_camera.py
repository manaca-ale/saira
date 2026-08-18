#!/usr/bin/env python3
"""Gemini Pro 2.5 as Agent-2 with per-camera prompts (campanha 21).

Mostra teto de qualidade do prompt — Pro 2.5 com thinking habilitado.
Pricing Gemini 2.5 Pro: in $1.25/M, out $10/M.
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _bench_common import (  # noqa: E402
    PROMPT_BY_CAM, DEVICE_BY_CAM, SYSTEMS, build_intro, fetch_events,
    jpeg_bytes, load_event, print_summary, resolve_frame, sample_n,
)
from google import genai
from google.genai import types

MODEL = "gemini-2.5-pro"
PRO_IN_PRICE = 1.25 / 1e6
PRO_OUT_PRICE = 10.0 / 1e6
# Match production: prod passes ALL frames in cascade window (up to
# GEMINI_CASCADE_MAX_FRAMES=48). Sub-sampling drops the critical deposit moment.
N_FRAMES = 48
TMP = Path("/tmp/pro_per_camera")
TMP.mkdir(parents=True, exist_ok=True)
CACHE_PATH = Path("/tmp/pro_per_camera_cache.json")

# Routing: prefer Vertex AI when GOOGLE_GENAI_USE_VERTEXAI=true (env defines
# GOOGLE_APPLICATION_CREDENTIALS + GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION).
# Falls back to AI Studio (api_key) for compatibility with older runs.
USE_VERTEX = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
if USE_VERTEX:
    CLIENT = genai.Client()  # auto-detects from env
    print(f"[init] backend=Vertex project={CLIENT._api_client.project} "
          f"location={CLIENT._api_client.location}", flush=True)
else:
    BENCH_KEY = os.environ["GEMINI_TEST_API_KEY"]
    CLIENT = genai.Client(api_key=BENCH_KEY)
    print("[init] backend=AI Studio", flush=True)


def call_pro(paths, frame_names, cam_id, prompt_version: str):
    intro = build_intro(paths, frame_names, cam_id)
    parts = [types.Part.from_text(text=intro)]
    for p in paths:
        parts.append(types.Part.from_bytes(data=jpeg_bytes(p), mime_type="image/jpeg"))
    t0 = time.monotonic()
    resp = CLIENT.models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=parts, role="user")],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEMS[prompt_version],
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
        prompt_version = PROMPT_BY_CAM.get(ev["cam"], "IMBIRIBEIRA")
        try:
            obj, in_tok, out_tok, latency = call_pro(paths, names, ev["cam"], prompt_version)
        except Exception as exc:
            print(f"  {ev['id'][:8]} ERROR: {exc}", flush=True)
            continue
        ev_cost = in_tok * PRO_IN_PRICE + out_tok * PRO_OUT_PRICE
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
               "prompt_version": prompt_version,
               "in_tok": in_tok, "out_tok": out_tok, "latency_ms": latency,
               "cost_usd": round(ev_cost, 6),
               "n_frames_used": len(paths)}
        results.append(row)
        cache[ev["id"]] = row
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

        mark = "OK" if pred == gt else "MISS"
        print(f"  {i:>2}/{len(events)} {ev['ts'][:16]} cam_{ev['cam']} [{prompt_version}] "
              f"gt={gt} pred={pred} conf={obj.get('confidence_0_100')} {mark} "
              f"({latency}ms in={in_tok} out={out_tok} ${ev_cost:.4f})", flush=True)

    print_summary("Gemini Pro 2.5", results, total_in, total_out, cost)
    out = Path("/tmp/pro_per_camera_results.json")
    out.write_text(json.dumps({"model": MODEL, "results": results,
                               "cost_usd": round(cost, 6)},
                              ensure_ascii=False, indent=2))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    sys.exit(main())
