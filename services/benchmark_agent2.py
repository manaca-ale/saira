"""Run Agent 2 on triggered windows of each field_cctv dataset.

Tries ALL triggered windows per dataset, stops at first confirmed.
For datasets with no confirmed window, reports the best rejected result.

Usage:
    cd services
    python benchmark_agent2.py
    python benchmark_agent2.py --only-missing   # skip already confirmed datasets
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

# Bootstrap
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

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from worker import config  # noqa: E402
from worker.detector_gemini import analyze_with_gemini  # noqa: E402

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "datasets" / "field_cctv"
WINDOW_SECONDS = 120
MAX_FRAMES = 12
MIN_FRAMES = 2

INPUT_PRICE = 0.30   # flash (not lite)
OUTPUT_PRICE = 2.50
USD_TO_BRL = 5.70

# Datasets already confirmed in previous run — skip with --only-missing
ALREADY_CONFIRMED: set[str] = set()


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
        if current and ((ts - window_start).total_seconds() >= WINDOW_SECONDS or len(current) >= MAX_FRAMES):
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


def run_agent2(window_frames: list[Path], ds_name: str, window_idx: int) -> dict:
    """Run Agent 2 on a window and return results."""
    camera_ctx = {
        "camera_name": ds_name,
        "horario_local": parse_timestamp(window_frames[-1].name).strftime("%H:%M"),
    }
    request_id = f"agent2-{ds_name}-w{window_idx}"

    try:
        result = analyze_with_gemini(
            image_paths=window_frames,
            camera_context=camera_ctx,
            request_id=request_id,
        )
        r = result.report
        cost = (result.usage.input_tokens / 1_000_000) * INPUT_PRICE + \
               (result.usage.output_tokens / 1_000_000) * OUTPUT_PRICE
        return {
            "infraction_confirmed": bool(r.infraction_confirmed),
            "confidence": int(r.confidence_0_100),
            "baseline_description": getattr(r, "baseline_description", ""),
            "evidence": r.evidence_summary,
            "event_frame_name": r.event_frame_name,
            "offender_frame_name": r.offender_frame_name,
            "waste_type": r.waste_type,
            "waste_bbox": getattr(r, "waste_bbox", None),
            "offender_bbox": getattr(r, "offender_bbox", None),
            "offender_detected": bool(r.offender_detected),
            "offender_types": r.offender_types,
            "vehicle_plate": r.vehicle_plate,
            "vehicle_color": r.vehicle_color,
            "vehicle_model": r.vehicle_model,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "latency_ms": result.latency_ms,
            "cost_usd": round(cost, 6),
            "error": None,
        }
    except Exception as e:
        return {
            "infraction_confirmed": None, "confidence": None,
            "evidence": None, "event_frame_name": None,
            "offender_frame_name": None, "waste_type": None,
            "offender_detected": None, "offender_types": None,
            "vehicle_plate": None, "vehicle_color": None,
            "vehicle_model": None,
            "input_tokens": 0, "output_tokens": 0,
            "latency_ms": 0, "cost_usd": 0, "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-missing", action="store_true",
                        help="Skip datasets already confirmed in previous run")
    args = parser.parse_args()

    # Load gate benchmark results to find triggered windows
    gate_results_path = Path(__file__).resolve().parent / "benchmark_gate_ab_results.json"
    if not gate_results_path.exists():
        print("ERROR: Run benchmark_gate_ab.py --dataset field_cctv first")
        return

    with open(gate_results_path, encoding="utf-8") as f:
        gate_data = json.load(f)

    # Find ALL triggered windows per dataset
    triggered_map: dict[str, list[int]] = {}
    for group in gate_data.get("groups", []):
        if group["group"] != "field_cctv":
            continue
        for ds in group["datasets"]:
            windows = [w["window"] for w in ds["windows"] if w["triggered"]]
            if windows:
                triggered_map[ds["dataset"]] = windows

    if args.only_missing:
        triggered_map = {k: v for k, v in triggered_map.items() if k not in ALREADY_CONFIRMED}

    if not triggered_map:
        print("No datasets to process")
        return

    print("=" * 90)
    print(f"Agent 2 (Full Analysis) — {len(triggered_map)} datasets")
    print(f"Model: {config.GEMINI_MODEL} | Timeout: {config.GEMINI_TIMEOUT_SECONDS}s")
    print(f"Max payload: {config.GEMINI_MAX_PAYLOAD_BYTES / 1_000_000:.0f}MB")
    print("=" * 90)

    total_cost = 0.0
    results = []

    for ds_name, triggered_windows in sorted(triggered_map.items()):
        ds_path = DATA_ROOT / ds_name
        if not ds_path.exists():
            print(f"\n  [{ds_name}] Directory not found, skipping")
            continue

        frames = get_sorted_frames(ds_path)
        windows = build_windows(frames)
        print(f"\n  [{ds_name}] {len(triggered_windows)} triggered windows: {[w+1 for w in triggered_windows]}")

        best_result = None

        for wi in triggered_windows:
            if wi >= len(windows):
                continue

            window_frames = windows[wi]
            print(f"    W{wi+1}/{len(windows)} ({len(window_frames)} frames)...", end=" ", flush=True)

            result = run_agent2(window_frames, ds_name, wi)
            result["dataset"] = ds_name
            result["window"] = wi
            total_cost += result.get("cost_usd", 0)

            if result["error"]:
                print(f"ERROR: {result['error'][:80]}")
                if best_result is None:
                    best_result = result
                continue

            confirmed = "CONFIRMED" if result["infraction_confirmed"] else "REJECTED"
            cost_brl = result["cost_usd"] * USD_TO_BRL
            print(f"{confirmed} (conf={result['confidence']})")
            print(f"      Event frame:    {result['event_frame_name']}")
            print(f"      Offender frame: {result['offender_frame_name']}")
            print(f"      Waste type:     {result['waste_type']}")
            print(f"      Offender:       {result['offender_detected']} {result['offender_types'] or ''}")
            print(f"      Vehicle:        {result['vehicle_color']} {result['vehicle_model']} plate={result['vehicle_plate']}")
            print(f"      Waste bbox:     {result.get('waste_bbox')}")
            print(f"      Offender bbox:  {result.get('offender_bbox')}")
            print(f"      Baseline:       {(result.get('baseline_description') or '')[:150]}")
            print(f"      Evidence:       {result['evidence'][:200]}")
            print(f"      Cost:           R${cost_brl:.4f} ({result['latency_ms']}ms)")

            if result["infraction_confirmed"]:
                best_result = result
                break  # found confirmation, stop trying more windows
            elif best_result is None or best_result.get("error"):
                best_result = result

        if best_result:
            results.append(best_result)

    # Summary
    print(f"\n{'=' * 90}")
    print("SUMMARY")
    print(f"{'=' * 90}")
    confirmed = sum(1 for r in results if r.get("infraction_confirmed"))
    rejected = sum(1 for r in results if r.get("infraction_confirmed") is False)
    errors = sum(1 for r in results if r.get("infraction_confirmed") is None)
    total_brl = total_cost * USD_TO_BRL

    print(f"  Datasets:  {len(results)}")
    print(f"  Confirmed: {confirmed}")
    print(f"  Rejected:  {rejected}")
    print(f"  Errors:    {errors}")
    print(f"  Total cost: ${total_cost:.4f} (R${total_brl:.4f})")

    # Per-dataset summary table
    print(f"\n  {'Dataset':<45} {'Result':<12} {'Event Frame':<30} {'Vehicle'}")
    print(f"  {'-'*120}")
    for r in results:
        status = "CONFIRMED" if r.get("infraction_confirmed") else ("REJECTED" if r.get("infraction_confirmed") is False else "ERROR")
        ef = r.get("event_frame_name") or "-"
        vehicle = f"{r.get('vehicle_color') or ''} {r.get('vehicle_model') or ''} {r.get('vehicle_plate') or ''}".strip() or "-"
        print(f"  {r['dataset']:<45} {status:<12} {ef:<30} {vehicle}")

    # Save
    out_path = Path(__file__).resolve().parent / "benchmark_agent2_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"model": config.GEMINI_MODEL, "results": results}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  Results saved to: {out_path}")


if __name__ == "__main__":
    main()
