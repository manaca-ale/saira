#!/usr/bin/env python3
"""Camp 39 Fase 0 — probe: por que o BGSUB do Arruda nunca suprime?

Roda o fg-extraction PROD-EXATO (worker.bgsub_filter real, npz de prod 10/06) nas
janelas NEG completas de 06/12 + 3 positivos de contraste, com as zonas ANTIGA e
NOVA (DB atual). Imprime persistence_px nos params de prod (min_frames=0.4,
threshold=1000, min_px_active=800) e salva heatmaps de votes das janelas vazias.
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(r"c:\saira")
sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
import worker.config as cfg  # noqa: E402
import worker.bgsub_filter as bgs  # noqa: E402

HERE = Path(__file__).resolve().parent
MODELS_DIR = HERE / "models"
MODELS_DIR.mkdir(exist_ok=True)
OUT = HERE / "probe_out"
OUT.mkdir(exist_ok=True)

# prod-faithful knobs
cfg.BGSUB_MORPHO_MODE = "open_close"
cfg.BGSUB_SHADOW_THRESHOLD = 100
cfg.BGSUB_AREA_MIN = 400
cfg.BGSUB_BBOX_CROP_ENABLED = False
cfg.BGSUB_DUAL_RATE_ENABLED = False
cfg.BGSUB_MODELS_DIR = str(MODELS_DIR)
cfg.BGSUB_MOG2_VAR_THRESHOLD = 40.0
cfg.BGSUB_MOG2_HISTORY = 80

PROD_NPZ = ROOT / "tmp" / "bgsub_esp32_005.npz"

ZONES = {
    "old": [[[585, 350], [658, 320], [874, 413], [768, 467], [755, 470]]],
    "new": [[[590, 330], [700, 330], [900, 400], [1120, 470], [1245, 540],
             [1245, 600], [1080, 580], [880, 500], [680, 420], [585, 375]]],
}
PROD_MIN_FRAMES = 0.4
PROD_THRESHOLD = 1000
PROD_MIN_PX = 800

NEG_ROOT = ROOT / "tmp" / "ar_neg12"
POS_SAMPLES = {  # contraste: descartes reais (janela completa)
    "POS_id31_drive": ROOT / "tmp" / "arruda_fn_drive" / "id31",
    "POS_50c32313": ROOT / "tmp" / "arruda_detail_corpus" / "50c32313",
    "POS_ce13f76c": ROOT / "tmp" / "arruda_detail_corpus" / "ce13f76c",
}


def window_votes(frames, zone_key, polygon, resolved):
    device = f"esp32_005_{zone_key}"
    # fresh model per window (prod = frozen baseline; sem drift entre janelas)
    bgs.invalidate_cache(device)
    src = MODELS_DIR / f"{device}.npz"
    if not src.exists():
        shutil.copyfile(PROD_NPZ, src)
    mask = bgs._cache.get_mask(device, polygon)
    bg_entry = bgs._cache.get_models(device, resolved)
    if bg_entry is None or mask is None:
        raise RuntimeError(f"model/mask build failed for {device}")
    morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg_masks = []
    for fp in frames:
        img = cv2.imread(str(fp))
        if img is None:
            continue
        rmask = mask
        if img.shape[:2] != mask.shape:
            rmask = cv2.resize(mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        fg = bgs._apply_and_combine(bg_entry, img, "single", int(cfg.BGSUB_SHADOW_THRESHOLD),
                                    morph_kernel)
        in_zone = cv2.bitwise_and(fg, rmask)
        if int(np.count_nonzero(in_zone)) >= PROD_MIN_PX:
            fg_masks.append(in_zone > 0)
        else:
            fg_masks.append(np.zeros(in_zone.shape, dtype=bool))
    n_total = len(fg_masks)
    votes = np.stack(fg_masks, axis=0).sum(axis=0) if fg_masks else None
    return votes, n_total


def persistence(votes, n_total, frac=PROD_MIN_FRAMES):
    min_frames = max(1, int(round(frac * n_total)))
    return int(np.count_nonzero(votes >= min_frames))


def save_heatmap(votes, n_total, ref_frame, name):
    """Overlay votes (red intensity) on the reference frame."""
    img = cv2.imread(str(ref_frame))
    if img is None or votes is None:
        return
    norm = (votes.astype(np.float32) / max(1, n_total))
    heat = (norm * 255).astype(np.uint8)
    heat_c = cv2.applyColorMap(heat, cv2.COLORMAP_JET)
    blend = cv2.addWeighted(img, 0.55, heat_c, 0.45, 0)
    cv2.imwrite(str(OUT / f"{name}.jpg"), blend)


def main() -> int:
    resolved = bgs._resolved_config(None)
    resolved["persistence_threshold"] = PROD_THRESHOLD
    resolved["min_persistence_frames"] = PROD_MIN_FRAMES
    resolved["min_px_active"] = PROD_MIN_PX

    windows = []
    for d in sorted(NEG_ROOT.iterdir()):
        if d.is_dir():
            windows.append((d.name, sorted(d.glob("*.jpg"))))
    for name, d in POS_SAMPLES.items():
        fs = sorted(Path(d).glob("*.jpg"))
        if fs:
            windows.append((name, fs))

    print(f"{len(windows)} janelas | params prod: min_frames={PROD_MIN_FRAMES} thr={PROD_THRESHOLD} min_px={PROD_MIN_PX}")
    print(f"{'janela':28} {'n':>3}" + "".join(f" | {z}: pers (ok_frames)" for z in ZONES))
    results = {}
    for name, frames in windows:
        row = [f"{name:28} {len(frames):>3}"]
        for zkey, poly in ZONES.items():
            votes, n_total = window_votes(frames, zkey, poly, resolved)
            p = persistence(votes, n_total)
            n_ok = "?"
            row.append(f" | {zkey}: {p:>6}px")
            results.setdefault(name, {})[zkey] = (p, n_total)
            # heatmaps das 3 primeiras janelas NEG + positivos
            if name.startswith(("01_", "07_", "13_", "POS")):
                save_heatmap(votes, n_total, frames[len(frames) // 2], f"{name}_{zkey}")
        sup = " <- SUPRIMIRIA(new)" if results[name]["new"][0] < PROD_THRESHOLD else ""
        print("".join(row) + sup, flush=True)

    negs = [n for n in results if n.startswith("0") or n.startswith("1") or n.startswith("2")]
    for z in ZONES:
        vals = sorted(results[n][z][0] for n in negs)
        sup = sum(1 for v in vals if v < PROD_THRESHOLD)
        print(f"\nzona {z}: NEG persistence min={vals[0]} p50={vals[len(vals)//2]} max={vals[-1]} | suprimiria {sup}/{len(vals)} a thr=1000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
