# Campaign 30 — Imbiribeira (esp32_001) gate V3+B3 recall test

**Date:** 2026-06-01
**Question:** Would porting the V3+B3 recall gate to Imbiribeira help — i.e. does it
catch Imbiribeira's real dumps (7 TP captured on the platform + 1 FN prod missed)
at least as well as the current V1 gate?

## Setup (gate-only, prod-faithful)
- Model `gemini-2.5-flash-lite`, thinking 2048, first+last+3 mid frames,
  trigger = `new_litter_detected AND confidence_0_100 >= 85`.
- Two arms on the SAME 8 events: **v1** (current prod gate) and **v3b3** (V3 base +
  Imbiribeira-adapted material-carrier recall block, deploy candidate).
- Events: 7 TP from `data/datasets/official/cam_imbiribeira/tp/` (occurrences prod
  captured) + 1 FN (id 18, 2026-06-01 05:17 dawn, "dois homens descartando lixo",
  frames pulled from prod esp32_001).

## Result — V3+B3 REGRESSES recall

| Arm | TP recall | FN recovered |
|-----|-----------|--------------|
| **V1 (current prod)** | **6/7** (1 event errored, see below; 6/6 of valid) | 0/1 (conf 80, PARKED — close) |
| **V3+B3 (candidate)** | **4/7** | 0/1 (conf 0, TRAFFIC) |

V3+B3 misses 3 TPs that V1 catches:
- `a73a3f44` — **dark-blue pickup dumping a large volume**: V1 conf **95 DUMPING** →
  V3+B3 conf **50 PARKED**. Clear regression.
- `48350bb4` — two men emptying a big bag: V1 conf 90 DUMPING → V3+B3 conf 50 TRAFFIC.
- `454c8308` — man with handcart: V1 errors (see below) → V3+B3 conf 50 TRAFFIC.

Both gates **miss the FN** (05:17 dawn, open lot, distant figures). V1 is closer
(conf 80 / PARKED) than V3+B3 (conf 0 / TRAFFIC).

## Note: V1 robustness bug on `454c8308`
The V1 gate prompt makes flash-lite emit malformed JSON (runaway string field,
`EOF while parsing ... column 7617`) on this handcart event — fails all 3 retries,
reproducibly. Latent V1-gate robustness issue, independent of this comparison.

## Conclusion
- **Do NOT port V3+B3 to Imbiribeira.** Its posture/material-carrier logic was tuned
  for Mangabeira's wall-pile sidewalk; on Imbiribeira's **open lot** it under-fires,
  calling vehicle/people dumps "PARKED"/"TRAFFIC". Recall drops 6→4 of 7.
- Porting V3+B3 would **not** fix the 05:17 FN either — both gates miss it. That FN is a
  hard dawn/open-lot case needing a different fix (not a Mangabeira-style recall prompt).
- Consistent with prior Imbiribeira findings: prompt changes regress cam_10 recall
  (camp 21 IMBIRIBEIRA 86→43 %, camp 28 prompt raised FP). The cam_10 lever is the
  **DINOv2 FP filter**, not gate-prompt recall tuning.

## Files
- `bench_imbiribeira_recall.py` — runner
- `results.json` — per-event gate output (both arms)
- `fn18_frames/` — FN id 18 frames pulled from prod
