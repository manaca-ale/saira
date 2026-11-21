#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — prompts de gate proprios desta campanha (19/11/2026, sessao interativa).

Entram no executor por rebind de `detector_gemini.NEW_LITTER_SYSTEM_PROMPT` (como o V4 no bench53),
com o MESMO esquema e a MESMA pos-regra do V1 (cena DUMPING + 2 de 3 sinais, confianca >= 85).

v1p ("V1 a pe"): o V1 de producao com UMA mudanca de sentido: o descarte nao exige veiculo.
  Motivo (secao 12.4 do handoff do replay): com o V1, os Gemini 3 perdem as confirmadas a pe, de
  carrinho de mao e de carroca porque leem ao pe da letra "A vehicle is STOPPED and a person is
  ACTIVELY depositing" (justificativas: "no vehicle is stopped for illegal dumping"). O prompt g3
  do worker conserta isso, mas traz junto as regras pro-recall ("DEFAULT to DUMPING", "lean toward
  DUMPING") e dispara em 55% dos eventos vazios que passam no filtro. O v1p muda so a definicao e
  mantem o resto do V1, inclusive "Over 95% of scenes are EMPTY, TRAFFIC, or PARKED".
  O texto e montado a partir do V1 do worker por substituicao, para a diferenca ser exatamente esta.
"""
from __future__ import annotations

import worker.detector_gemini as _dg

_V1 = _dg.NEW_LITTER_SYSTEM_PROMPT

_V1P_EDITS = [
    ("- DUMPING: A vehicle is STOPPED and a person is ACTIVELY depositing material on the ground.",
     "- DUMPING: A person is ACTIVELY depositing material on the ground or onto a waste pile. The material "
     "may be unloaded from a STOPPED vehicle, or brought ON FOOT, in a wheelbarrow, on a handcart or on an "
     "animal cart. A vehicle is NOT required."),
    ("- person_handling_material: Is a person carrying, unloading, or depositing material near a vehicle?",
     "- person_handling_material: Is a person carrying, unloading, or depositing material (from a vehicle, "
     "on foot, or with a wheelbarrow or cart)?"),
    ("- Pedestrians walking or standing = TRAFFIC",
     "- Pedestrians walking or standing without depositing material = TRAFFIC"),
]


def _build(base: str, edits) -> str:
    out = base
    for old, new in edits:
        if out.count(old) != 1:
            raise RuntimeError(f"prompts54: trecho do V1 nao encontrado uma unica vez: {old[:60]!r}")
        out = out.replace(old, new)
    return out


# rcl = RECALL_GATE_PROMPT do testspace do Gabriel (SAIRA-TESTSPACE, _prompts_deepseek.py, perfil `recall_v1`),
# copiado sem alteracao em 20/11/2026 para a missao 4b. La ele roda com o RecallGateReport; aqui, com o esquema
# e a pos-regra do worker (os campos deposit_evidence e collection_evidence que ele cita nao existem no esquema).
_RCL = """
Analyze the provided chronological CCTV frames for evidence of illegal waste deposition.
This is triage for a second visual reviewer. Judge the supplied evidence without assuming
that most examples are negative. Do not increase confidence to pass a threshold.

Classify scene_type as EMPTY, TRAFFIC, PARKED or DUMPING. DUMPING may involve a
person on foot or a vehicle; neither a vehicle nor an identifiable offender is required.
Look for material carried to the location, released, unloaded, or added to an existing pile.
An existing pile does not rule out a new deposit. A person carrying an object or an open
vehicle door alone does not establish deposition. Consider intermediate frames as well
as first and last frames. Distinguish deposit from collection, passage, passenger pickup,
proper use of a public bin, unchanged waste, shadows, lighting and occlusion.

Set deposit_evidence=true only when the sequence visibly supports material being left or
added at the site. Set collection_evidence=true for visible removal rather than deposit.
For plausible deposit evidence set scene_type=DUMPING and new_litter_detected=true.
For clear collection without deposition or no deposition evidence, return false.
Evaluate vehicle_stopped, person_handling_material and new_ground_material independently;
a false vehicle_stopped must not negate an on-foot deposit. Describe what changed and
why it supports or fails to support deposition. Ensure booleans and scene_type agree
with the factual evidence_summary. Confidence describes confidence in deposition,
not confidence that the scene is normal. Return only JSON matching the supplied schema.
Write descriptive text in English.
""".strip()

GATE_PROMPTS = {
    "v1p": _build(_V1, _V1P_EDITS),
    "rcl": _RCL,
}

if __name__ == "__main__":
    for name, text in GATE_PROMPTS.items():
        print(f"===== {name} =====\n{text}\n")
