#!/usr/bin/env python3
"""Cruza predições DINOv2 (OOF, polígonos novos) vs decisão do Gemini E+CROPS
(camp 24) nos mesmos eventos cam_11, + checa o FP de hoje (49e304b7).

Pergunta: quais erros do Gemini o DINOv2 corrigiria? Vale como Agent-3 grátis?
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path("benchmarks/campaigns")
EMB = ROOT / "26-dinov2-new-polygons-2026-05-31/results/embeddings.npz"
C24 = ROOT / "24-detail-mangabeira-pilezone-crops-2026-05-30/results/flash_mangabeira_E_CROPS_results.json"


def dinov2_oof():
    """Return {id: {'gt','pred','p'}} from per-camera 5-fold OOF."""
    d = np.load(EMB, allow_pickle=True)
    X, y, cams, ids = d["X"], d["y"], d["cams"], d["ids"]
    out = {}
    for cam in sorted(set(cams.tolist())):
        m = cams == cam
        Xc, yc, idc = X[m], y[m], ids[m]
        if len(yc) < 10:
            continue
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        pipe = Pipeline([("sc", StandardScaler()),
                         ("lr", LogisticRegression(max_iter=2000,
                                                   class_weight="balanced", C=1.0))])
        proba = cross_val_predict(pipe, Xc, yc, cv=skf, method="predict_proba")[:, 1]
        for j in range(len(yc)):
            out[str(idc[j])] = {
                "cam": int(cam),
                "gt": "CON" if yc[j] else "REJ",
                "dino_pred": "CON" if proba[j] >= 0.5 else "REJ",
                "dino_p": round(float(proba[j]), 2),
            }
    return out


def main():
    dino = dinov2_oof()
    c24 = json.load(open(C24, encoding="utf-8"))
    if "results" in c24:
        c24 = {r["id"]: r for r in c24["results"]}

    ids = sorted(set(dino) & set(c24))
    print(f"eventos cruzados (cam_11): {len(ids)}\n")

    # Tally: for each combination of (gemini correct?, dino correct?)
    g_only_right = g_only_wrong = both_right = both_wrong = 0
    dino_fixes_gemini = []   # gemini wrong, dino right
    dino_breaks = []         # gemini right, dino wrong
    for i in ids:
        gt = dino[i]["gt"]
        g = c24[i]["pred"]
        dp = dino[i]["dino_pred"]
        gok = (g == gt)
        dok = (dp == gt)
        if gok and dok: both_right += 1
        elif gok and not dok: dino_breaks.append(i)
        elif not gok and dok: dino_fixes_gemini.append(i)
        else: both_wrong += 1

    print(f"both right:        {both_right}")
    print(f"both wrong:        {both_wrong}")
    print(f"DINO fixes Gemini: {len(dino_fixes_gemini)}  (Gemini errou, DINO acertou)")
    print(f"DINO breaks:       {len(dino_breaks)}  (Gemini acertou, DINO errou)")

    print("\n--- DINO corrige erros do Gemini ---")
    for i in dino_fixes_gemini:
        d = dino[i]
        print(f"  {i[:8]} gt={d['gt']} gemini={c24[i]['pred']} dino={d['dino_pred']} "
              f"(p={d['dino_p']})")
    print("\n--- DINO quebra acertos do Gemini ---")
    for i in dino_breaks:
        d = dino[i]
        print(f"  {i[:8]} gt={d['gt']} gemini={c24[i]['pred']} dino={d['dino_pred']} "
              f"(p={d['dino_p']})")

    # ensemble ideas
    def conf(pred_fn):
        tp=tn=fp=fn=0
        for i in ids:
            gt=dino[i]["gt"]; p=pred_fn(i)
            if p=="CON" and gt=="CON": tp+=1
            elif p=="REJ" and gt=="REJ": tn+=1
            elif p=="CON" and gt=="REJ": fp+=1
            else: fn+=1
        n=tp+tn+fp+fn
        return dict(acc=(tp+tn)/n, rec=tp/max(tp+fn,1), spec=tn/max(tn+fp,1),
                    tp=tp,tn=tn,fp=fp,fn=fn)
    print("\n=== ensembles (cam_11) ===")
    def show(name, fn):
        s=conf(fn)
        print(f"  {name:34} acc={s['acc']:.1%} rec={s['rec']:.1%} spec={s['spec']:.1%} "
              f"TP={s['tp']} TN={s['tn']} FP={s['fp']} FN={s['fn']}")
    show("Gemini E+CROPS alone", lambda i: c24[i]["pred"])
    show("DINOv2 alone", lambda i: dino[i]["dino_pred"])
    # AND = CON só se ambos CON (maximiza specificity)
    show("AND (both CON)", lambda i: "CON" if (c24[i]["pred"]=="CON" and dino[i]["dino_pred"]=="CON") else "REJ")
    # OR = CON se qualquer CON (maximiza recall)
    show("OR (any CON)", lambda i: "CON" if (c24[i]["pred"]=="CON" or dino[i]["dino_pred"]=="CON") else "REJ")
    # DINO as veto on Gemini CON: gemini CON but dino strongly REJ (p<0.2) -> REJ
    show("Gemini, veto if dino p<0.2", lambda i: "REJ" if (c24[i]["pred"]=="CON" and dino[i]["dino_p"]<0.2) else c24[i]["pred"])


if __name__ == "__main__":
    main()
