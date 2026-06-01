# Campaign 31 — Imbiribeira (esp32_001) gate prompt-angle exploration

**Date:** 2026-06-01
**Goal:** Design an Imbiribeira-specific gate prompt. The Mangabeira V3+B3 gate regresses
here (camp 30: 4/7), and prod V1 has poor specificity. Imbiribeira is an **open vacant
lot** (no single pile, scattered debris, central pole obstruction, small/distant subjects,
day/dusk/dawn/night-IR) whose dominant FP is **garbage collection/removal** misread as
dumping.

## Setup (gate-only, prod-faithful)
- `gemini-2.5-flash-lite`, thinking 2048, first+last+3 mid frames, trigger conf >= 85.
- Eval set (local): **recall** = 7 TP (captured on platform) + 1 FN (id 18, prod missed,
  05:17 dawn); **specificity** = 31 FP (operator-rejected captures, mostly collection).
- All angles append an open-lot reframing block to V3 base. Score = (3·recall + spec)/4
  (SAIRA weights recall heavily).

## Ranking

| Arm | TP recall | FN | FP trig / 31 | Spec | Score |
|-----|-----------|----|--------------|------|-------|
| **E_modality** ⭐ | **6/7** | 0/1 | **13** | **0.58** | **0.708** |
| D_smallsubject | 6/7 | 0/1 | 20 | 0.35 | 0.651 |
| E2_tight | 5/7 | 0/1 | 9 | 0.71 | 0.646 |
| **v1 (prod today)** | 6/7 | 0/1 | 25 | 0.19 | 0.611 |
| F_combined | 5/7 | 0/1 | 17 | 0.45 | 0.582 |
| v3_base | 2/7 | 0/1 | 7 | 0.77 | 0.381 |
| C_direction | 2/7 | 0/1 | 12 | 0.61 | 0.341 |

## Winner: **E_modality** (modality checklist)
Enumerates the dump modalities seen at this camera — (a) vehicle stops & unloads, (b)
on-foot bag left, (c) handcart dumped, (d) group depositing — escalate on any; HARD
suppress collection/removal, parked-only, dogs/rain, pass-through.

- **Keeps V1's recall (6/7)** — both miss only `454c8308` (man with handcart, far, behind
  the pole; this same event also crashes the V1 gate with a malformed-JSON bug).
- **Nearly triples specificity (0.58 vs V1 0.19)** — suppresses 13 of V1's false alarms,
  and they are exactly the right ones: **7× "caminhão retirada de lixo" + "coleta"**, plus
  "pessoas/veículos passando", "um cachorro andando", "apenas chovendo", "nada ocorrendo".
  E nails the **collection-vs-dumping** distinction V1 fails.
- Its residual 13 FP triggers are genuinely-ambiguous "stopped vehicle/person interacting"
  cases — defensible gate escalations that Agent-2 / DINOv2 filter downstream.

## Why the other angles lost
- **C_direction / F_combined**: "flow-direction first" makes flash-lite too conservative at
  distance (can't read to_pile vs from_pile reliably) → recall collapses (2/7, 5/7).
- **D_smallsubject**: good recall but escalates too eagerly (FP 20/31).
- **E2_tight** (require material to reach the ground): best specificity (0.71) but drops to
  5/7 — loses `cb49921a` (bag emptying) and the handcart. Under recall×3, not worth it.
- **v3_base**: too conservative (2/7).

## The FN (05:17) is NOT a gate-prompt problem
**Every** arm misses the 05:17 dawn FN (two men, open lot, distant, low light). Porting any
gate prompt will not recover it — needs a different lever (BGSUB/night handling or detail).

## Recommendation
- Adopt **E_modality** as the esp32_001 gate addon (analogous to esp32_002's B3): same
  recall as today, ~3× specificity, kills the collection-truck FP. Wire via an
  `esp32_001` branch in `gate_system_prompt_for_camera()` and shadow A/B.
- Consistent with prior cam_10 findings, but note: unlike generic prompt tweaks (which
  regressed cam_10), this is a **specificity** win at equal recall — the gain is FP, which
  is cam_10's actual problem. Complements the DINOv2 FP filter, not competes.

## Files
- `prompts_imbiribeira.py` — angle definitions (E_modality is `ANGLE_E_MODALITY`)
- `bench_imbiribeira_angles.py` — runner
- `results.json` (E2 run) · `results-round1.json` (6-arm run) — per-event gate output
