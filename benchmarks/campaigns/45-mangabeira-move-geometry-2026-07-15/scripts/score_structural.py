#!/usr/bin/env python3
"""Camp 45 — structural-delta à distância: sinais + separabilidade CONF vs REJ.

Importa worker.detector_structural.score_window direto (paridade prod comprovada
na camp 41) e pontua cada janela rotulada (1º-vs-último frame legível dentro do
polígono) com STRUCTURAL_TILE ∈ {32, 16} — na cena nova (câmera distante) o
depósito pode tocar < 2 tiles de 32px, o que mataria o veto thr=2; t16 é o
candidato de resgate.

Saídas:
  results/struct_signals_45.csv  — det_id8, bucket(CONF/REJ), first, ntiles_t32,
                                   ntiles_t16, reason, zona
  results/struct_roc_45.json + stdout — AUC (keep CONF vs REJ), bootstrap CI,
  sweep de veto com piso de recall 100% (12/12) e 90%, holdout temporal por dia.
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

import numpy as np  # noqa: E402

ROOT = Path(r"c:\saira")
sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
import worker.config as wcfg  # noqa: E402
from worker import detector_structural as ds  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
DATA = ROOT / "tmp" / "mangabeira_move"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)
RNG = np.random.default_rng(42)

# prod-exact (defaults do código; compose não passa esses params)
wcfg.STRUCTURAL_HAM_THR = 3
wcfg.STRUCTURAL_TILE_FRAC = 0.50
wcfg.STRUCTURAL_MIN_TILE_COVER = 24

POLYGONS = json.loads((HERE / "polygons.json").read_text(encoding="utf-8"))
ZONE_KEY = sys.argv[1] if len(sys.argv) > 1 else "proposed"
ZONE = POLYGONS.get(ZONE_KEY)
if not ZONE:
    raise SystemExit(f"polygons.json não tem '{ZONE_KEY}' preenchido")

TILES = (32, 16)


def frame_index():
    idx = {}
    for d in sorted(DATA.glob("day*")):
        if d.is_dir():
            for p in d.rglob("*.jpg"):
                idx[p.name] = p
    return idx, sorted(idx)


def window_names(names_sorted, lo, hi):
    import bisect
    return names_sorted[bisect.bisect_left(names_sorted, lo):bisect.bisect_right(names_sorted, hi)]


def score_all() -> list[dict]:
    fidx, names_sorted = frame_index()
    with (RESULTS / "manifest.csv").open(encoding="utf-8") as fh:
        man = [r for r in csv.DictReader(fh) if r["label"] in ("CONF", "REJ")]
    print(f"{len(man)} janelas rotuladas | zona={ZONE_KEY} tiles={TILES}", flush=True)

    rows = []
    for i, w in enumerate(man):
        names = window_names(names_sorted, w["first"], w["last"])
        paths = [fidx[n] for n in names]
        rec = {"det_id8": w["det_id8"], "bucket": w["label"], "first": w["first"], "zona": ZONE_KEY}
        for tile in TILES:
            wcfg.STRUCTURAL_TILE = tile
            res = ds.score_window(paths, ZONE)
            rec[f"ntiles_t{tile}"] = res.n_tiles_changed
            rec[f"reason_t{tile}"] = res.reason
        rows.append(rec)
        if i % 20 == 0:
            print(f"  {i}/{len(man)}", flush=True)

    with (RESULTS / f"struct_signals_45_{ZONE_KEY}.csv").open("w", encoding="utf-8", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wtr.writeheader()
        wtr.writerows(rows)
    return rows


def veto_sweep(conf, rej, floor):
    """veto: rejeita se ntiles < thr. Max REJ mortas s.t. CONF preservadas >= floor."""
    best = None
    need = int(np.ceil(floor * len(conf)))
    for thr in range(0, int(max(conf.max(initial=0), rej.max(initial=0))) + 2):
        conf_keep = int((conf >= thr).sum())
        rej_kill = int((rej < thr).sum())
        if conf_keep >= need and (best is None or rej_kill > best["rej_kill"]):
            best = {"thr": thr, "conf_keep": conf_keep, "conf_n": len(conf),
                    "rej_kill": rej_kill, "rej_n": len(rej),
                    "rej_kill_pct": rej_kill / max(1, len(rej))}
    return best


def analyze(rows) -> None:
    from sklearn.metrics import roc_auc_score
    out = {}
    for tile in TILES:
        sig = f"ntiles_t{tile}"
        ok = [r for r in rows if r[f"reason_t{tile}"] == "scored"]
        conf = np.array([r[sig] for r in ok if r["bucket"] == "CONF"], dtype=float)
        rej = np.array([r[sig] for r in ok if r["bucket"] == "REJ"], dtype=float)
        if not len(conf) or not len(rej):
            print(f"t{tile}: sem dados ({len(conf)} CONF / {len(rej)} REJ scored)", flush=True)
            continue
        y = np.r_[np.ones(len(conf)), np.zeros(len(rej))]
        auc = roc_auc_score(y, np.r_[conf, rej])
        aucs = []
        for _ in range(5000):
            i = RNG.integers(0, len(conf), len(conf))
            j = RNG.integers(0, len(rej), len(rej))
            try:
                aucs.append(roc_auc_score(y, np.r_[conf[i], rej[j]]))
            except ValueError:
                pass
        lo, hi = np.percentile(aucs, [2.5, 97.5])
        v100 = veto_sweep(conf, rej, 1.0)
        v90 = veto_sweep(conf, rej, 0.9)

        # holdout temporal: treina dias 09-12, testa 13-15
        cut = "2026-07-13"
        tr = [r for r in ok if r["first"] < cut]
        te = [r for r in ok if r["first"] >= cut]
        ho = {}
        tr_c = np.array([r[sig] for r in tr if r["bucket"] == "CONF"], dtype=float)
        tr_r = np.array([r[sig] for r in tr if r["bucket"] == "REJ"], dtype=float)
        te_c = np.array([r[sig] for r in te if r["bucket"] == "CONF"], dtype=float)
        te_r = np.array([r[sig] for r in te if r["bucket"] == "REJ"], dtype=float)
        fit = veto_sweep(tr_c, tr_r, 1.0) if len(tr_c) and len(tr_r) else None
        if fit and len(te_r):
            ho = {"train_thr": fit["thr"],
                  "test_conf_keep": f"{int((te_c >= fit['thr']).sum())}/{len(te_c)}",
                  "test_rej_kill": f"{int((te_r < fit['thr']).sum())}/{len(te_r)}"}

        print(f"\n=== t{tile} (n scored: {len(conf)} CONF / {len(rej)} REJ) ===", flush=True)
        print(f"  CONF ntiles: min={conf.min():.0f} p50={np.median(conf):.0f} max={conf.max():.0f}", flush=True)
        print(f"  REJ  ntiles: min={rej.min():.0f} p50={np.median(rej):.0f} max={rej.max():.0f}", flush=True)
        print(f"  AUC(keep CONF)={auc:.3f} CI95=[{lo:.3f},{hi:.3f}]", flush=True)
        print(f"  veto@100% CONF: {v100}", flush=True)
        print(f"  veto@90%  CONF: {v90}", flush=True)
        print(f"  holdout (cut {cut}): {ho}", flush=True)
        out[f"t{tile}"] = {"auc": float(auc), "ci": [float(lo), float(hi)],
                           "veto_100": v100, "veto_90": v90, "holdout": ho,
                           "conf_values": conf.tolist(), "rej_p50": float(np.median(rej))}

    (RESULTS / f"struct_roc_45_{ZONE_KEY}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {RESULTS / 'struct_roc_45.json'}", flush=True)


def main() -> int:
    rows = score_all()
    analyze(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
