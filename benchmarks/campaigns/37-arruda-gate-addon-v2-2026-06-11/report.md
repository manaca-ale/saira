# Campaign 37 — Arruda (esp32_005) gate addon V2 (2026-06-11)

## Hypothesis
A camera-specific gate addon over V3 (ARRUDA_RECALL_V2) — with an explicit
anti-regression rule ("a lone carrier who arrives WITH an object and leaves WITHOUT
it is DUMPING, not collection, even with a cart") — would catch the on-foot/cart
disposals V1 misses (ID 31 carrinho, ID 32 sacolas, 09/06) WITHOUT regressing the
clean TP id24 the way Camp 34's V3+B3 did.

## Result — HYPOTHESIS REJECTED. V1 wins on all measurable data.

| Gate | id24 (clean missed TP) | FP on 8 clean negatives |
|------|------------------------|--------------------------|
| **v1 (prod)** | **DUMPING 95 — caught** | **1/8 (12.5%)** |
| v3+b3 (Camp 34) | COLLECTION — missed | 2/8 (25%) |
| v3+v2 (this camp) | COLLECTION — missed | 3/8 (37.5%) |

Both V3-based addons MISS id24 and raise the FP rate. v2's recall-priority rule made
FPs worse, not recall better. conf_single (6) ignored — single representative frame
only, all gates degrade to PARKED/TRAFFIC (not informative).
Cost: $0.058.

## Why offline cannot settle Arruda (3 confounds discovered)
1. **Frame corruption (episodic).** The genuinely gate-missed events (id25/26/27/31/32)
   have CORRUPTED stored frames (rainbow-glitch, std≈98). Today's frames (06/11) are
   clean (std≈68) → corruption was a past episode, not ongoing. But the target events
   are untestable offline.
2. **Camera was repositioned.** id24 (02/06) is a CLOSE top-down view of the pile/green
   dumpster corner; today (06/11) is a WIDE elevated street view. Old TPs (id24-27) are
   an obsolete framing; the V3 context + fresh negatives describe the new one.
3. **id24 is visually ambiguous.** Two people next to a green dumpster — reads as
   municipal collection. V3's (correct, in general) collection-discrimination fires;
   no prompt tweak (b3 or v2) flips it. V1's DUMPING-95 is arguably the lucky/risky call.

## Reframe (important)
- The "better gate prompt" hypothesis for Arruda has now failed TWICE (Camp 34 b3, Camp
  37 v2). For Arruda's data/geometry, **V1 > V3** on everything we can measure.
- id24's real prod FN cause was **BGSUB suppression, not the gate** (Camp 34); and V1
  DOES catch obvious pedestrian dumps (id24) on clean frames. So the evidence that Arruda
  needs a gate-prompt fix is weak — the misses are more likely BGSUB + frame corruption +
  genuinely subtle/ambiguous events.
- Small samples (1 TP, 8 neg) → FP ordering has variance, but the direction (recall
  addons add FPs, miss id24) is consistent with the smoke run and theory.

## Recommendation
- **Do NOT deploy v2 or b3.** Keep V1 for Arruda.
- Stop iterating the Arruda gate prompt offline — the data is too compromised (corruption
  + re-angle + ambiguity) and the prompt lever underperforms V1.
- If a gate change is still wanted, validate ONLY via **live shadow A/B** on current
  clean frames (log-only), gathering a proper current-angle labeled set first.
- Point Arruda recall effort at the levers the evidence supports: BGSUB (frozen-baseline
  deployed 06/04), the frame-corruption capture/transport bug, and the gate pile-crop
  (flag OFF for esp32_005).

Data: TP from Camp 34 (missed_clean/id24 + conf_single); negatives = 8 windows sampled
from 2026-06-11 esp32_005 sem_ocorrencia (clean). Runner: bench_arruda_addon_v2.py.
