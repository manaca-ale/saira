#!/usr/bin/env python3
"""Campanha 26 — LogReg 5-fold CV sobre embeddings DINOv2 (polígonos novos).

Roda LOCAL (sklearn). Lê o .npz produzido por extract_embeddings.py no container.
Reporta acc/AUC per-camera e dumpa misclassificados.

Compara com baseline 2026-05-29 (polígonos antigos):
  cam_10: 96% acc / AUC 0.933   cam_11: 47% / AUC 0.525
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

EMB = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "benchmarks/campaigns/26-dinov2-new-polygons-2026-05-31/results/embeddings.npz")


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.preprocessing import StandardScaler

    d = np.load(EMB, allow_pickle=True)
    X, y, cams, ids = d["X"], d["y"], d["cams"], d["ids"]
    print(f"X={X.shape} y={y.shape} cams={sorted(set(cams.tolist()))}")
    print(f"bbox_10={d['bbox_10'].tolist()}  bbox_11={d['bbox_11'].tolist()}")

    for cam in sorted(set(cams.tolist())):
        mask = cams == cam
        Xc, yc, idc = X[mask], y[mask], ids[mask]
        n_con = int(yc.sum()); n_rej = int(len(yc) - n_con)
        if len(yc) < 10 or n_con < 3 or n_rej < 3:
            print(f"cam_{cam}: too few (n={len(yc)} CON={n_con} REJ={n_rej})")
            continue
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        accs, aucs = [], []
        miss = []
        oof_pred = np.zeros(len(yc), dtype=int)
        oof_proba = np.zeros(len(yc), dtype=float)
        for tr, te in skf.split(Xc, yc):
            sc = StandardScaler().fit(Xc[tr])
            clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
            clf.fit(sc.transform(Xc[tr]), yc[tr])
            pr = clf.predict(sc.transform(Xc[te]))
            pb = clf.predict_proba(sc.transform(Xc[te]))[:, 1]
            oof_pred[te] = pr; oof_proba[te] = pb
            accs.append(accuracy_score(yc[te], pr))
            try:
                aucs.append(roc_auc_score(yc[te], pb))
            except ValueError:
                pass
        # confusion from OOF
        tp = int(((oof_pred == 1) & (yc == 1)).sum())
        tn = int(((oof_pred == 0) & (yc == 0)).sum())
        fp = int(((oof_pred == 1) & (yc == 0)).sum())
        fn = int(((oof_pred == 0) & (yc == 1)).sum())
        recall = tp / max(tp + fn, 1)
        spec = tn / max(tn + fp, 1)
        print(f"\ncam_{cam}: n={len(yc)} (CON={n_con} REJ={n_rej})")
        print(f"  acc={np.mean(accs):.3f}  AUC={np.mean(aucs) if aucs else float('nan'):.3f}")
        print(f"  OOF: TP={tp} TN={tn} FP={fp} FN={fn}  recall={recall:.2%} spec={spec:.2%}")
        for j in range(len(yc)):
            if oof_pred[j] != yc[j]:
                miss.append(f"    {idc[j][:8]} gt={'CON' if yc[j] else 'REJ'} "
                            f"pred={'CON' if oof_pred[j] else 'REJ'} p={oof_proba[j]:.2f}")
        if miss:
            print("  misclassified:")
            print("\n".join(miss))


if __name__ == "__main__":
    main()
