"""Standalone test script for the Gemini cascade pipeline.

Processes a dataset directory of real-world images through Stage 1 (gate) and
Stage 2 (detail) WITHOUT touching the database or Redis. Designed for comparing
pipeline behavior before and after prompt/logic changes.

Usage:
    GEMINI_API_KEY=<key> python services/scripts/test_cascade_retest.py \\
        --dataset C:/saira/tmp/test_logs/datasets/cascade_retest_20260311_160241 \\
        --output C:/saira/tmp/test_logs \\
        --runs 5

Dataset layout expected:
    <dataset>/
        <device_id>/
            <YYYY>/<MM>/<DD>/
                YYYY-MM-DD_HH-MM-SS.jpg
                ...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

# Make the worker package importable when running from repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKER_PKG = _REPO_ROOT / "services" / "yolo-worker-vm" / "src"
if str(_WORKER_PKG) not in sys.path:
    sys.path.insert(0, str(_WORKER_PKG))

# Auto-load .env from services/ so GEMINI_API_KEY is available without manual export.
_ENV_FILE = _REPO_ROOT / "services" / ".env"
if _ENV_FILE.exists():
    with _ENV_FILE.open(encoding="utf-8") as _fh:
        for _line in _fh:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

# Config overrides must come BEFORE importing the worker package so that env
# vars are set before module-level constants are evaluated.
os.environ.setdefault("AI_MODE", "gemini")
os.environ.setdefault("GEMINI_CASCADE_ENABLED", "true")
os.environ.setdefault("MOCK_MODE", "false")
# Suppress YOLO model-missing warnings — we never use YOLO here.
os.environ.setdefault("P1_MODEL_PATH", "/dev/null")
os.environ.setdefault("P2_MODEL_PATH", "/dev/null")

from worker import config  # noqa: E402
from worker.detector_gemini import analyze_new_litter_with_gemini, analyze_with_gemini  # noqa: E402
from worker.schemas_gemini import GeminiNewLitterReport  # noqa: E402

BRASILIA = ZoneInfo("America/Sao_Paulo")

# Window parameters — mirror worker defaults.
WINDOW_SECONDS = config.GEMINI_CASCADE_WINDOW_SECONDS   # 120
MAX_FRAMES = config.GEMINI_CASCADE_MAX_FRAMES            # 12
MIN_FRAMES = max(2, config.GEMINI_CASCADE_MIN_FRAMES)    # 6
THRESHOLD = config.GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE  # 75 (after Option D)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_timestamp(filename: str) -> datetime:
    stem = Path(filename).stem
    try:
        return datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return datetime.now(BRASILIA).replace(tzinfo=None)


def collect_device_images(device_dir: Path) -> list[Path]:
    """Recursively collect all .jpg files under a device directory."""
    return sorted(
        device_dir.rglob("*.jpg"),
        key=lambda p: (parse_timestamp(p.name), p.name),
    )


def build_cascade_windows(images: list[Path]) -> list[list[Path]]:
    """Group chronological images into non-overlapping time windows."""
    if not images:
        return []

    ordered = sorted(images, key=lambda p: (parse_timestamp(p.name), p.name))
    windows: list[list[Path]] = []
    current: list[Path] = []
    window_start = parse_timestamp(ordered[0].name)

    for img in ordered:
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


def run_cascade_window(
    window_paths: list[Path],
    device_id: str,
    prior_had_litter: bool,
    prior_waste_type: Optional[str],
    prev_last_frame: Optional[Path] = None,
) -> dict:
    """Run one cascade window and return a result dict (no DB/Redis calls)."""
    # Correction 2: use last frame of previous window as reference when available
    if prev_last_frame and prev_last_frame.exists():
        first_frame = prev_last_frame
    else:
        first_frame = window_paths[0]
    last_frame = window_paths[-1]

    # Build prior-window context (English, consistent with updated prompt)
    prior_window_context: Optional[str] = None
    if prior_had_litter:
        waste_label = f" (type: {prior_waste_type})" if prior_waste_type else ""
        prior_window_context = (
            f"- The previous 2-minute window ALREADY had waste at this location{waste_label}. "
            "Confirm NEW_SOLID_WASTE only if a NEW object appeared or the volume visibly increased."
        )

    # Inject local time for time-of-day awareness (Option B)
    last_frame_ts = parse_timestamp(last_frame.name)
    local_time_hhmm = last_frame_ts.strftime("%H:%M")

    camera_context = {
        "camera_name": device_id,
        "horario_local": local_time_hhmm,
    }

    # Dynamic threshold when pre-existing litter is known (Option B)
    effective_threshold = max(THRESHOLD, 80) if prior_had_litter else THRESHOLD

    # --- Stage 1: Gate ---
    gate_result: dict = {}
    gate_triggered = False
    gate_error: Optional[str] = None
    gate_cost = 0.0

    try:
        gate = analyze_new_litter_with_gemini(
            first_frame=first_frame,
            last_frame=last_frame,
            camera_context=camera_context,
            prior_window_context=prior_window_context,
        )
        gr = gate.report
        gate_result = {
            "new_litter_detected": bool(gr.new_litter_detected),
            "confidence_0_100": int(gr.confidence_0_100),
            "effective_threshold": effective_threshold,
            "first_frame_has_litter": bool(gr.first_frame_has_litter),
            "last_frame_has_litter": bool(gr.last_frame_has_litter),
            "waste_type": gr.waste_type,
            "scene_delta_analysis": gr.scene_delta_analysis or "",
            "evidence_summary": gr.evidence_summary,
            "raw_reason_codes": gr.raw_reason_codes,
            "latency_ms": gate.latency_ms,
            "input_tokens": gate.usage.input_tokens,
            "output_tokens": gate.usage.output_tokens,
            "estimated_cost_usd": gate.usage.estimated_cost_usd,
        }
        gate_cost = gate.usage.estimated_cost_usd or 0.0
        gate_triggered = (
            bool(gr.new_litter_detected)
            and int(gr.confidence_0_100) >= effective_threshold
        )
        # Update prior state for next window
        prior_had_litter = bool(gr.last_frame_has_litter)
        prior_waste_type = gr.waste_type
    except Exception as exc:
        gate_error = str(exc)
        print(f"  [GATE ERROR] {device_id} | {first_frame.name}: {exc}")
        prior_had_litter = False

    # --- Stage 2: Detail (only if gate triggered) ---
    stage2_result: dict = {}
    stage2_error: Optional[str] = None
    stage2_cost = 0.0
    infraction_confirmed = False

    if gate_triggered:
        try:
            detail = analyze_with_gemini(
                image_paths=window_paths,
                camera_context=camera_context,
            )
            dr = detail.report
            stage2_result = {
                "infraction_confirmed": bool(dr.infraction_confirmed),
                "confidence_0_100": int(dr.confidence_0_100),
                "waste_type": dr.waste_type,
                "material_type": dr.material_type,
                "volume_m3": dr.volume_m3,
                "offender_detected": bool(dr.offender_detected),
                "offender_types": dr.offender_types,
                "vehicle_plate": dr.vehicle_plate,
                "event_frame_name": dr.event_frame_name,
                "offender_frame_name": dr.offender_frame_name,
                "evidence_summary": dr.evidence_summary,
                "raw_reason_codes": dr.raw_reason_codes,
                "latency_ms": detail.latency_ms,
                "input_tokens": detail.usage.input_tokens,
                "output_tokens": detail.usage.output_tokens,
                "estimated_cost_usd": detail.usage.estimated_cost_usd,
            }
            stage2_cost = detail.usage.estimated_cost_usd or 0.0
            infraction_confirmed = bool(dr.infraction_confirmed)
        except Exception as exc:
            stage2_error = str(exc)
            print(f"  [STAGE2 ERROR] {device_id} | {last_frame.name}: {exc}")

    return {
        "device_id": device_id,
        "first_frame": first_frame.name,
        "last_frame": last_frame.name,
        "window_size": len(window_paths),
        "window_frames": [p.name for p in window_paths],
        "prior_had_litter": prior_had_litter,
        "gate_error": gate_error,
        "gate_triggered": gate_triggered,
        "gate_result": gate_result,
        "stage2_error": stage2_error,
        "stage2_triggered": gate_triggered,
        "infraction_confirmed": infraction_confirmed,
        "stage2_result": stage2_result,
        "total_cost_usd": round(gate_cost + stage2_cost, 8),
        # Updated prior state to carry forward
        "_next_prior_had_litter": prior_had_litter,
        "_next_prior_waste_type": prior_waste_type,
        "_next_prev_last_frame": last_frame,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_once(dataset_dir: Path, run_index: int, hour_ranges: Optional[list[tuple[int, int]]] = None) -> tuple[list[dict], dict]:
    """Process all devices/windows once. Returns (results, summary).

    Args:
        hour_ranges: Optional list of (start_hour, end_hour) tuples (inclusive start,
            exclusive end) to filter images by local time. E.g. [(6, 12), (14, 18)].
    """
    all_results: list[dict] = []
    total_windows = 0
    gate_triggered_count = 0
    infraction_count = 0
    total_cost = 0.0
    per_device: dict[str, dict] = {}

    for device_dir in sorted(dataset_dir.iterdir()):
        if not device_dir.is_dir():
            continue
        device_id = device_dir.name
        images = collect_device_images(device_dir)
        if not images:
            print(f"  [{device_id}] No images found, skipping.")
            continue

        # Filter by hour range when requested
        if hour_ranges:
            filtered = [
                img for img in images
                if any(start <= parse_timestamp(img.name).hour < end for start, end in hour_ranges)
            ]
            images = filtered

        windows = build_cascade_windows(images)
        if hour_ranges:
            hour_desc = ",".join(f"{s}-{e}" for s, e in hour_ranges)
            print(f"  [{device_id}] {len(images)} images (hours={hour_desc}) -> {len(windows)} windows")
        else:
            print(f"  [{device_id}] {len(images)} images -> {len(windows)} windows")

        dev_stats = {"windows": 0, "gate_triggered": 0, "infractions": 0, "cost_usd": 0.0}
        prior_had_litter = False
        prior_waste_type: Optional[str] = None
        prev_last_frame: Optional[Path] = None

        for wi, window_paths in enumerate(windows):
            print(
                f"    window {wi+1}/{len(windows)} "
                f"({window_paths[0].name} -> {window_paths[-1].name}, "
                f"{len(window_paths)} frames, prior_litter={prior_had_litter}) ...",
                end=" ",
                flush=True,
            )
            result = run_cascade_window(
                window_paths, device_id, prior_had_litter, prior_waste_type,
                prev_last_frame=prev_last_frame,
            )
            result["run_index"] = run_index
            result["window_index"] = wi

            # Carry forward litter state and last frame for next window
            prior_had_litter = result.pop("_next_prior_had_litter")
            prior_waste_type = result.pop("_next_prior_waste_type")
            prev_last_frame = result.pop("_next_prev_last_frame")

            all_results.append(result)
            total_windows += 1
            dev_stats["windows"] += 1

            status = "INFRACTION" if result["infraction_confirmed"] else ("GATE_PASS" if result["gate_triggered"] else "GATE_REJECT")
            print(f"=> {status}  conf={result['gate_result'].get('confidence_0_100', 'N/A')}  cost=${result['total_cost_usd']:.5f}")

            if result["gate_triggered"]:
                gate_triggered_count += 1
                dev_stats["gate_triggered"] += 1
            if result["infraction_confirmed"]:
                infraction_count += 1
                dev_stats["infractions"] += 1
            total_cost += result["total_cost_usd"]
            dev_stats["cost_usd"] += result["total_cost_usd"]

        per_device[device_id] = dev_stats

    summary = {
        "run_index": run_index,
        "total_windows": total_windows,
        "gate_triggered": gate_triggered_count,
        "gate_trigger_rate_pct": round(100 * gate_triggered_count / max(1, total_windows), 1),
        "infractions_confirmed": infraction_count,
        "stage2_confirmation_rate_pct": round(100 * infraction_count / max(1, gate_triggered_count), 1),
        "total_cost_usd": round(total_cost, 6),
        "per_device": per_device,
    }
    return all_results, summary


def parse_hour_ranges(value: str) -> list[tuple[int, int]]:
    """Parse hour range string like '06-12,14-18' into [(6,12),(14,18)]."""
    ranges = []
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            ranges.append((int(start_s), int(end_s)))
        else:
            h = int(part)
            ranges.append((h, h + 1))
    return ranges


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Gemini cascade pipeline on a dataset.")
    parser.add_argument("--dataset", required=True, type=Path, help="Path to dataset root directory.")
    parser.add_argument("--output", required=True, type=Path, help="Directory to write result files.")
    parser.add_argument("--runs", type=int, default=1, help="Number of times to process the full dataset.")
    parser.add_argument(
        "--hours",
        type=str,
        default=None,
        help="Comma-separated hour ranges to filter images, e.g. '06-12,14-18'. "
             "Uses local timestamps in filenames.",
    )
    args = parser.parse_args()

    hour_ranges = parse_hour_ranges(args.hours) if args.hours else None

    dataset_dir: Path = args.dataset.resolve()
    output_dir: Path = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not config.GEMINI_API_KEY:
        sys.exit("ERROR: GEMINI_API_KEY environment variable is not set.")

    if not dataset_dir.exists():
        sys.exit(f"ERROR: Dataset directory not found: {dataset_dir}")

    ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = output_dir / f"cascade_retest_results_{ts_label}.jsonl"
    summary_path = output_dir / f"cascade_retest_summary_{ts_label}.json"

    all_summaries: list[dict] = []

    print(f"\n=== SAIRA Gemini Cascade Retest ===")
    print(f"Dataset  : {dataset_dir}")
    print(f"Output   : {results_path}")
    print(f"Runs     : {args.runs}")
    print(f"Model    : {config.GEMINI_MODEL}")
    print(f"Threshold: {THRESHOLD} (80 when prior litter known)")
    if hour_ranges:
        print(f"Hours    : {args.hours}")
    print()

    with results_path.open("w", encoding="utf-8") as fh:
        for run_idx in range(1, args.runs + 1):
            print(f"--- Run {run_idx}/{args.runs} ---")
            run_results, run_summary = run_once(dataset_dir, run_idx, hour_ranges=hour_ranges)

            for r in run_results:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()

            all_summaries.append(run_summary)

            print(f"\n  Run {run_idx} summary:")
            print(f"    Windows         : {run_summary['total_windows']}")
            print(f"    Gate triggered  : {run_summary['gate_triggered']} ({run_summary['gate_trigger_rate_pct']}%)")
            print(f"    Infractions conf: {run_summary['infractions_confirmed']} ({run_summary['stage2_confirmation_rate_pct']}% of gate-pass)")
            print(f"    Total cost      : ${run_summary['total_cost_usd']:.4f}")
            print()

            if run_idx < args.runs:
                time.sleep(1)  # small pause between runs

    summary_path.write_text(
        json.dumps({"runs": all_summaries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Aggregate across all runs
    if len(all_summaries) > 1:
        avg_trigger_rate = round(sum(s["gate_trigger_rate_pct"] for s in all_summaries) / len(all_summaries), 1)
        avg_confirmation_rate = round(sum(s["stage2_confirmation_rate_pct"] for s in all_summaries) / len(all_summaries), 1)
        total_cost_all = round(sum(s["total_cost_usd"] for s in all_summaries), 4)
        print("=== Aggregate across all runs ===")
        print(f"  Avg gate trigger rate  : {avg_trigger_rate}%")
        print(f"  Avg confirmation rate  : {avg_confirmation_rate}%")
        print(f"  Total API cost         : ${total_cost_all:.4f}")
        print()

    print(f"Results written to: {results_path}")
    print(f"Summary written to: {summary_path}")


if __name__ == "__main__":
    main()
