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


GATE_PROMPTS = {
    "v1p": _build(_V1, _V1P_EDITS),
}

if __name__ == "__main__":
    for name, text in GATE_PROMPTS.items():
        print(f"===== {name} =====\n{text}\n")
