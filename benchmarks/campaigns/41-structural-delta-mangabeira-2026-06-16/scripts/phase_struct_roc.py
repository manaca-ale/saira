#!/usr/bin/env python3
"""Phase 1.3 — separability of structural-delta signals (TP vs B3).

Reuses the Camp-40 Phase-A pattern: per-signal ROC/AUC, bootstrap 95% CI, a veto
threshold sweep at a recall floor, a TEMPORAL HOLDOUT (train old / test new — the
Camp 27/40 lesson: in-sample AUC must hold forward), and a permutation check.

Decision frame: a structural-delta veto SUPPRESSES (REJ) an event with LOW change
and KEEPS one with HIGH change. So at a recall floor of >=85% TP kept we maximise
B3 suppressed. NCC signals are inverted (low NCC = high change = TP).

GATE: AUC>=0.75 AND CI_low>0.5 AND B3_supp>=30% at TP_keep>=85% AND temporal holdout
does NOT collapse (test AUC stays >~0.6 and test B3_supp stays meaningful).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

ROOT = Path(r"c:\saira")
CAMP = ROOT / "benchmarks" / "campaigns" / "41-structural-delta-mangabeira-2026-06-16"
RES = CAMP / "results"
sys.stdout.reconfigure(encoding="utf-8")
RNG = np.random.default_rng(42)

# signals where LOWER value means more structural change (=> TP). All others: higher=TP.
LOWER_IS_TP = {"ncc_min_t16", "ncc_mean_t16", "ncc_min_t32", "ncc_mean_t32", "g_ncc"}
NON_SIGNAL = {"event_id", "bucket", "created_at", "after_motion", "mask_area_px"}

RECALL_FLOOR = 0.85   # keep >=85% of TP (lose <=15%)


SUFFIX = sys.argv[1] if len(sys.argv) > 1 else ""


def load():
    rows = list(csv.DictReader((RES / f"struct_signals{SUFFIX}.csv").open(encoding="utf-8")))
    for r in rows:
        for k, v in list(r.items()):
            if k not in NON_SIGNAL and k not in ("event_id", "bucket", "created_at"):
                try:
                    r[k] = float(v)
                except (ValueError, TypeError):
                    pass
        r["after_motion"] = float(r["after_motion"])
    return rows


def oriented(sig, x):
    """Return values oriented so HIGHER = more TP-like (for a 'keep if >=thr' rule)."""
    return -np.asarray(x) if sig in LOWER_IS_TP else np.asarray(x)


def auc_keep_tp(rows, sig):
    tp = oriented(sig, [r[sig] for r in rows if r["bucket"] == "TP"])
    b3 = oriented(sig, [r[sig] for r in rows if r["bucket"] == "B3"])
    y = np.r_[np.ones(len(tp)), np.zeros(len(b3))]
    x = np.r_[tp, b3]
    return roc_auc_score(y, x), tp, b3


def bootstrap_ci(tp, b3, n=5000):
    aucs = []
    y = np.r_[np.ones(len(tp)), np.zeros(len(b3))]
    for _ in range(n):
        i = RNG.integers(0, len(tp), len(tp))
        j = RNG.integers(0, len(b3), len(b3))
        try:
            aucs.append(roc_auc_score(y, np.r_[tp[i], b3[j]]))
        except ValueError:
            pass
    return np.percentile(aucs, [2.5, 97.5])


def sweep_veto(tp, b3, floor=RECALL_FLOOR):
    """Keep if value>=thr. Maximise B3 suppressed s.t. TP_keep fraction >= floor."""
    thrs = np.unique(np.r_[tp, b3])
    best = None
    need = int(np.ceil(floor * len(tp)))
    for thr in thrs:
        tp_keep = int((tp >= thr).sum())
        b3_supp = int((b3 < thr).sum())
        if tp_keep >= need and (best is None or b3_supp > best["b3_supp"]):
            best = {"thr": float(thr), "tp_keep": tp_keep, "tp_n": len(tp),
                    "b3_supp": b3_supp, "b3_n": len(b3),
                    "tp_keep_pct": tp_keep / len(tp), "b3_supp_pct": b3_supp / len(b3)}
    return best


def temporal_holdout(rows, sig, train_frac=0.6):
    rs = sorted(rows, key=lambda r: r["created_at"])
    cut = int(len(rs) * train_frac)
    train, test = rs[:cut], rs[cut:]
    cut_date = rs[cut]["created_at"][:10]

    def split(rr):
        tp = oriented(sig, [r[sig] for r in rr if r["bucket"] == "TP"])
        b3 = oriented(sig, [r[sig] for r in rr if r["bucket"] == "B3"])
        return tp, b3
    tr_tp, tr_b3 = split(train)
    te_tp, te_b3 = split(test)
    # fit threshold on TRAIN, apply to TEST
    fit = sweep_veto(tr_tp, tr_b3)
    out = {"cut_date": cut_date, "train_n": len(train), "test_n": len(test),
           "test_tp": len(te_tp), "test_b3": len(te_b3)}
    if fit and len(te_tp) and len(te_b3):
        thr = fit["thr"]
        te_keep = int((te_tp >= thr).sum())
        te_supp = int((te_b3 < thr).sum())
        out.update({
            "train_thr": thr,
            "test_tp_keep_pct": te_keep / len(te_tp),
            "test_b3_supp_pct": te_supp / len(te_b3),
        })
    # test-set AUC (in-distribution-for-test) for collapse check
    if len(te_tp) and len(te_b3):
        y = np.r_[np.ones(len(te_tp)), np.zeros(len(te_b3))]
        out["test_auc"] = float(roc_auc_score(y, np.r_[te_tp, te_b3]))
    if len(tr_tp) and len(tr_b3):
        y = np.r_[np.ones(len(tr_tp)), np.zeros(len(tr_b3))]
        out["train_auc"] = float(roc_auc_score(y, np.r_[tr_tp, tr_b3]))
    return out


def permutation(rows, sig, n=2000):
    vals = oriented(sig, [r[sig] for r in rows])
    labels = np.array([1 if r["bucket"] == "TP" else 0 for r in rows])
    obs, _, _ = auc_keep_tp(rows, sig)
    obs = max(obs, 1 - obs)
    aucs = []
    for _ in range(n):
        perm = RNG.permutation(labels)
        tp = vals[perm == 1]
        b3 = vals[perm == 0]
        y = np.r_[np.ones(len(tp)), np.zeros(len(b3))]
        a = roc_auc_score(y, np.r_[tp, b3])
        aucs.append(max(a, 1 - a))
    aucs = np.array(aucs)
    return {"obs_auc": obs, "perm_mean": float(aucs.mean()),
            "perm_p95": float(np.percentile(aucs, 95)),
            "p_value": float((aucs >= obs).mean())}


def main() -> int:
    rows = load()
    tp_n = sum(1 for r in rows if r["bucket"] == "TP")
    b3_n = sum(1 for r in rows if r["bucket"] == "B3")
    print(f"N: TP={tp_n}  B3={b3_n}\n")
    signals = [k for k in rows[0] if k not in NON_SIGNAL
               and k not in ("event_id", "bucket", "created_at") and isinstance(rows[0][k], float)]

    ranked = []
    for sig in signals:
        try:
            auc, tp, b3 = auc_keep_tp(rows, sig)
        except ValueError:
            continue
        oriented_auc = max(auc, 1 - auc)
        ranked.append((oriented_auc, sig, tp, b3))
    ranked.sort(reverse=True)

    print(f"{'signal':<22s} {'AUC(keep TP)':>12s}  {'B3supp@85%recall':>18s}")
    print("-" * 58)
    summary = []
    for oriented_auc, sig, tp, b3 in ranked:
        veto = sweep_veto(tp, b3)
        bs = f"{veto['b3_supp']}/{veto['b3_n']} ({veto['b3_supp_pct']:.0%}) @TP {veto['tp_keep_pct']:.0%}" if veto else "—"
        print(f"{sig:<22s} {oriented_auc:>12.3f}  {bs:>18s}")
        summary.append({"signal": sig, "auc": round(oriented_auc, 4), "veto": veto})

    # deep-dive the top 3 signals
    print("\n=== DEEP DIVE (top 3) ===")
    deep = {}
    for oriented_auc, sig, tp, b3 in ranked[:3]:
        lo, hi = bootstrap_ci(tp, b3)
        ho = temporal_holdout(rows, sig)
        pm = permutation(rows, sig)
        veto = sweep_veto(tp, b3)
        print(f"\n--- {sig} ---")
        print(f"  AUC={oriented_auc:.3f}  95%CI=[{lo:.3f},{hi:.3f}]")
        if veto:
            print(f"  veto@>=85%recall: TPkeep {veto['tp_keep']}/{veto['tp_n']} ({veto['tp_keep_pct']:.0%})"
                  f"  B3supp {veto['b3_supp']}/{veto['b3_n']} ({veto['b3_supp_pct']:.0%})")
        print(f"  TEMPORAL holdout (cut={ho.get('cut_date')}): train_auc={ho.get('train_auc',float('nan')):.3f}"
              f"  test_auc={ho.get('test_auc',float('nan')):.3f}"
              f"  test_B3supp={ho.get('test_b3_supp_pct',float('nan')):.0%}"
              f"  test_TPkeep={ho.get('test_tp_keep_pct',float('nan')):.0%}")
        print(f"  permutation: obs={pm['obs_auc']:.3f}  perm_mean={pm['perm_mean']:.3f}"
              f"  p95={pm['perm_p95']:.3f}  p={pm['p_value']:.4f}")
        deep[sig] = {"auc": oriented_auc, "ci": [lo, hi], "veto": veto,
                     "holdout": ho, "permutation": pm}

    (RES / f"struct_roc{SUFFIX}.json").write_text(json.dumps(
        {"n": {"TP": tp_n, "B3": b3_n}, "ranked": summary, "deep": deep},
        ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(f"\n-> {RES/'struct_roc.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
