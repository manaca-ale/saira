#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Camp 43 — Persistence-by-vote vs first-vs-last structural-delta (Mangabeira).

Tests Proposta #1 (persistência tile-level por majority-vote) against the deployed
first-vs-last census_ntiles_t32, with a TEMPORAL split stratified by FP subtype
(Proposta #2 harness). All offline, $0, reuses Camp 41 census + Camp 42 frames.

Signal definitions (pile-zone polygon esp32_002, tile=32, HAM_THR=3, frac>0.50):
  - census_ntiles_t32 (DEPLOYED): #tiles changed between frame[0] and frame[-1].
  - persist_pXX (NEW): baseline=frame[0]; over the 2nd half of frames, a tile is
    "persistently changed" if it is census-changed vs baseline in >= XX% of those
    frames. score = #persistent tiles. Rationale: a deposited object stays changed
    every late frame (persists); a person standing/rummaging occupies a tile only
    transiently (reverts) -> not counted -> the residual FP the 2-frame signal misses.

Detection logic (matches production detector_structural): suppress (reject the CON)
when score < threshold T. So for keep(TP) we want score>=T (recall); for kill(FP)
we want score<T (fp_supp). recall decreases in T, fp_supp increases in T.
"""
from __future__ import annotations
import csv, json, sys
from pathlib import Path
import numpy as np
import cv2

ROOT = Path(r"c:\saira")
C41 = ROOT / "benchmarks" / "campaigns" / "41-structural-delta-mangabeira-2026-06-16" / "scripts"
C42 = ROOT / "benchmarks" / "campaigns" / "42-mangabeira-agent3-fp-screen-2026-06-19"
CAMP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(C41))
sys.stdout.reconfigure(encoding="utf-8")
from census import census_hamming  # noqa: E402

# --- exact pile polygon + params from Camp 41/42 ---
PILE_POLY = np.array([[461, 154], [704, 66], [939, 299], [617, 416]], dtype=np.int32)
HAM_THR = 3
CENSUS_TILE_FRAC = 0.50
MIN_TILE_COVER_PX = 24
TILE = 32
KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))


def build_mask(shape):
    m = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(m, [PILE_POLY], 255)
    return m


def tile_coords(mask):
    x0, y0 = int(PILE_POLY[:, 0].min()), int(PILE_POLY[:, 1].min())
    x1, y1 = int(PILE_POLY[:, 0].max()), int(PILE_POLY[:, 1].max())
    tiles = []
    for ty in range(y0, y1, TILE):
        for tx in range(x0, x1, TILE):
            tm = mask[ty:ty + TILE, tx:tx + TILE] > 0
            if int(tm.sum()) >= MIN_TILE_COVER_PX:
                tiles.append((ty, tx, tm))
    return tiles


def changed_map(gp, gq):
    ham = census_hamming(gp, gq)
    changed = (ham >= HAM_THR).astype(np.uint8)
    return cv2.morphologyEx(changed, cv2.MORPH_OPEN, KERNEL)


def tile_changed_flags(changed, tiles):
    """For each valid tile, True if frac of census-changed pixels (within mask) > 0.50."""
    out = np.zeros(len(tiles), dtype=bool)
    for i, (ty, tx, tm) in enumerate(tiles):
        cc = changed[ty:ty + TILE, tx:tx + TILE][tm]
        out[i] = float(cc.mean()) > CENSUS_TILE_FRAC
    return out


def compute_event(jpgs, mask, tiles):
    """Returns dict with first-vs-last and persistence scores, or None on read fail."""
    imgs = [cv2.imread(str(p)) for p in jpgs]
    grays = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in imgs if im is not None]
    if len(grays) < 4 or any(g.shape != grays[0].shape for g in grays):
        return None
    base = grays[0]
    # first-vs-last (deployed)
    fl_flags = tile_changed_flags(changed_map(base, grays[-1]), tiles)
    fvl = int(fl_flags.sum())
    # persistence over 2nd half
    half = grays[len(grays) // 2:]
    counts = np.zeros(len(tiles), dtype=float)
    for g in half:
        counts += tile_changed_flags(changed_map(base, g), tiles)
    ratio = counts / len(half)
    out = {"census_ntiles_t32_recomputed": fvl, "n_half": len(half)}
    for P in (0.5, 0.7, 0.9):
        out[f"persist_p{int(P*100)}"] = int((ratio >= P).sum())
    return out


# ---------------- evaluation ----------------
def recall_fpsupp(keep, kill, T):
    keep = np.asarray(keep); kill = np.asarray(kill)
    rec = float(np.mean(keep >= T)) if keep.size else float("nan")
    sup = float(np.mean(kill < T)) if kill.size else float("nan")
    return rec, sup


def pick_T(keep_train, target=0.95):
    keep_train = np.asarray(keep_train)
    hi = int(max(keep_train.max(), 1)) + 2
    best = 0
    for T in range(0, hi):
        if float(np.mean(keep_train >= T)) >= target:
            best = T
    return best


def eval_signal(rows, score_key, split_dt, target=0.95):
    train = [r for r in rows if r["dt"] <= split_dt]
    test = [r for r in rows if r["dt"] > split_dt]

    def kv(subset, gold):
        return [r[score_key] for r in subset if r["gold"] == gold]

    T = pick_T(kv(train, "keep"), target)
    r_tr, s_tr = recall_fpsupp(kv(train, "keep"), kv(train, "kill"), T)
    r_te, s_te = recall_fpsupp(kv(test, "keep"), kv(test, "kill"), T)
    by_sub = {}
    for sub in ("passante_parado", "revira_explicit", "revira_mexe"):
        sc = [r[score_key] for r in test if r["subtype"] == sub]
        by_sub[sub] = round(float(np.mean(np.asarray(sc) < T)), 3) if sc else None
    # full-set curve point too (recall>=target on ALL data) for reference
    T_full = pick_T(kv(rows, "keep"), target)
    r_full, s_full = recall_fpsupp(kv(rows, "keep"), kv(rows, "kill"), T_full)
    by_sub_full = {}
    for sub in ("passante_parado", "revira_explicit", "revira_mexe"):
        sc = [r[score_key] for r in rows if r["subtype"] == sub]
        by_sub_full[sub] = round(float(np.mean(np.asarray(sc) < T_full)), 3) if sc else None
    return {
        "T_train": T, "recall_train": round(r_tr, 3), "fpsupp_train": round(s_tr, 3),
        "recall_test": round(r_te, 3), "fpsupp_test": round(s_te, 3),
        "fpsupp_gap_train_minus_test": round(s_tr - s_te, 3),
        "fpsupp_test_by_subtype": by_sub,
        "FULLSET": {"T": T_full, "recall": round(r_full, 3), "fpsupp": round(s_full, 3),
                    "by_subtype": by_sub_full},
    }


def main():
    ss = list(csv.DictReader((C42 / "struct_scores.csv").open(encoding="utf-8")))
    em = {r["event_id"]: r["frames_dir"] for r in csv.DictReader((C42 / "eval_manifest.csv").open(encoding="utf-8"))}
    mr = {r["event_id"]: r for r in csv.DictReader(
        (ROOT / "data/datasets/official/cam_mangabeira/manifest_revira.csv").open(encoding="utf-8"))}
    mask = build_mask((720, 1280))
    tiles = tile_coords(mask)
    print(f"valid tiles in polygon: {len(tiles)}", flush=True)

    rows, miss = [], 0
    for i, r in enumerate(ss, 1):
        fd = em.get(r["event_id"])
        dt = mr.get(r["event_id"], {}).get("datetime", "")
        if not fd or not Path(fd).is_dir() or not dt:
            miss += 1; continue
        jpgs = sorted(p for p in Path(fd).glob("*.jpg") if p.stat().st_size > 1000)
        m = compute_event(jpgs, mask, tiles)
        if m is None:
            miss += 1; continue
        rows.append({
            "event_id": r["event_id"], "gold": r["gold"], "subtype": r["subtype"], "dt": dt,
            "census_ntiles_t32": int(r["census_ntiles_t32"]),  # from CSV (deployed)
            **m,
        })
        if i % 40 == 0:
            print(f"  {i}/{len(ss)} ...", flush=True)
    print(f"scored {len(rows)} (missing {miss})", flush=True)

    dts = sorted(r["dt"] for r in rows)
    split_dt = dts[len(dts) // 2]
    n_tr = sum(1 for r in rows if r["dt"] <= split_dt)
    print(f"temporal split @ {split_dt}  -> train {n_tr} / test {len(rows)-n_tr}", flush=True)

    signals = ["census_ntiles_t32", "persist_p50", "persist_p70", "persist_p90"]
    results = {"n": len(rows), "split_dt": split_dt, "n_train": n_tr, "n_test": len(rows) - n_tr,
               "counts": {"keep": sum(r["gold"] == "keep" for r in rows),
                          "kill": sum(r["gold"] == "kill" for r in rows)},
               "signals": {}}
    for s in signals:
        results["signals"][s] = eval_signal(rows, s, split_dt)

    (CAMP / "results" / "persistence_eval.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    # also dump per-event scores for inspection
    with (CAMP / "results" / "scores.csv").open("w", encoding="utf-8", newline="") as f:
        keys = ["event_id", "gold", "subtype", "dt", "census_ntiles_t32", "persist_p50", "persist_p70", "persist_p90", "n_half"]
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in keys})

    # ---- print summary ----
    print("\n=== FP-supp @ recall>=95% (TEMPORAL split: train older -> test newer) ===")
    print(f"{'signal':<20} {'T':>3} {'rec_tr':>7} {'sup_tr':>7} {'rec_te':>7} {'sup_te':>7} {'gap':>6}  by-subtype(test): pass/rev_exp/rev_mexe")
    for s in signals:
        e = results["signals"][s]
        bs = e["fpsupp_test_by_subtype"]
        print(f"{s:<20} {e['T_train']:>3} {e['recall_train']:>7} {e['fpsupp_train']:>7} "
              f"{e['recall_test']:>7} {e['fpsupp_test']:>7} {e['fpsupp_gap_train_minus_test']:>6}  "
              f"{bs['passante_parado']}/{bs['revira_explicit']}/{bs['revira_mexe']}")
    print("\n=== FULL-SET reference (recall>=95% on all 243, no split) ===")
    print(f"{'signal':<20} {'T':>3} {'recall':>7} {'fpsupp':>7}  by-subtype: pass/rev_exp/rev_mexe")
    for s in signals:
        fu = results["signals"][s]["FULLSET"]; bs = fu["by_subtype"]
        print(f"{s:<20} {fu['T']:>3} {fu['recall']:>7} {fu['fpsupp']:>7}  "
              f"{bs['passante_parado']}/{bs['revira_explicit']}/{bs['revira_mexe']}")


if __name__ == "__main__":
    main()
