"""Benchmark A/B: Run Agent 1 (gate) with NEW prompt on multiple datasets.

Compares results against stored baseline (benchmark_lite_lite_full_results.json).
Runs ONLY Agent 1 (gate) to save cost — Agent 2 is not invoked.

Usage:
    cd services
    python benchmark_gate_ab.py                          # all datasets
    python benchmark_gate_ab.py --dataset field_cctv     # only field_cctv
    python benchmark_gate_ab.py --dataset fp_test_server # only FPs
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
# Force Lite/Lite (same as production test server)
os.environ["GEMINI_MODEL"] = "gemini-2.5-flash-lite"
os.environ["GEMINI_AGENT1_MODEL"] = "gemini-2.5-flash-lite"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from worker import config  # noqa: E402
from worker.detector_gemini import (  # noqa: E402
    analyze_new_litter_with_gemini,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "datasets"
WINDOW_SECONDS = 120
MAX_FRAMES = 12
MIN_FRAMES = 2
GATE_CONFIDENCE_THRESHOLD = int(os.getenv("GATE_THRESHOLD_OVERRIDE", str(config.GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE)))

INPUT_PRICE = 0.10
OUTPUT_PRICE = 0.40
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
            "scene_type": getattr(r, "scene_type", ""),
            "vehicle_stopped": bool(getattr(r, "vehicle_stopped", False)),
            "person_handling_material": bool(getattr(r, "person_handling_material", False)),
            "new_ground_material": bool(getattr(r, "new_ground_material", False)),
            "evidence": r.evidence_summary,
            "waste_type": r.waste_type,
            "scene_delta": (r.scene_delta_analysis or "")[:300],
            "first_has_litter": bool(r.first_frame_has_litter),
            "last_has_litter": bool(r.last_frame_has_litter),
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "latency_ms": result.latency_ms,
            "cost_usd": round(cost, 6),
            "error": None,
        }
    except Exception as e:
        return {
            "new_litter_detected": None, "confidence": None,
            "evidence": None, "waste_type": None, "scene_delta": "",
            "first_has_litter": None, "last_has_litter": None,
            "input_tokens": 0, "output_tokens": 0,
            "latency_ms": 0, "cost_usd": 0, "error": str(e),
        }


def process_dataset_group(group_name: str, group_path: Path) -> dict:
    """Process all datasets in a group directory (e.g. field_cctv/ or fp_test_server/)."""
    datasets = sorted([
        d for d in group_path.iterdir()
        if d.is_dir() and any(d.glob("*.jpg"))
    ], key=lambda d: d.name)

    if not datasets:
        print(f"  No datasets with .jpg files found in {group_path}")
        return {"group": group_name, "datasets": [], "totals": {}}

    print(f"\n{'=' * 80}")
    print(f"GROUP: {group_name} ({len(datasets)} datasets)")
    print(f"{'=' * 80}")

    all_ds_results = []
    totals = {
        "total_windows": 0, "gate_triggered": 0,
        "cost_usd": 0.0, "latency_ms": 0,
        "tokens_in": 0, "tokens_out": 0, "errors": 0,
    }

    for ds_path in datasets:
        ds_name = ds_path.name
        frames = get_sorted_frames(ds_path)
        windows = build_windows(frames)

        if not windows:
            print(f"  [{ds_name}] {len(frames)} frames -> 0 windows (skipped)")
            continue

        print(f"\n  [{ds_name}] {len(frames)} frames -> {len(windows)} windows")

        ds_stats = {
            "dataset": ds_name, "total_frames": len(frames),
            "total_windows": len(windows), "gate_triggered": 0,
            "cost_usd": 0.0, "windows": [],
        }

        prior_had_litter = False
        prior_waste_type: Optional[str] = None
        prev_last_frame: Optional[Path] = None

        for wi, window in enumerate(windows):
            first_frame = prev_last_frame if prev_last_frame and prev_last_frame.exists() else window[0]
            last_frame = window[-1]

            prior_ctx: Optional[str] = None
            if prior_had_litter:
                waste_label = f" (type: {prior_waste_type})" if prior_waste_type else ""
                prior_ctx = (
                    f"- Previous window ALREADY had waste at this location{waste_label}. "
                    "Confirm NEW_SOLID_WASTE only if a NEW object appeared or volume visibly increased."
                )

            effective_threshold = max(GATE_CONFIDENCE_THRESHOLD, 80) if prior_had_litter else GATE_CONFIDENCE_THRESHOLD
            camera_ctx = {"camera_name": ds_name, "horario_local": parse_timestamp(last_frame.name).strftime("%H:%M")}

            # Mid-frame selection
            mid_frames: Optional[list[Path]] = None
            wn = len(window)
            if wn >= 5:
                mid_frames = [window[wn // 4], window[wn // 2], window[3 * wn // 4]]
            elif wn >= 4:
                mid_frames = [window[wn // 2]]

            n_gate = 2 + (len(mid_frames) if mid_frames else 0)
            print(f"    W{wi+1}/{len(windows)} ({len(window)}fr, gate={n_gate}fr) ", end="", flush=True)

            gate = run_gate(first_frame, last_frame, camera_ctx, prior_ctx,
                            f"{group_name}-{ds_name}-w{wi}", mid_frames=mid_frames)

            if gate["error"]:
                print(f"ERROR: {gate['error'][:50]}")
                totals["errors"] += 1
                prev_last_frame = last_frame
                prior_had_litter = False
                ds_stats["windows"].append({"window": wi, "gate": gate, "triggered": False})
                continue

            triggered = bool(gate["new_litter_detected"]) and gate["confidence"] >= effective_threshold

            # Update state
            prior_had_litter = bool(gate.get("last_has_litter"))
            prior_waste_type = gate.get("waste_type")
            prev_last_frame = last_frame

            # Accumulate
            totals["total_windows"] += 1
            totals["cost_usd"] += gate["cost_usd"]
            totals["latency_ms"] += gate["latency_ms"]
            totals["tokens_in"] += gate["input_tokens"]
            totals["tokens_out"] += gate["output_tokens"]

            if triggered:
                totals["gate_triggered"] += 1
                ds_stats["gate_triggered"] += 1
                print(f"TRIGGER(det={gate['new_litter_detected']}, conf={gate['confidence']}, thr={effective_threshold})")
            else:
                litter = "+" if gate.get("last_has_litter") else "-"
                print(f"REJECT(det={gate['new_litter_detected']}, conf={gate['confidence']}, litter={litter})")

            ds_stats["cost_usd"] += gate["cost_usd"]
            ds_stats["windows"].append({"window": wi, "gate": gate, "triggered": triggered})

        ds_cost_brl = ds_stats["cost_usd"] * USD_TO_BRL
        print(f"    >> {ds_name}: {ds_stats['gate_triggered']}/{len(windows)} triggered, R${ds_cost_brl:.4f}")
        all_ds_results.append(ds_stats)

    return {"group": group_name, "datasets": all_ds_results, "totals": totals}


def load_baseline() -> Optional[dict]:
    baseline_path = Path(__file__).resolve().parent / "benchmark_lite_lite_full_results.json"
    if not baseline_path.exists():
        return None
    with open(baseline_path, encoding="utf-8") as f:
        return json.load(f)


def print_comparison(results: list[dict], baseline: Optional[dict]):
    print("\n" + "=" * 90)
    print("COMPARISON: NEW PROMPT vs BASELINE")
    print("=" * 90)

    # Build baseline lookup
    baseline_ds = {}
    if baseline:
        for ds in baseline.get("datasets", []):
            baseline_ds[ds["dataset"]] = ds

    print(f"\n{'Dataset':<40} {'B-Win':<6} {'B-Trig':<7} {'N-Win':<6} {'N-Trig':<7} {'Delta':<8}")
    print("-" * 80)

    total_b_win, total_b_trig = 0, 0
    total_n_win, total_n_trig = 0, 0

    for group in results:
        group_name = group["group"]
        print(f"\n  -- {group_name} --")
        for ds in group["datasets"]:
            ds_name = ds["dataset"]
            n_win = ds["total_windows"]
            n_trig = ds["gate_triggered"]

            bl = baseline_ds.get(ds_name, {})
            b_win = bl.get("total_windows", "-")
            b_trig = bl.get("gate_triggered", "-")

            if isinstance(b_trig, int):
                delta = n_trig - b_trig
                delta_str = f"{delta:+d}"
                total_b_win += b_win
                total_b_trig += b_trig
            else:
                delta_str = "new"

            total_n_win += n_win
            total_n_trig += n_trig

            print(f"  {ds_name:<38} {str(b_win):<6} {str(b_trig):<7} {n_win:<6} {n_trig:<7} {delta_str:<8}")

    print(f"\n{'TOTAL':<40} {total_b_win:<6} {total_b_trig:<7} {total_n_win:<6} {total_n_trig:<7} {total_n_trig - total_b_trig:+d}")

    # Cost summary
    total_cost = sum(g["totals"].get("cost_usd", 0) for g in results)
    total_cost_brl = total_cost * USD_TO_BRL
    total_windows = sum(g["totals"].get("total_windows", 0) for g in results)
    print(f"\nTotal cost: ${total_cost:.4f} (R${total_cost_brl:.4f}) | "
          f"Avg: R${total_cost_brl/max(1, total_windows):.4f}/window")


def main():
    parser = argparse.ArgumentParser(description="Benchmark A/B: gate-only with new prompt")
    parser.add_argument("--dataset", choices=["field_cctv", "fp_test_server", "all"], default="all")
    parser.add_argument("--threshold", type=int, default=None, help="Override gate confidence threshold")
    args = parser.parse_args()

    if args.threshold is not None:
        global GATE_CONFIDENCE_THRESHOLD
        GATE_CONFIDENCE_THRESHOLD = args.threshold

    print("=" * 90)
    print("SAIRA Benchmark A/B - Gate Only (NEW prompt)")
    print(f"Model: {config.GEMINI_AGENT1_MODEL}")
    print(f"Threshold: {GATE_CONFIDENCE_THRESHOLD}")
    print("=" * 90)

    groups_to_run = []
    if args.dataset in ("field_cctv", "all"):
        p = DATA_ROOT / "field_cctv"
        if p.exists():
            groups_to_run.append(("field_cctv", p))
    if args.dataset in ("fp_test_server", "all"):
        p = DATA_ROOT / "fp_test_server"
        if p.exists():
            groups_to_run.append(("fp_test_server", p))

    all_results = []
    for group_name, group_path in groups_to_run:
        result = process_dataset_group(group_name, group_path)
        all_results.append(result)

    baseline = load_baseline()
    print_comparison(all_results, baseline)

    # Save results
    output_path = Path(__file__).resolve().parent / "benchmark_gate_ab_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "threshold": GATE_CONFIDENCE_THRESHOLD,
            "model": config.GEMINI_AGENT1_MODEL,
            "groups": all_results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
