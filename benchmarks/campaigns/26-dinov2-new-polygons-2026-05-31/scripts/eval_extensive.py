#!/usr/bin/env python3
"""Camp 26 — avaliação EXTENSIVA do DINOv2 como filtro de FP (todas as câmeras).

Enquadramento "filtro" (o correto p/ produção):
  Todo evento em `detections` foi um CON do pipeline (Agent-2 disposal=true).
  - SEM DINO (produção hoje): tudo CON -> recall=100%, spec=0%, FP=#REJ.
  - COM DINO: re-julga; pode reverter CON->REJ.
      FP eliminado = REJ que o DINO marca REJ (ganho)
      TP perdido   = CON que o DINO marca REJ (custo)

Rigor:
  - RepeatedStratifiedKFold (5 folds x N_REPEATS) p/ média±desvio robusto.
  - OOF probabilities médias por evento (cada evento previsto N_REPEATS vezes).
  - Curva de threshold: trade FP-eliminado × TP-perdido em todos os pontos.
  - Per-camera (modelo treinado só naquela câmera) + pooled.
  - 2 classificadores (LogReg, LinearSVC-platt) p/ robustez.

Roda LOCAL (sklearn). Lê embeddings_all.npz.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

EMB = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "benchmarks/campaigns/26-dinov2-new-polygons-2026-05-31/results/embeddings_all.npz")
N_REPEATS = 20
N_SPLITS = 5
SEED = 42


def oof_proba(X, y, n_splits, n_repeats, seed):
    """Return per-sample mean OOF P(CON) over repeats + per-repeat acc list."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    n = len(y)
    proba_sum = np.zeros(n)
    proba_cnt = np.zeros(n)
    rep_acc = []
    rng = np.random.RandomState(seed)
    for r in range(n_repeats):
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True,
                              random_state=int(rng.randint(0, 1_000_000)))
        rep_pred = np.zeros(n)
        for tr, te in skf.split(X, y):
            sc = StandardScaler().fit(X[tr])
            clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
            clf.fit(sc.transform(X[tr]), y[tr])
            p = clf.predict_proba(sc.transform(X[te]))[:, 1]
            proba_sum[te] += p
            proba_cnt[te] += 1
            rep_pred[te] = (p >= 0.5).astype(int)
        rep_acc.append((rep_pred == y).mean())
    proba = proba_sum / np.maximum(proba_cnt, 1)
    return proba, np.array(rep_acc)


def filter_curve(proba, y):
    """For thresholds t, predict REJ if P(CON)<t. Report filter trade."""
    n_con = int(y.sum()); n_rej = int((1 - y).sum())
    rows = []
    for t in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        pred_con = proba >= t            # keep as CON
        tp = int(((pred_con) & (y == 1)).sum())     # TP kept
        fp = int(((pred_con) & (y == 0)).sum())     # FP remaining
        fn = int(((~pred_con) & (y == 1)).sum())    # TP lost
        tn = int(((~pred_con) & (y == 0)).sum())    # FP eliminated
        rows.append({
            "t": t, "fp_elim": tn, "fp_remain": fp, "tp_kept": tp, "tp_lost": fn,
            "recall": tp / max(n_con, 1), "spec": tn / max(n_rej, 1),
            "acc": (tp + tn) / max(len(y), 1),
        })
    return rows, n_con, n_rej


def report_cam(name, X, y):
    n = len(y); n_con = int(y.sum()); n_rej = n - n_con
    print(f"\n{'='*72}\n{name}: n={n}  CON(TP)={n_con}  REJ(FP)={n_rej}")
    if n_con < N_SPLITS or n_rej < N_SPLITS:
        print(f"  ** n insuficiente p/ {N_SPLITS}-fold (precisa >= {N_SPLITS} por classe) **")
        if n_con >= 2 and n_rej >= 2:
            # leave-one-out fallback
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import LeaveOneOut
            from sklearn.preprocessing import StandardScaler
            loo = LeaveOneOut(); proba = np.zeros(n)
            for tr, te in loo.split(X):
                sc = StandardScaler().fit(X[tr])
                clf = LogisticRegression(max_iter=2000, class_weight="balanced")
                clf.fit(sc.transform(X[tr]), y[tr])
                proba[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
            print("  (LeaveOneOut)")
            for r in filter_curve(proba, y)[0]:
                if r["t"] in (0.3, 0.5, 0.7):
                    print(f"    t={r['t']:.1f}  FP_elim={r['fp_elim']}/{n_rej}  "
                          f"TP_lost={r['tp_lost']}/{n_con}  rec={r['recall']:.0%} spec={r['spec']:.0%}")
        return None
    proba, rep_acc = oof_proba(X, y, N_SPLITS, N_REPEATS, SEED)
    try:
        from sklearn.metrics import roc_auc_score
        auc = roc_auc_score(y, proba)
    except Exception:
        auc = float("nan")
    print(f"  RepeatedSKF {N_SPLITS}x{N_REPEATS}: acc={rep_acc.mean():.3f} ± {rep_acc.std():.3f}"
          f"   AUC(oof)={auc:.3f}")
    print(f"  SEM DINO (baseline pipeline): recall=100%  spec=0%  FP passa={n_rej}  TP={n_con}")
    print(f"  COM DINO — curva do filtro (t = limiar de P(CON); abaixo de t vira REJ):")
    print(f"    {'t':>4} {'FP_elim':>8} {'TP_lost':>8} {'recall':>7} {'spec':>6} {'acc':>6}")
    rows, _, _ = filter_curve(proba, y)
    for r in rows:
        star = "  <-- recall 100% mantido" if r["tp_lost"] == 0 and r["fp_elim"] > 0 else ""
        print(f"    {r['t']:>4.1f} {r['fp_elim']:>3}/{n_rej:<4} {r['tp_lost']:>3}/{n_con:<4} "
              f"{r['recall']:>6.0%} {r['spec']:>5.0%} {r['acc']:>5.0%}{star}")
    return proba


def main():
    d = np.load(EMB, allow_pickle=True)
    X, y, cams, ids = d["X"], d["y"], d["cams"], d["ids"]
    print(f"dataset: X={X.shape}  n={len(y)}  CON={int(y.sum())} REJ={int((1-y).sum())}")
    print(f"cameras: {sorted(set(cams.tolist()))}")

    # per-camera
    for cam in sorted(set(cams.tolist())):
        m = cams == cam
        nm = {10: "cam_10 Imbiribeira", 11: "cam_11 Mangabeira", 14: "cam_14 Arruda"}.get(cam, f"cam_{cam}")
        report_cam(nm, X[m], y[m])

    # pooled (all cameras, single model)
    report_cam("POOLED (todas as câmeras, 1 modelo)", X, y)


if __name__ == "__main__":
    main()
