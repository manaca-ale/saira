#!/usr/bin/env python3
"""Run Claude Haiku 4.5 on the same Agent-1 B2 gate sample as campaign 18."""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

import boto3

CAMPAIGN_DIR = Path(__file__).parent
PROJECT_ROOT = Path(r"c:\saira")
WORKER_SRC = PROJECT_ROOT / "services" / "yolo-worker-vm" / "src"

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from worker import _prompts_v3  # noqa: E402


def _load_bench18_module():
    path = CAMPAIGN_DIR / "bench_gate_v3_vs_recall.py"
    spec = importlib.util.spec_from_file_location("bench18_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bench18_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


def _image_block(path: Path) -> dict:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": data,
        },
    }


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start:end + 1]
    return text


def run_haiku_gate(client, window, model_id: str, system_prompt: str, user_prompt: str) -> dict:
    content = [{"type": "text", "text": user_prompt}]
    image_paths = [window.first_frame]
    if window.mid_frames:
        image_paths.extend(window.mid_frames)
    image_paths.append(window.last_frame)
    for image_path in image_paths:
        content.append(_image_block(image_path))

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": system_prompt,
        "max_tokens": 1200,
        "temperature": 0,
        "messages": [{"role": "user", "content": content}],
    }

    started = time.monotonic()
    response = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    payload = json.loads(response["body"].read().decode("utf-8"))
    raw_text = "\n".join(part.get("text", "") for part in payload.get("content", []) if part.get("type") == "text")
    raw_json = _extract_json(raw_text)

    report = _prompts_v3.GeminiNewLitterReportV3.model_validate_json(raw_json)
    report.waste_type = report.waste_type
    report.confidence_0_100 = max(0, min(100, int(report.confidence_0_100)))
    report, is_maintenance = _prompts_v3.apply_v3_gates(report, request_id=f"haiku-{window.window_id[:8]}")

    usage = payload.get("usage", {}) or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cost = (input_tokens / 1_000_000.0) * 1.00 + (output_tokens / 1_000_000.0) * 5.00

    return {
        "ok": True,
        "provider": "bedrock",
        "model": model_id,
        "prompt_label": "haiku_b2",
        "n_frames_sent": len(image_paths),
        "confidence_0_100": int(report.confidence_0_100),
        "new_litter_detected": bool(report.new_litter_detected),
        "scene_type": report.scene_type,
        "person_position_signature": report.person_position_signature,
        "vehicle_stopped": bool(report.vehicle_stopped),
        "person_handling_material": bool(report.person_handling_material),
        "new_ground_material": bool(report.new_ground_material),
        "material_flow_direction": report.material_flow_direction,
        "pile_volume_change": report.pile_volume_change,
        "municipal_equipment_present": bool(report.municipal_equipment_present),
        "is_maintenance": bool(is_maintenance),
        "evidence_summary": (report.evidence_summary or "")[:500],
        "scene_delta_analysis": (report.scene_delta_analysis or "")[:500],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "latency_ms": latency_ms,
        "cost_usd": round(cost, 8),
        "raw_json": raw_json,
    }


def result_entry(window, gate: dict) -> dict:
    return {
        "event": window.window_id,
        "ground_truth": "TP" if window.category == "tp" else ("FP" if window.category == "fp" else "BASELINE"),
        "source": window.source,
        "camera": window.camera,
        "category": window.category,
        "metadata": window.metadata,
        "gate": gate,
        "triggered": bool(gate.get("new_litter_detected")),
        "detail": None,
        "total_cost_usd": gate.get("cost_usd", 0.0) or 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_DIR)
    parser.add_argument("--baseline-per-period", type=int, default=10)
    parser.add_argument("--profile", default="codex-ops")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--model-id", default="us.anthropic.claude-haiku-4-5-20251001-v1:0")
    args = parser.parse_args()

    bench18 = _load_bench18_module()
    windows = bench18.build_windows_from_manifest() + bench18.build_baseline_windows(per_period=args.baseline_per_period)
    system_prompt = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 + "\n\n" + bench18.ESP32_RECALL_BLOCK_B2
    camera_context = bench18.CAMERA_CONTEXT["cam_mangabeira"] | {"device_id": "esp32_002"}

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("bedrock-runtime")

    results = []
    total = len(windows)
    started = time.monotonic()
    for idx, window in enumerate(windows, 1):
        if idx == 1 or idx % 10 == 0 or idx == total:
            print(f"[E_haiku_b2] {idx}/{total} {window.window_id[:8]} {window.category}", flush=True)
        mid_names = [p.name for p in window.mid_frames] if window.mid_frames else None
        user_prompt = _prompts_v3.build_v3_user_prompt_gate(
            window.first_frame.name,
            window.last_frame.name,
            camera_context,
            prior_window_context=None,
            mosaic=False,
            mid_frame_names=mid_names,
        )
        try:
            gate = run_haiku_gate(client, window, args.model_id, system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001
            gate = {
                "ok": False,
                "provider": "bedrock",
                "model": args.model_id,
                "prompt_label": "haiku_b2",
                "n_frames_sent": 2 + len(window.mid_frames),
                "error": f"{type(exc).__name__}: {exc}",
            }
        results.append(result_entry(window, gate))

    elapsed = time.monotonic() - started
    cost = sum(r["total_cost_usd"] for r in results)
    ok = sum(1 for r in results if r["gate"].get("ok"))
    triggered = sum(1 for r in results if r["triggered"])
    out = {
        "summary": {
            "arm": "E_haiku_b2",
            "description": "Claude Haiku 4.5 Bedrock Agent-1 with B2 gate prompt",
            "provider": "bedrock",
            "model_gate": args.model_id,
            "events_total": total,
            "events_ok": ok,
            "events_triggered": triggered,
            "total_cost_usd": round(cost, 6),
            "elapsed_seconds": round(elapsed, 1),
        },
        "results": results,
    }
    out_path = args.campaign / "results-E_haiku_b2.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done ok={ok}/{total} triggered={triggered} cost=${cost:.4f} elapsed={elapsed:.1f}s -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
