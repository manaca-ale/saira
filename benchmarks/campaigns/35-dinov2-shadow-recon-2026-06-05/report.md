# Campaign 35 — DINOv2 shadow filter: retroactive eval + decision persistence

**Date:** 2026-06-05
**Two deliverables (user request "faça os 2"):**
1. **Persist** the shadow decisions going forward (they were being lost on every
   container recreate) — worker code change.
2. **Reconstruct** the shadow track record retroactively (since 2026-06-01) and score
   it against operator labels.

## Context
The DINOv2 post-detail FP filter runs in **shadow** mode for **esp32_001 only**
(`DINOV2_FILTER_MODE=shadow`, `DINOV2_FILTER_DEVICES=esp32_001`), threshold 0.50,
model trained 2026-06-01 (CV AUC 0.945, n=32 = 10 CON / 22 REJ). It only ever logged
to stdout, so the recreate on 06-04 18:22 wiped ~4 days of shadow decisions — only 1
survived (`f7f0cc93`, p_con 0.0015).

## #2 Reconstruction — re-ran the *persisted* classifier on all 25 esp32_001 detections

Method: `detector_dinov2.evaluate()` (prod's exact scoring path) inside the worker, on
each detection's representative frame, cross-referenced with the operator's final label.
Single-frame proxy (cascade window rotated); **validated** against the one live log —
`f7f0cc93` live p_con 0.0015 vs recon 0.0020 ✓.

| Operator label | n | DINOv2 would-reject | Read |
|----------------|--:|--------------------:|------|
| **REJEITADO** (true FP) | 13 | **13** (100%) | catches every FP ✅ |
| **CONFIRMADO** (true TP) | 1 | **1** | **false-reject — kills the real disposal** ❌ |
| INDETERMINADO | 9 | 9 | — |
| PENDENTE | 2 | 2 | unlabeled |
| **TOTAL** | 25 | **25** | rejects everything |

**The model rejects 25/25.** `p_con` is uniformly tiny (all < 0.06; 19 of 25 < 0.01).
The single CONFIRMADO real disposal (`c9c2c83e`, 06-03 19:33, a **night** scene of a
vehicle + person depositing by the pile — clean, not annotated) scored p_con 0.0161 —
and **ranks below 6 of the FPs**. So it is not a threshold-calibration issue; forward
**discrimination has collapsed**.

## Interpretation — Camp 27's temporal drift, now confirmed against ground truth
- In-sample CV was AUC 0.945 ([[project_camp26_dinov2_new_polygons_2026-05-31]]).
  [[project_camp27_dinov2_temporal_drift_2026-06-01]] warned the static model decays
  forward. This eval proves it on **real operator labels**: across the forward window
  the model says "reject" to essentially everything, including the one confirmed TP.
- The "100% FP catch" is therefore **meaningless** — it comes from zero specificity, not
  discrimination.
- **Enforcing DINOv2 as-is would suppress real disposals.** Shadow was the correct call.
  The night TP miss matches the known IR/low-light weakness.

**Implications:**
- Keep DINOv2 in **shadow**; do **not** enforce on the strength of the 06-01 model.
- The weekly retrain (Sun 04:10 BRT) is essential, but Camp 27 showed retrain alone
  doesn't fully fix forward decay — threshold needs per-period recalibration and/or more
  frequent retrain. The static threshold 0.5 is far too aggressive for the forward
  p_con distribution.
- n is small (only 1 CONFIRMADO in the whole window — Imbiribeira is ~93% FP), so the
  false-reject claim rests on 1 event; the uniform-rejection pattern is the stronger
  signal.

## #1 Decision persistence — shipped (worker code)
- `detector_dinov2.record_shadow_decision()` appends one JSON line per scored decision
  (reject + pass) to `{DINOV2_MODELS_DIR}/shadow_decisions.jsonl` (models volume →
  survives recreate). Fail-safe: never raises, skips non-scored reasons.
- Wired in `main.py` right after `detector_dinov2.evaluate(...)`.
- 4 unit tests (`tests/test_dinov2_shadow_persist.py`); full worker suite 109 passed.
- Lets future shadow decisions be joined to operator labels by `request_id` — no more
  archaeology, drift becomes monitorable.

## Files
- `recon_dinov2.py` — reconstruction runner (runs inside the worker)
- `results.json` — per-detection p_con + would-reject vs operator label
