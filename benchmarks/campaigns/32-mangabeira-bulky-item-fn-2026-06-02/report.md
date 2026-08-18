# Campaign 32 — Mangabeira bulky-item clause: REJECTED

**Date:** 2026-06-02
**Hypothesis (mine):** the deployed esp32_002 gate (V3+B3) missed the 2026-06-02 13:13
dump (people placing green doors/panels, wood, metal rails — bulky construction debris)
because B3 keys on a bag/sack "material-carrier" signal and lacks a bulky-item clause.
Adding a bulky clause should recover it without hurting FP.

**Result: hypothesis WRONG. Keep the deployed B3.**

## Setup (gate-only, prod-faithful)
- `gemini-2.5-flash-lite`, thinking 2048, first+last+3 mid, trigger conf >= 85.
- Eval (cam_mangabeira, local): recall = 13 TP + 6 dataset 'missed' + the 13:13 FN (`fn_1313`);
  specificity = 43 FP. Score = (3·recall + spec)/4.
- Arms: `b3` (deployed prod), `b3_bulky` (B3 + bulky-item clause), `b4` (camp-19 reference,
  already has a bulky clause).

## Ranking

| Arm | Recall | FP trig / 43 | Spec | Score |
|-----|--------|--------------|------|-------|
| **b3 (deployed)** ⭐ | 11/20 | **16** | **0.63** | **0.570** |
| b4 (camp-19 ref) | 12/20 | 27 | 0.37 | 0.543 |
| b3_bulky (candidate) | 11/20 | 24 | 0.44 | 0.523 |

## Why the bulky clause is rejected
- **b3_bulky recovers 0 additional real dumps vs b3** (and loses none) — same recall 11/20.
- **It adds 9 false positives** (spec 0.63 → 0.44). The 9 new FPs are exactly the failure
  mode feared: tree-pruning cleanup ("realizando a poda", "limpando restos de poda" ×3),
  a parked car, and people merely passing — the "any bulky item near the pile" language
  makes the gate over-escalate on cleanup/maintenance.
- b4 is worse still (27/43 FP).

## The real cause of the 13:13 prod miss: frame sampling, NOT the prompt
The deployed B3 **reliably catches `fn_1313`** in the bench — 5/5 repeats at conf 90
DUMPING — given a window that brackets the deposit action (13:13:52→13:16:58). Yet the
prod batch (first 13:13:57, last 13:16:58) returned conf 50. Same prompt, near-identical
window → the miss is a **gate frame-sampling artifact** of that batch (the sampled
frames/mids did not present the deposit clearly), not a prompt blind-spot.

Consistent with the long-standing cam_11/cam_10 pattern (camps 11-16, 21, 28): adding
prompt instructions regresses these cameras via confabulation on cleanup. Tested instead
of assumed — saved a bad deploy.

## Recommendation
- **Keep the deployed B3.** Do NOT add a bulky-item clause; do NOT switch to B4.
- Real levers for borderline-confidence misses like 13:13 (no prompt change):
  1. **Gate pile-crop** — flag `GEMINI_GATE_PILECROP_ENABLED` (currently OFF) feeds a
     hi-res pile-zone crop to the gate; should lift borderline cases without new FP.
  2. Improve the gate's mid-frame selection to capture the deposit moment.

## Files
- `bench_mangabeira_bulky.py` — runner (b3 / b3_bulky / b4)
- `results.json` — per-event gate output
