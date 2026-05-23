#!/usr/bin/env python3
"""Spike — OpenCV background subtraction como pré-filtro para Gemini gate.

Hipótese: pode-se eliminar a maioria dos FPs "nada acontecendo" / "trânsito"
antes de chamar o LLM, usando apenas OpenCV + heurísticas geométricas:

1. Construir um modelo de fundo (MOG2) por câmera a partir dos frames de baseline.
2. Para cada janela de teste, aplicar bgsub aos N frames e medir:
   - foreground_in_pile_zone = quantidade de pixels mudados DENTRO da zona da pilha
   - foreground_outside_pile = quantidade fora da zona (proxy para tráfego)
   - persistence_in_pile_zone = pixels que ficam mudados em 3+ dos N frames
3. Heurística de "atividade real na pilha":
   - persistence >= MIN_PERSISTENCE (pixels estáveis na zona)
   - E foreground_in_pile_zone / total_foreground >= MIN_RATIO (mudança concentrada
     na pilha, não espalhada por trânsito)

Métricas:
- TPs preservados (não suprimidos) — quanto maior melhor
- FPs nada/trânsito suprimidos — quanto maior melhor
- Decisão: se TP recall mantém >= 90% E FP filtragem >= 50%, vale integrar.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(r"c:\saira")
DATASET = PROJECT_ROOT / "data" / "datasets" / "official"

# =============================================================================
# Zonas da pilha — polígonos definidos visualmente a partir dos frames baseline.
# Frame 1280x720. Coordenadas (x, y).
# =============================================================================
PILE_ZONES = {
    # Imbiribeira: terreno baldio aberto. Poste vertical no centro divide a cena.
    # A "pilha" é toda a área de chão/entulho da metade inferior — sem o poste.
    "cam_imbiribeira": [
        # Polígono cobrindo metade inferior, evitando o poste central (x≈600-780)
        np.array([
            (40, 280), (560, 280), (560, 720),
            (40, 720),
        ], dtype=np.int32),
        np.array([
            (800, 280), (1240, 280), (1240, 720),
            (800, 720),
        ], dtype=np.int32),
    ],
    # Mangabeira: pilha concentrada no canto da calçada (centro-direita).
    "cam_mangabeira": [
        np.array([
            (480, 60), (920, 60), (920, 340),
            (480, 340),
        ], dtype=np.int32),
    ],
}


@dataclass
class WindowScore:
    event_id: str
    camera: str
    category: str
    justificativa: str
    n_frames: int
    fg_in_pile: float       # media de pixels mudados na zona pilha (per frame)
    fg_outside_pile: float  # media fora da zona pilha
    persistence: float      # pixels mudados em >=60% dos frames, na zona pilha
    ratio_in_pile: float    # fg_in_pile / (fg_in_pile + fg_outside_pile)


def build_zone_mask(camera: str, shape: tuple[int, int]) -> np.ndarray:
    """Constrói máscara binária 0/255 da zona da pilha para a câmera."""
    mask = np.zeros(shape, dtype=np.uint8)
    for poly in PILE_ZONES[camera]:
        cv2.fillPoly(mask, [poly], 255)
    return mask


def build_bg_model(camera: str, n_frames: int = 80) -> cv2.BackgroundSubtractor:
    """Treina MOG2 com frames de baseline (mix day+night)."""
    bg = cv2.createBackgroundSubtractorMOG2(
        history=n_frames, varThreshold=40.0, detectShadows=True,
    )
    frames_used = 0
    for period in ("day", "night"):
        period_dir = DATASET / camera / "baseline" / period
        if not period_dir.exists():
            continue
        frames = sorted(period_dir.glob("*.jpg"))
        # Espaca para cobrir o periodo todo
        step = max(1, len(frames) // (n_frames // 2))
        for f in frames[::step][:n_frames // 2]:
            img = cv2.imread(str(f))
            if img is None:
                continue
            bg.apply(img)
            frames_used += 1
    print(f"  bg model {camera}: trained on {frames_used} frames", flush=True)
    return bg


def score_window(
    bg: cv2.BackgroundSubtractor,
    zone_mask: np.ndarray,
    frame_paths: list[Path],
    morph_kernel: np.ndarray,
) -> dict:
    """Calcula scores de foreground para uma janela.

    Não MUTA o bg model (clona por chamada se preciso — mas MOG2 não tem clone,
    então aceitamos um pouco de drift do modelo entre janelas)."""
    fg_in_zone_per_frame = []
    fg_outside_per_frame = []
    fg_masks = []

    for fp in frame_paths:
        img = cv2.imread(str(fp))
        if img is None:
            continue
        # learningRate=0 → não atualiza o modelo durante o teste
        fg_mask = bg.apply(img, learningRate=0)
        # MOG2 com detectShadows=True marca sombras como 127. Filtramos.
        fg_mask = (fg_mask > 200).astype(np.uint8) * 255
        # Morfologia: remove ruido pontual e fecha buracos pequenos
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, morph_kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, morph_kernel)

        in_zone = cv2.bitwise_and(fg_mask, zone_mask)
        outside = cv2.bitwise_and(fg_mask, cv2.bitwise_not(zone_mask))
        fg_in_zone_per_frame.append(int(np.count_nonzero(in_zone)))
        fg_outside_per_frame.append(int(np.count_nonzero(outside)))
        fg_masks.append(in_zone)

    fg_in_pile = float(np.mean(fg_in_zone_per_frame)) if fg_in_zone_per_frame else 0.0
    fg_outside_pile = float(np.mean(fg_outside_per_frame)) if fg_outside_per_frame else 0.0
    total = fg_in_pile + fg_outside_pile
    ratio = fg_in_pile / total if total > 0 else 0.0

    # Persistencia: pixels mudados em >=60% dos frames (na zona).
    if fg_masks:
        stack = np.stack(fg_masks, axis=0) > 0  # bool
        votes = stack.sum(axis=0)
        persistence_mask = votes >= max(1, int(0.6 * len(fg_masks)))
        persistence = int(np.count_nonzero(persistence_mask))
    else:
        persistence = 0

    return {
        "fg_in_pile": fg_in_pile,
        "fg_outside_pile": fg_outside_pile,
        "persistence": float(persistence),
        "ratio_in_pile": ratio,
        "n_frames_ok": len(fg_in_zone_per_frame),
    }


def sample_frames_from_window(frames_dir: Path) -> list[Path]:
    """Pega first + 3 mid + last (idêntico ao bench atual)."""
    all_frames = sorted(frames_dir.glob("*.jpg"))
    if len(all_frames) < 2:
        return all_frames
    if len(all_frames) < 5:
        return [all_frames[0], all_frames[-1]]
    n = len(all_frames)
    indices = sorted({0, n // 4, n // 2, 3 * n // 4, n - 1})
    return [all_frames[i] for i in indices]


def build_baseline_windows(camera: str, window_size: int = 12, per_series: int = 15) -> list[tuple[str, Path]]:
    """Replica a lógica de build_baseline_windows do bench oficial."""
    out = []
    for period in ("day", "night"):
        period_dir = DATASET / camera / "baseline" / period
        if not period_dir.exists():
            continue
        frames = sorted(period_dir.glob("*.jpg"))
        all_starts = list(range(0, len(frames) - window_size + 1, window_size))
        step = len(all_starts) / per_series
        indices = [all_starts[int(i * step)] for i in range(per_series)]
        for i, idx in enumerate(indices):
            window_frames = frames[idx:idx + window_size]
            # Salvar como "diretorio virtual" — usa indice como id
            out.append((f"baseline_{camera}_{period}_{i:03d}", window_frames))
    return out


def main() -> int:
    print("Spike — OpenCV bgsub pré-filtro\n", flush=True)

    # Carrega manifest oficial
    manifest_path = DATASET / "manifest.csv"
    events = []
    with manifest_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            events.append(row)
    print(f"Eventos no manifest: {len(events)}", flush=True)

    # Build bg model + zone mask por câmera
    bg_models = {}
    zone_masks = {}
    for camera in ("cam_imbiribeira", "cam_mangabeira"):
        print(f"\nTraining bg model: {camera}", flush=True)
        bg_models[camera] = build_bg_model(camera)
        zone_masks[camera] = build_zone_mask(camera, (720, 1280))

    morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    # Score eventos (TPs, FPs foco, indefinidos, missed)
    scores: list[WindowScore] = []
    print(f"\nScoring eventos...", flush=True)
    for i, row in enumerate(events, 1):
        if i % 30 == 0:
            print(f"  {i}/{len(events)}...", flush=True)
        local = DATASET / row["local_path"] / "frames"
        if not local.exists():
            continue
        frames = sample_frames_from_window(local)
        if len(frames) < 2:
            continue
        bg = bg_models[row["camera"]]
        zm = zone_masks[row["camera"]]
        s = score_window(bg, zm, frames, morph_kernel)
        scores.append(WindowScore(
            event_id=row["event_id"],
            camera=row["camera"],
            category=row["category"],
            justificativa=(row.get("justificativa") or "")[:80],
            n_frames=s["n_frames_ok"],
            fg_in_pile=s["fg_in_pile"],
            fg_outside_pile=s["fg_outside_pile"],
            persistence=s["persistence"],
            ratio_in_pile=s["ratio_in_pile"],
        ))

    # Score baselines
    print(f"\nScoring baselines (15/série × 4 séries = 60 windows)...", flush=True)
    for camera in ("cam_imbiribeira", "cam_mangabeira"):
        bg = bg_models[camera]
        zm = zone_masks[camera]
        for wid, frames in build_baseline_windows(camera, window_size=12, per_series=15):
            if len(frames) < 2:
                continue
            picked = sample_frames_from_window(frames[0].parent) if False else None
            # Manual sample 5 of these 12
            n = len(frames)
            indices = sorted({0, n // 4, n // 2, 3 * n // 4, n - 1})
            picked = [frames[i] for i in indices]
            s = score_window(bg, zm, picked, morph_kernel)
            scores.append(WindowScore(
                event_id=wid,
                camera=camera,
                category="baseline",
                justificativa="",
                n_frames=s["n_frames_ok"],
                fg_in_pile=s["fg_in_pile"],
                fg_outside_pile=s["fg_outside_pile"],
                persistence=s["persistence"],
                ratio_in_pile=s["ratio_in_pile"],
            ))

    # Classifica FPs em "foco" (nada/trânsito) vs "poda" (ignorar)
    poda_keywords = ["retirando", "coleta", "caminhão", "poda", "limpeza", "limpando"]
    def is_focus_fp(j: str) -> bool:
        jl = j.lower()
        if any(k in jl for k in poda_keywords):
            return False
        return True

    # Salvar CSV
    out_dir = PROJECT_ROOT / "tools" / "spike_bgsub_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "scores.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "camera", "category", "is_focus_fp",
                    "n_frames", "fg_in_pile", "fg_outside_pile", "persistence",
                    "ratio_in_pile", "justificativa"])
        for s in scores:
            focus = is_focus_fp(s.justificativa) if s.category == "fp" else False
            w.writerow([s.event_id, s.camera, s.category, focus,
                        s.n_frames, f"{s.fg_in_pile:.0f}",
                        f"{s.fg_outside_pile:.0f}", f"{s.persistence:.0f}",
                        f"{s.ratio_in_pile:.3f}", s.justificativa])

    print(f"\n  → {out_csv} ({len(scores)} rows)", flush=True)

    # Análise: avaliar threshold candidatos
    print("\n=== Análise de thresholds ===\n", flush=True)

    tps = [s for s in scores if s.category == "tp"]
    missed = [s for s in scores if s.category == "missed"]
    fps_focus = [s for s in scores if s.category == "fp" and is_focus_fp(s.justificativa)]
    fps_poda = [s for s in scores if s.category == "fp" and not is_focus_fp(s.justificativa)]
    baselines = [s for s in scores if s.category == "baseline"]

    print(f"N: TP={len(tps)} | missed={len(missed)} | "
          f"FP foco={len(fps_focus)} | FP poda={len(fps_poda)} | baseline={len(baselines)}")

    # Estatisticas das distribuicoes — pra escolher threshold
    def stats(label: str, items: list[WindowScore]):
        if not items:
            return
        vals = [s.persistence for s in items]
        ratios = [s.ratio_in_pile for s in items]
        print(f"\n  {label} (N={len(items)}):")
        print(f"    persistence (px na zona, em >=60% frames):"
              f"  min={min(vals):6.0f}  med={np.median(vals):6.0f}  max={max(vals):6.0f}")
        print(f"    ratio_in_pile (fg pilha / fg total):"
              f"        min={min(ratios):.2f}    med={np.median(ratios):.2f}    max={max(ratios):.2f}")

    stats("TP (esperado: persistence alta)", tps)
    stats("MISSED", missed)
    stats("FP FOCO (esperado: persistence baixa OU ratio baixo)", fps_focus)
    stats("FP poda (ignorar)", fps_poda)
    stats("BASELINE (esperado: tudo baixo)", baselines)

    # Grid search: thresholds candidatos
    print("\n=== Grid search de thresholds ===\n", flush=True)
    print(f"{'persist_thr':>12s} {'ratio_thr':>10s} | "
          f"{'TP keep':>10s} {'missed keep':>12s} | "
          f"{'FP foco supr':>14s} {'baseline supr':>14s} | {'FP poda':>10s}", flush=True)
    print("-" * 100)

    best = None
    for pthr in [50, 100, 200, 500, 1000, 2000, 5000, 10000]:
        for rthr in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
            def passes(s: WindowScore) -> bool:
                return s.persistence >= pthr and s.ratio_in_pile >= rthr

            tp_keep = sum(1 for s in tps if passes(s))
            ms_keep = sum(1 for s in missed if passes(s))
            fp_focus_supr = sum(1 for s in fps_focus if not passes(s))
            base_supr = sum(1 for s in baselines if not passes(s))
            fp_poda_supr = sum(1 for s in fps_poda if not passes(s))

            tp_pct = tp_keep / max(1, len(tps)) * 100
            fp_foco_pct = fp_focus_supr / max(1, len(fps_focus)) * 100

            # Critério: TP mantém >=90% E FP foco suprime >=50%
            score_metric = tp_pct + fp_foco_pct
            if best is None or score_metric > best["score"]:
                best = {
                    "score": score_metric, "pthr": pthr, "rthr": rthr,
                    "tp_keep": tp_keep, "ms_keep": ms_keep,
                    "fp_focus_supr": fp_focus_supr, "base_supr": base_supr,
                    "fp_poda_supr": fp_poda_supr,
                    "tp_pct": tp_pct, "fp_foco_pct": fp_foco_pct,
                }
            # imprimir apenas linhas onde TP >= 80% pra reduzir poluição
            if tp_pct >= 80.0:
                print(f"{pthr:>12d} {rthr:>10.2f} | "
                      f"{tp_keep:>4d}/{len(tps):2d} ({tp_pct:4.0f}%) "
                      f"{ms_keep:>4d}/{len(missed):2d}      | "
                      f"{fp_focus_supr:>4d}/{len(fps_focus):2d} ({fp_foco_pct:4.0f}%)   "
                      f"{base_supr:>4d}/{len(baselines):2d}        | "
                      f"{fp_poda_supr:>4d}/{len(fps_poda):2d}", flush=True)

    if best:
        print(f"\n=== Melhor threshold candidato ===")
        print(f"  persistence >= {best['pthr']} pixels AND ratio_in_pile >= {best['rthr']}")
        print(f"  TP keep: {best['tp_keep']}/{len(tps)} ({best['tp_pct']:.0f}%)")
        print(f"  FP foco suprimidos: {best['fp_focus_supr']}/{len(fps_focus)} ({best['fp_foco_pct']:.0f}%)")
        print(f"  Baseline suprimidos: {best['base_supr']}/{len(baselines)}")
        print(f"  FP poda suprimidos: {best['fp_poda_supr']}/{len(fps_poda)} (informativo)")

    # Salva resultado
    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump({
            "n": {"tp": len(tps), "missed": len(missed),
                  "fp_focus": len(fps_focus), "fp_poda": len(fps_poda),
                  "baseline": len(baselines)},
            "best_threshold": best,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  → {out_dir / 'summary.json'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
