#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — conjuntos de perguntas novos para o Decisions (gemini-decision-1) como FILTRO antes do gate.

Segue o guia oficial (aistudio.google.com/docs/decisions-api, lido em 18/11/2026): perguntas estreitas,
de proposito unico, em forma positiva; `true_description` / `false_description` quando a pergunta sozinha
e ambigua; combinar as respostas no codigo. O modelo nao ve as chaves, so `instructions` e as descricoes.

q2 (18/11/2026, turno da tarde) — exploracao larga numa unica requisicao (a entrada e cobrada uma vez):
  - c_actor_at_pile, c_deposit: copias literais do q1, para conferir se a resposta de uma pergunta
    depende das outras perguntas do mesmo pedido (deve dar o mesmo numero do q1 no mesmo evento);
  - presenca e atividade (person_any ... unloading): candidatas a filtro;
  - worth_look: pergunta larga, escrita como filtro (contraria o guia de proposito, para comparar);
  - activity (score) e closest (choice): os outros dois tipos de pergunta;
  - picker, uses_bin, collection_crew: causas de rejeicao do operador (frente de falsos positivos).
p_fmt_*: sondas de formato (2 eventos), para descobrir onde a API aceita as descricoes do `noul`.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "53-picam001-migration-post-25flash-2026-11-16" / "scripts"))
from bench_decisions import QSETS as _Q53  # noqa: E402

_Q1 = _Q53["q1"]


def _noul(instructions, true_description=None, false_description=None):
    # sonda de 18/11: no nivel da pergunta a API devolve HTTP 400 ("Unknown parameter 'true_description'");
    # dentro de `criteria` ela aceita.
    q = {"type": "noul", "instructions": instructions}
    crit = {}
    if true_description:
        crit["true_description"] = true_description
    if false_description:
        crit["false_description"] = false_description
    if crit:
        q["criteria"] = crit
    return q


_PRESENCE = {
    "person_any": _noul(
        "Is at least one person visible in at least one frame?"),
    "person_near_pile": _noul(
        "Is a person within arm's reach of the waste pile, or of the curb area where waste is left, "
        "in at least one frame?",
        "A person stands, crouches or bends right at the pile or deposit area in one or more frames.",
        "No person is visible, or every person stays away from the pile (roadway, far sidewalk)."),
    "person_lingers": _noul(
        "Does the same person appear in two or more frames at roughly the same place?",
        "The same person stays in about the same spot across two or more frames.",
        "No person is visible, or each person only crosses the scene."),
    "vehicle_stopped": _noul(
        "Is a car, truck, van, motorcycle, cart or wheelbarrow stopped at or right next to the waste "
        "pile in at least one frame?",
        "A vehicle, cart or wheelbarrow is stationary beside the pile.",
        "No vehicle stops beside the pile; vehicles are only driving through or parked far from it."),
    "carrying": _noul(
        "Is any person holding, carrying, pushing or pulling a bag, box, bucket, sack, cart, "
        "wheelbarrow or other load in at least one frame?"),
    "handling": _noul(
        "Is a person seen bending over, reaching toward, placing, dropping or throwing something at "
        "the waste pile or on the ground?"),
    "new_object": _noul(
        "Is there a bag, object or material on the ground or on the pile in the last frame that was "
        "absent in the first frame?",
        "The last frame shows a bag, object or material that the first frame does not show.",
        "The ground and the pile hold the same items in the first and the last frame."),
    "pile_changed": _noul(
        "Comparing the first frame with the last frame, does the waste pile look different, with "
        "items added, removed or moved?"),
    "unloading": _noul(
        "Is someone unloading material from a vehicle, cart or wheelbarrow onto the ground or the "
        "waste pile?"),
}

QSETS = {
    "q2": {
        "c_actor_at_pile": _Q1["actor_at_pile"],
        "c_deposit": _Q1["deposit"],
        **_PRESENCE,
        "worth_look": _noul(
            "Could this sequence plausibly show someone leaving waste, bags, debris or objects at the "
            "pile or on the ground, so that it deserves a closer look?",
            "A person or vehicle stops at or interacts with the pile area, carries or unloads "
            "something, or new material appears on the ground.",
            "Clearly nothing of the sort: an empty scene, a lighting change, or people and vehicles "
            "that only pass through."),
        "activity": {
            "type": "score",
            "instructions": (
                "Rate the highest level of interaction with the waste pile reached by any person or "
                "vehicle in this sequence."),
            "criteria": [
                "Nobody and no vehicle comes near the pile: empty scene or only distant traffic.",
                "A person or vehicle passes close to the pile without stopping.",
                "A person or vehicle stops near the pile, but nobody touches or handles any material.",
                "A person handles material at the pile: touching, sorting, picking up or putting down.",
                "A person clearly leaves a bag, object or material at the pile or on the ground.",
            ],
        },
        "closest": {
            "type": "choice",
            "instructions": "What is the closest any person gets to the waste pile in this sequence?",
            "criteria": {
                "NONE": "No person is visible in any frame.",
                "FAR": "People are visible only away from the pile, in the roadway or far sidewalk.",
                "PASSING": "A person walks right past the pile without stopping.",
                "AT_PILE": "A person stops at the pile.",
            },
        },
        "picker": _noul(
            "Is a person rummaging through, sorting or collecting items from the waste pile to take "
            "them away?"),
        "uses_bin": _noul(
            "Does a person put waste inside a large waste container, bin or dumpster, rather than on "
            "the ground?"),
        "collection_crew": _noul(
            "Is a garbage truck or a uniformed municipal cleaning crew visible?"),
    },
    # sondas de formato: descricoes do noul no nivel da pergunta x dentro de `criteria`
    "p_fmt_top": {
        "person_near_pile": {
            "type": "noul",
            "instructions": _PRESENCE["person_near_pile"]["instructions"],
            **_PRESENCE["person_near_pile"]["criteria"],
        },
        "plain": _noul("Is at least one person visible in at least one frame?"),
    },
    "p_fmt_crit": {"person_near_pile": _PRESENCE["person_near_pile"]},
    "p_one": {"actor_at_pile": _Q1["actor_at_pile"]},
}

# q3 (18/11): a pergunta que venceu a varredura do q2, sozinha no pedido (a configuracao que iria para producao).
QSETS["q3"] = {"worth_look": QSETS["q2"]["worth_look"]}

# q4 (18/11): worth_look (ancora, literal) + variante escrita depois de olhar os frames das confirmadas de nota
# mais baixa (carrinho de mao no meio de gente de colete, cacamba a noite, pessoa que chega a pilha e sai).
QSETS["q4"] = {
    "worth_look": QSETS["q2"]["worth_look"],
    "wl_v2": _noul(
        QSETS["q2"]["worth_look"]["instructions"],
        "A person or vehicle stops at or interacts with the pile area, carries or unloads something, or new "
        "material appears on the ground. Also yes when a truck, cart or wheelbarrow is at or backing toward "
        "the pile, or when a person walks up to the pile and walks away, including at night or among other "
        "people and vehicles, even if the unloading itself is not visible.",
        "Clearly nothing of the sort: an empty scene, a lighting change, animals, or people and vehicles that "
        "only pass through or stay parked away from the pile."),
}

# q5 (18/11): wl_v2 sozinha no pedido (a resposta depende das outras perguntas do pedido; medir como iria ao ar).
QSETS["q5"] = {"wl_v2": QSETS["q4"]["wl_v2"]}
