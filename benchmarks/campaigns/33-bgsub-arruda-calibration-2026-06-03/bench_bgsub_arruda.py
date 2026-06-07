#!/usr/bin/env python3
"""Camp 33 — BGSUB calibration sweep for esp32_005 (Arruda).

Goal: find a per-camera BGSUB operating point that lets the 4 suppressed real
dumps of 02/06 (IDs 24-27) PASS the pre-filter while still suppressing
empty/transit windows — instead of disabling BGSUB outright.

Faithfulness: imports the REAL worker.bgsub_filter (same model-build +
_apply_and_combine dual/single + persistence math as prod). Only the threshold
sweep is done analytically over the per-frame foreground masks (computed once
per window per mode), so single vs dual and all thresholds are prod-exact.

Data:
  - TP set: data/datasets/official/cam_arruda/tp/{id24..id27}/frames  (Drive)
  - Negatives: .tmp/arruda_sample/neg/win*  (esp32_005 sem_ocorrencia 06/03)
  - Baseline: .tmp/arruda_sample/baseline   (esp32_005 sem_ocorrencia 06/03, day+night)

Anti-regression note: lowering threshold / min_persistence_frames in SINGLE
mode is monotonic (looser → passes a superset), so it cannot regress recall.
DUAL mode is a different signal and would need the captured-dump controls
before adoption (flagged in the report).
"""
from __future__ import annotations

import csv
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import cv2
import numpy as np

ROOT = Path(r"c:\saira")
sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))

import worker.config as cfg          # noqa: E402
import worker.bgsub_filter as bgs    # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

DEVICE = "esp32_005"
POLYGON = [[[585, 350], [658, 320], [874, 413], [768, 467], [755, 470]]]

TP_ROOT = ROOT / "data" / "datasets" / "official" / "cam_arruda" / "tp"
SAMPLE = ROOT / ".tmp" / "arruda_sample"
BASELINE_DIR = SAMPLE / "baseline"
NEG_ROOT = SAMPLE / "neg"

# Prod-faithful fixed knobs
cfg.BGSUB_MORPHO_MODE = "open_close"
cfg.BGSUB_SHADOW_THRESHOLD = 100
cfg.BGSUB_AREA_MIN = 400
cfg.BGSUB_BBOX_CROP_ENABLED = False
cfg.BGSUB_MIN_PX_ACTIVE = 800       # prod default; held fixed (could be swept)

MODELS_DIR = HERE / "models"
MODELS_DIR.mkdir(exist_ok=True)
cfg.BGSUB_MODELS_DIR = str(MODELS_DIR)

# Sweep grid
MIN_FRAMES_GRID = [0.10, 0.15, 0.20, 0.30, 0.40]
THRESHOLD_GRID = [200, 300, 500, 750, 1000]
MODES = ["single", "dual"]


def build_baseline_npz() -> None:
    frames = sorted(BASELINE_DIR.glob("*.jpg"))
    arrays = []
    for f in frames:
        img = cv2.imread(str(f))
        if img is not None:
            arrays.append(img)
    stack = np.stack(arrays, axis=0)
    out = MODELS_DIR / f"{DEVICE}.npz"
    np.savez_compressed(str(out), frames=stack)
    print(f"baseline npz: {out} ({stack.shape}, {out.stat().st_size/1e6:.1f} MB)", flush=True)


def list_windows() -> tuple[list, list]:
    tps = []
    for ev in sorted(TP_ROOT.iterdir()):
        frames = sorted((ev / "frames").glob("*.jpg"))
        if frames:
            tps.append((ev.name, frames))
    negs = []
    for win in sorted(NEG_ROOT.iterdir()):
        frames = sorted(win.glob("*.jpg"))
        if frames:
            negs.append((win.name, frames))
    return tps, negs


def window_votes(frames: list[Path], mode: str, resolved: dict) -> tuple[np.ndarray, int]:
    """Run the REAL per-frame fg extraction; return (votes, n_total).

    Rebuilds a FRESH model for this window (no cross-window drift) — matches the
    proposed prod config: adaptive OFF + periodic fresh recalibration.
    votes[y,x] = number of frames where pixel is foreground inside the pile zone
    AND that frame had >= min_px_active in-zone pixels (per-frame gate, as evaluate).
    """
    cfg.BGSUB_DUAL_RATE_ENABLED = (mode == "dual")
    bgs.invalidate_cache(DEVICE)
    mask = bgs._cache.get_mask(DEVICE, POLYGON)
    bg_entry = bgs._cache.get_models(DEVICE, resolved)
    if bg_entry is None or mask is None:
        raise RuntimeError("model/mask build failed")
    morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    min_active = int(resolved["min_px_active"])
    shadow = int(resolved["shadow_threshold"])
    lr_fast = resolved["lr_fast"] if mode == "dual" else 0.0
    lr_slow = resolved["lr_slow"] if mode == "dual" else 0.0

    fg_masks = []
    for fp in frames:
        img = cv2.imread(str(fp))
        if img is None:
            continue
        rmask = mask
        if img.shape[:2] != mask.shape:
            rmask = cv2.resize(mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        fg = bgs._apply_and_combine(bg_entry, img, mode, shadow, morph_kernel,
                                    lr_fast=lr_fast, lr_slow=lr_slow)
        in_zone = cv2.bitwise_and(fg, rmask)
        if int(np.count_nonzero(in_zone)) >= min_active:
            fg_masks.append(in_zone > 0)
        else:
            fg_masks.append(np.zeros(in_zone.shape, dtype=bool))
    n_total = len(fg_masks)
    votes = np.stack(fg_masks, axis=0).sum(axis=0) if fg_masks else np.zeros(mask.shape, dtype=int)
    return votes, n_total


def persistence_px(votes: np.ndarray, n_total: int, min_frames_frac: float) -> int:
    min_frames = max(1, int(round(min_frames_frac * n_total)))
    return int(np.count_nonzero(votes >= min_frames))


def main() -> int:
    build_baseline_npz()
    resolved = bgs._resolved_config(None)
    tps, negs = list_windows()
    print(f"TP windows: {[t[0] for t in tps]}", flush=True)
    print(f"NEG windows: {len(negs)}", flush=True)

    # Compute votes once per (window, mode)
    cache = {}  # (kind, name, mode) -> (votes, n_total)
    for mode in MODES:
        for name, frames in tps:
            cache[("tp", name, mode)] = window_votes(frames, mode, resolved)
        for name, frames in negs:
            cache[("neg", name, mode)] = window_votes(frames, mode, resolved)
        print(f"  computed votes for mode={mode}", flush=True)

    # Per-window persistence table at current prod config (single, 0.40, thr 1000)
    print("\n=== Per-TP persistence (FRESH baseline) ===", flush=True)
    print(f"{'event':<20s} {'mode':<7s} {'mf=0.40':>8s} {'mf=0.20':>8s} {'mf=0.10':>8s}", flush=True)
    for name, _ in tps:
        for mode in MODES:
            v, n = cache[("tp", name, mode)]
            row = [persistence_px(v, n, mf) for mf in (0.40, 0.20, 0.10)]
            print(f"{name:<20s} {mode:<7s} {row[0]:>8d} {row[1]:>8d} {row[2]:>8d}", flush=True)

    # Full sweep
    rows = []
    for mode in MODES:
        for mf in MIN_FRAMES_GRID:
            for thr in THRESHOLD_GRID:
                tp_pass = 0
                tp_detail = {}
                for name, _ in tps:
                    v, n = cache[("tp", name, mode)]
                    p = persistence_px(v, n, mf)
                    passed = p >= thr
                    tp_pass += int(passed)
                    tp_detail[name] = (p, passed)
                neg_suppress = 0
                for name, _ in negs:
                    v, n = cache[("neg", name, mode)]
                    p = persistence_px(v, n, mf)
                    if p < thr:
                        neg_suppress += 1
                rows.append({
                    "mode": mode, "min_frames": mf, "threshold": thr,
                    "tp_pass": tp_pass, "tp_total": len(tps),
                    "neg_suppress": neg_suppress, "neg_total": len(negs),
                    "neg_suppress_rate": round(neg_suppress / max(1, len(negs)), 3),
                    "tp_detail": {k: v[0] for k, v in tp_detail.items()},
                })

    # Save
    with (RESULTS / "sweep.json").open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    with (RESULTS / "sweep.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "min_frames", "threshold", "tp_pass", "neg_suppress",
                    "neg_suppress_rate"])
        for r in rows:
            w.writerow([r["mode"], r["min_frames"], r["threshold"], r["tp_pass"],
                        r["neg_suppress"], r["neg_suppress_rate"]])

    # Print configs achieving 4/4 TP, ranked by neg suppression
    print("\n=== Configs with 4/4 TP pass (ranked by neg suppression) ===", flush=True)
    winners = [r for r in rows if r["tp_pass"] == len(tps)]
    winners.sort(key=lambda r: -r["neg_suppress_rate"])
    print(f"{'mode':<7s} {'min_frames':>10s} {'threshold':>10s} {'TP':>5s} {'neg_supr':>10s}", flush=True)
    for r in winners[:15]:
        print(f"{r['mode']:<7s} {r['min_frames']:>10.2f} {r['threshold']:>10d} "
              f"{r['tp_pass']}/{r['tp_total']:>3d} {r['neg_suppress']}/{r['neg_total']} "
              f"({r['neg_suppress_rate']*100:.0f}%)", flush=True)
    if not winners:
        print("  NONE — no config passes all 4 TP. Best per mode:", flush=True)
        for mode in MODES:
            best = max((r for r in rows if r["mode"] == mode), key=lambda r: (r["tp_pass"], r["neg_suppress_rate"]))
            print(f"  {mode}: {best['tp_pass']}/{best['tp_total']} TP @ mf={best['min_frames']} thr={best['threshold']} "
                  f"neg_supr={best['neg_suppress_rate']*100:.0f}%", flush=True)

    # Current prod config reference
    prod = next(r for r in rows if r["mode"] == "single" and r["min_frames"] == 0.40 and r["threshold"] == 1000)
    print(f"\n=== Current prod config (single, mf=0.40, thr=1000) ===", flush=True)
    print(f"  TP pass: {prod['tp_pass']}/{prod['tp_total']}  |  neg suppress: {prod['neg_suppress']}/{prod['neg_total']}", flush=True)
    print(f"  TP persistence: {prod['tp_detail']}", flush=True)

    print(f"\n  → {RESULTS / 'sweep.csv'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
