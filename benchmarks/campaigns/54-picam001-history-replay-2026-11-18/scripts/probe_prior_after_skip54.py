"""Missao 11 (21/11): o que a producao mandou como "aviso da janela anterior" logo DEPOIS de uma
janela que o filtro barraria?

Pergunta: no worker com o filtro (PR #95), uma janela barrada nao roda o gate, entao
`last_window_had_litter` fica com o ultimo valor. A missao 9 propos contar a janela barrada como
"sem descarte". Isso so reproduz o benchmark se, em producao, o gate dessas janelas costumava gravar
`last_frame_has_litter = False`. O benchmark usou o aviso que a producao mandou (contagem de tokens).

Medida, sem custo: para cada evento da amostra com nota do filtro (dev e aval), o proximo evento
avaliado pelo gate na cadeia (ordem do event_id, que e a hora) e o aviso que a producao mandou nele.
Se o evento anterior e barrado (nota < 0,30) e o seguinte recebeu "ALREADY had waste", o gate de
producao, na janela barrada, gravou "havia lixo no ultimo frame".
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_gate54 as g  # noqa: E402

RES = Path(__file__).resolve().parents[1] / "results"
THR = 0.30


def scores() -> dict:
    out = {}
    for name in ("dgate54__q5_gate5_low__r1.jsonl", "dgate54__q5_gate5_low__aval__r1.jsonl"):
        for line in (RES / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if not r.get("error") and r.get("answers"):
                    p = g.probs(r)
                    if g.FILTER_Q in p:
                        out[r["event_id"]] = p[g.FILTER_Q]
    return out


def main() -> None:
    sc = scores()
    prior = g.prior_contexts()
    with (g.ROOT / "base" / "base_eventos.csv").open(encoding="utf-8", newline="") as fh:
        evs = [r for r in csv.DictReader(fh) if r["gate_avaliou"] == "1"]
    evs.sort(key=lambda r: r["event_id"])
    nxt = {evs[i]["event_id"]: evs[i + 1]["event_id"] for i in range(len(evs) - 1)}
    tab = Counter()
    for eid, s in sc.items():
        n = nxt.get(eid)
        if n is None:
            continue
        p_type, _, src = prior.get(n, (None, None, "sem_base"))
        if src == "sem_par":
            tab[("barrado" if s < THR else "passa", "sem_par")] += 1
            continue
        tab[("barrado" if s < THR else "passa", "aviso" if p_type is not None else "sem_aviso")] += 1
    # base geral: em todos os eventos avaliados, quanto o aviso aparece
    geral = Counter("sem_par" if prior.get(r["event_id"], (0, 0, "x"))[2] == "sem_par"
                    else ("aviso" if prior.get(r["event_id"], (None,))[0] is not None else "sem_aviso")
                    for r in evs)
    lines = ["# Aviso da janela anterior depois de janela barrada pelo filtro (missao 11, sem custo)", ""]
    lines.append(f"Eventos com nota do filtro (dev + aval): {len(sc)}; eventos avaliados pelo gate na base: {len(evs)}")
    lines.append(f"Base geral (todos os avaliados): {dict(geral)}")
    for k in ("barrado", "passa"):
        a, sa, sp = tab[(k, "aviso")], tab[(k, "sem_aviso")], tab[(k, "sem_par")]
        tot = a + sa
        pct = 100 * a / tot if tot else 0
        lines.append(f"Evento anterior {k}: proximo com aviso {a}, sem aviso {sa}, sem par no log {sp}"
                     f" -> aviso em {pct:.1f}% ({a}/{tot})")
    out = "\n".join(lines)
    print(out)
    (RES / "prior_after_skip54.txt").write_text(out + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
