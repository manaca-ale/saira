#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shadow B — poder discriminante do structural-delta (census_ntiles_t32) na pi-cam-001.

Reusa o PRÓPRIO código de produção (`worker.detector_structural.score_window`) sobre o
dataset oficial `cam_picam001`, de modo que o threshold calibrado aqui transfere 1:1 para
o hook de prod (mesmo census, mesmos TILE=32/FRAC=0.50/HAM_THR=3/MIN_COVER=24, mesma regra
`should_reject = n_tiles_changed < thr`).

Janela por evento = `sorted(evt/frames/*.jpg)` (ordenação lexicográfica == cronológica,
idêntico ao caminho event-driven da prod / bench_picam.py). score_window varre o 1º/último
frame LEGÍVEL e conta os tiles census-changed dentro do pile_zone_polygon.

Alvo PRIMÁRIO de calibração = TP vs FP (o set que o shadow de prod verá: só dispara em
`disposal=True` = detecções que o pipeline 2.5 CONFIRMOU = TP+FP). `baseline` (negativos
verdadeiros, não vistos pelo shadow) e `indefinido` são reportados à parte.

Saídas:
  results/struct_picam_signals.csv  — 1 linha/evento (event_id, category, n_tiles_changed, ...)
  results/struct_picam_roc.json     — AUC + IC + sweep de threshold + holdout + permutação

Uso:
  python scripts/phase_struct_picam.py
"""
from __future__ import annotations
import csv, json, math, os, sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

ROOT = Path(r"c:\saira")
HERE = Path(__file__).resolve().parent.parent
CAM = ROOT / "data" / "datasets" / "official" / "cam_picam001"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)
SIGNALS_CSV = RESULTS / "struct_picam_signals.csv"
ROC_JSON = RESULTS / "struct_picam_roc.json"

# Polígono VIGENTE em prod (SELECT pile_zone_polygon FROM cameras WHERE device_id='pi-cam-001',
# 22/07/2026 — fonte de verdade; difere do valor desatualizado no handoff). Ref 1280×720.
PILE_POLY = [
    [[18, 550], [12, 709], [1264, 709], [1262, 540]],
    [[325, 3], [288, 73], [1191, 162], [1167, 8]],
]

RECALL_FLOOR = 0.85  # mesmo floor da camp 41 (rejeita ~0..15% de TP)

# ── Import do código de PROD (bypass do gating de modo/câmera via score_window) ──────
# Defaults defensivos p/ o import de worker.config não falhar fora do container.
os.environ.setdefault("STATE_DIR", str(HERE / "results" / "_state_tmp"))
os.environ.setdefault("DATABASE_URL", "postgresql://bench:bench@localhost/bench")
sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
import worker.detector_structural as ds  # noqa: E402
import worker.config as cfg  # noqa: E402

CATEGORIES = ["tp", "fp", "indefinido", "baseline"]


def load_datetime(evt_dir: Path) -> str:
    """created_at do evento (para holdout temporal). Preferir label.json; fallback = nome."""
    lj = evt_dir / "label.json"
    if lj.exists():
        try:
            d = json.loads(lj.read_text(encoding="utf-8"))
            if d.get("datetime"):
                return str(d["datetime"])
        except Exception:
            pass
    # evt-YYYYMMDD_HHMMSS
    stem = evt_dir.name.replace("evt-", "")
    return stem


def score_all() -> list[dict]:
    rows: list[dict] = []
    for cat in CATEGORIES:
        cdir = CAM / cat
        if not cdir.exists():
            continue
        for evt in sorted(cdir.glob("evt-*")):
            frames = sorted((evt / "frames").glob("*.jpg"))
            res = ds.score_window(frames, PILE_POLY)
            rows.append({
                "event_id": evt.name,
                "category": cat,
                "n_tiles_changed": int(res.n_tiles_changed),
                "reason": res.reason,
                "n_frames": len(frames),
                "n_frames_used": int(res.n_frames_used),
                "latency_ms": round(res.latency_ms, 1),
                "datetime": load_datetime(evt),
            })
    return rows


# ── métricas (espelham phase_struct_roc.py da camp 41) ───────────────────────────────
def auc_score(pos: np.ndarray, neg: np.ndarray) -> float:
    """AUC = P(score_pos > score_neg) via Mann-Whitney U (empates = 0.5). Higher = TP-like."""
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    n_gt = 0.0
    for p in pos:
        n_gt += float(np.sum(p > neg)) + 0.5 * float(np.sum(p == neg))
    return n_gt / (len(pos) * len(neg))


def bootstrap_ci(pos: np.ndarray, neg: np.ndarray, n: int = 5000, seed: int = 42):
    rng = np.random.default_rng(seed)
    aucs = []
    for _ in range(n):
        bp = rng.choice(pos, size=len(pos), replace=True)
        bn = rng.choice(neg, size=len(neg), replace=True)
        aucs.append(auc_score(bp, bn))
    lo, hi = np.percentile(aucs, [2.5, 97.5])
    return float(lo), float(hi)


def sweep_veto(tp: np.ndarray, fp: np.ndarray, floor: float):
    """Regra de prod: KEEP se n_tiles >= thr (reject se < thr). Entre os thr que mantêm
    >= floor dos TP, escolhe o que mais SUPRIME FP. Varre todos os valores observados."""
    n_tp = len(tp)
    min_keep = math.ceil(floor * n_tp)
    cand = sorted(set(int(v) for v in np.concatenate([tp, fp])) | {0})
    best = None
    for thr in cand:
        tp_keep = int(np.sum(tp >= thr))
        if tp_keep < min_keep:
            continue
        fp_supp = int(np.sum(fp < thr))
        rec = {
            "threshold": int(thr),
            "tp_keep": tp_keep, "tp_keep_pct": round(100 * tp_keep / n_tp, 1),
            "tp_reject": int(n_tp - tp_keep),
            "fp_supp": fp_supp, "fp_supp_pct": round(100 * fp_supp / len(fp), 1),
        }
        if best is None or fp_supp > best["fp_supp"] or (
            fp_supp == best["fp_supp"] and thr > best["threshold"]):
            best = rec
    return best


def full_sweep_table(tp: np.ndarray, fp: np.ndarray, base: np.ndarray):
    n_tp, n_fp, n_base = len(tp), len(fp), max(len(base), 1)
    rows = []
    for thr in range(0, int(max(tp.max() if len(tp) else 0, fp.max() if len(fp) else 0)) + 2):
        rows.append({
            "threshold": thr,
            "tp_keep_pct": round(100 * np.sum(tp >= thr) / n_tp, 1) if n_tp else None,
            "fp_supp_pct": round(100 * np.sum(fp < thr) / n_fp, 1) if n_fp else None,
            "baseline_supp_pct": round(100 * np.sum(base < thr) / n_base, 1) if len(base) else None,
        })
    return rows


def temporal_holdout(rows_tp, rows_fp, floor: float):
    """Ordena por datetime, treina o veto em 60% e aplica em 40% (checagem de colapso)."""
    both = sorted(rows_tp + rows_fp, key=lambda r: r["datetime"])
    if len(both) < 10:
        return {"skipped": "N<10"}
    cut = int(len(both) * 0.6)
    train, test = both[:cut], both[cut:]
    tr_tp = np.array([r["n_tiles_changed"] for r in train if r["category"] == "tp"])
    tr_fp = np.array([r["n_tiles_changed"] for r in train if r["category"] == "fp"])
    te_tp = np.array([r["n_tiles_changed"] for r in test if r["category"] == "tp"])
    te_fp = np.array([r["n_tiles_changed"] for r in test if r["category"] == "fp"])
    if len(tr_tp) == 0 or len(tr_fp) == 0 or len(te_tp) == 0 or len(te_fp) == 0:
        return {"skipped": "split degenerado (uma classe vazia)"}
    veto = sweep_veto(tr_tp, tr_fp, floor)
    thr = veto["threshold"] if veto else 0
    return {
        "cut_datetime": test[0]["datetime"],
        "train_auc": round(auc_score(tr_tp, tr_fp), 4),
        "test_auc": round(auc_score(te_tp, te_fp), 4),
        "train_thr": thr,
        "test_tp_keep_pct": round(100 * np.sum(te_tp >= thr) / len(te_tp), 1),
        "test_fp_supp_pct": round(100 * np.sum(te_fp < thr) / len(te_fp), 1),
        "n_train_tp": len(tr_tp), "n_train_fp": len(tr_fp),
        "n_test_tp": len(te_tp), "n_test_fp": len(te_fp),
    }


def permutation(tp: np.ndarray, fp: np.ndarray, n: int = 2000, seed: int = 42):
    rng = np.random.default_rng(seed)
    obs = auc_score(tp, fp)
    allv = np.concatenate([tp, fp])
    n_tp = len(tp)
    perm = []
    for _ in range(n):
        rng.shuffle(allv)
        perm.append(auc_score(allv[:n_tp], allv[n_tp:]))
    perm = np.array(perm)
    return {
        "obs_auc": round(obs, 4),
        "perm_mean": round(float(perm.mean()), 4),
        "perm_p95": round(float(np.percentile(perm, 95)), 4),
        "p_value": round(float(np.mean(perm >= obs)), 4),
    }


def main():
    print(f"config prod: TILE={cfg.STRUCTURAL_TILE} FRAC={cfg.STRUCTURAL_TILE_FRAC} "
          f"HAM_THR={cfg.STRUCTURAL_HAM_THR} MIN_COVER={cfg.STRUCTURAL_MIN_TILE_COVER}")
    rows = score_all()

    with SIGNALS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[signals] {len(rows)} eventos -> {SIGNALS_CSV.relative_to(ROOT)}")

    by = {c: [r for r in rows if r["category"] == c] for c in CATEGORIES}
    scored = {c: [r for r in by[c] if r["reason"] == "scored"] for c in CATEGORIES}
    for c in CATEGORIES:
        skipped = [r for r in by[c] if r["reason"] != "scored"]
        print(f"  {c}: {len(scored[c])}/{len(by[c])} scored"
              + (f"  (skip: {[(r['event_id'], r['reason']) for r in skipped]})" if skipped else ""))

    tp = np.array([r["n_tiles_changed"] for r in scored["tp"]])
    fp = np.array([r["n_tiles_changed"] for r in scored["fp"]])
    base = np.array([r["n_tiles_changed"] for r in scored["baseline"]])
    indef = np.array([r["n_tiles_changed"] for r in scored["indefinido"]])

    def stats(a):
        if len(a) == 0:
            return {}
        return {"n": len(a), "min": int(a.min()), "median": float(np.median(a)),
                "mean": round(float(a.mean()), 2), "max": int(a.max())}

    auc_tp_fp = auc_score(tp, fp)
    ci = bootstrap_ci(tp, fp)
    veto = sweep_veto(tp, fp, RECALL_FLOOR)
    hold = temporal_holdout(scored["tp"], scored["fp"], RECALL_FLOOR)
    perm = permutation(tp, fp)
    # bônus: separação vs baseline (especificidade limpa)
    auc_tp_base = auc_score(tp, base) if len(base) else None

    out = {
        "dataset": "cam_picam001",
        "polygon_source": "prod DB cameras.pile_zone_polygon (2026-07-22)",
        "polygon": PILE_POLY,
        "frame_resolution": "1280x720 (todos os 122 eventos)",
        "config": {"tile": cfg.STRUCTURAL_TILE, "tile_frac": cfg.STRUCTURAL_TILE_FRAC,
                   "ham_thr": cfg.STRUCTURAL_HAM_THR, "min_cover": cfg.STRUCTURAL_MIN_TILE_COVER,
                   "recall_floor": RECALL_FLOOR},
        "counts_scored": {c: len(scored[c]) for c in CATEGORIES},
        "signal_stats": {"tp": stats(tp), "fp": stats(fp),
                         "baseline": stats(base), "indefinido": stats(indef)},
        "primary_tp_vs_fp": {
            "auc": round(auc_tp_fp, 4),
            "auc_ci95": [round(ci[0], 4), round(ci[1], 4)],
            "recall_safe_veto": veto,
            "temporal_holdout": hold,
            "permutation": perm,
        },
        "bonus_tp_vs_baseline_auc": round(auc_tp_base, 4) if auc_tp_base is not None else None,
        "sweep_table": full_sweep_table(tp, fp, base),
        "gate": {
            "criteria": "AUC>=0.75 AND CI_low>0.5 AND existe threshold recall-safe (>=85% TP) que suprime FP",
            "auc_pass": bool(auc_tp_fp >= 0.75),
            "ci_pass": bool(ci[0] > 0.5),
            "verdict": None,  # preenchido abaixo
        },
    }
    g = out["gate"]
    g["verdict"] = "PASS" if (g["auc_pass"] and g["ci_pass"] and veto and veto["fp_supp"] > 0) else "FAIL"
    ROC_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== TP vs FP (alvo primário) ===")
    print(f"  AUC = {auc_tp_fp:.4f}  IC95 [{ci[0]:.3f}, {ci[1]:.3f}]")
    print(f"  sinal TP: {stats(tp)}")
    print(f"  sinal FP: {stats(fp)}")
    print(f"  sinal baseline: {stats(base)}   (AUC TP-vs-baseline = {auc_tp_base})")
    print(f"  veto recall-safe (>= {int(RECALL_FLOOR*100)}% TP): {veto}")
    print(f"  holdout temporal: {hold}")
    print(f"  permutação: {perm}")
    print(f"\n  >>> GATE: {g['verdict']}  (AUC>=0.75:{g['auc_pass']} CI_low>0.5:{g['ci_pass']})")
    print(f"[roc] -> {ROC_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
