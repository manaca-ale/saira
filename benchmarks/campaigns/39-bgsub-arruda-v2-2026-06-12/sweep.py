#!/usr/bin/env python3
"""Camp 39 Fase 1 — sweep de calibração BGSUB esp32_005.

Braços: baseline {prod npz 10/06, fresh 00-03h de hoje} × zona {old, new} ×
modo {single, dual}. Votes prod-exatos (worker.bgsub_filter real) computados 1×
por janela/braço; sweep analítico de min_frames × threshold por cima.

Conjuntos:
- NEG hoje (23 janelas completas; braço fresh usa só >=03h, sem vazamento)
- TRIG hoje (7 janelas com gate>=85 — guarda de atividade same-day)
- POS históricos (26 S3 + 5 FN Drive) — só braço prod (staleness comparável)

Critério: 0 supressão em TRIG/POS no braço + max taxa de supressão NEG.
"""
from __future__ import annotations

import json
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
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

cfg.BGSUB_MORPHO_MODE = "open_close"
cfg.BGSUB_SHADOW_THRESHOLD = 100
cfg.BGSUB_AREA_MIN = 400
cfg.BGSUB_BBOX_CROP_ENABLED = False
cfg.BGSUB_MODELS_DIR = str(MODELS_DIR)
cfg.BGSUB_MOG2_VAR_THRESHOLD = 40.0
cfg.BGSUB_MOG2_HISTORY = 80

PROD_NPZ = ROOT / "tmp" / "bgsub_esp32_005.npz"
FRESH_DIR = ROOT / "tmp" / "base12"          # 130 frames 00-03h de hoje

ZONES = {
    "old": [[[585, 350], [658, 320], [874, 413], [768, 467], [755, 470]]],
    "new": [[[590, 330], [700, 330], [900, 400], [1120, 470], [1245, 540],
             [1245, 600], [1080, 580], [880, 500], [680, 420], [585, 375]]],
}
MIN_PX = 800
MIN_FRAMES_GRID = [0.10, 0.20, 0.30, 0.40, 0.60]
THRESHOLD_GRID = [200, 500, 1000, 2000, 3000, 5000]

NEG_ROOT = ROOT / "tmp" / "ar_neg12"
TRIG_ROOT = ROOT / "tmp" / "ar_trig12"
POS_S3 = ROOT / "tmp" / "arruda_detail_corpus"
POS_FN = ROOT / "tmp" / "arruda_fn_drive"
POS_S3_IDS = ["01c9e4c7", "6834dad7", "01e54259", "9085ad0e", "d7822b53", "bcb8038c",
              "a5a72209", "ce13f76c", "6328e4e6", "50c32313", "b797daa9", "95dd7824",
              "bd466bda", "6e2e95ce", "6a126950", "9e112c6d", "4d51d0a1", "0c4976c0",
              "f7913b02", "0f2e9b60", "0cb3394b"]
POS_FN_IDS = ["id25", "id26", "id27", "id31", "id32"]


def build_fresh_npz() -> Path:
    out = MODELS_DIR / "fresh_base.npz"
    if out.exists():
        return out
    arrays = []
    for f in sorted(FRESH_DIR.glob("*.jpg")):
        img = cv2.imread(str(f))
        if img is not None:
            arrays.append(img)
    np.savez_compressed(str(out), frames=np.stack(arrays, axis=0))
    print(f"fresh baseline: {out.name} n={len(arrays)}", flush=True)
    return out


def window_votes(frames, device_key, polygon, npz_src, mode):
    cfg.BGSUB_DUAL_RATE_ENABLED = (mode == "dual")
    bgs.invalidate_cache(device_key)
    dst = MODELS_DIR / f"{device_key}.npz"
    if not dst.exists():
        shutil.copyfile(npz_src, dst)
    resolved = bgs._resolved_config(None)
    mask = bgs._cache.get_mask(device_key, polygon)
    bg_entry = bgs._cache.get_models(device_key, resolved)
    if bg_entry is None or mask is None:
        raise RuntimeError(f"build failed {device_key}")
    morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
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
        fg = bgs._apply_and_combine(bg_entry, img, mode, int(cfg.BGSUB_SHADOW_THRESHOLD),
                                    morph_kernel, lr_fast=lr_fast, lr_slow=lr_slow)
        in_zone = cv2.bitwise_and(fg, rmask)
        if int(np.count_nonzero(in_zone)) >= MIN_PX:
            fg_masks.append(in_zone > 0)
        else:
            fg_masks.append(np.zeros(in_zone.shape, dtype=bool))
    n_total = len(fg_masks)
    votes = np.stack(fg_masks, axis=0).sum(axis=0) if fg_masks else None
    return votes, n_total


def load_windows():
    wins = []
    for d in sorted(NEG_ROOT.iterdir()):
        if d.is_dir():
            hour = int(d.name.split("_")[-1][:2])
            wins.append(("NEG", d.name, sorted(d.glob("*.jpg")), hour))
    for d in sorted(TRIG_ROOT.iterdir()):
        if d.is_dir():
            hour = int(d.name.split("_")[-1][:2])
            wins.append(("TRIG", d.name, sorted(d.glob("*.jpg")), hour))
    for det8 in POS_S3_IDS:
        fs = sorted((POS_S3 / det8).glob("*.jpg"))
        if fs:
            wins.append(("POS", det8, fs, -1))
    for ev in POS_FN_IDS:
        fs = sorted((POS_FN / ev).glob("*.jpg"))
        if fs:
            wins.append(("POS", ev, fs, -1))
    return wins


def main() -> int:
    fresh_npz = build_fresh_npz()
    wins = load_windows()
    print(f"{len(wins)} janelas "
          f"(NEG={sum(1 for w in wins if w[0]=='NEG')}, TRIG={sum(1 for w in wins if w[0]=='TRIG')}, "
          f"POS={sum(1 for w in wins if w[0]=='POS')})", flush=True)

    baselines = {"prod": PROD_NPZ, "fresh": fresh_npz}
    cache = {}  # (base,zone,mode,name) -> (votes, n_total)
    rows = []
    for bkey, bsrc in baselines.items():
        for zkey, poly in ZONES.items():
            for mode in ("single", "dual"):
                arm = f"{bkey}/{zkey}/{mode}"
                for kind, name, frames, hour in wins:
                    if bkey == "fresh" and kind == "POS":
                        continue  # staleness incomparável; POS só no braço prod
                    if bkey == "fresh" and kind in ("NEG", "TRIG") and 0 <= hour < 3:
                        continue  # sem vazamento baseline->eval
                    votes, n_total = window_votes(frames, f"a_{bkey}_{zkey}_{mode}", poly, bsrc, mode)
                    cache[(arm, kind, name)] = (votes, n_total)
                print(f"  votes ok: {arm}", flush=True)

    # sweep analítico
    out = []
    for arm in sorted({k[0] for k in cache}):
        items = [(kind, name, v) for (a, kind, name), v in cache.items() if a == arm]
        negs = [(n, v) for k, n, v in items if k == "NEG"]
        trigs = [(n, v) for k, n, v in items if k == "TRIG"]
        poss = [(n, v) for k, n, v in items if k == "POS"]
        for mf in MIN_FRAMES_GRID:
            for thr in THRESHOLD_GRID:
                def pers(v):
                    votes, n_total = v
                    k = max(1, int(round(mf * n_total)))
                    return int(np.count_nonzero(votes >= k))
                neg_sup = sum(1 for _, v in negs if pers(v) < thr)
                trig_sup = sum(1 for _, v in trigs if pers(v) < thr)
                pos_sup = sum(1 for _, v in poss if pers(v) < thr)
                out.append({"arm": arm, "min_frames": mf, "threshold": thr,
                            "neg_sup": neg_sup, "neg_n": len(negs),
                            "trig_sup": trig_sup, "trig_n": len(trigs),
                            "pos_sup": pos_sup, "pos_n": len(poss)})
    (RESULTS / "sweep_39.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("\n=== configs com 0 supressão em TRIG+POS, ordenadas por NEG suprimidos ===", flush=True)
    safe = [r for r in out if r["trig_sup"] == 0 and r["pos_sup"] == 0 and r["neg_sup"] > 0]
    safe.sort(key=lambda r: -r["neg_sup"] / max(1, r["neg_n"]))
    for r in safe[:15]:
        print(f"  {r['arm']:18} mf={r['min_frames']:.2f} thr={r['threshold']:>5} | "
              f"NEG {r['neg_sup']}/{r['neg_n']} | TRIG 0/{r['trig_n']} | POS 0/{r['pos_n']}", flush=True)
    if not safe:
        print("  (nenhuma config segura suprime NEG > 0)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
