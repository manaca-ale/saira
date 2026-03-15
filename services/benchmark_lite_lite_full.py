"""Benchmark Lite/Lite across ALL field_cctv datasets with proper cascade windowing.

Runs Agent 1 (gate) on every window. Agent 2 (detail) only when gate triggers.
Mirrors production cascade logic: 120s windows, 6-12 frames, prior context propagation.

Usage:
    cd services
    python benchmark_lite_lite_full.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
_worker_root = Path(__file__).resolve().parent / "yolo-worker-vm" / "src"
if str(_worker_root) not in sys.path:
    sys.path.insert(0, str(_worker_root))

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

os.environ["AI_MODE"] = "gemini"
os.environ["MOCK_MODE"] = "false"
os.environ.setdefault("P1_MODEL_PATH", "/dev/null")
os.environ.setdefault("P2_MODEL_PATH", "/dev/null")
# Force Lite/Lite
os.environ["GEMINI_MODEL"] = "gemini-2.5-flash-lite"
os.environ["GEMINI_AGENT1_MODEL"] = "gemini-2.5-flash-lite"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from worker import config  # noqa: E402
from worker.detector_gemini import (  # noqa: E402
    analyze_new_litter_with_gemini,
    analyze_with_gemini,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "datasets" / "field_cctv"
WINDOW_SECONDS = 120
MAX_FRAMES = 12
MIN_FRAMES = 2  # relaxed: some datasets are small
GATE_CONFIDENCE_THRESHOLD = 75
MAX_PAYLOAD_BYTES = 7_500_000  # conservative limit

# Pricing: Flash Lite
INPUT_PRICE = 0.10   # $/1M tokens
OUTPUT_PRICE = 0.40  # $/1M tokens
USD_TO_BRL = 5.70


def parse_timestamp(filename: str) -> datetime:
    stem = Path(filename).stem
    try:
        return datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return datetime.now()


def get_sorted_frames(dataset_dir: Path) -> list[Path]:
    return sorted(dataset_dir.glob("*.jpg"), key=lambda p: (parse_timestamp(p.name), p.name))


def build_windows(frames: list[Path]) -> list[list[Path]]:
    if not frames:
        return []
    windows: list[list[Path]] = []
    current: list[Path] = []
    window_start = parse_timestamp(frames[0].name)

    for img in frames:
        ts = parse_timestamp(img.name)
        exceeds_time = (ts - window_start).total_seconds() >= WINDOW_SECONDS
        exceeds_count = len(current) >= MAX_FRAMES
        if current and (exceeds_time or exceeds_count):
            if len(current) >= MIN_FRAMES:
                windows.append(current)
            current = [img]
            window_start = ts
            continue
        if not current:
            window_start = ts
        current.append(img)

    if len(current) >= MIN_FRAMES:
        windows.append(current)
    return windows


def calc_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * INPUT_PRICE + (output_tokens / 1_000_000) * OUTPUT_PRICE


def estimate_payload_size(frames: list[Path]) -> int:
    return sum(f.stat().st_size for f in frames)


def run_gate(first_frame: Path, last_frame: Path, camera_context: dict,
             prior_window_context: Optional[str], request_id: str,
             mid_frames: Optional[list[Path]] = None) -> dict:
    try:
        result = analyze_new_litter_with_gemini(
            first_frame=first_frame,
            last_frame=last_frame,
            camera_context=camera_context,
            request_id=request_id,
            prior_window_context=prior_window_context,
            use_mosaic=False,
            mid_frames=mid_frames,
        )
        cost = calc_cost(result.usage.input_tokens, result.usage.output_tokens)
        r = result.report
        return {
            "new_litter_detected": bool(r.new_litter_detected),
            "confidence": int(r.confidence_0_100),
            "evidence": r.evidence_summary,
            "waste_type": r.waste_type,
            "scene_delta": (r.scene_delta_analysis or "")[:300],
            "first_has_litter": bool(r.first_frame_has_litter),
            "last_has_litter": bool(r.last_frame_has_litter),
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
            "latency_ms": result.latency_ms,
            "cost_usd": round(cost, 6),
            "error": None,
        }
    except Exception as e:
        return {
            "new_litter_detected": None, "confidence": None,
            "evidence": None, "waste_type": None, "scene_delta": "",
            "first_has_litter": None, "last_has_litter": None,
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "latency_ms": 0, "cost_usd": 0, "error": str(e),
        }


def run_detail(frames: list[Path], camera_context: dict, request_id: str) -> dict:
    try:
        result = analyze_with_gemini(
            image_paths=frames,
            camera_context=camera_context,
            request_id=request_id,
            mosaic_mode="off",
        )
        cost = calc_cost(result.usage.input_tokens, result.usage.output_tokens)
        r = result.report
        return {
            "infraction_confirmed": bool(r.infraction_confirmed),
            "confidence": int(r.confidence_0_100),
            "evidence": r.evidence_summary,
            "waste_type": r.waste_type,
            "offender_detected": bool(r.offender_detected),
            "offender_types": r.offender_types,
            "volume_m3": r.volume_m3,
            "vehicle_plate": r.vehicle_plate,
            "event_frame": r.event_frame_name,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
            "latency_ms": result.latency_ms,
            "cost_usd": round(cost, 6),
            "error": None,
        }
    except Exception as e:
        return {
            "infraction_confirmed": None, "confidence": None,
            "evidence": str(e)[:100], "waste_type": None,
            "offender_detected": None, "offender_types": None,
            "volume_m3": None, "vehicle_plate": None, "event_frame": None,
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "latency_ms": 0, "cost_usd": 0, "error": str(e),
        }


def main():
    print("=" * 90)
    print("SAIRA Benchmark - Lite/Lite - ALL field_cctv datasets")
    print(f"Model: {config.GEMINI_MODEL} | Agent1: {config.GEMINI_AGENT1_MODEL}")
    print(f"Window: {WINDOW_SECONDS}s | Frames: {MIN_FRAMES}-{MAX_FRAMES} | Threshold: {GATE_CONFIDENCE_THRESHOLD}")
    print("=" * 90)

    # Discover all datasets
    datasets = sorted([
        d for d in DATA_ROOT.iterdir()
        if d.is_dir() and any(d.glob("*.jpg"))
    ], key=lambda d: d.name)

    print(f"\nFound {len(datasets)} datasets\n")

    all_results = []
    grand_totals = {
        "total_windows": 0, "gate_triggered": 0, "infractions": 0,
        "gate_cost_usd": 0.0, "detail_cost_usd": 0.0,
        "gate_latency_ms": 0, "detail_latency_ms": 0,
        "gate_tokens_in": 0, "gate_tokens_out": 0,
        "detail_tokens_in": 0, "detail_tokens_out": 0,
        "payload_skipped": 0,
    }

    for ds_path in datasets:
        ds_name = ds_path.name
        frames = get_sorted_frames(ds_path)
        windows = build_windows(frames)

        if not windows:
            print(f"[{ds_name}] {len(frames)} frames -> 0 windows (skipped)")
            continue

        ts_range = f"{frames[0].stem} -> {frames[-1].stem}"
        print(f"\n{'=' * 70}")
        print(f"[{ds_name}]  {len(frames)} frames -> {len(windows)} windows")
        print(f"  Time: {ts_range}")
        print(f"{'=' * 70}")

        ds_stats = {
            "dataset": ds_name, "total_frames": len(frames),
            "total_windows": len(windows), "gate_triggered": 0,
            "infractions": 0, "cost_usd": 0.0, "windows": [],
        }

        prior_had_litter = False
        prior_waste_type: Optional[str] = None
        prev_last_frame: Optional[Path] = None

        for wi, window in enumerate(windows):
            # Use previous window's last frame as reference when available
            first_frame = prev_last_frame if prev_last_frame and prev_last_frame.exists() else window[0]
            last_frame = window[-1]

            # Build prior context
            prior_ctx: Optional[str] = None
            if prior_had_litter:
                waste_label = f" (type: {prior_waste_type})" if prior_waste_type else ""
                prior_ctx = (
                    f"- Previous window ALREADY had waste at this location{waste_label}. "
                    "Confirm NEW_SOLID_WASTE only if a NEW object appeared or volume visibly increased."
                )

            effective_threshold = max(GATE_CONFIDENCE_THRESHOLD, 80) if prior_had_litter else GATE_CONFIDENCE_THRESHOLD

            camera_ctx = {"camera_name": ds_name, "horario_local": parse_timestamp(last_frame.name).strftime("%H:%M")}
            req_prefix = f"{ds_name}-w{wi}"

            # ---- Agent 1 (gate) ----
            # Select mid-window frames at 25%/50%/75% for ghost event detection (Pattern C)
            mid_frames: Optional[list[Path]] = None
            wn = len(window)
            if wn >= 5:
                mid_frames = [window[wn // 4], window[wn // 2], window[3 * wn // 4]]
            elif wn >= 4:
                mid_frames = [window[wn // 2]]

            n_gate_frames = 2 + (len(mid_frames) if mid_frames else 0)
            print(f"  W{wi+1}/{len(windows)} [{window[0].stem} -> {window[-1].stem}] "
                  f"({len(window)}fr, gate={n_gate_frames}fr, prior={prior_had_litter}) ", end="", flush=True)

            gate = run_gate(first_frame, last_frame, camera_ctx, prior_ctx, f"ag1-{req_prefix}",
                            mid_frames=mid_frames)

            if gate["error"]:
                print(f"GATE_ERROR: {gate['error'][:60]}")
                prior_had_litter = False
                prev_last_frame = last_frame
                ds_stats["windows"].append({"window": wi, "gate": gate, "detail": None, "outcome": "GATE_ERROR"})
                ds_stats["cost_usd"] += gate["cost_usd"]
                grand_totals["total_windows"] += 1
                continue

            gate_triggered = bool(gate["new_litter_detected"]) and gate["confidence"] >= effective_threshold

            grand_totals["total_windows"] += 1
            grand_totals["gate_cost_usd"] += gate["cost_usd"]
            grand_totals["gate_latency_ms"] += gate["latency_ms"]
            grand_totals["gate_tokens_in"] += gate["input_tokens"]
            grand_totals["gate_tokens_out"] += gate["output_tokens"]

            # Update prior state
            prior_had_litter = bool(gate.get("last_has_litter"))
            prior_waste_type = gate.get("waste_type")
            prev_last_frame = last_frame

            # ---- Agent 2 (detail) — only if gate triggered ----
            detail = None
            outcome = "GATE_REJECT"

            if gate_triggered:
                grand_totals["gate_triggered"] += 1
                ds_stats["gate_triggered"] += 1

                payload = estimate_payload_size(window)
                if payload > MAX_PAYLOAD_BYTES:
                    # Try with fewer frames
                    reduced = window[:max(6, MAX_FRAMES * MAX_PAYLOAD_BYTES // payload)]
                    payload2 = estimate_payload_size(reduced)
                    if payload2 > MAX_PAYLOAD_BYTES:
                        print(f"GATE_PASS(conf={gate['confidence']}) -> PAYLOAD_SKIP({payload//1024}KB)")
                        grand_totals["payload_skipped"] += 1
                        outcome = "PAYLOAD_SKIP"
                        ds_stats["windows"].append({"window": wi, "gate": gate, "detail": None, "outcome": outcome})
                        ds_stats["cost_usd"] += gate["cost_usd"]
                        continue
                    send_frames = reduced
                else:
                    send_frames = window

                print(f"GATE_PASS(conf={gate['confidence']}) -> Ag2...", end=" ", flush=True)
                detail = run_detail(send_frames, camera_ctx, f"ag2-{req_prefix}")

                if detail["error"]:
                    print(f"AG2_ERROR: {detail['error'][:60]}")
                    outcome = "AG2_ERROR"
                elif detail["infraction_confirmed"]:
                    print(f"INFRACTION(conf={detail['confidence']}, waste={detail['waste_type']}, "
                          f"offender={detail['offender_detected']})")
                    outcome = "INFRACTION"
                    grand_totals["infractions"] += 1
                    ds_stats["infractions"] += 1
                else:
                    print(f"AG2_REJECT(conf={detail['confidence']})")
                    outcome = "AG2_REJECT"

                grand_totals["detail_cost_usd"] += detail["cost_usd"]
                grand_totals["detail_latency_ms"] += detail["latency_ms"]
                grand_totals["detail_tokens_in"] += detail["input_tokens"]
                grand_totals["detail_tokens_out"] += detail["output_tokens"]
            else:
                litter = "+" if gate.get("last_has_litter") else "-"
                print(f"GATE_REJECT(det={gate['new_litter_detected']}, conf={gate['confidence']}, litter={litter})")

            ds_stats["cost_usd"] += gate["cost_usd"] + (detail["cost_usd"] if detail else 0)
            ds_stats["windows"].append({"window": wi, "gate": gate, "detail": detail, "outcome": outcome})

        # Dataset summary
        ds_cost_brl = ds_stats["cost_usd"] * USD_TO_BRL
        print(f"\n  >> {ds_name}: {ds_stats['gate_triggered']}/{len(windows)} triggered, "
              f"{ds_stats['infractions']} infractions, R${ds_cost_brl:.4f}")
        all_results.append(ds_stats)

    # -----------------------------------------------------------------------
    # Grand summary
    # -----------------------------------------------------------------------
    total_cost = grand_totals["gate_cost_usd"] + grand_totals["detail_cost_usd"]
    total_cost_brl = total_cost * USD_TO_BRL

    print("\n" + "=" * 90)
    print("GRAND SUMMARY - Lite/Lite")
    print("=" * 90)
    print(f"\nDatasets processed : {len(all_results)}")
    print(f"Total windows      : {grand_totals['total_windows']}")
    print(f"Gate triggered     : {grand_totals['gate_triggered']} "
          f"({100*grand_totals['gate_triggered']/max(1,grand_totals['total_windows']):.1f}%)")
    print(f"Infractions conf.  : {grand_totals['infractions']} "
          f"({100*grand_totals['infractions']/max(1,grand_totals['gate_triggered']):.1f}% of gate-pass)")
    print(f"Payload skipped    : {grand_totals['payload_skipped']}")

    print(f"\n--- Agent 1 (Gate) ---")
    print(f"  Total calls      : {grand_totals['total_windows']}")
    print(f"  Total tokens     : {grand_totals['gate_tokens_in']} in / {grand_totals['gate_tokens_out']} out")
    print(f"  Avg latency      : {grand_totals['gate_latency_ms']//max(1,grand_totals['total_windows'])}ms")
    print(f"  Total cost       : ${grand_totals['gate_cost_usd']:.4f} (R${grand_totals['gate_cost_usd']*USD_TO_BRL:.4f})")

    print(f"\n--- Agent 2 (Detail) ---")
    ag2_calls = grand_totals['gate_triggered'] - grand_totals['payload_skipped']
    print(f"  Total calls      : {ag2_calls}")
    print(f"  Total tokens     : {grand_totals['detail_tokens_in']} in / {grand_totals['detail_tokens_out']} out")
    if ag2_calls > 0:
        print(f"  Avg latency      : {grand_totals['detail_latency_ms']//ag2_calls}ms")
    print(f"  Total cost       : ${grand_totals['detail_cost_usd']:.4f} (R${grand_totals['detail_cost_usd']*USD_TO_BRL:.4f})")

    print(f"\n--- TOTAL ---")
    print(f"  Cost             : ${total_cost:.4f} (R${total_cost_brl:.4f})")
    print(f"  Avg cost/window  : R${total_cost_brl/max(1,grand_totals['total_windows']):.4f}")

    # Per-dataset summary table
    print(f"\n{'Dataset':<45} {'Win':<5} {'Trig':<5} {'Infr':<5} {'Cost R$':<10}")
    print("-" * 75)
    for ds in all_results:
        brl = ds["cost_usd"] * USD_TO_BRL
        print(f"{ds['dataset']:<45} {ds['total_windows']:<5} {ds['gate_triggered']:<5} "
              f"{ds['infractions']:<5} {brl:<10.4f}")

    # Save JSON
    output_path = Path(__file__).resolve().parent / "benchmark_lite_lite_full_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"grand_totals": grand_totals, "datasets": all_results},
                  f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
