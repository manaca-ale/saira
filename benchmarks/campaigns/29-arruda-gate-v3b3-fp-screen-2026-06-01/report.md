# Campaign 29 — Arruda (esp32_005) gate V3+B3 FP screen

**Date:** 2026-06-01
**Question:** Before porting the esp32_002 V3+B3 recall gate to esp32_005 (Arruda) to
fix the 2026-06-01 cart-dumping false negative, does that gate explode false positives
on Arruda's busy street?

## Setup (prod-faithful)
- **Gate only (Agent-1).** Model `gemini-2.5-flash-lite`, thinking 2048, cascade window
  37 frames / ~3 min, `SEQUENCE_SIZE=5` frames sent (first+last+3 mid), trigger =
  `new_litter_detected AND confidence_0_100 >= 85` (matches prod `GEMINI_AGENT1_*`).
- **Prompt:** V3 base + B3 material-carrier recall block, Arruda-adapted scene context
  (pile against the right-side wall). This is the deploy candidate.
- **Baseline windows (no real occurrence):**
  - Day: local export 2026-06-01 08:00–14:11, 40 windows (real 11:27 dump excluded).
  - Night: prod `sem_ocorrencia` 2026-06-01 02:00–04:59 (dark/streetlight), 40 windows.

## Result

| Period | Triggered / OK | Gate FP rate |
|--------|----------------|--------------|
| Day    | **7 / 40**     | **17.5 %**   |
| Night  | **2 / 40**     | **5.0 %**    |

Cost $0.12. (Two transient 503s, auto-retried OK.)

## Visual verification of the 7 day + 2 night triggers
Inspected mid-frames. Classification:
- **Genuine hallucinations (FP):** pedestrian with a bag on the LEFT sidewalk far from
  the pile (08:24); people merely walking, the "white pile" being the pre-existing
  morning-dump leftover (12:15); a person **pushing a handcart through the street**, not
  stopping at the pile (11:17); near-empty night scene with only a distant car (04:12).
  → B3's permissive "material-carrier" recall fires on Arruda's constant through-traffic
  of pedestrians/carts passing the chronic pile.
- **Legitimate suspect escalation (not a clear FP):** white pickup **stopped beside the
  pile with a person alongside** (08:06) — exactly the kind of case Agent-2 should judge.

## Interpretation
- These are **GATE escalations**, not final operator FPs — Agent-2 would still filter.
  But 17.5 % daytime escalation = high Agent-2 volume + real FP risk if Agent-2 also
  confirms.
- The B3 block was tuned for Mangabeira's quiet sidewalk corner. Arruda is a busy
  two-way thoroughfare where carts and pedestrians *constantly pass* the chronic pile,
  so "material-carrier near pile" is a weak discriminator here.

## V1 control (same 80 windows) — the decisive comparison

| Gate | Day FP | Night FP | Notes |
|------|--------|----------|-------|
| **V1 (current prod)** | **7/40 (17.5 %)** | 0/40 (0 %) | fires on stationary vehicles + **misreads the municipal loader cleanup as DUMPING** |
| **V3+B3 (candidate)** | **7/40 (17.5 %)** | 2/40 (5 %) | fires on pedestrians/carts carrying material near pile |

**Overlap:** only **1** window triggered by both (13:36). 6 V1-only, 8 V3+B3-only.
So the two gates over-fire at the *same rate* but on *different* windows.

Visual adjudication of V1-only triggers:
- **09:41 + 10:00 = a yellow loader (JCB) + dump truck + uniformed workers REMOVING the
  chronic pile** (municipal/contractor cleanup). V1 calls it DUMPING — a clear FP on a
  removal op. **V3+B3 correctly did NOT fire on these** (its posture/flow logic suppresses
  removal). Quality win for V3+B3.
- 13:00 / 13:46 = parked/passing vehicles, hallucinated deposition.

Context that inflates BOTH rates today: 2026-06-01 had a major mid-morning municipal
**cleanup** (loader removing the pile, ~09:40–13:00), the real 11:27 cart dump, plus
constant traffic — an unusually activity-rich day.

## Revised conclusion
- **The FP screen does NOT block the V3+B3 port.** Day gate FP is **identical to current
  prod V1 (17.5 %)**; V3+B3 even *avoids* the municipal-cleanup FP that V1 produces. Only
  regression is +5 % night (2 windows, distant figures).
- High raw gate FP on Arruda is driven by the **busy/active scene**, not by B3 specifically.
- **Caveat:** this bench is **gate-only — it bypasses BGSUB and Agent-2**, which both
  filter downstream in prod (BGSUB suppresses most esp32_005 baseline batches). So 17.5 %
  is the *raw gate escalation*, an upper bound; operator-facing FP is much lower.

## Recommendation
- **Cleared for a shadow A/B on Arruda** (not a hard enforce). V3+B3 is no more FP-prone at
  the gate than today's V1, and it adds the cart/pedestrian recall that fixes the 11:27 FN.
- Before/while shadowing:
  1. Watch **night** (small new FP) and overall Agent-2 volume.
  2. Add a **municipal-equipment suppressor** — even V1 mislabels the EMLURB/loader cleanup;
     worth hardening for both.
  3. Validate on **more days** (today's loader cleanup is not representative).

## Files
- `bench_arruda_gate_fp.py` — runner
- `results.json` — per-window gate output
- `night_frames/` — 2160 night baseline frames pulled from prod
