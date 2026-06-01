#!/usr/bin/env python3
"""Camp 27 — backtest offline do filtro DINOv2 em cam_10 (Imbiribeira).

Conjunto COMPLETO de eventos rotulados (todos FP + TP) com timestamps.

Enquadramento "filtro" (igual Camp 26):
  Todo evento foi um CON do pipeline (Agent-2 disposal=true).
  - SEM DINO: tudo CON -> recall=100%, spec=0%.
  - COM DINO: re-julga; P(CON)<t -> REJ.
      FP eliminado = REJ que o DINO marca REJ (ganho)
      TP perdido   = CON que o DINO marca REJ (custo)

Três avaliações:
  1. RepeatedStratifiedKFold 5x20 (robustez: acc±dp, AUC, curva de threshold) — random CV.
  2. Holdout TEMPORAL: treina no passado, testa no futuro.
     ⚠️ Confound: as classes são quase separadas no tempo (CONs 19-28/05, REJs 27/05-01/06).
     Logo o teste futuro é ~100% REJ → mede ESPECIFICIDADE out-of-sample (FP-elimination em
     dados futuros), não recall. É exatamente a pergunta operacional: "continua filtrando FP?".
  3. Fit completo (modelo de produção em todos os 32) + curva de threshold in-sample.

Roda LOCAL (sklearn). Lê embeddings_cam10.npz.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime
import numpy as np

EMB = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "benchmarks/campaigns/27-dinov2-cam10-full-backtest-2026-06-01/results/embeddings_cam10.npz")
N_REPEATS = 20
N_SPLITS = 5
SEED = 42
THRESHOLDS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def parse_ts(s):
    # '2026-05-19 21:39:29+00'
    return datetime.fromisoformat(str(s).replace(" ", "T"))


def oof_proba(X, y, n_splits, n_repeats, seed):
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    n = len(y)
    proba_sum = np.zeros(n); proba_cnt = np.zeros(n); rep_acc = []
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
            proba_sum[te] += p; proba_cnt[te] += 1
            rep_pred[te] = (p >= 0.5).astype(int)
        rep_acc.append((rep_pred == y).mean())
    proba = proba_sum / np.maximum(proba_cnt, 1)
    return proba, np.array(rep_acc)


def filter_curve(proba, y, thresholds=THRESHOLDS):
    n_con = int(y.sum()); n_rej = int((1 - y).sum())
    rows = []
    for t in thresholds:
        pred_con = proba >= t
        tp = int((pred_con & (y == 1)).sum())
        fp = int((pred_con & (y == 0)).sum())
        fn = int((~pred_con & (y == 1)).sum())
        tn = int((~pred_con & (y == 0)).sum())
        rows.append({"t": t, "fp_elim": tn, "fp_remain": fp, "tp_kept": tp,
                     "tp_lost": fn, "recall": tp / max(n_con, 1),
                     "spec": tn / max(n_rej, 1), "acc": (tp + tn) / max(len(y), 1)})
    return rows


def main():
    d = np.load(EMB, allow_pickle=True)
    X, y, ids, ts = d["X"], d["y"], d["ids"], d["ts"]
    order = np.argsort([parse_ts(t).timestamp() for t in ts])
    X, y, ids, ts = X[order], y[order], ids[order], ts[order]
    n = len(y); n_con = int(y.sum()); n_rej = n - n_con
    print(f"# Camp 27 — DINOv2 filter backtest cam_10 (Imbiribeira)")
    print(f"dataset: n={n}  CON(TP)={n_con}  REJ(FP)={n_rej}  bbox={d['bbox'].tolist()}")
    print(f"período: {ts[0]} -> {ts[-1]}\n")

    # distribuição temporal por classe (evidência do confound)
    print("## Distribuição temporal por classe")
    con_ts = [str(t)[:10] for t, yy in zip(ts, y) if yy == 1]
    rej_ts = [str(t)[:10] for t, yy in zip(ts, y) if yy == 0]
    print(f"  CON: {con_ts[0]} .. {con_ts[-1]}  (n={len(con_ts)})")
    print(f"  REJ: {rej_ts[0]} .. {rej_ts[-1]}  (n={len(rej_ts)})\n")

    # === 1. RepeatedSKF ===
    print("## 1. RepeatedStratifiedKFold 5x20 (random CV)")
    proba, rep_acc = oof_proba(X, y, N_SPLITS, N_REPEATS, SEED)
    try:
        from sklearn.metrics import roc_auc_score
        auc = roc_auc_score(y, proba)
    except Exception:
        auc = float("nan")
    print(f"  acc = {rep_acc.mean():.3f} ± {rep_acc.std():.3f}   AUC(oof) = {auc:.3f}")
    print(f"  {'t':>4} {'FP_elim':>9} {'TP_lost':>9} {'recall':>7} {'spec':>6} {'acc':>6}")
    for r in filter_curve(proba, y):
        star = "  <== platô" if r["t"] in (0.2, 0.3, 0.4, 0.5) else ""
        print(f"  {r['t']:>4.1f} {r['fp_elim']:>4}/{n_rej:<4} {r['tp_lost']:>4}/{n_con:<4} "
              f"{r['recall']:>6.0%} {r['spec']:>5.0%} {r['acc']:>5.0%}{star}")
    # eventos que o filtro perderia em t=0.2 (TP com proba baixa)
    lost = [(ids[i], proba[i]) for i in range(n) if y[i] == 1 and proba[i] < 0.2]
    print(f"  TPs perdidos em t=0.2 (OOF): {[(s[:8], round(p,3)) for s,p in lost]}\n")

    # === 2. Holdout temporal ===
    print("## 2. Holdout TEMPORAL (treina passado, testa futuro)")
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    # corte no último CON (todo evento posterior é REJ -> mede spec out-of-sample)
    ts_epoch = np.array([parse_ts(t).timestamp() for t in ts])
    last_con_epoch = ts_epoch[y == 1].max()
    for label, cut in [("último CON (28/05)", last_con_epoch),
                       ("mediana temporal", float(np.median(ts_epoch)))]:
        tr = ts_epoch <= cut
        te = ts_epoch > cut
        ntr_c, ntr_r = int(y[tr].sum()), int((1 - y[tr]).sum())
        nte_c, nte_r = int(y[te].sum()), int((1 - y[te]).sum())
        if te.sum() == 0 or tr.sum() == 0 or y[tr].sum() == 0 or (1 - y[tr]).sum() == 0:
            print(f"  corte={label}: split inviável (tr {ntr_c}/{ntr_r}, te {nte_c}/{nte_r})")
            continue
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
        clf.fit(sc.transform(X[tr]), y[tr])
        p_te = clf.predict_proba(sc.transform(X[te]))[:, 1]
        print(f"  corte={label}: train CON={ntr_c} REJ={ntr_r} | test CON={nte_c} REJ={nte_r}")
        for r in filter_curve(p_te, y[te], [0.2, 0.3, 0.5]):
            extra = ""
            if nte_c > 0:
                extra = f" recall={r['recall']:.0%}"
            print(f"    t={r['t']:.1f}  FP_elim(futuro)={r['fp_elim']}/{nte_r}  "
                  f"TP_lost={r['tp_lost']}/{nte_c}  spec={r['spec']:.0%}{extra}")
    print()

    # === 2b. Diagnóstico: drift temporal vs starvation da classe REJ ===
    # Replica a composição do treino temporal (10 CON + 5 REJ) mas com amostragem
    # ALEATÓRIA (sem ordem temporal). Se o FP-elim aqui também for baixo -> a culpa é
    # falta de exemplos REJ no treino (curável com mais rótulos). Se for alto -> a queda
    # temporal é drift real (pessimista).
    print("## 2b. Diagnóstico — split random REJ-starved (10 CON + 5 REJ no treino)")
    rng = np.random.RandomState(SEED)
    con_idx = np.where(y == 1)[0]; rej_idx = np.where(y == 0)[0]
    elim02, elim05, n_runs = [], [], 100
    for _ in range(n_runs):
        tr_con = rng.choice(con_idx, size=min(10, len(con_idx)), replace=False)
        tr_rej = rng.choice(rej_idx, size=5, replace=False)
        tr = np.concatenate([tr_con, tr_rej])
        te_rej = np.array([i for i in rej_idx if i not in set(tr_rej.tolist())])
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
        clf.fit(sc.transform(X[tr]), y[tr])
        p = clf.predict_proba(sc.transform(X[te_rej]))[:, 1]
        elim02.append((p < 0.2).mean()); elim05.append((p < 0.5).mean())
    print(f"  FP_elim médio em test REJ (n_runs={n_runs}):")
    print(f"    t=0.2: {np.mean(elim02):.0%} ± {np.std(elim02):.0%}   "
          f"(temporal foi 18-31%)")
    print(f"    t=0.5: {np.mean(elim05):.0%} ± {np.std(elim05):.0%}   "
          f"(temporal foi 53-62%)")
    print("  -> se ~igual ao temporal: queda = falta de REJ no treino (curável). "
          "se >> temporal: drift real.\n")

    # === 3. Fit completo (modelo de produção) ===
    print("## 3. Fit completo nos 32 (modelo de produção, in-sample)")
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(sc.transform(X), y)
    p_in = clf.predict_proba(sc.transform(X))[:, 1]
    for r in filter_curve(p_in, y, [0.2, 0.3, 0.5]):
        print(f"    t={r['t']:.1f}  FP_elim={r['fp_elim']}/{n_rej}  TP_lost={r['tp_lost']}/{n_con}  "
              f"recall={r['recall']:.0%} spec={r['spec']:.0%} acc={r['acc']:.0%}")
    print("\n(modelo in-sample é otimista; serve só p/ ver separabilidade e exportar pesos)")


if __name__ == "__main__":
    main()
