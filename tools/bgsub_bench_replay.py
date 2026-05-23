#!/usr/bin/env python3
"""Bench replay — uses worker.bgsub_filter.evaluate() in-process against the
official dataset to confirm the integration reproduces the spike numbers.

Custo: zero (sem Gemini). Roda só OpenCV + lógica determinística.

Espera-se (do spike v1 com threshold=1000):
- TP keep: 100% (14/14)
- Baseline supr: 73% (44/60)

Pré-requisitos:
- Modelos calibrados em STATE_DIR/bgsub_models/esp32_{001,002}.npz
- Variáveis de ambiente: STATE_DIR, BGSUB_PREFILTER_ENABLED=true (este script
  monkey-patches diretamente, não precisa de env)
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(r"c:\saira")
WORKER_SRC = PROJECT_ROOT / "services" / "yolo-worker-vm" / "src"
DATASET = PROJECT_ROOT / "data" / "datasets" / "official"

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Force STATE_DIR so config picks up the calibrated models from .tmp/state.
os.environ.setdefault("STATE_DIR", str(PROJECT_ROOT / ".tmp" / "state"))
os.environ["BGSUB_PREFILTER_ENABLED"] = "true"

if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from worker import bgsub_filter, config  # noqa: E402

# Polygons (matching spike + DB seed)
POLYGONS = {
    "cam_imbiribeira": [
        [[40, 280], [560, 280], [560, 720], [40, 720]],
        [[800, 280], [1240, 280], [1240, 720], [800, 720]],
    ],
    "cam_mangabeira": [
        [[480, 60], [920, 60], [920, 340], [480, 340]],
    ],
}

DEVICE_ID = {"cam_imbiribeira": "esp32_001", "cam_mangabeira": "esp32_002"}


def sample_frames(frames_dir: Path) -> list[Path]:
    """Same sampling as worker (first + 3 mid + last for N >= 5)."""
    all_frames = sorted(frames_dir.glob("*.jpg"))
    if len(all_frames) < 2:
        return all_frames
    if len(all_frames) < 5:
        return [all_frames[0], all_frames[-1]]
    n = len(all_frames)
    indices = sorted({0, n // 4, n // 2, 3 * n // 4, n - 1})
    return [all_frames[i] for i in indices]


def build_baseline_windows(camera: str, window_size: int = 12, per_series: int = 15):
    out = []
    for period in ("day", "night"):
        period_dir = DATASET / camera / "baseline" / period
        if not period_dir.exists():
            continue
        frames = sorted(period_dir.glob("*.jpg"))
        all_starts = list(range(0, len(frames) - window_size + 1, window_size))
        step = len(all_starts) / per_series if per_series < len(all_starts) else 1
        indices = [all_starts[int(i * step)] for i in range(per_series)] if per_series < len(all_starts) else all_starts
        for i, idx in enumerate(indices):
            window_frames = frames[idx:idx + window_size]
            out.append((f"baseline_{camera}_{period}_{i:03d}", camera, "baseline", window_frames, ""))
    return out


def main() -> int:
    print(f"Bench replay — STATE_DIR={config.BGSUB_MODELS_DIR}")
    print(f"  BGSUB_PREFILTER_ENABLED={config.BGSUB_PREFILTER_ENABLED}")
    print(f"  threshold={config.BGSUB_PERSISTENCE_THRESHOLD}\n")

    # Carrega manifest
    rows = []
    with (DATASET / "manifest.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)

    # Build all windows: events + baseline
    windows = []  # (id, camera, category, frame_paths, justificativa)
    for r in rows:
        frames_dir = DATASET / r["local_path"] / "frames"
        if not frames_dir.exists():
            continue
        frames = sample_frames(frames_dir)
        if len(frames) < 2:
            continue
        windows.append((r["event_id"], r["camera"], r["category"], frames, r.get("justificativa") or ""))

    for camera in ("cam_imbiribeira", "cam_mangabeira"):
        windows.extend(build_baseline_windows(camera))

    poda_keywords = ["retirando", "coleta", "caminhão", "poda", "limpeza", "limpando"]
    def is_focus_fp(j: str) -> bool:
        return not any(k in j.lower() for k in poda_keywords)

    # Evaluate each window via worker.bgsub_filter
    results = []  # (id, camera, category, focus, reason, should_suppress, persistence)
    print(f"Evaluating {len(windows)} windows...", flush=True)
    for i, (wid, camera, category, frame_paths, justif) in enumerate(windows, 1):
        if i % 50 == 0:
            print(f"  {i}/{len(windows)}", flush=True)
        polygon = POLYGONS.get(camera)
        device_id = DEVICE_ID.get(camera, "unknown")
        result = bgsub_filter.evaluate(
            frame_paths=frame_paths,
            device_id=device_id,
            pile_zone_polygon=polygon,
        )
        focus = is_focus_fp(justif) if category == "fp" else False
        results.append((wid, camera, category, focus, result.reason, result.should_suppress, result.persistence))

    # Aggregate
    cats = {
        "tp": [r for r in results if r[2] == "tp"],
        "missed": [r for r in results if r[2] == "missed"],
        "fp_focus": [r for r in results if r[2] == "fp" and r[3]],
        "fp_poda": [r for r in results if r[2] == "fp" and not r[3]],
        "indef": [r for r in results if r[2] == "indefinido"],
        "baseline": [r for r in results if r[2] == "baseline"],
    }

    print(f"\n=== Resultados ===\n")
    print(f"{'categoria':12s} | {'N':>3s} | {'kept':>5s} | {'suppressed':>10s} | %supr")
    print("-" * 60)
    for name, items in cats.items():
        suppressed = sum(1 for r in items if r[5])
        kept = len(items) - suppressed
        pct = (suppressed / len(items) * 100) if items else 0
        print(f"{name:12s} | {len(items):3d} | {kept:5d} | {suppressed:10d} | {pct:.1f}%")

    # Save CSV
    out_csv = PROJECT_ROOT / "tools" / "spike_bgsub_output" / "bench_replay.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "camera", "category", "is_focus_fp", "reason",
                    "should_suppress", "persistence"])
        for r in results:
            w.writerow(r)
    print(f"\n  → {out_csv}")

    # Sanity check
    tp_kept = sum(1 for r in cats["tp"] if not r[5])
    baseline_supr = sum(1 for r in cats["baseline"] if r[5])
    print(f"\n=== Critério de aceitação (do spike) ===")
    print(f"  TP keep: {tp_kept}/{len(cats['tp'])} ({tp_kept/max(1,len(cats['tp']))*100:.0f}%) — esperado 100%")
    print(f"  Baseline supr: {baseline_supr}/{len(cats['baseline'])} ({baseline_supr/max(1,len(cats['baseline']))*100:.0f}%) — esperado ~73%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
