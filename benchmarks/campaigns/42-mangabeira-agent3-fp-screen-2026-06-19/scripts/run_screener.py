#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run the Agent-3 FP-screener over the eval manifest for one arm.

Arms / providers:
  --provider baseline : no screener -> always KEEP (= prod today). FP-suppression 0.
  --provider gemini   : Gemini 2.5 Flash via google-genai (GEMINI_TEST_API_KEY).
  --provider bedrock  : Claude Haiku 4.5 via AWS Bedrock (profile codex-ops).

Eval manifest CSV columns: event_id, gold (keep|kill), subtype, source, frames_dir

Writes results-<arm>.json (compatible-ish with the bench summary tooling) plus
a per-event verdict list. Caches per event_id so re-runs are cheap.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import screener_common as sc  # noqa: E402

GEMINI_MODEL = os.getenv("SCREENER_GEMINI_MODEL", "gemini-2.5-flash")
HAIKU_MODEL = os.getenv("SCREENER_HAIKU_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
GEMINI_IN_PRICE, GEMINI_OUT_PRICE = 0.15, 0.60          # $/1M tokens (Flash)
HAIKU_IN_PRICE, HAIKU_OUT_PRICE = 1.00, 5.00            # $/1M tokens (Haiku 4.5)


# --------------------------- providers ---------------------------

def call_gemini(client, payload):
    from google.genai import types
    # Interleave label-text before each image (DR#1 technique 1: temporal anchoring)
    parts = [types.Part.from_text(text=sc.SCREENER_INTRO)]
    for data, label in payload:
        parts.append(types.Part.from_text(text=f"--- {label} ---"))
        parts.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text=sc.SCREENER_TASK_INSTRUCTION))
    started = time.monotonic()
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=sc.SCREENER_SYSTEM_PROMPT,
            temperature=0,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    latency = int((time.monotonic() - started) * 1000)
    text = resp.text or ""
    um = getattr(resp, "usage_metadata", None)
    it = int(getattr(um, "prompt_token_count", 0) or 0)
    ot = int(getattr(um, "candidates_token_count", 0) or 0)
    tt = int(getattr(um, "thoughts_token_count", 0) or 0)
    cost = it / 1e6 * GEMINI_IN_PRICE + (ot + tt) / 1e6 * GEMINI_OUT_PRICE
    return text, it, ot + tt, latency, cost


_HAIKU_THINKING = int(os.getenv("SCREENER_HAIKU_THINKING", "1024"))
_HAIKU_USE_OUTPUT_CONFIG = os.getenv("SCREENER_HAIKU_OUTPUT_CONFIG", "1") == "1"


def _bedrock_content(payload):
    """XML-interleaved <frame> markers (DR#1 technique 1: temporal anchoring)."""
    content = [{"type": "text", "text": "<frame_sequence>"}]
    for data, label in payload:
        content.append({"type": "text", "text": f"<frame>{label}</frame>"})
        content.append({"type": "image", "source": {"type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(data).decode("ascii")}})
    content.append({"type": "text", "text": "</frame_sequence>\n\n" + sc.SCREENER_TASK_INSTRUCTION})
    return content


def call_bedrock(client, payload):
    """Haiku 4.5 DR#1-tuned: forensic system + XML frames + extended thinking +
    native structured output (output_config), falling back to prompted JSON."""
    global _HAIKU_USE_OUTPUT_CONFIG
    content = _bedrock_content(payload)
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": sc.HAIKU_SYSTEM_PROMPT,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": content}],
    }
    if _HAIKU_THINKING > 0:
        body["thinking"] = {"type": "enabled", "budget_tokens": _HAIKU_THINKING}
    else:
        body["temperature"] = 0
    if _HAIKU_USE_OUTPUT_CONFIG:
        body["output_config"] = {"format": {"type": "json_schema", "schema": sc.OUTPUT_JSON_SCHEMA}}

    started = time.monotonic()
    try:
        resp = client.invoke_model(modelId=HAIKU_MODEL, body=json.dumps(body),
                                   contentType="application/json", accept="application/json")
    except Exception as exc:  # noqa: BLE001
        # If structured-output / thinking params are rejected, degrade gracefully.
        msg = str(exc)
        if _HAIKU_USE_OUTPUT_CONFIG and ("output_config" in msg or "ValidationException" in msg):
            _HAIKU_USE_OUTPUT_CONFIG = False
            body.pop("output_config", None)
            resp = client.invoke_model(modelId=HAIKU_MODEL, body=json.dumps(body),
                                       contentType="application/json", accept="application/json")
        else:
            raise
    latency = int((time.monotonic() - started) * 1000)
    payload_out = json.loads(resp["body"].read().decode("utf-8"))
    text = "\n".join(p.get("text", "") for p in payload_out.get("content", []) if p.get("type") == "text")
    usage = payload_out.get("usage", {}) or {}
    it = int(usage.get("input_tokens") or 0)
    ot = int(usage.get("output_tokens") or 0)  # includes thinking tokens
    cost = it / 1e6 * HAIKU_IN_PRICE + ot / 1e6 * HAIKU_OUT_PRICE
    return text, it, ot, latency, cost


# --------------------------- runner ---------------------------

def process_event(row, provider, client, cache):
    eid = row["event_id"]
    if eid in cache:
        return cache[eid]
    frames_dir = Path(row["frames_dir"])
    base = {"event": eid, "gold": row["gold"], "subtype": row.get("subtype", ""),
            "source": row.get("source", "")}
    if provider == "baseline":
        base.update(keep=True, verdict={"is_real_new_disposal": True, "reason": "baseline-no-screener"},
                    cost_usd=0.0, latency_ms=0, input_tokens=0, output_tokens=0, ok=True)
        cache[eid] = base
        return base
    payload = sc.build_image_payload(frames_dir, with_pile_crop=True)
    if not payload:
        base.update(ok=False, error="no_frames", keep=True, cost_usd=0.0)
        cache[eid] = base
        return base
    fn = call_gemini if provider == "gemini" else call_bedrock
    for attempt in range(3):
        try:
            text, it, ot, latency, cost = fn(client, payload)
            verdict = sc.normalize_verdict(sc.extract_json(text))
            base.update(keep=sc.decision_keep(verdict), verdict=verdict, cost_usd=round(cost, 8),
                        latency_ms=latency, input_tokens=it, output_tokens=ot,
                        n_images=len(payload), ok=True)
            cache[eid] = base
            return base
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                base.update(ok=False, error=f"{type(exc).__name__}: {exc}", keep=True, cost_usd=0.0)
                cache[eid] = base
                return base
            time.sleep(2 * (attempt + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["baseline", "gemini", "bedrock"])
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--profile", default="codex-ops")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()

    rows = list(csv.DictReader(args.manifest.open(encoding="utf-8")))
    if args.limit:
        rows = rows[:args.limit]

    client = None
    if args.provider == "gemini":
        from google import genai
        key = os.environ.get("GEMINI_TEST_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not key:
            print("ERROR: GEMINI_TEST_API_KEY not set"); sys.exit(1)
        client = genai.Client(api_key=key)
    elif args.provider == "bedrock":
        import boto3
        from botocore.config import Config
        client = boto3.Session(profile_name=args.profile, region_name=args.region).client(
            "bedrock-runtime", config=Config(read_timeout=300, retries={"max_attempts": 2}))

    cache = {}
    cache_file = args.out.with_suffix(".cache.json")
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    results = []
    total = len(rows)
    started = time.monotonic()
    workers = 1 if args.provider == "baseline" else args.workers

    def work(r):
        return process_event(r, args.provider, client, cache)

    if workers == 1:
        for i, r in enumerate(rows, 1):
            results.append(work(r))
            if i == 1 or i % 10 == 0 or i == total:
                print(f"[{args.arm}] {i}/{total}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, res in enumerate(ex.map(work, rows), 1):
                results.append(res)
                if i == 1 or i % 10 == 0 or i == total:
                    print(f"[{args.arm}] {i}/{total}", flush=True)

    cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    elapsed = time.monotonic() - started
    cost = sum(r.get("cost_usd", 0) or 0 for r in results)
    ok = sum(1 for r in results if r.get("ok"))
    out = {
        "summary": {
            "arm": args.arm, "provider": args.provider,
            "model": (HAIKU_MODEL if args.provider == "bedrock"
                      else GEMINI_MODEL if args.provider == "gemini" else "none"),
            "events_total": total, "events_ok": ok,
            "total_cost_usd": round(cost, 6), "elapsed_seconds": round(elapsed, 1),
        },
        "results": results,
    }
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done {args.arm}: ok={ok}/{total} cost=${cost:.4f} elapsed={elapsed:.1f}s -> {args.out}")


if __name__ == "__main__":
    main()
