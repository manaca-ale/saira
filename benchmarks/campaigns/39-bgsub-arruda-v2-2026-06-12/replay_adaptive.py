#!/usr/bin/env python3
"""Camp 39b — replay full-day: BGSUB ADAPTIVO vs RECAL-ESTÁTICO no Arruda (06/12).

Reproduz a dinâmica de prod janela a janela (audit = fonte das janelas E do
veredito do gate que governa a absorção adaptativa, igual main.py):

  policy STATIC : baseline fresco 00-03h, sem updates (= shadow atual pós-recal)
  policy ADAPT  : mesmo baseline inicial + absorção lr=0.05 de toda janela em que
                  o gate disse "sem lixo novo" (= adaptivo dos outros pontos,
                  MIN_CONFIDENCE=0; exatamente o esquema do incidente de 02/06)

Frames: tmp/day12 (sem_ocorrencia + ocorrencias completos do dia). Janelas <03h
ficam fora da avaliação (baseline usa 00-03h) mas ADAPT também não as absorve
para manter o pareamento com STATIC.

Métrica: would-suppress por política × hora; CRÍTICO: triggers/detecções reais
suprimidos (recall) — o modo de falha histórico do adaptivo neste ponto.
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
cfg.BGSUB_MORPHO_MODE = "open_close"
cfg.BGSUB_SHADOW_THRESHOLD = 100
cfg.BGSUB_BBOX_CROP_ENABLED = False
cfg.BGSUB_DUAL_RATE_ENABLED = False
cfg.BGSUB_MODELS_DIR = str(MODELS_DIR)
cfg.BGSUB_MOG2_VAR_THRESHOLD = 40.0
cfg.BGSUB_MOG2_HISTORY = 80

ZONE = [[[590, 330], [700, 330], [900, 400], [1120, 470], [1245, 540],
         [1245, 600], [1080, 580], [880, 500], [680, 420], [585, 375]]]
THR = 1000
MF = 0.4
MIN_PX = 800
ADAPT_LR = 0.05

DAY = ROOT / "tmp" / "day12"
FRESH_NPZ = MODELS_DIR / "fresh_base.npz"
AUDIT = ROOT / "tmp" / "audit_0612_now.jsonl"


def frame_index():
    idx = {}
    for p in DAY.rglob("*.jpg"):
        idx[p.name] = p
    return idx


def persistence(fg_masks):
    n = len(fg_masks)
    if not n:
        return 0, 0
    votes = np.stack(fg_masks, axis=0).sum(axis=0)
    k = max(1, int(round(MF * n)))
    return int(np.count_nonzero(votes >= k)), n


def main() -> int:
    fidx = frame_index()
    aud = [json.loads(l) for l in open(AUDIT, encoding="utf-8")]
    aud.sort(key=lambda r: r["window_first_frame"])
    wins = [r for r in aud if r["window_first_frame"][11:13] >= "03"]
    print(f"{len(wins)} janelas >=03h | frames indexados: {len(fidx)}", flush=True)

    res = bgs._resolved_config(None)
    mk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    models = {}
    for pol in ("STATIC", "ADAPT"):
        dev = f"replay_{pol}"
        dst = MODELS_DIR / f"{dev}.npz"
        if dst.exists():
            dst.unlink()
        shutil.copyfile(FRESH_NPZ, dst)
        bgs.invalidate_cache(dev)
        models[pol] = bgs._cache.get_models(dev, res)
        assert models[pol] is not None
    mask = bgs._cache.get_mask("replay_STATIC", ZONE)

    rows = []
    for i, r in enumerate(wins):
        lo, hi = r["window_first_frame"], r["window_last_frame"]
        names = sorted(n for n in fidx if lo <= n <= hi)
        if len(names) < 5:
            continue
        rec = {"last": hi, "hour": hi[11:13], "trig": bool(r["agent1_triggered"]),
               "det": (r.get("detection_id") or "")[:8] or None, "n": len(names)}
        for pol in ("STATIC", "ADAPT"):
            ent = models[pol]
            fgm = []
            for nm in names:
                img = cv2.imread(str(fidx[nm]))
                if img is None:
                    continue
                rm = mask if img.shape[:2] == mask.shape else cv2.resize(
                    mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
                fg = bgs._apply_and_combine(ent, img, "single", 100, mk)
                iz = cv2.bitwise_and(fg, rm)
                fgm.append(iz > 0 if int(np.count_nonzero(iz)) >= MIN_PX else
                           np.zeros(iz.shape, dtype=bool))
            p, n = persistence(fgm)
            rec[pol] = p
            rec[f"{pol}_sup"] = p < THR
            # absorção adaptativa: igual main.py — só quando o gate NÃO detectou
            if pol == "ADAPT" and not r["agent1_triggered"]:
                for nm in names:
                    img = cv2.imread(str(fidx[nm]))
                    if img is not None:
                        ent.apply(img, learningRate=ADAPT_LR)
        rows.append(rec)
        if i % 20 == 0:
            print(f"  {i}/{len(wins)} {hi[11:16]} STATIC={rec['STATIC']} ADAPT={rec['ADAPT']}", flush=True)

    (HERE / "results" / "replay_adaptive.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8")

    print("\n=== resumo por hora (suprimidas/total) ===", flush=True)
    import collections
    byh = collections.defaultdict(lambda: [0, 0, 0])
    for rec in rows:
        byh[rec["hour"]][0] += 1
        byh[rec["hour"]][1] += rec["STATIC_sup"]
        byh[rec["hour"]][2] += rec["ADAPT_sup"]
    for h in sorted(byh):
        t, s, a = byh[h]
        print(f"  {h}h: STATIC {s}/{t} | ADAPT {a}/{t}", flush=True)
    tot = len(rows)
    print(f"\nTOTAL: STATIC {sum(r['STATIC_sup'] for r in rows)}/{tot} | "
          f"ADAPT {sum(r['ADAPT_sup'] for r in rows)}/{tot}", flush=True)
    print("\n=== RECALL: janelas com trigger ===", flush=True)
    for rec in rows:
        if rec["trig"]:
            print(f"  {rec['last'][11:16]} det={rec['det']} "
                  f"STATIC={'SUP!' if rec['STATIC_sup'] else 'passa'}({rec['STATIC']}) "
                  f"ADAPT={'SUP!' if rec['ADAPT_sup'] else 'passa'}({rec['ADAPT']})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
