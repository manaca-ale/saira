# Campaign 34 — Arruda (esp32_005) GATE RECALL: V1 vs V3+B3

**Date:** 2026-06-04
**Question (Phase 5):** After the BGSUB frozen-baseline fix unblocks the gate, does
the current prod gate **V1** still MISS the real on-foot/cart/poda disposals — and does
the candidate **V3+B3** (material-carrier recall, Arruda-adapted) CATCH them without
regressing the platform-confirmed occurrences?

## Test set (all real TP events; trigger = recall hit)
- **4 missed events** of 2026-06-02 (spreadsheet "Não Capturadas" IDs 24-27): id24 lixo
  12:42, id25 poda 15:28, id26 poda 15:59, id27 entulho/carroça 18:26.
- **6 platform-CONFIRMADO** detections for cam_14 (status=CONFIRMADO in prod DB):
  3× 05/29, 1× 05/30, 2× 06/04.

## ⚠️ Major data-quality finding — most of the corpus is unusable
esp32_005 frame history is **ephemeral** (only 06/04 raw frames survive on prod; all
prior days rotated). The archived copies we have are degraded:

| Source | State | Usable? |
|--------|-------|---------|
| `data/datasets/official/cam_arruda/tp/id24..id27` | **CORRUPTED** JPEGs (ESP32 rainbow-glitch, std≈98 vs clean≈45-68) | ❌ all 4 |
| Downloads export `7841a9ef.../2026-06-02` (12:00–14:22 only) | **CLEAN** (std≈45) | ✅ only id24 (12:42 in range) |
| 6 CONFIRMADO detections | only the **single** representative frame survives (S3 / `labeled/`) | ⚠️ 1-frame degraded |

Consequences:
- **id25/26/27 are unrecoverable** — corrupt in the dataset, outside the clean export's
  12:00–14:22 window, gone from prod. No offline test possible.
- **id24 rebuilt clean** from the Downloads export → 30-frame window 12:41:04–12:43:28.
- The 6 confirmed survive only as **single frames** → degraded check: the gate's
  cross-frame `scene_delta_analysis` / `material_flow_direction` logic is blind, which
  depresses recall for BOTH gates equally. Read as indicative only.

**This also retroactively explains Campaign 33's invalid TP side.** Camp 33 blamed the
"persistence = whole zone, saturated in the first frame" on a cross-day baseline
mismatch; the real cause is that **those same dataset frames are corrupt** (rainbow
noise reads as full-zone foreground). Camp 33's *valid* conclusions (adaptive drift =
root cause; threshold not the lever) came from **prod logs**, not these frames, and stand.

## Result (clean run: id24 clean + 6 confirmed single-frame)

| Event | frames | V1 (prod) | V3+B3 (candidate) |
|-------|-------:|-----------|-------------------|
| **id24 lixo** (missed) | 30 (clean) | **HIT** — DUMPING, conf 95 | **FN** — COLLECTION_OR_MAINTENANCE, conf 0 |
| c0529_1043 | 1 | FN (PARKED) | FN (PARKED) |
| c0529_1108 | 1 | FN (TRAFFIC) | FN (PARKED, c50) |
| c0529_1145 | 1 | FN (TRAFFIC) | FN (TRAFFIC) |
| c0530_0933 | 1 | FN (PARKED) | FN (TRAFFIC, c50) |
| c0604_1528 | 1 | FN (PARKED) | FN (TRAFFIC, c50) |
| c0604_1541 | 1 | **HIT** — DUMPING, conf 95 | FN (PARKED, c60) |

- **missed (clean, n=1):** V1 **1/1**, V3+B3 **0/1**.
- **confirmed (single-frame, n=6, degraded):** V1 **1/6**, V3+B3 **0/6**.
- Cost $0.016.

## Interpretation
1. **The id24 FN in prod was BGSUB-only, not a gate failure.** Run directly on the clean
   window, the **V1 gate catches id24** (DUMPING 95). BGSUB suppressed it upstream
   (persistence 0.0) — exactly the drift the frozen-baseline fix (deployed 06/04) targets.
2. **V3+B3 REGRESSES the one clean case** — it relabels id24 as
   `COLLECTION_OR_MAINTENANCE` and suppresses. Same failure mode as Campaign 30
   (V3+B3 turns Imbiribeira disposals into PARKED). On every single-frame confirmed case
   V3+B3 is also ≤ V1.
3. The single-frame confirmed recall (V1 1/6) is **not** a real recall estimate — it is the
   expected degradation when the gate's temporal logic is starved of frames; the only
   valid read there is the *direction* (V3+B3 ≤ V1).

## Conclusion / Recommendation
- **Do NOT port V3+B3 to esp32_005.** The only clean, multi-frame evidence shows V1
  already catches the disposal once BGSUB unblocks it, and V3+B3 actively regresses it
  (collection/maintenance confusion). Combined with Camp 29 (V3+B3 gives no FP benefit on
  Arruda) and Camp 30 (V3+B3 regresses on open-lot cameras), the gate prompt is **not**
  the lever for Arruda. **BGSUB frozen-baseline (already deployed) is.**
- **Recall for the Arruda fix can only be validated live** (Camp 33's verdict, now
  doubly confirmed: ephemeral + corrupt offline data). Watch prod: do real disposals now
  reach the gate (`agent1_*` in `gemini_cascade_audit/esp32_005.jsonl`) and become cam_14
  occurrences, post-06/04 BGSUB activation.

## Latent bug flagged
`data/datasets/official/cam_arruda/tp/{id24,id25,id26,id27}/frames` are corrupt. id24
should be replaced with the clean Downloads export window (done here in
`data/missed_clean/`); id25/26/27 have **no** clean source and should be re-sourced if a
backup exists, or marked corrupt in the dataset manifest.

## Files
- `bench_arruda_gate_recall.py` — runner (reuses Camp 29 ARRUDA context + B3 block)
- `results.json` — clean run (id24 clean + 6 confirmed)
- `results-CORRUPT-INVALID.json` — first run on corrupt dataset frames (kept as evidence; 0/4 is an artifact of the corruption, not the prompt)
- `data/missed_clean/id24_lixo_1242/` — clean 30-frame rebuild
