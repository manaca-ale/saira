#!/usr/bin/env python3
"""Camp 27 — exporta o classificador DINOv2 de cam_10 como artefato NUMPY-puro.

Treina LogReg+StandardScaler em TODOS os eventos rotulados de cam_10 (mesma config do
eval: class_weight=balanced, C=1.0) e exporta um .npz que o worker carrega SEM sklearn:

    p_con = sigmoid( ((feat - scaler_mean)/scaler_scale) @ coef + intercept )
    should_reject = p_con < threshold

Verifica paridade: a inferência numpy-pura deve bater com sklearn.predict_proba (atol 1e-6).

Uso: python export_clf.py [embeddings.npz] [out.npz]
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

EMB = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "benchmarks/campaigns/27-dinov2-cam10-full-backtest-2026-06-01/results/embeddings_cam10.npz")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
    "benchmarks/campaigns/27-dinov2-cam10-full-backtest-2026-06-01/results/dinov2_clf_esp32_001.npz")
THRESHOLD = 0.5          # platô t=0,4–0,5 (domina o 0,2 da Camp 26; ver report.md)
DEVICE_ID = "esp32_001"


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    d = np.load(EMB, allow_pickle=True)
    X, y = d["X"].astype(np.float64), d["y"]
    bbox = d["bbox"]

    sc = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(sc.transform(X), y)
    # coluna do predict_proba correspondente à classe CON (=1)
    con_idx = int(np.where(clf.classes_ == 1)[0][0])
    # LogReg binário: coef_ tem 1 linha (decisão p/ classes_[1] = positivo). Se a classe
    # positiva for classes_[0], invertemos o sinal.
    sign = 1.0 if clf.classes_[1] == 1 else -1.0

    scaler_mean = sc.mean_.astype(np.float64)
    scaler_scale = sc.scale_.astype(np.float64)
    coef = (sign * clf.coef_[0]).astype(np.float64)
    intercept = float(sign * clf.intercept_[0])

    # --- paridade numpy vs sklearn ---
    z = (X - scaler_mean) / scaler_scale
    logit = z @ coef + intercept
    p_np = 1.0 / (1.0 + np.exp(-logit))
    p_sk = clf.predict_proba(sc.transform(X))[:, con_idx]
    max_err = float(np.abs(p_np - p_sk).max())
    print(f"paridade numpy vs sklearn: max|Δ| = {max_err:.2e}")
    assert max_err < 1e-6, "inferência numpy NÃO bate com sklearn!"

    # confusão in-sample no threshold escolhido
    pred = p_np >= THRESHOLD
    tp = int((pred & (y == 1)).sum()); tn = int((~pred & (y == 0)).sum())
    fp = int((pred & (y == 0)).sum()); fn = int((~pred & (y == 1)).sum())
    print(f"in-sample @t={THRESHOLD}: TP={tp} TN={tn} FP={fp} FN={fn} "
          f"(in-sample é otimista)")

    np.savez(
        OUT,
        scaler_mean=scaler_mean, scaler_scale=scaler_scale,
        coef=coef, intercept=np.array(intercept),
        threshold=np.array(THRESHOLD),
        con_class_index=np.array(con_idx),
        device_id=np.array(DEVICE_ID),
        dino_variant=np.array("dinov2_vits14"),
        dino_input=np.array(224), n_frames=np.array(3),
        bbox=bbox,
        n_train=np.array(len(y)),
        n_con=np.array(int(y.sum())), n_rej=np.array(int((1 - y).sum())),
        trained_at=np.array(datetime.now(timezone.utc).isoformat()),
    )
    print(f"saved {OUT}  (coef {coef.shape}, threshold={THRESHOLD}, n_train={len(y)})")


if __name__ == "__main__":
    main()
