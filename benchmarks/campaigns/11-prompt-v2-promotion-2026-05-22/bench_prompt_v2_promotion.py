#!/usr/bin/env python3
"""bench_prompt_v2_promotion.py — Campanha 11 — A/B prompt_version (current vs v2).

Testa se o prompt V2 (com fix carroça aplicado em 2026-05-22) supera o prompt V1
atual em produção no dataset oficial v1, com 5 frames/janela (first + 3 mid + last)
para reproduzir fielmente o pipeline de produção.

2 arms:
- A_current:    prompt_version="current" (V1, em produção)
- B_v2_patched: prompt_version="v2"      (V2 com fix carroça)

Ambos os arms usam thinking_budget=1024 (sweet spot validado) para isolar o efeito
do prompt em si, sem confundir com thinking budget. Modelo Gemini idêntico nos dois.

Adaptado de bench_thinking_ab.py (camp 09). Diferenças:
- Troca thinking_budget por prompt_version no spec do arm.
- ARM_SPECS reflete arms novos.
- Output mantém shape compatível com compute_metrics para reuso.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(r"c:\saira")
WORKER_SRC = PROJECT_ROOT / "services" / "yolo-worker-vm" / "src"
DATASET_ROOT = PROJECT_ROOT / "data" / "datasets" / "official"
CAMPAIGN_DIR = Path(__file__).parent

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if v.startswith("<"):
            continue
        os.environ.setdefault(k.strip(), v)


_load_env_file(CAMPAIGN_DIR / ".env.benchmark")

if not os.environ.get("GEMINI_API_KEY"):
    services_env = PROJECT_ROOT / "services" / ".env.benchmark"
    if services_env.exists():
        for line in services_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == "GEMINI_TEST_API_KEY" and v.strip():
                os.environ["GEMINI_API_KEY"] = v.strip()
                break

if not os.environ.get("GEMINI_API_KEY"):
    print("ERR: GEMINI_API_KEY not set. Provide via .env.benchmark or env var.", file=sys.stderr)
    sys.exit(2)

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://stub@localhost/stub")
os.environ.setdefault("GEMINI_AGENT1_MODEL", "gemini-2.5-flash-lite")
os.environ.setdefault("GEMINI_INPUT_TOKEN_PRICE_PER_1M", "0.10")
os.environ.setdefault("GEMINI_OUTPUT_TOKEN_PRICE_PER_1M", "0.40")


if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from worker import config as worker_config  # noqa: E402
from worker.detector_gemini import analyze_new_litter_with_gemini  # noqa: E402


PRICE_INPUT_PER_1M_USD = float(os.environ["GEMINI_INPUT_TOKEN_PRICE_PER_1M"])
PRICE_OUTPUT_PER_1M_USD = float(os.environ["GEMINI_OUTPUT_TOKEN_PRICE_PER_1M"])
THINKING_BUDGET_BOTH = 1024  # sweet spot validado em project_thinking_budget_validated


CAMERA_CONTEXT = {
    "cam_mangabeira": {
        "camera_name": "ESP32-002 - Mangabeira",
        "logradouro": "Av. Prof. José dos Anjos, 3254",
        "bairro": "Mangabeira",
        "rpa": "RPA 3",
    },
    "cam_imbiribeira": {
        "camera_name": "ESP32-001 - Imbiribeira",
        "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
        "bairro": "Imbiribeira",
        "rpa": "RPA 2",
    },
}


@dataclass
class Window:
    window_id: str
    source: str
    camera: str
    category: str
    first_frame: Path
    last_frame: Path
    mid_frames: list[Path]
    is_positive: bool
    metadata: dict = field(default_factory=dict)


def _sample_mid_frames(frames: list[Path]) -> list[Path]:
    """Pick 3 mid frames at ~25%, 50%, 75% of the index range (exclusive of endpoints).

    Identical helper to camp 09. Windows with <5 frames get no mids (first+last only).
    """
    n = len(frames)
    if n < 5:
        return []
    quarters = [int(n * 0.25), int(n * 0.5), int(n * 0.75)]
    picked = []
    for idx in quarters:
        idx = max(1, min(n - 2, idx))
        if idx not in picked and idx != 0 and idx != n - 1:
            picked.append(idx)
    return [frames[i] for i in picked]


def build_windows_from_manifest(manifest_path: Path) -> list[Window]:
    windows: list[Window] = []
    with manifest_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                frame_count = int(row.get("frame_count") or 0)
            except ValueError:
                continue
            if frame_count < 2:
                continue
            local = DATASET_ROOT / row["local_path"]
            frames_dir = local / "frames"
            if not frames_dir.exists():
                continue
            frames = sorted(frames_dir.glob("*.jpg"))
            if len(frames) < 2:
                continue
            cat = row["category"]
            mids = _sample_mid_frames(frames)
            windows.append(Window(
                window_id=row["event_id"],
                source="event",
                camera=row["camera"],
                category=cat,
                first_frame=frames[0],
                last_frame=frames[-1],
                mid_frames=mids,
                is_positive=cat in ("tp", "missed"),
                metadata={
                    "datetime": row.get("datetime"),
                    "tipo_residuo": row.get("tipo_residuo"),
                    "volumetria": row.get("volumetria"),
                    "justificativa": row.get("justificativa"),
                    "frame_count": frame_count,
                    "classificacao": row.get("classificacao"),
                    "n_mid_frames": len(mids),
                },
            ))
    return windows


def build_baseline_windows(window_size: int = 12, per_series: int | None = None) -> list[Window]:
    windows: list[Window] = []
    for cam in ("cam_mangabeira", "cam_imbiribeira"):
        for period in ("day", "night"):
            period_dir = DATASET_ROOT / cam / "baseline" / period
            if not period_dir.exists():
                continue
            frames = sorted(period_dir.glob("*.jpg"))
            all_starts = list(range(0, len(frames) - window_size + 1, window_size))
            if per_series is not None and per_series < len(all_starts):
                step = len(all_starts) / per_series
                indices = [all_starts[int(i * step)] for i in range(per_series)]
            else:
                indices = all_starts
            for i in indices:
                chunk = frames[i:i + window_size]
                mids = _sample_mid_frames(chunk)
                windows.append(Window(
                    window_id=f"baseline_{cam}_{period}_{i // window_size:03d}",
                    source="baseline",
                    camera=cam,
                    category="baseline",
                    first_frame=chunk[0],
                    last_frame=chunk[-1],
                    mid_frames=mids,
                    is_positive=False,
                    metadata={
                        "period": period,
                        "first_frame_name": chunk[0].name,
                        "last_frame_name": chunk[-1].name,
                        "window_size": window_size,
                        "n_mid_frames": len(mids),
                    },
                ))
    return windows


def run_gate_call(window: Window, prompt_version: str) -> dict:
    """Call Agent-1 gate with the requested prompt version. thinking_budget fixed at 1024."""
    prev_budget = worker_config.GEMINI_AGENT1_THINKING_BUDGET
    worker_config.GEMINI_AGENT1_THINKING_BUDGET = THINKING_BUDGET_BOTH
    try:
        ctx = CAMERA_CONTEXT.get(window.camera, {})
        request_id = f"bench11-{window.window_id[:12]}-{prompt_version}-{uuid.uuid4().hex[:4]}"
        t0 = time.monotonic()
        result = analyze_new_litter_with_gemini(
            first_frame=window.first_frame,
            last_frame=window.last_frame,
            camera_context=ctx,
            request_id=request_id,
            prior_window_context=None,
            use_mosaic=False,
            mid_frames=window.mid_frames if window.mid_frames else None,
            prompt_version=prompt_version,
        )
        wall_ms = int((time.monotonic() - t0) * 1000)
        report = result.report
        usage = result.usage
        billable_output = max(0, usage.total_tokens - usage.input_tokens)
        thinking_tokens = max(0, billable_output - usage.output_tokens)
        cost = ((usage.input_tokens / 1_000_000.0) * PRICE_INPUT_PER_1M_USD
                + (billable_output / 1_000_000.0) * PRICE_OUTPUT_PER_1M_USD)
        # V2-only fields when present.
        flow = getattr(report, "material_flow_direction", None)
        pile = getattr(report, "pile_volume_change", None)
        munic_equip = getattr(report, "municipal_equipment_present", None)
        return {
            "ok": True,
            "prompt_version": prompt_version,
            "thinking_budget": THINKING_BUDGET_BOTH,
            "n_frames_sent": 2 + len(window.mid_frames),
            "confidence": int(report.confidence_0_100),
            "new_litter_detected": bool(report.new_litter_detected),
            "scene_type": getattr(report, "scene_type", "") or "",
            "waste_type": report.waste_type,
            "vehicle_stopped": bool(getattr(report, "vehicle_stopped", False)),
            "person_handling_material": bool(getattr(report, "person_handling_material", False)),
            "new_ground_material": bool(getattr(report, "new_ground_material", False)),
            "material_flow_direction": flow,
            "pile_volume_change": pile,
            "municipal_equipment_present": munic_equip,
            "is_maintenance": bool(getattr(result, "is_maintenance", False)),
            "evidence_summary": (report.evidence_summary or "")[:300],
            "input_tokens": usage.input_tokens,
            "output_visible_tokens": usage.output_tokens,
            "thinking_tokens": thinking_tokens,
            "billable_output_tokens": billable_output,
            "total_tokens": usage.total_tokens,
            "latency_ms": result.latency_ms,
            "wall_ms": wall_ms,
            "cost_usd": round(cost, 8),
            "model": result.model,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "prompt_version": prompt_version,
            "thinking_budget": THINKING_BUDGET_BOTH,
            "n_frames_sent": 2 + len(window.mid_frames),
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        worker_config.GEMINI_AGENT1_THINKING_BUDGET = prev_budget


def _entry_from(window: Window, p1: dict, arm_name: str) -> dict:
    return {
        "arm": arm_name,
        "window_id": window.window_id,
        "source": window.source,
        "camera": window.camera,
        "category": window.category,
        "is_positive": window.is_positive,
        "metadata": window.metadata,
        "pass1": p1,
        "pass2": None,        # shape compat with camp 08/09 metrics
        "escalated": False,
        "final_confidence": p1.get("confidence"),
        "final_new_litter_detected": p1.get("new_litter_detected"),
        "final_ok": p1.get("ok", False),
        "total_cost_usd": p1.get("cost_usd", 0.0) or 0.0,
        "total_latency_ms": p1.get("wall_ms", 0) or 0,
    }


def run_arm(arm_name: str, windows: list[Window], prompt_version: str) -> list[dict]:
    out: list[dict] = []
    for i, w in enumerate(windows, 1):
        if i == 1 or i % 25 == 0 or i == len(windows):
            print(f"  [{arm_name}] {i}/{len(windows)} — {w.window_id[:8]} ({w.category}, "
                  f"{2+len(w.mid_frames)} frames)", flush=True)
        p1 = run_gate_call(w, prompt_version)
        out.append(_entry_from(w, p1, arm_name))
    return out


ARM_SPECS = {
    "A_current":     {"prompt_version": "current", "description": "Prompt V1 atual em produção"},
    "B_v2_patched":  {"prompt_version": "v2",      "description": "Prompt V2 com fix carroça (2026-05-22)"},
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--campaign", type=Path, default=CAMPAIGN_DIR)
    p.add_argument("--arms", default="A_current,B_v2_patched")
    p.add_argument("--limit-events", type=int, default=None,
                   help="Limit number of event windows (smoke-test sized).")
    p.add_argument("--baseline-per-series", type=int, default=None,
                   help="N janelas baseline por (camera, periodo). Total = 4 * N.")
    p.add_argument("--skip-baseline", action="store_true")
    p.add_argument("--smoke-test", action="store_true",
                   help="Run only 1 TP + 1 FP + 1 baseline per arm.")
    args = p.parse_args()

    out_dir = args.campaign.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Campanha: {out_dir}", flush=True)
    print(f"GEMINI_API_KEY: {'set' if os.environ.get('GEMINI_API_KEY') else 'MISSING'}", flush=True)
    print(f"Modelo gate: {worker_config.GEMINI_AGENT1_MODEL}", flush=True)
    print(f"Thinking budget (fixo em ambos arms): {THINKING_BUDGET_BOTH}", flush=True)
    print(f"Pricing USD/1M: input={PRICE_INPUT_PER_1M_USD} output={PRICE_OUTPUT_PER_1M_USD}\n", flush=True)

    print("Construindo janelas (com mid_frames)...", flush=True)
    event_windows = build_windows_from_manifest(DATASET_ROOT / "manifest.csv")
    n_with_mids = sum(1 for w in event_windows if w.mid_frames)
    print(f"  {len(event_windows)} eventos (filtro frame_count>=2); "
          f"{n_with_mids} têm 3 mid_frames; {len(event_windows)-n_with_mids} só first+last", flush=True)

    if args.skip_baseline:
        baseline_windows = []
        print("  (baseline pulado)", flush=True)
    else:
        baseline_windows = build_baseline_windows(window_size=12,
                                                  per_series=args.baseline_per_series)
        n_bw_mids = sum(1 for w in baseline_windows if w.mid_frames)
        print(f"  {len(baseline_windows)} baseline ({args.baseline_per_series or 'all'}/série); "
              f"{n_bw_mids} com mid_frames", flush=True)

    if args.smoke_test:
        tp_one = [w for w in event_windows if w.category == "tp"][:1]
        fp_one = [w for w in event_windows if w.category == "fp"][:1]
        bl_one = baseline_windows[:1]
        all_windows = tp_one + fp_one + bl_one
        print(f"  SMOKE TEST: {len(all_windows)} janelas\n", flush=True)
    else:
        if args.limit_events:
            event_windows = event_windows[:args.limit_events]
        all_windows = event_windows + baseline_windows

    arms_to_run = [a.strip() for a in args.arms.split(",") if a.strip()]
    bad = [a for a in arms_to_run if a not in ARM_SPECS]
    if bad:
        print(f"ERR: arms desconhecidos: {bad}", file=sys.stderr)
        return 2

    print(f"Total: {len(all_windows)} janelas x {len(arms_to_run)} arms = "
          f"{len(all_windows)*len(arms_to_run)} chamadas\n", flush=True)

    summary = []
    for arm in arms_to_run:
        spec = ARM_SPECS[arm]
        print(f"\n=== Arm {arm} — {spec['description']} ===", flush=True)
        t_start = time.monotonic()
        results = run_arm(arm, all_windows, spec["prompt_version"])
        elapsed = time.monotonic() - t_start

        n = len(results)
        n_ok = sum(1 for r in results if r.get("final_ok"))
        cost_total = sum(r["total_cost_usd"] for r in results)
        print(f"  Concluído em {elapsed:.1f}s — final_ok={n_ok}/{n}, "
              f"custo total ${cost_total:.4f}", flush=True)

        out_path = out_dir / f"results-{arm}.json"
        out_path.write_text(json.dumps({
            "arm": arm,
            "spec": spec,
            "n_windows": n,
            "n_ok": n_ok,
            "n_err": n - n_ok,
            "n_escalated": 0,
            "total_cost_usd": round(cost_total, 6),
            "elapsed_seconds": round(elapsed, 1),
            "pricing": {
                "input_per_1m_usd": PRICE_INPUT_PER_1M_USD,
                "output_per_1m_usd": PRICE_OUTPUT_PER_1M_USD,
            },
            "thinking_budget": THINKING_BUDGET_BOTH,
            "windows": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append({
            "arm": arm, "n": n, "n_ok": n_ok, "cost_usd": cost_total,
            "elapsed_s": elapsed,
        })
        print(f"  -> {out_path.name}", flush=True)

    print(f"\n=== Resumo ===", flush=True)
    print(f"{'Arm':14s} {'N':>5s} {'OK':>5s} {'Cost USD':>10s} {'Tempo':>8s}", flush=True)
    for s in summary:
        print(f"{s['arm']:14s} {s['n']:5d} {s['n_ok']:5d} {s['cost_usd']:10.4f} "
              f"{s['elapsed_s']:7.1f}s", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
