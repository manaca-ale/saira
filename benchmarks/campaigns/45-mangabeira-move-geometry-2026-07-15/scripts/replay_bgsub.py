#!/usr/bin/env python3
"""Camp 45 — replay BGSUB esp32_002 pós-mudança (sweep estático + replay sequencial).

Semântica prod-exata via worker.bgsub_filter real (mesmo caminho da camp 39):
por frame fg = MOG2(lr=0) > shadow_thr → morpho open_close → AND zona → gate
min_px_active(800); janela: votes >= round(mf*N) → persistence_px < thr ⇒ suprime.

Modos:
  sweep   — braços {prod,fresh} npz × {current,proposed} zona (estático; lr=0 ⇒
            janelas independentes) × grid mf × thr, sobre CONF/REJ/TRIG_NOLABEL
            (todos os dias) + NEG do --neg-day. Critério: 0 CONF suprimidas.
  replay  — sequencial dias 10..15, STATIC vs ADAPT (absorção lr=0.05 quando o
            gate disse "sem lixo novo" — BGSUB_ADAPTIVE_MIN_CONFIDENCE=0 em prod);
            --enforce simula semântica enforce (janela suprimida não absorve).

Frames: tmp/mangabeira_move/day{09..15} (nomes = timestamp BRT naive, 5s).
Braço fresh: baseline = 120 frames de 07-10 00-03h BRT; avalia só first>=07-10_03
(sem vazamento). Braço prod: npz de prod baixado 15/07 (state/), avalia tudo.
Janelas de 07-09 anteriores à mudança física ficam fora das métricas headline
(dia misto) — o sweep as marca com day=09.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import warnings
from collections import defaultdict
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

HERE = Path(__file__).resolve().parent.parent
DATA = ROOT / "tmp" / "mangabeira_move"
MODELS_DIR = HERE / "models"
MODELS_DIR.mkdir(exist_ok=True)
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

# ── prod-exact config (runtime esp32_002 verificado 15/07) ──────────────────
cfg.BGSUB_PREFILTER_ENABLED = True
cfg.BGSUB_MORPHO_MODE = "open_close"
cfg.BGSUB_SHADOW_THRESHOLD = 100
cfg.BGSUB_MIN_PX_ACTIVE = 800
cfg.BGSUB_BBOX_CROP_ENABLED = False
cfg.BGSUB_DUAL_RATE_ENABLED = False
cfg.BGSUB_MODELS_DIR = str(MODELS_DIR)
cfg.BGSUB_MOG2_VAR_THRESHOLD = 40.0
cfg.BGSUB_MOG2_HISTORY = 80

PROD_NPZ = DATA / "state" / "esp32_002_prod_20260715.npz"
FRESH_BASE_HOURS = ("2026-07-10_00", "2026-07-10_03")   # BRT [00h,03h)
FRESH_EVAL_MIN_FIRST = "2026-07-10_03"                   # sem vazamento
ADAPT_LR = 0.05

MIN_FRAMES_GRID = [0.05, 0.10, 0.20, 0.30, 0.40, 0.60]
THRESHOLD_GRID = [50, 100, 200, 400, 700, 1000, 1500, 2500, 5000]
# BGSUB_MIN_PX_ACTIVE: gate de ruído POR FRAME — um frame com menos de min_px de
# foreground na zona contribui ZERO votos. O valor de prod (800) zera frames em
# que só a sacola depositada está presente (a essa distância ela tem centenas de
# px), o que explica frames_ok=2/43 na CONF 356f26ed. Varremos essa dimensão: os
# votos dependem só de min_px (não de mf/thr), então acumulamos um array de votos
# por min_px no mesmo passe de MOG2.
MIN_PX_GRID = [100, 200, 400, 800]

POLYGONS = json.loads((HERE / "polygons.json").read_text(encoding="utf-8"))
ZONES = {k: v for k, v in POLYGONS.items() if not k.startswith("_") and v}


def frame_index() -> tuple[dict[str, Path], list[str]]:
    idx: dict[str, Path] = {}
    for d in sorted(DATA.glob("day*")):
        if d.is_dir():
            for p in d.rglob("*.jpg"):
                idx[p.name] = p
    return idx, sorted(idx)


def load_manifest() -> list[dict]:
    with (RESULTS / "manifest.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def window_names(names_sorted: list[str], lo: str, hi: str) -> list[str]:
    import bisect
    return names_sorted[bisect.bisect_left(names_sorted, lo):bisect.bisect_right(names_sorted, hi)]


def build_fresh_npz(fidx: dict[str, Path], names_sorted: list[str]) -> Path:
    out = MODELS_DIR / "fresh_base.npz"
    if out.exists():
        return out
    cand = [n for n in names_sorted if FRESH_BASE_HOURS[0] <= n < FRESH_BASE_HOURS[1]]
    if len(cand) < 40:
        raise RuntimeError(f"frames insuficientes p/ baseline fresh: {len(cand)}")
    step = max(1, len(cand) // 120)
    arrays = []
    for n in cand[::step][:120]:
        img = cv2.imread(str(fidx[n]))
        if img is not None:
            arrays.append(img)
    np.savez_compressed(str(out), frames=np.stack(arrays, axis=0))
    print(f"fresh baseline: {out.name} n={len(arrays)} ({cand[0]}..{cand[-1]})", flush=True)
    return out


def get_model(device_key: str, npz_src: Path):
    dst = MODELS_DIR / f"{device_key}.npz"
    if dst.exists():
        dst.unlink()
    shutil.copyfile(npz_src, dst)
    bgs.invalidate_cache(device_key)
    ent = bgs._cache.get_models(device_key, bgs._resolved_config(None))
    if ent is None:
        raise RuntimeError(f"model build failed: {device_key}")
    return ent


def window_votes_multi(names, fidx, ent, masks: dict, morph_kernel) -> tuple[dict, int]:
    """Votos por (zona, min_px) numa única passada de MOG2. Retorna (votes, n_frames).

    Em single mode o apply usa learningRate=0.0 → NÃO muta o modelo, logo o fg de
    um frame independe de zona/min_px e o MOG2 (parte cara) roda 1× por frame. O
    gate min_px_active de evaluate() é por frame/zona: frame com fg in-zone <
    min_px contribui zero votos — por isso acumulamos um array de votos por
    min_px em vez de fixar o valor de prod.
    """
    votes = {(z, mp): None for z in masks for mp in MIN_PX_GRID}
    n = 0
    for nm in names:
        img = cv2.imread(str(fidx[nm]))
        if img is None:
            continue
        n += 1
        fg = bgs._apply_and_combine(ent, img, "single", int(cfg.BGSUB_SHADOW_THRESHOLD), morph_kernel)
        for z, mask in masks.items():
            rm = mask if img.shape[:2] == mask.shape else cv2.resize(
                mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
            iz = cv2.bitwise_and(fg, rm)
            px = int(np.count_nonzero(iz))
            if px == 0:
                continue
            b = (iz > 0).astype(np.uint16)
            for mp in MIN_PX_GRID:
                if px >= mp:
                    k = (z, mp)
                    votes[k] = b.copy() if votes[k] is None else votes[k] + b
    return votes, n


def window_fg_masks(names, fidx, ent, mask, morph_kernel):
    """fg in-zone por frame, uma zona, min_px de prod (usado pelo replay sequencial)."""
    fgm = []
    for nm in names:
        img = cv2.imread(str(fidx[nm]))
        if img is None:
            continue
        rm = mask if img.shape[:2] == mask.shape else cv2.resize(
            mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        fg = bgs._apply_and_combine(ent, img, "single", int(cfg.BGSUB_SHADOW_THRESHOLD), morph_kernel)
        iz = cv2.bitwise_and(fg, rm)
        fgm.append(iz > 0 if int(np.count_nonzero(iz)) >= int(cfg.BGSUB_MIN_PX_ACTIVE)
                   else np.zeros(iz.shape, dtype=bool))
    return fgm


def cmd_sweep(args) -> int:
    fidx, names_sorted = frame_index()
    man = load_manifest()
    fresh_npz = build_fresh_npz(fidx, names_sorted)

    wins = [r for r in man if r["label"] in ("CONF", "REJ", "TRIG_NOLABEL")]
    negs = [r for r in man if r["label"] == "NEG" and r["day"] == args.neg_day]
    if args.neg_sample and len(negs) > args.neg_sample:  # amostra determinística
        step = len(negs) / args.neg_sample
        negs = [negs[int(i * step)] for i in range(args.neg_sample)]
    wins += negs
    print(f"janelas no sweep: {len(wins)} "
          f"({sum(1 for w in wins if w['label']=='CONF')} CONF, "
          f"{sum(1 for w in wins if w['label']=='REJ')} REJ, "
          f"{sum(1 for w in wins if w['label']=='TRIG_NOLABEL')} TRIG, "
          f"{len(negs)} NEG day{args.neg_day}) | zonas: {list(ZONES)} | "
          f"min_px: {MIN_PX_GRID}", flush=True)

    baselines = {"prod": PROD_NPZ, "fresh": fresh_npz}
    morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    models = {b: get_model(f"c45_{b}", src) for b, src in baselines.items() if src.exists()}
    if "prod" not in models:
        print(f"AVISO: npz de prod ausente em {PROD_NPZ} — só braço fresh", flush=True)
    masks = {z: bgs._cache.get_mask(f"c45_zone_{z}", poly) for z, poly in ZONES.items()}

    rows = []
    for i, w in enumerate(wins):
        names = window_names(names_sorted, w["first"], w["last"])
        if len(names) < 5:
            continue
        for b, ent in models.items():
            if b == "fresh" and w["first"] < FRESH_EVAL_MIN_FIRST:
                continue
            votes, n = window_votes_multi(names, fidx, ent, masks, morph_kernel)
            for (z, mp), v in votes.items():
                for mf in MIN_FRAMES_GRID:
                    k = max(1, int(round(mf * n)))
                    p = 0 if v is None else int(np.count_nonzero(v >= k))
                    rows.append({"arm": f"{b}/{z}", "min_px": mp, "mf": mf,
                                 "request_id": w["request_id"], "label": w["label"],
                                 "day": w["day"], "det_id8": w["det_id8"],
                                 "persistence": p, "n_frames": n})
        if i % 25 == 0:
            print(f"  {i}/{len(wins)}", flush=True)

    with (RESULTS / "sweep_windows.csv").open("w", encoding="utf-8", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wtr.writeheader()
        wtr.writerows(rows)

    # agregação analítica (arm × min_px × mf × thr); por JANELA e por DETECÇÃO
    agg = []
    by_cfg = defaultdict(list)
    for r in rows:
        by_cfg[(r["arm"], r["min_px"], r["mf"])].append(r)
    for (arm, mp, mf), items in sorted(by_cfg.items()):
        for thr in THRESHOLD_GRID:
            c = defaultdict(lambda: [0, 0])
            # por detecção: sobrevive se QUALQUER janela dela passa (prod cria a
            # detecção na 1ª janela que escapa do filtro)
            det_pass = defaultdict(bool)
            det_label = {}
            for it in items:
                g = it["label"]
                c[g][1] += 1
                if it["persistence"] < thr:
                    c[g][0] += 1
                if it["det_id8"]:
                    det_pass[it["det_id8"]] |= (it["persistence"] >= thr)
                    det_label[it["det_id8"]] = g
            conf_det = [d for d, g in det_label.items() if g == "CONF"]
            rej_det = [d for d, g in det_label.items() if g == "REJ"]
            agg.append({"arm": arm, "min_px": mp, "mf": mf, "thr": thr,
                        **{f"{g.lower()}_sup": c[g][0] for g in ("CONF", "REJ", "TRIG_NOLABEL", "NEG")},
                        **{f"{g.lower()}_n": c[g][1] for g in ("CONF", "REJ", "TRIG_NOLABEL", "NEG")},
                        "conf_det_lost": sum(1 for d in conf_det if not det_pass[d]),
                        "conf_det_n": len(conf_det),
                        "rej_det_killed": sum(1 for d in rej_det if not det_pass[d]),
                        "rej_det_n": len(rej_det)})
    (RESULTS / "sweep_45.json").write_text(json.dumps(agg, indent=2), encoding="utf-8")

    print("\n=== POR DETECÇÃO: 0 confirmadas perdidas, ordenado por rejeitadas mortas ===", flush=True)
    safe = [a for a in agg if a["conf_det_lost"] == 0 and a["conf_det_n"] > 0 and a["rej_det_killed"] > 0]
    safe.sort(key=lambda a: (-a["rej_det_killed"], -a["neg_sup"]))
    for a in safe[:25]:
        print(f"  {a['arm']:18} min_px={a['min_px']:>4} mf={a['mf']:.2f} thr={a['thr']:>5} | "
              f"CONF perdidas 0/{a['conf_det_n']} | REJ mortas {a['rej_det_killed']}/{a['rej_det_n']} "
              f"({a['rej_det_killed']/max(1,a['rej_det_n']):.0%}) | "
              f"TRIG jan {a['trig_nolabel_sup']}/{a['trig_nolabel_n']} | "
              f"NEG jan {a['neg_sup']}/{a['neg_n']} ({a['neg_sup']/max(1,a['neg_n']):.0%})", flush=True)
    if not safe:
        print("  (NENHUMA config segura mata rejeitadas — BGSUB inviável nesta cena)", flush=True)
    return 0


def cmd_replay(args) -> int:
    fidx, names_sorted = frame_index()
    man = load_manifest()
    fresh_npz = build_fresh_npz(fidx, names_sorted)
    zone = ZONES[args.zone]
    thr, mf = args.thr, args.mf

    wins = [r for r in man if r["first"] >= FRESH_EVAL_MIN_FIRST]
    wins.sort(key=lambda r: r["first"])
    print(f"replay sequencial: {len(wins)} janelas >= {FRESH_EVAL_MIN_FIRST} | "
          f"zona={args.zone} thr={thr} mf={mf} enforce={args.enforce}", flush=True)

    morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    models = {p: get_model(f"c45_replay_{p}", fresh_npz) for p in ("STATIC", "ADAPT")}
    mask = bgs._cache.get_mask("c45_replay_zone", zone)

    rows = []
    for i, w in enumerate(wins):
        names = window_names(names_sorted, w["first"], w["last"])
        if len(names) < 5:
            continue
        rec = {"request_id": w["request_id"], "first": w["first"], "label": w["label"],
               "det_id8": w["det_id8"], "n": len(names)}
        for pol, ent in models.items():
            fgm = window_fg_masks(names, fidx, ent, mask, morph_kernel)
            n = len(fgm)
            votes = np.stack(fgm, axis=0).sum(axis=0) if fgm else None
            k = max(1, int(round(mf * n))) if n else 1
            p = int(np.count_nonzero(votes >= k)) if votes is not None else 0
            rec[pol] = p
            rec[f"{pol}_sup"] = p < thr
            if pol == "ADAPT":
                # absorção prod: gate disse "sem lixo novo" (MIN_CONFIDENCE=0 em prod);
                # em enforce, janela suprimida retorna antes do gate ⇒ não absorve
                litter = str(w["agent1_litter"]).lower() == "true"
                suppressed_here = args.enforce and rec["ADAPT_sup"]
                if not litter and not suppressed_here:
                    for nm in names:
                        img = cv2.imread(str(fidx[nm]))
                        if img is not None:
                            ent.apply(img, learningRate=ADAPT_LR)
        rows.append(rec)
        if i % 40 == 0:
            print(f"  {i}/{len(wins)} {w['first'][5:16]} STATIC={rec['STATIC']} ADAPT={rec['ADAPT']}", flush=True)

    suffix = "_enforce" if args.enforce else ""
    (RESULTS / f"replay_{args.zone}_thr{thr}_mf{mf}{suffix}.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8")

    tot = len(rows)
    print(f"\nTOTAL suprimidas: STATIC {sum(r['STATIC_sup'] for r in rows)}/{tot} | "
          f"ADAPT {sum(r['ADAPT_sup'] for r in rows)}/{tot}", flush=True)
    print("\n=== RECALL: CONF + TRIG_NOLABEL ===", flush=True)
    for r in rows:
        if r["label"] in ("CONF", "TRIG_NOLABEL"):
            tag = f"{r['label']} {r['det_id8']}"
            print(f"  {r['first'][5:16]} {tag:22} "
                  f"STATIC={'SUP!' if r['STATIC_sup'] else 'ok'}({r['STATIC']}) "
                  f"ADAPT={'SUP!' if r['ADAPT_sup'] else 'ok'}({r['ADAPT']})", flush=True)
    conf_sup = [(p, sum(1 for r in rows if r["label"] == "CONF" and r[f"{p}_sup"])) for p in ("STATIC", "ADAPT")]
    print(f"\nCONF suprimidas: {conf_sup} (criterio duro: 0)", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    sw = sub.add_parser("sweep")
    sw.add_argument("--neg-day", default="12")
    sw.add_argument("--neg-sample", type=int, default=120,
                    help="amostra determinística de janelas NEG (0 = todas)")
    rp = sub.add_parser("replay")
    rp.add_argument("--zone", default="proposed")
    rp.add_argument("--thr", type=int, default=1000)
    rp.add_argument("--mf", type=float, default=0.4)
    rp.add_argument("--enforce", action="store_true")
    args = ap.parse_args()
    return cmd_sweep(args) if args.mode == "sweep" else cmd_replay(args)


if __name__ == "__main__":
    sys.exit(main())
