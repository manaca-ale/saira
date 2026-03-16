#!/usr/bin/env python3
"""Run Gemini 2-stage cascade validation over chronological CCTV frames."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})")


def _load_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'").strip('"')
    return data


def _parse_ts_from_name(path: Path) -> datetime:
    match = TS_RE.search(path.stem)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M-%S")
        except Exception:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def _collect_images(root: Path) -> list[Path]:
    images = [p for p in root.rglob("*.jpg") if p.is_file()]
    return sorted(images, key=lambda p: (_parse_ts_from_name(p), p.name))


def _build_windows(images: list[Path], window_seconds: int, max_frames: int, min_frames: int) -> list[list[Path]]:
    if not images:
        return []
    windows: list[list[Path]] = []
    current: list[Path] = []
    start_ts = _parse_ts_from_name(images[0])

    for img in images:
        ts = _parse_ts_from_name(img)
        exceeds_time = (ts - start_ts).total_seconds() >= window_seconds
        exceeds_count = len(current) >= max_frames
        if current and (exceeds_time or exceeds_count):
            if len(current) >= max(2, min_frames):
                windows.append(current)
            current = [img]
            start_ts = ts
            continue
        if not current:
            start_ts = ts
        current.append(img)

    if len(current) >= max(2, min_frames):
        windows.append(current)
    return windows


def main() -> int:
    parser = argparse.ArgumentParser(description="Gemini cascade validation on chronological CCTV frames.")
    parser.add_argument(
        "--images-root",
        required=True,
        help="Root directory containing JPG frames to evaluate.",
    )
    parser.add_argument(
        "--env-file",
        default=r"c:\saira\services\.env",
        help="Env file with GEMINI_API_KEY and model settings.",
    )
    parser.add_argument("--window-seconds", type=int, default=120)
    parser.add_argument("--max-frames", type=int, default=12)
    parser.add_argument("--min-frames", type=int, default=6)
    parser.add_argument("--agent1-min-confidence", type=int, default=60)
    parser.add_argument("--max-windows", type=int, default=0, help="0 means process all windows.")
    parser.add_argument("--report-prefix", default="gemini_cascade_validation")
    args = parser.parse_args()

    root = Path(args.images_root)
    if not root.exists():
        raise RuntimeError(f"images-root not found: {root}")

    env_data = _load_env_file(Path(args.env_file))
    for key, value in env_data.items():
        os.environ.setdefault(key, value)

    # Ensure worker package import path.
    worker_src = Path(r"c:\saira\services\yolo-worker-vm\src")
    if str(worker_src) not in sys.path:
        sys.path.insert(0, str(worker_src))

    from worker.detector_gemini import analyze_new_litter_with_gemini, analyze_with_gemini

    images = _collect_images(root)
    windows = _build_windows(
        images,
        window_seconds=int(args.window_seconds),
        max_frames=int(args.max_frames),
        min_frames=int(args.min_frames),
    )
    if int(args.max_windows) > 0:
        windows = windows[: int(args.max_windows)]

    report_rows: list[dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost_usd = 0.0
    total_gate_calls = 0
    total_agent2_calls = 0
    total_gate_triggered = 0
    total_disposals = 0

    for idx, window in enumerate(windows, start=1):
        first_frame = window[0]
        last_frame = window[-1]

        gate = analyze_new_litter_with_gemini(
            first_frame=first_frame,
            last_frame=last_frame,
            camera_context={"source": "offline_validation"},
            request_id=f"gate-{idx}",
        )
        total_gate_calls += 1
        total_input_tokens += gate.usage.input_tokens
        total_output_tokens += gate.usage.output_tokens
        total_cost_usd += gate.usage.estimated_cost_usd

        gate_triggered = bool(gate.report.new_litter_detected) and int(gate.report.confidence_0_100) >= int(
            args.agent1_min_confidence
        )
        if gate_triggered:
            total_gate_triggered += 1

        agent2_payload: dict[str, Any] | None = None
        if gate_triggered:
            agent2 = analyze_with_gemini(
                image_paths=window,
                camera_context={"source": "offline_validation"},
                request_id=f"agent2-{idx}",
            )
            total_agent2_calls += 1
            total_input_tokens += agent2.usage.input_tokens
            total_output_tokens += agent2.usage.output_tokens
            total_cost_usd += agent2.usage.estimated_cost_usd

            disposal = bool(agent2.report.infraction_confirmed)
            if disposal:
                total_disposals += 1

            agent2_payload = {
                "disposal": disposal,
                "latency_ms": agent2.latency_ms,
                "confidence_0_100": agent2.report.confidence_0_100,
                "waste_type": agent2.report.waste_type,
                "offender_detected": agent2.report.offender_detected,
                "offender_types": agent2.report.offender_types,
                "vehicle_plate": agent2.report.vehicle_plate,
                "event_frame_name": agent2.report.event_frame_name,
                "offender_frame_name": agent2.report.offender_frame_name,
                "evidence_summary": agent2.report.evidence_summary,
                "usage": {
                    "input_tokens": agent2.usage.input_tokens,
                    "output_tokens": agent2.usage.output_tokens,
                    "total_tokens": agent2.usage.total_tokens,
                    "estimated_cost_usd": agent2.usage.estimated_cost_usd,
                },
            }

        report_rows.append(
            {
                "window_index": idx,
                "window_size": len(window),
                "first_frame": first_frame.name,
                "last_frame": last_frame.name,
                "all_frames": [p.name for p in window],
                "agent1": {
                    "triggered_agent2": gate_triggered,
                    "new_litter_detected": gate.report.new_litter_detected,
                    "confidence_0_100": gate.report.confidence_0_100,
                    "first_frame_has_litter": gate.report.first_frame_has_litter,
                    "last_frame_has_litter": gate.report.last_frame_has_litter,
                    "waste_type": gate.report.waste_type,
                    "evidence_summary": gate.report.evidence_summary,
                    "usage": {
                        "input_tokens": gate.usage.input_tokens,
                        "output_tokens": gate.usage.output_tokens,
                        "total_tokens": gate.usage.total_tokens,
                        "estimated_cost_usd": gate.usage.estimated_cost_usd,
                    },
                },
                "agent2": agent2_payload,
            }
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(r"c:\saira\tmp") / f"{args.report_prefix}_{ts}.json"
    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "images_root": str(root),
        "window_seconds": int(args.window_seconds),
        "max_frames": int(args.max_frames),
        "min_frames": int(args.min_frames),
        "agent1_min_confidence": int(args.agent1_min_confidence),
        "windows_total": len(windows),
        "summary": {
            "agent1_calls_total": total_gate_calls,
            "agent2_calls_total": total_agent2_calls,
            "agent1_trigger_rate": round(total_gate_triggered / max(1, len(windows)), 6),
            "disposals_detected_total": total_disposals,
            "input_tokens_total": total_input_tokens,
            "output_tokens_total": total_output_tokens,
            "estimated_cost_usd_total": round(total_cost_usd, 8),
        },
        "windows": report_rows,
    }
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {out_path}")
    print(json.dumps(output["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

