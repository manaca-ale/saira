#!/usr/bin/env python3
"""Campaign 19 — pile-crop arm.

Tests the user's idea: focus Agent-1 on the pile zone. We crop every frame to the
esp32_002 pile polygon bbox (x[480:920], y[60:340] on 1280x720) and run the gate on
the cropped (zoomed) frames. This isolates the CROP effect: same prompt, crop vs
full-frame. Compare results-CROP_* here against results-C_v3_esp32_recall_b2 /
results-D_v3_esp32_recall_b3 / results-G_v3_esp32_recall_b5 (full-frame) in this folder.

Reuses the window-building, camera context, gate call and prompt blocks from
bench_gate_esp32_b4.py (same directory).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from PIL import Image

CAMPAIGN_DIR = Path(__file__).parent
# Pile polygon bbox for esp32_002 (from cameras.pile_zone_polygon), native 1280x720.
PILE_BOX = (480, 60, 920, 340)
UPSCALE = 2  # zoom the crop so the gate gets more effective pixels


def _load_runner_module():
    path = CAMPAIGN_DIR / "bench_gate_esp32_b4.py"
    spec = importlib.util.spec_from_file_location("bench_b4", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # register before exec so @dataclass can resolve __module__
    spec.loader.exec_module(mod)  # runs module-level env load + key check
    return mod


B4 = _load_runner_module()

CROP_DIR = CAMPAIGN_DIR / ".crops"


def _crop_path(src: Path) -> Path:
    # mirror the source path under .crops, keyed by parent dir name to avoid collisions
    key = f"{src.parent.parent.name}_{src.stem}.jpg"
    return CROP_DIR / key


def _ensure_crop(src: Path) -> Path:
    dst = _crop_path(src)
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGB")
    crop = img.crop(PILE_BOX)
    if UPSCALE != 1:
        crop = crop.resize((crop.width * UPSCALE, crop.height * UPSCALE), Image.LANCZOS)
    crop.save(dst, quality=92)
    return dst


def _cropped_window(w):
    first = _ensure_crop(w.first_frame)
    last = _ensure_crop(w.last_frame)
    mids = [_ensure_crop(m) for m in w.mid_frames]
    return replace(w, first_frame=first, last_frame=last, mid_frames=mids)


CROP_ARMS = {
    "CROP_b2": "C_v3_esp32_recall_b2",
    "CROP_b3": "D_v3_esp32_recall_b3",
    "CROP_b5": "G_v3_esp32_recall_b5",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arms", default="CROP_b2,CROP_b3")
    ap.add_argument("--baseline-per-period", type=int, default=30)
    args = ap.parse_args()

    event_windows = B4.build_windows_from_manifest()
    baseline_windows = B4.build_baseline_windows(per_period=args.baseline_per_period)
    windows = event_windows + baseline_windows
    print(f"Windows: events={len(event_windows)} baseline={len(baseline_windows)} total={len(windows)}", flush=True)
    print(f"Pile box={PILE_BOX} upscale={UPSCALE}x", flush=True)

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for arm in arms:
        base_arm = CROP_ARMS[arm]
        spec = B4.ARM_SPECS[base_arm]
        print(f"\n=== Arm {arm} (crop) — prompt={base_arm} ===", flush=True)
        started = time.monotonic()
        results = []
        for idx, w in enumerate(windows, 1):
            cw = _cropped_window(w)
            if idx == 1 or idx % 25 == 0 or idx == len(windows):
                print(f"  [{arm}] {idx}/{len(windows)} - {w.window_id[:8]} ({w.category})", flush=True)
            gate = B4.run_gate_call(cw, spec["prompt_label"] + "_crop", spec["prompt_text"],
                                    spec.get("prompt_version", "v3"))
            results.append(B4.result_entry(w, gate))  # keep original window meta (category/id)
        elapsed = time.monotonic() - started
        cost = sum(r.get("total_cost_usd", 0.0) or 0.0 for r in results)
        ok = sum(1 for r in results if r["gate"].get("ok"))
        trig = sum(1 for r in results if r.get("triggered"))
        payload = {
            "summary": {
                "arm": arm, "base_prompt": base_arm, "crop": True, "pile_box": PILE_BOX,
                "upscale": UPSCALE, "model_gate": B4.worker_config.GEMINI_AGENT1_MODEL,
                "events_total": len(results), "events_ok": ok, "events_triggered": trig,
                "total_cost_usd": round(cost, 6), "elapsed_seconds": round(elapsed, 1),
            },
            "results": results,
        }
        out = CAMPAIGN_DIR / f"results-{arm}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Done: ok={ok}/{len(results)} triggered={trig} cost=${cost:.4f} "
              f"elapsed={elapsed:.1f}s -> {out.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
