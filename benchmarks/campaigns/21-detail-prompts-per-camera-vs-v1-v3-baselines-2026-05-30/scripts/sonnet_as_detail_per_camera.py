#!/usr/bin/env python3
"""Claude Sonnet 4.6 (Bedrock) as Agent-2 with per-camera prompts (campanha 21).

Mirror of pro_as_detail_per_camera.py but using AWS Bedrock + Sonnet.
Same per-camera prompts, same N_FRAMES=48 (production parity).

Pricing Sonnet 4.6 Bedrock: in $3/M, out $15/M.
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
import boto3

MODEL_ID = "us.anthropic.claude-sonnet-4-6"
REGION = "us-east-1"
SONNET_IN_PRICE = 3.0 / 1e6
SONNET_OUT_PRICE = 15.0 / 1e6
N_FRAMES = 48  # match production
TMP = Path("/tmp/sonnet_per_camera")
TMP.mkdir(parents=True, exist_ok=True)
CACHE_PATH = Path("/tmp/sonnet_per_camera_cache.json")

BEDROCK = boto3.client("bedrock-runtime", region_name=REGION)


def call_sonnet(paths, frame_names, cam_id, prompt_version: str):
    intro = build_intro(paths, frame_names, cam_id)
    content = [{"text": intro}]
    for p in paths:
        content.append({"image": {"format": "jpeg",
                                   "source": {"bytes": jpeg_bytes(p)}}})
    t0 = time.monotonic()
    resp = BEDROCK.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEMS[prompt_version]}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"temperature": 0.0, "maxTokens": 2048},
    )
    latency = int((time.monotonic() - t0) * 1000)
    text = resp["output"]["message"]["content"][0]["text"]
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        obj = json.loads(text.strip())
    except Exception:
        obj = {"raw": text[:400]}
    u = resp.get("usage", {})
    return obj, u.get("inputTokens", 0), u.get("outputTokens", 0), latency


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
            obj, in_tok, out_tok, latency = call_sonnet(paths, names, ev["cam"], prompt_version)
        except Exception as exc:
            print(f"  {ev['id'][:8]} ERROR: {exc}", flush=True)
            continue
        ev_cost = in_tok * SONNET_IN_PRICE + out_tok * SONNET_OUT_PRICE
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

    print_summary("Claude Sonnet 4.6 (Bedrock)", results, total_in, total_out, cost)
    out = Path("/tmp/sonnet_per_camera_results.json")
    out.write_text(json.dumps({"model": MODEL_ID, "results": results,
                               "cost_usd": round(cost, 6)},
                              ensure_ascii=False, indent=2))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    sys.exit(main())
