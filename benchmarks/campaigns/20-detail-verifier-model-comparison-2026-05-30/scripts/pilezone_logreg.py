#!/usr/bin/env python3
"""Ceiling check: logistic regression on all pile-delta features.

Loads pilezone_v2_results.json and pilezone_full_results.json (v1 features).
Trains LogReg with 5-fold CV. If even LogReg can't beat ~60%, the features
themselves don't separate REJ from CON — the filter idea is dead end.
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

v2 = json.loads(Path("/tmp/pilezone_v2_results.json").read_text())
v1 = json.loads(Path("/tmp/pilezone_full_results.json").read_text())
v1_by_id = {r["id"]: r for r in v1}

# join v1 + v2 by id
rows = []
for r in v2:
    v1r = v1_by_id.get(r["id"])
    if not v1r:
        continue
    rows.append({**v1r, **r})

features = [
    "v1_pile_delta", "v1_ctrl_delta", "v1_lift",
    "max_lift_any", "max_lift_anchor0", "max_pile_any",
    "changed_pct", "edge_a_pct", "edge_b_pct", "edge_delta_pct",
    "sat_delta", "ncc", "pile_first", "pile_last",
]
X = np.array([[r.get(f, 0.0) for f in features] for r in rows])
y = np.array([1 if r["gt"] == "CON" else 0 for r in rows])

print(f"rows: {len(rows)}, features: {len(features)}, "
      f"class balance: CON={int(y.sum())} REJ={int((1-y).sum())}")

pipe = Pipeline([("sc", StandardScaler()),
                 ("lr", LogisticRegression(max_iter=1000, C=1.0))])
skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

acc_scores = cross_val_score(pipe, X, y, cv=skf, scoring="accuracy")
auc_scores = cross_val_score(pipe, X, y, cv=skf, scoring="roc_auc")

print(f"\n5-fold CV accuracy: mean={acc_scores.mean():.2%} +- {acc_scores.std():.2%}  "
      f"folds={[f'{s:.2%}' for s in acc_scores]}")
print(f"5-fold CV ROC AUC : mean={auc_scores.mean():.3f} +- {auc_scores.std():.3f}  "
      f"folds={[f'{s:.3f}' for s in auc_scores]}")

# train on all, inspect coefficients
pipe.fit(X, y)
lr = pipe.named_steps["lr"]
print("\n=== Feature importance (LogReg coef on standardized X) ===")
order = np.argsort(-np.abs(lr.coef_[0]))
for i in order:
    print(f"  {features[i]:<22s} coef={lr.coef_[0][i]:+.3f}")
