#!/usr/bin/env python3
"""Spike v2 — métricas adicionais para distinguir TP de FP trânsito.

V1 achou que `persistence` e `ratio_in_pile` têm distribuições sobrepostas
entre TP e FP "passando". Hipótese: o que distingue é **stationarity** —
TPs envolvem pessoa parada por vários frames; FPs "passando" são 1-2 frames
de pessoa em movimento.

Novas métricas:
1. `n_frames_active`: em quantos dos N frames há FG significativo na zona da
   pilha (>= MIN_PX). TP espera 4-5; FP passando espera 1-2.
2. `centroid_variance`: variância da posição do centroide do FG na zona ao
   longo dos frames. Baixa = parado; alta = movendo.
3. `bbox_iou_chain`: IoU médio entre bounding boxes da maior blob frame-a-frame.
   Alto = mesmo objeto/pessoa nas mesmas coordenadas (parado).
"""
from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(r"c:\saira")
DATASET = PROJECT_ROOT / "data" / "datasets" / "official"

PILE_ZONES = {
    "cam_imbiribeira": [
        np.array([(40, 280), (560, 280), (560, 720), (40, 720)], dtype=np.int32),
        np.array([(800, 280), (1240, 280), (1240, 720), (800, 720)], dtype=np.int32),
    ],
    "cam_mangabeira": [
        np.array([(480, 60), (920, 60), (920, 340), (480, 340)], dtype=np.int32),
    ],
}

MIN_PX_ACTIVE = 800  # px mínimo de FG na zona para o frame contar como "ativo"


def build_zone_mask(camera: str, shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    for poly in PILE_ZONES[camera]:
        cv2.fillPoly(mask, [poly], 255)
    return mask


def build_bg_model(camera: str, n_frames: int = 80) -> cv2.BackgroundSubtractor:
    bg = cv2.createBackgroundSubtractorMOG2(
        history=n_frames, varThreshold=40.0, detectShadows=True,
    )
    frames_used = 0
    for period in ("day", "night"):
        period_dir = DATASET / camera / "baseline" / period
        if not period_dir.exists():
            continue
        frames = sorted(period_dir.glob("*.jpg"))
        step = max(1, len(frames) // (n_frames // 2))
        for f in frames[::step][:n_frames // 2]:
            img = cv2.imread(str(f))
            if img is None:
                continue
            bg.apply(img)
            frames_used += 1
    return bg


def largest_blob_props(mask: np.ndarray) -> tuple[int, tuple[int, int], tuple[int, int, int, int]] | None:
    """Retorna (area, centroid, bbox) da maior componente conectada na máscara."""
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return None
    # 0 é background
    idx = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    area = int(stats[idx, cv2.CC_STAT_AREA])
    if area < MIN_PX_ACTIVE:
        return None
    cx, cy = centroids[idx]
    bbox = (
        int(stats[idx, cv2.CC_STAT_LEFT]),
        int(stats[idx, cv2.CC_STAT_TOP]),
        int(stats[idx, cv2.CC_STAT_WIDTH]),
        int(stats[idx, cv2.CC_STAT_HEIGHT]),
    )
    return area, (int(cx), int(cy)), bbox


def iou(b1: tuple[int, int, int, int], b2: tuple[int, int, int, int]) -> float:
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    ix1, iy1 = max(x1, x2), max(y1, y2)
    ix2, iy2 = min(x1 + w1, x2 + w2), min(y1 + h1, y2 + h2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = w1 * h1 + w2 * h2 - inter
    return inter / union if union > 0 else 0.0


def score_window(
    bg: cv2.BackgroundSubtractor,
    zone_mask: np.ndarray,
    frame_paths: list[Path],
    morph_kernel: np.ndarray,
) -> dict:
    blobs = []  # lista de (area, centroid, bbox) ou None
    for fp in frame_paths:
        img = cv2.imread(str(fp))
        if img is None:
            continue
        fg = bg.apply(img, learningRate=0)
        fg = (fg > 200).astype(np.uint8) * 255
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, morph_kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, morph_kernel)
        in_zone = cv2.bitwise_and(fg, zone_mask)
        blobs.append(largest_blob_props(in_zone))

    n_active = sum(1 for b in blobs if b is not None)
    centroids = [b[1] for b in blobs if b is not None]
    bboxes = [b[2] for b in blobs if b is not None]

    if len(centroids) >= 2:
        xs = np.array([c[0] for c in centroids])
        ys = np.array([c[1] for c in centroids])
        # std dos centroides em pixels (deslocamento)
        centroid_std = float(np.sqrt(xs.std()**2 + ys.std()**2))
    else:
        centroid_std = 0.0

    # IoU médio entre pares consecutivos
    iou_chain = []
    for i in range(len(bboxes) - 1):
        iou_chain.append(iou(bboxes[i], bboxes[i + 1]))
    iou_mean = float(np.mean(iou_chain)) if iou_chain else 0.0

    return {
        "n_total": len(blobs),
        "n_active": n_active,
        "centroid_std": centroid_std,
        "iou_mean": iou_mean,
    }


def sample_frames_from_window(frames_dir: Path) -> list[Path]:
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
        if per_series < len(all_starts):
            step = len(all_starts) / per_series
            indices = [all_starts[int(i * step)] for i in range(per_series)]
        else:
            indices = all_starts
        for i, idx in enumerate(indices):
            window_frames = frames[idx:idx + window_size]
            out.append((f"baseline_{camera}_{period}_{i:03d}", window_frames))
    return out


def main() -> int:
    print("Spike v2 — bgsub + stationarity metrics\n", flush=True)

    manifest_path = DATASET / "manifest.csv"
    events = []
    with manifest_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            events.append(row)

    bg_models = {c: build_bg_model(c) for c in ("cam_imbiribeira", "cam_mangabeira")}
    zone_masks = {c: build_zone_mask(c, (720, 1280)) for c in ("cam_imbiribeira", "cam_mangabeira")}
    morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    scores = []

    print("\nScoring events...", flush=True)
    for i, row in enumerate(events, 1):
        if i % 30 == 0:
            print(f"  {i}/{len(events)}", flush=True)
        local = DATASET / row["local_path"] / "frames"
        if not local.exists():
            continue
        frames = sample_frames_from_window(local)
        if len(frames) < 2:
            continue
        s = score_window(bg_models[row["camera"]], zone_masks[row["camera"]], frames, morph_kernel)
        s.update({
            "event_id": row["event_id"],
            "camera": row["camera"],
            "category": row["category"],
            "justificativa": (row.get("justificativa") or "")[:80],
        })
        scores.append(s)

    print("\nScoring baselines...", flush=True)
    for camera in ("cam_imbiribeira", "cam_mangabeira"):
        bg = bg_models[camera]
        zm = zone_masks[camera]
        for wid, frames in build_baseline_windows(camera):
            if len(frames) < 2:
                continue
            n = len(frames)
            indices = sorted({0, n // 4, n // 2, 3 * n // 4, n - 1})
            picked = [frames[i] for i in indices]
            s = score_window(bg, zm, picked, morph_kernel)
            s.update({
                "event_id": wid,
                "camera": camera,
                "category": "baseline",
                "justificativa": "",
            })
            scores.append(s)

    poda_keywords = ["retirando", "coleta", "caminhão", "poda", "limpeza", "limpando"]
    def is_focus_fp(j: str) -> bool:
        return not any(k in j.lower() for k in poda_keywords)

    out_dir = PROJECT_ROOT / "tools" / "spike_bgsub_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "scores_v2.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "camera", "category", "is_focus_fp",
                    "n_total", "n_active", "centroid_std", "iou_mean", "justificativa"])
        for s in scores:
            focus = is_focus_fp(s["justificativa"]) if s["category"] == "fp" else False
            w.writerow([s["event_id"], s["camera"], s["category"], focus,
                        s["n_total"], s["n_active"],
                        f"{s['centroid_std']:.1f}", f"{s['iou_mean']:.2f}",
                        s["justificativa"]])

    print("\n=== Distribuições por categoria ===\n", flush=True)
    tps = [s for s in scores if s["category"] == "tp"]
    fps_focus = [s for s in scores if s["category"] == "fp" and is_focus_fp(s["justificativa"])]
    fps_poda = [s for s in scores if s["category"] == "fp" and not is_focus_fp(s["justificativa"])]
    baselines = [s for s in scores if s["category"] == "baseline"]

    def stats(label: str, items: list[dict]):
        if not items:
            return
        na = [s["n_active"] for s in items]
        cs = [s["centroid_std"] for s in items]
        iou_ = [s["iou_mean"] for s in items]
        print(f"  {label} (N={len(items)}):")
        print(f"    n_active (frames com FG na zona):      min={min(na)}  med={int(np.median(na))}  max={max(na)}")
        print(f"    centroid_std (px, baixo = estatico):   min={min(cs):.0f}  med={np.median(cs):.0f}  max={max(cs):.0f}")
        print(f"    iou_mean (alto = mesmo objeto):        min={min(iou_):.2f}  med={np.median(iou_):.2f}  max={max(iou_):.2f}")

    stats("TP (esperado: n_active alto, centroid_std baixo, iou_mean alto)", tps)
    print()
    stats("FP FOCO (esperado: n_active 1-2, centroid_std alto, iou_mean baixo)", fps_focus)
    print()
    stats("FP poda", fps_poda)
    print()
    stats("BASELINE", baselines)

    print("\n=== Grid search ===\n", flush=True)
    print(f"{'n_act_min':>10s} {'cstd_max':>9s} {'iou_min':>9s} | "
          f"{'TP keep':>10s} {'FP foco supr':>14s} {'baseline supr':>14s} | {'FP poda':>10s}")
    print("-" * 100)

    best = None
    for na_min in [2, 3, 4]:
        for cstd_max in [50, 100, 200, 500, 1000, 9999]:
            for iou_min in [0.0, 0.1, 0.2, 0.3]:
                def passes(s):
                    return (s["n_active"] >= na_min
                            and s["centroid_std"] <= cstd_max
                            and s["iou_mean"] >= iou_min)

                tp_keep = sum(1 for s in tps if passes(s))
                fp_focus_supr = sum(1 for s in fps_focus if not passes(s))
                base_supr = sum(1 for s in baselines if not passes(s))
                fp_poda_supr = sum(1 for s in fps_poda if not passes(s))

                tp_pct = tp_keep / max(1, len(tps)) * 100
                fp_foco_pct = fp_focus_supr / max(1, len(fps_focus)) * 100
                metric = tp_pct + fp_foco_pct

                if best is None or metric > best["m"]:
                    best = dict(m=metric, na=na_min, cs=cstd_max, io=iou_min,
                                tk=tp_keep, ffs=fp_focus_supr, bs=base_supr,
                                fps=fp_poda_supr, tpp=tp_pct, fpp=fp_foco_pct)

                if tp_pct >= 80.0:
                    print(f"{na_min:>10d} {cstd_max:>9d} {iou_min:>9.2f} | "
                          f"{tp_keep:>4d}/{len(tps):2d} ({tp_pct:4.0f}%) "
                          f"{fp_focus_supr:>4d}/{len(fps_focus):2d} ({fp_foco_pct:4.0f}%)   "
                          f"{base_supr:>4d}/{len(baselines):2d}        | "
                          f"{fp_poda_supr:>4d}/{len(fps_poda):2d}", flush=True)

    if best:
        print(f"\n=== Melhor combo ===")
        print(f"  passes if: n_active >= {best['na']} AND centroid_std <= {best['cs']} AND iou_mean >= {best['io']}")
        print(f"  TP keep: {best['tk']}/{len(tps)} ({best['tpp']:.0f}%)")
        print(f"  FP foco supr: {best['ffs']}/{len(fps_focus)} ({best['fpp']:.0f}%)")
        print(f"  Baseline supr: {best['bs']}/{len(baselines)}")
        print(f"  FP poda supr: {best['fps']}/{len(fps_poda)} (informativo)")

    with (out_dir / "summary_v2.json").open("w", encoding="utf-8") as f:
        json.dump({"best": best,
                   "n": {"tp": len(tps), "fp_focus": len(fps_focus),
                         "fp_poda": len(fps_poda), "baseline": len(baselines)}},
                  f, ensure_ascii=False, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
