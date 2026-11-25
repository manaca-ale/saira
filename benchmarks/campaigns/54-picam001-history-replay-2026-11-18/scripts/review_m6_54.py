#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — revisao da missao 5 e falsos por causa (missao 6). Sem custo: so le arquivos de resultado.

  1. refaz o funil gate -> detail com um leitor proprio (sem agg_detail54) para conferir os numeradores
  2. lista os disparos de gate que ficaram sem veredito do detail, com o motivo
  3. lista os S0 em que o detail de controle disse sim (quem disparou, nota, hora, o que os outros bracos
     e a repeticao disseram) e a margem dos alertas por 1.000 eventos que vem do S0
  4. cruza as deteccoes rejeitadas que sobrevivem a cada funil com o comentario do operador e com a
     categoria da revisao de janela completa da frente saira-falsos (so leitura)

Uso:
  python review_m6_54.py [--tsv results/s0_sim_controle54.tsv]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import run_gate54 as g54
from agg_gate54 import weights
from run_detail54 import RESULTS

sys.stdout.reconfigure(encoding="utf-8")
GATES = ("g25l_v1_t2048_ctx", "g31l_v1p_min_low_ctx", "nvl_v1p_low_ctx")
DETAILS = ("d25f_v1", "d38f_g3_low_low")
FALSOS = Path.home() / ".claude" / "runs" / "saira-falsos" / "saida" / "fp_sobreviventes_dev.jsonl"


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def read_jsonl(path):
    """ultimo registro sem erro por evento; devolve tambem os eventos que so tem registro com erro"""
    ok, err = {}, {}
    if not path.exists():
        return ok, err
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            (err if r.get("error") else ok)[r["event_id"]] = r
    return ok, {e: r for e, r in err.items() if e not in ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv", default="")
    a = ap.parse_args()

    pass_rows = g54.build_set("pass", 0.30)
    sub = {r["event_id"]: r["sub"] for r in pass_rows}
    det_of = {r["event_id"]: r["detection_id"] for r in pass_rows}
    score = {r["event_id"]: r["score"] for r in pass_rows}
    base = {}
    with (g54.ROOT / "base" / "base_eventos.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["event_id"] in sub:
                base[r["event_id"]] = r
    gates = {g: read_jsonl(RESULTS / f"gate54__{g}__r1.jsonl")[0] for g in GATES}
    fire = {g: {e for e, r in gr.items() if r.get("fire") and e in sub} for g, gr in gates.items()}
    det, det_err = {}, {}
    for d in DETAILS:
        det[d], det_err[d] = read_jsonl(RESULTS / f"detail54__{d}__r1.jsonl")
    r2 = read_jsonl(RESULTS / "detail54__d25f_v1__r2.jsonl")[0]
    n_det = {s: len({r["detection_id"] for r in pass_rows if r["sub"] == s}) for s in ("S2C", "S2R", "S2X")}

    print("== 1. funil refeito (deteccoes com pelo menos um evento em que o gate dispara e o detail diz sim)")
    surv = {}
    for d in DETAILS:
        for g in GATES:
            ds = defaultdict(set)
            ev = Counter()
            for e in fire[g]:
                r = det[d].get(e)
                if r and r.get("disposal"):
                    if sub[e] in n_det:
                        ds[sub[e]].add(det_of[e])
                    ev[sub[e]] += 1
            surv[(d, g)] = ds
            print(f"  {d:<16} {g:<22} confirmadas {len(ds['S2C']):>2}/{n_det['S2C']} | rejeitadas "
                  f"{len(ds['S2R']):>2}/{n_det['S2R']} | S2X {len(ds['S2X'])}/{n_det['S2X']} | S1 sim {ev['S1']:>2} | "
                  f"S0 sim {ev['S0']:>2}")

    print("\n== 2. disparos de gate sem veredito do detail de controle (d25f_v1)")
    union = set().union(*fire.values())
    print(f"  uniao dos disparos dos tres gates no conjunto pass: {len(union)} eventos "
          f"{dict(Counter(sub[e] for e in union))}; com veredito do controle: {len(union & set(det['d25f_v1']))}")
    for e in sorted(union - set(det["d25f_v1"])):
        why = "chamada com erro: " + str(det_err["d25f_v1"][e].get("error"))[:80] if e in det_err["d25f_v1"] \
            else "nunca foi chamado"
        b = base.get(e, {})
        print(f"  {e} {sub[e]:<4} nota {score[e]:.2f} | gates {[g for g in GATES if e in fire[g]]} | "
              f"producao: detail rodou={b.get('detail_rodou')} sim={b.get('detail_sim')} | {why}")
    extra = set(det["d25f_v1"]) - union
    print(f"  eventos com detail de controle que nao sao disparo de nenhum gate _ctx r1: {len(extra)} "
          f"{dict(Counter(sub.get(e, 'fora do pass') for e in extra))}")

    print("\n== 3. S0 com sim do detail de controle")
    w = weights()
    dev = g54.load_dev()
    n_all, n_ok = Counter(), Counter()
    for r in dev:
        if r["score"] is not None:
            n_all[r["sub"]] += 1
            n_ok[r["sub"]] += r["score"] >= 0.30
    print(f"  S0 no dev com nota: {n_all['S0']}; passam no filtro: {n_ok['S0']} ({n_ok['S0'] / n_all['S0']:.1%}); "
          f"peso do S0 na camera: {w['S0']:.3f}")
    s0 = [e for e, r in det["d25f_v1"].items() if sub.get(e) == "S0"]
    sim = sorted(e for e in s0 if det["d25f_v1"][e].get("disposal"))
    print(f"  S0 com veredito do controle: {len(s0)}; sim: {len(sim)}")
    for g in GATES:
        cov = [e for e in fire[g] if sub[e] == "S0" and e in det["d25f_v1"]]
        k = sum(1 for e in cov if det["d25f_v1"][e].get("disposal"))
        nf = sum(1 for e in fire[g] if sub[e] == "S0")
        f = 1000 * w["S0"] * (n_ok["S0"] / n_all["S0"]) * nf / n_ok["S0"]
        lo, hi = wilson(k, len(cov))
        flo, fhi = wilson(nf, n_ok["S0"])
        f2 = 1000 * w["S0"] * (n_ok["S0"] / n_all["S0"])
        print(f"  {g:<22} disparos S0 {nf}/{n_ok['S0']} | sim do detail {k}/{len(cov)} | alertas S0 por 1.000: "
              f"{f * k / len(cov):.1f} (so a margem do detail: {f * lo:.1f} a {f * hi:.1f}; so a do gate: "
              f"{f2 * flo * k / len(cov):.1f} a {f2 * fhi * k / len(cov):.1f})")
    c = Counter()
    for e in sim:
        g3 = det["d38f_g3_low_low"].get(e)
        c[("g3 sim" if g3 and g3.get("disposal") else "g3 nao") if g3 else "g3 sem veredito"] += 1
        if e in r2:
            c["r2 sim" if r2[e].get("disposal") else "r2 nao"] += 1
        c["hora " + ("noite" if int(e[13:15]) >= 18 or int(e[13:15]) < 6 else "dia")] += 1
        c["gates: " + "+".join(g.split("_")[0] for g in GATES if e in fire[g])] += 1
    for k, v in sorted(c.items()):
        print(f"    {k:<40} {v}")
    if a.tsv:
        with open(a.tsv, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("event_id\tnota_wl_v2\tgates\tconf_controle\tg3\tr2\tgate_conf_producao\tevidencia_controle\n")
            for e in sim:
                r = det["d25f_v1"][e]
                g3 = det["d38f_g3_low_low"].get(e)
                fh.write("\t".join([
                    e, f"{score[e]:.3f}", "+".join(g.split("_")[0] for g in GATES if e in fire[g]),
                    str(r.get("conf")), "" if not g3 else str(int(bool(g3.get("disposal")))),
                    "" if e not in r2 else str(int(bool(r2[e].get("disposal")))),
                    base.get(e, {}).get("gate_conf", ""), " ".join(str(r.get("evidence", "")).split())]) + "\n")
        print(f"  lista gravada em {a.tsv}")

    print("\n== 4. deteccoes rejeitadas que sobrevivem, por causa")
    rev = {}
    if FALSOS.exists():
        for line in FALSOS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rev[r["id"]] = r
    comment = {}
    for e, b in base.items():
        if sub[e] == "S2R":
            comment[det_of[e]] = " ".join((b.get("validity_comment") or "").split())
    for d in DETAILS:
        for g in GATES:
            cat, err = Counter(), Counter()
            for dt in surv[(d, g)]["S2R"]:
                evs = [e for e in fire[g] if det_of[e] == dt and det[d].get(e, {}).get("disposal")]
                cs = {rev[e]["categoria_revisao"] for e in evs if e in rev}
                es = {rev[e]["erro_operador"] for e in evs if e in rev}
                cat[" / ".join(sorted(cs)) or "sem revisao"] += 1
                err[" / ".join(sorted(es)) or "sem revisao"] += 1
            print(f"  {d} + {g}: {len(surv[(d, g)]['S2R'])} rejeitadas")
            for k, v in cat.most_common():
                print(f"      {v:>2}  {k}")
            print("      erro do operador: " + ", ".join(f"{k} {v}" for k, v in err.most_common()))
    print("\n  comentarios do operador nas rejeitadas que sobrevivem ao controle + g31l (as mais numerosas):")
    for dt in sorted(surv[("d25f_v1", "g31l_v1p_min_low_ctx")]["S2R"]):
        evs = sorted(e for e in fire["g31l_v1p_min_low_ctx"] if det_of[e] == dt
                     and det["d25f_v1"].get(e, {}).get("disposal"))
        cats = sorted({rev[e]["categoria_revisao"] for e in evs if e in rev})
        print(f"    {evs[0]} [{'/'.join(cats) or '-'}] {comment.get(dt, '')[:150]}")

    print("\n== 5. leitura a olho da janela inteira dos S0 com sim de algum detail (um revisor, sem cegamento)")
    leit = {}
    for name in ("s0_sim_controle54__revisao.tsv", "s0_sim_so_g3_54__revisao.tsv"):
        if (RESULTS / name).exists():
            with (RESULTS / name).open(encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh, delimiter="\t"):
                    leit[r["event_id"]] = r
    kinds = ("descarte_provavel", "falso_provavel", "indeterminado", "sem leitura")
    per_ev = 1000 * w["S0"] * (n_ok["S0"] / n_all["S0"]) / n_ok["S0"]

    def tally(evs):
        c = Counter(leit[e]["leitura"] if e in leit else "sem leitura" for e in evs)
        return c, " | ".join(f"{k} {c[k]}" for k in kinds if c[k] or k != "sem leitura")

    print(f"  eventos lidos: {len(leit)} -> {tally(leit)[1]}")
    print("  por causa: " + ", ".join(f"{k[0]}/{k[1]} {v}" for k, v in sorted(
        Counter((r["leitura"], r["causa"]) for r in leit.values()).items())))
    night = [e for e in leit if int(e[13:15]) >= 18 or int(e[13:15]) < 6]
    print(f"  noite (18h a 6h): {tally(night)[1]}")
    print(f"  dia: {tally([e for e in leit if e not in night])[1]}")
    for g in GATES:
        print(f"  disparos do gate {g} entre os lidos: {tally([e for e in leit if e in fire[g]])[1]}")
    for d in DETAILS:
        yes = [e for e, r in det[d].items() if sub.get(e) == "S0" and r.get("disposal")]
        print(f"  {d}: S0 com sim {len(yes)} -> {tally(yes)[1]}")
        for g in GATES:
            cov = [e for e in fire[g] if sub[e] == "S0" and e in det[d]]
            nf = sum(1 for e in fire[g] if sub[e] == "S0")
            c, _ = tally([e for e in cov if det[d][e].get("disposal")])
            print(f"    {g:<22} " + " | ".join(
                f"{k} {c[k]} ({c[k] * per_ev * nf / len(cov):.1f} por 1.000)" for k in kinds if c[k]))


if __name__ == "__main__":
    main()
