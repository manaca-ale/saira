"""Benchmark: compare Agent1 x Agent2 model combinations on real field datasets.

Usage:
    cd services
    python benchmark_models.py

Requires GEMINI_API_KEY set in environment (or services/.env).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
_worker_root = Path(__file__).resolve().parent / "yolo-worker-vm" / "src"
if str(_worker_root) not in sys.path:
    sys.path.insert(0, str(_worker_root))

# Load .env
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

# Suppress YOLO warnings
os.environ.setdefault("AI_MODE", "gemini")
os.environ.setdefault("MOCK_MODE", "false")
os.environ.setdefault("P1_MODEL_PATH", "/dev/null")
os.environ.setdefault("P2_MODEL_PATH", "/dev/null")

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from worker import config  # noqa: E402
from worker.detector_gemini import (  # noqa: E402
    analyze_new_litter_with_gemini,
    analyze_with_gemini,
)

# ---------------------------------------------------------------------------
# Datasets (real field infractions)
# ---------------------------------------------------------------------------
DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "datasets" / "field_cctv"

DATASETS = {
    "ch26": DATA_ROOT / "BOA_VISTA_ch26_20260126124237",
    "ch28": DATA_ROOT / "BOA_VISTA_ch28_20260211092230",
    "ch23": DATA_ROOT / "BOA_VISTA_ch23_20260202101133",
}

# ---------------------------------------------------------------------------
# Model combinations
# ---------------------------------------------------------------------------
COMBINATIONS = [
    ("gemini-2.5-flash-lite", "gemini-2.5-flash-lite", "Lite/Lite"),
    ("gemini-2.5-flash", "gemini-2.5-flash-lite", "Flash/Lite"),
    ("gemini-2.5-flash-lite", "gemini-2.5-flash", "Lite/Flash"),
    ("gemini-2.5-flash", "gemini-2.5-flash", "Flash/Flash"),
]

# Pricing per 1M tokens (USD)
PRICING = {
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}

USD_TO_BRL = 5.70


def get_sorted_frames(dataset_dir: Path) -> list[Path]:
    frames = sorted(dataset_dir.glob("*.jpg"))
    if not frames:
        raise FileNotFoundError(f"No .jpg frames in {dataset_dir}")
    return frames


def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICING[model]
    return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]


def run_agent1(first_frame: Path, last_frame: Path, model: str, dataset_name: str) -> dict:
    original = config.GEMINI_AGENT1_MODEL
    config.GEMINI_AGENT1_MODEL = model
    try:
        result = analyze_new_litter_with_gemini(
            first_frame=first_frame,
            last_frame=last_frame,
            camera_context={"location": "Boa Vista, Recife", "type": "CCTV"},
            request_id=f"bench-ag1-{dataset_name}-{model}",
            use_mosaic=False,
        )
        cost = calc_cost(model, result.usage.input_tokens, result.usage.output_tokens)
        return {
            "model": model,
            "dataset": dataset_name,
            "triggered": result.report.new_litter_detected,
            "confidence": result.report.confidence_0_100,
            "evidence": result.report.evidence_summary,
            "waste_type": result.report.waste_type,
            "scene_delta": result.report.scene_delta_analysis[:200] if result.report.scene_delta_analysis else "",
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
            "latency_ms": result.latency_ms,
            "cost_usd": round(cost, 6),
            "cost_brl": round(cost * USD_TO_BRL, 4),
            "error": None,
        }
    except Exception as e:
        return {
            "model": model, "dataset": dataset_name,
            "triggered": None, "confidence": None, "evidence": str(e),
            "waste_type": None, "scene_delta": "",
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "latency_ms": 0, "cost_usd": 0, "cost_brl": 0, "error": str(e),
        }
    finally:
        config.GEMINI_AGENT1_MODEL = original


def run_agent2(frames: list[Path], model: str, dataset_name: str) -> dict:
    original = config.GEMINI_MODEL
    config.GEMINI_MODEL = model
    send_frames = frames[:12]
    try:
        result = analyze_with_gemini(
            image_paths=send_frames,
            camera_context={"location": "Boa Vista, Recife", "type": "CCTV"},
            request_id=f"bench-ag2-{dataset_name}-{model}",
            mosaic_mode="off",
        )
        cost = calc_cost(model, result.usage.input_tokens, result.usage.output_tokens)
        return {
            "model": model,
            "dataset": dataset_name,
            "infraction_confirmed": result.report.infraction_confirmed,
            "confidence": result.report.confidence_0_100,
            "evidence": result.report.evidence_summary,
            "waste_type": result.report.waste_type,
            "offender_detected": result.report.offender_detected,
            "volume_m3": result.report.volume_m3,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
            "latency_ms": result.latency_ms,
            "cost_usd": round(cost, 6),
            "cost_brl": round(cost * USD_TO_BRL, 4),
            "error": None,
        }
    except Exception as e:
        return {
            "model": model, "dataset": dataset_name,
            "infraction_confirmed": None, "confidence": None, "evidence": str(e),
            "waste_type": None, "offender_detected": None, "volume_m3": None,
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "latency_ms": 0, "cost_usd": 0, "cost_brl": 0, "error": str(e),
        }
    finally:
        config.GEMINI_MODEL = original


def main():
    print("=" * 80)
    print("SAIRA Model Benchmark - Agent1 x Agent2 on field datasets")
    print("=" * 80)

    all_results = []

    for ag1_model, ag2_model, combo_name in COMBINATIONS:
        print(f"\n{'-' * 70}")
        print(f"  COMBO: {combo_name}  (Ag1={ag1_model}, Ag2={ag2_model})")
        print(f"{'-' * 70}")

        combo_cost_usd = 0.0
        combo_latency_ms = 0

        for ds_name, ds_path in DATASETS.items():
            frames = get_sorted_frames(ds_path)
            print(f"\n  [{ds_name}] {len(frames)} frames - {ds_path.name}")

            # Agent 1: gate (first vs last frame)
            print(f"    Agent 1 ({ag1_model})...", end=" ", flush=True)
            ag1 = run_agent1(frames[0], frames[-1], ag1_model, ds_name)
            if ag1["error"]:
                print(f"ERROR: {ag1['error'][:100]}")
            else:
                print(
                    f"triggered={ag1['triggered']}  conf={ag1['confidence']}  "
                    f"lat={ag1['latency_ms']}ms  cost=R${ag1['cost_brl']}"
                )
                print(f"      tokens: in={ag1['input_tokens']} out={ag1['output_tokens']} total={ag1['total_tokens']}")
                ev = (ag1['evidence'] or '')[:120]
                print(f"      evidence: {ev}")

            combo_cost_usd += ag1["cost_usd"]
            combo_latency_ms += ag1["latency_ms"]

            # Agent 2: detail (all frames, max 12)
            print(f"    Agent 2 ({ag2_model})...", end=" ", flush=True)
            ag2 = run_agent2(frames, ag2_model, ds_name)
            if ag2["error"]:
                print(f"ERROR: {ag2['error'][:100]}")
            else:
                print(
                    f"infraction={ag2['infraction_confirmed']}  conf={ag2['confidence']}  "
                    f"lat={ag2['latency_ms']}ms  cost=R${ag2['cost_brl']}"
                )
                print(f"      tokens: in={ag2['input_tokens']} out={ag2['output_tokens']} total={ag2['total_tokens']}")
                print(f"      waste={ag2['waste_type']}  offender={ag2['offender_detected']}  vol={ag2['volume_m3']}m3")
                ev = (ag2['evidence'] or '')[:120]
                print(f"      evidence: {ev}")

            combo_cost_usd += ag2["cost_usd"]
            combo_latency_ms += ag2["latency_ms"]

            all_results.append({"combo": combo_name, "ag1": ag1, "ag2": ag2})

        combo_cost_brl = combo_cost_usd * USD_TO_BRL
        print(f"\n  COMBO TOTAL: R${combo_cost_brl:.4f}  ({combo_latency_ms}ms)")

    # -----------------------------------------------------------------------
    # Summary table
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SUMMARY TABLE")
    print("=" * 80)

    print(f"\n{'Combo':<14} {'DS':<5} {'Ag1':<6} {'Ag1Conf':<8} {'Ag2':<6} {'Ag2Conf':<8} "
          f"{'Ag1Lat':<8} {'Ag2Lat':<8} {'Ag1 R$':<9} {'Ag2 R$':<9} {'Tot R$':<9}")
    print("-" * 100)

    combo_totals: dict[str, dict] = {}

    for r in all_results:
        combo = r["combo"]
        ds = r["ag1"]["dataset"]
        ag1_trig = r["ag1"]["triggered"]
        ag2_infr = r["ag2"].get("infraction_confirmed")
        ag1_conf = r["ag1"]["confidence"]
        ag2_conf = r["ag2"]["confidence"]
        ag1_lat = r["ag1"]["latency_ms"]
        ag2_lat = r["ag2"]["latency_ms"]
        ag1_brl = r["ag1"]["cost_brl"]
        ag2_brl = r["ag2"]["cost_brl"]
        total_brl = ag1_brl + ag2_brl

        ag1_mark = "OK" if ag1_trig else "MISS"
        ag2_mark = "OK" if ag2_infr else "MISS"

        print(f"{combo:<14} {ds:<5} {ag1_mark:<6} {str(ag1_conf):<8} {ag2_mark:<6} {str(ag2_conf):<8} "
              f"{str(ag1_lat):<8} {str(ag2_lat):<8} {ag1_brl:<9.4f} {ag2_brl:<9.4f} {total_brl:<9.4f}")

        if combo not in combo_totals:
            combo_totals[combo] = {
                "ag1_correct": 0, "ag2_correct": 0, "total_tests": 0,
                "ag1_cost": 0.0, "ag2_cost": 0.0,
                "ag1_latency": 0, "ag2_latency": 0,
                "ag1_tokens_in": 0, "ag1_tokens_out": 0,
                "ag2_tokens_in": 0, "ag2_tokens_out": 0,
            }
        ct = combo_totals[combo]
        ct["total_tests"] += 1
        ct["ag1_correct"] += 1 if ag1_trig else 0
        ct["ag2_correct"] += 1 if ag2_infr else 0
        ct["ag1_cost"] += ag1_brl
        ct["ag2_cost"] += ag2_brl
        ct["ag1_latency"] += ag1_lat
        ct["ag2_latency"] += ag2_lat
        ct["ag1_tokens_in"] += r["ag1"]["input_tokens"]
        ct["ag1_tokens_out"] += r["ag1"]["output_tokens"]
        ct["ag2_tokens_in"] += r["ag2"]["input_tokens"]
        ct["ag2_tokens_out"] += r["ag2"]["output_tokens"]

    print("\n" + "=" * 80)
    print("TOTALS PER COMBINATION (3 datasets, all REAL infractions)")
    print("=" * 80)
    print(f"\n{'Combo':<14} {'Ag1Acc':<8} {'Ag2Acc':<8} {'Ag1AvgLat':<10} {'Ag2AvgLat':<10} "
          f"{'TotCost':<10} {'Ag1Tok':<14} {'Ag2Tok':<14}")
    print("-" * 92)

    for combo, ct in combo_totals.items():
        n = ct["total_tests"]
        ag1_acc = ct["ag1_correct"] / n * 100
        ag2_acc = ct["ag2_correct"] / n * 100
        ag1_avg_lat = ct["ag1_latency"] // n
        ag2_avg_lat = ct["ag2_latency"] // n
        total_cost = ct["ag1_cost"] + ct["ag2_cost"]
        ag1_tok = f"{ct['ag1_tokens_in']}/{ct['ag1_tokens_out']}"
        ag2_tok = f"{ct['ag2_tokens_in']}/{ct['ag2_tokens_out']}"
        print(f"{combo:<14} {ag1_acc:.0f}%     {ag2_acc:.0f}%     {ag1_avg_lat}ms       {ag2_avg_lat}ms       "
              f"R${total_cost:<8.4f} {ag1_tok:<14} {ag2_tok:<14}")

    # Save JSON
    output_path = Path(__file__).resolve().parent / "benchmark_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nDetailed results saved to: {output_path}")


if __name__ == "__main__":
    main()
