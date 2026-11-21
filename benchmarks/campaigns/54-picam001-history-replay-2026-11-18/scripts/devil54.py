#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — advogado do diabo (missao 9). Sem custo: so le arquivos de resultado do DESENVOLVIMENTO.

Refaz os funis finalistas com leitor proprio (nao usa funnels54) e tenta derruba-los:
  1. conferencia do funil com o filtro aplicado EVENTO A EVENTO (o `pass` leva todos os eventos das
     confirmadas ao gate, inclusive os que o filtro barraria) e de onde vem cada alerta (estrato);
  2. pares A x B, A x controle, B x controle nas deteccoes (McNemar exato);
  3. por periodo (antes e depois de 02/08) e por hora (dia x noite);
  4. margem por reamostragem (bootstrap pareado) de alertas por 1.000, custo e das diferencas;
  5. sensibilidade a leitura a olho dos S0 (os indefinidos) e contagem bruta por tras de cada taxa;
  6. o que a regua proposta para a medicao final consegue distinguir com 47 confirmadas.

Uso: python devil54.py > ../results/devil54__dev.txt
     CAMP54_SPLIT=aval python devil54.py > ../results/devil54__aval.txt   (medicao final, missao 10; sem a secao 7)
"""
from __future__ import annotations

import csv
import json
import random
import statistics
from collections import Counter, defaultdict
from math import comb

import run_gate54 as g54
from agg_dgate54 import TODAY
from agg_gate54 import C_D, weights
from bench_budget import cost_usd

RESULTS = g54.RESULTS
THR = 0.30
SUBS = ("S2C", "S2R", "S2X", "S1", "S0")
FUNNELS = {   # nome -> (gate, detail)
    "hoje refeito": ("g25l_v1_t2048_ctx", "d25f_v1"),
    "A nova+3.8": ("nvl_v1p_low_ctx", "d38f_g3_low_low"),
    "B 3.1fl+3.8": ("g31l_v1p_min_low_ctx", "d38f_g3_low_low"),
}
CUT = "20260802"
N_AVAL_CONF = 47          # confirmadas no conjunto de avaliacao (numero do handoff, 12.2; nada foi lido de la)


def read_ok(path):
    out = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                if not r.get("error"):
                    out[r["event_id"]] = r
    return out


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def mcnemar(b, c):
    """p bilateral exato para pares discordantes b x c."""
    n = b + c
    if not n:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def night(e):
    h = int(e[13:15])
    return h >= 18 or h < 6


def day_of(e):
    return e[4:12]


class Data:
    def __init__(self):
        self.rows = g54.build_set("pass", THR)
        self.sub = {r["event_id"]: r["sub"] for r in self.rows}
        self.det_of = {r["event_id"]: r["detection_id"] for r in self.rows}
        self.score = {r["event_id"]: r["score"] for r in self.rows}
        self.w = weights()
        n_all, n_ok = Counter(), Counter()
        for r in g54.load_dev():
            if r["score"] is not None:
                n_all[r["sub"]] += 1
                n_ok[r["sub"]] += r["score"] >= THR
        self.n_all, self.n_ok = n_all, n_ok
        self.pf = {s: n_ok[s] / n_all[s] for s in SUBS}
        self.gate, self.det = {}, {}
        for g, d in FUNNELS.values():
            if g not in self.gate:
                self.gate[g] = {e: r for e, r in read_ok(g54.out_path(g, 1)).items()
                                if e in self.sub}
            if d not in self.det:
                self.det[d] = read_ok(RESULTS / f"detail54__{d}{g54.SFX}__r1.jsonl")
        self.leit = {}
        for name in ("s0_sim_controle54__revisao.tsv", "s0_sim_so_g3_54__revisao.tsv"):
            with (RESULTS / name).open(encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh, delimiter="\t"):
                    self.leit[r["event_id"]] = r["leitura"]
        self.c_gate = {g: statistics.fmean(r["cost_usd"] for r in recs.values())
                       for g, recs in self.gate.items()}
        self.c_det = {d: statistics.fmean(cost_usd(r["model"], r["tok_in"], r["tok_out"], r["tok_think"])
                                          for r in recs.values()) for d, recs in self.det.items()}

    def passes(self, e):
        sc = self.score[e]
        return sc is not None and sc >= THR

    def state(self, f, e, filtro=True):
        """'barrado' | 'gate_nao' | 'sem_gate' | 'sim' | 'nao' | 'sem_detail' para o evento e no funil f."""
        g, d = FUNNELS[f]
        if filtro and not self.passes(e):
            return "barrado"
        r = self.gate[g].get(e)
        if r is None:
            return "sem_gate"
        if not r.get("fire"):
            return "gate_nao"
        v = self.det[d].get(e)
        if v is None:
            return "sem_detail"
        return "sim" if v.get("disposal") else "nao"

    def kept(self, f, s, events=None, filtro=True):
        evs = events if events is not None else [e for e in self.sub if self.sub[e] == s]
        return {self.det_of[e] for e in evs if self.sub[e] == s and self.state(f, e, filtro) == "sim"}

    def dets(self, s, events=None):
        evs = events if events is not None else list(self.sub)
        return {self.det_of[e] for e in evs if self.sub[e] == s}

    def funnel(self, f, pool=None, pf=None):
        """alertas por 1.000 por estrato, P(disparo) e custo. pool: {estrato: [eventos que passam no filtro]}."""
        g, d = FUNNELS[f]
        pf = pf or self.pf
        alerts, fire_rate = {}, {}
        for s in SUBS:
            evs = pool[s] if pool else [e for e in self.sub if self.sub[e] == s and self.passes(e)]
            st = Counter(self.state(f, e) for e in evs)
            n = len(evs) - st["sem_gate"]
            fired = st["sim"] + st["nao"] + st["sem_detail"]
            cov = st["sim"] + st["nao"]
            fr = self.w[s] * pf[s] * (fired / n if n else 0.0)
            fire_rate[s] = fr
            alerts[s] = 1000 * fr * (st["sim"] / cov if cov else 0.0)
        p_gate = sum(self.w[s] * pf[s] for s in SUBS)
        cost = C_D + p_gate * self.c_gate[g] + sum(fire_rate.values()) * self.c_det[d]
        return alerts, sum(fire_rate.values()), cost / TODAY - 1


def vertex_section(D):
    """A com o detail 3.8-flash no Vertex (pendencia 11): so nos eventos em que o gate do A dispara e que
    couberam na verba, S2C primeiro. Compara com o mesmo detail no AI Studio nos mesmos eventos."""
    path = RESULTS / f"detail54__d38f_g3_low_low_vtx{g54.SFX}__r1.jsonl"
    if not path.exists():
        return
    vx, ai = read_ok(path), D.det["d38f_g3_low_low"]
    sec("8. funil A com o detail no Vertex (mesma chamada; so eventos com disparo do A que couberam na verba)")
    for s in SUBS:
        evs = [e for e in vx if D.sub.get(e) == s and e in ai and D.passes(e)]
        if not evs:
            continue
        both = sum(bool(vx[e].get("disposal")) == bool(ai[e].get("disposal")) for e in evs)
        print(f"  {s:<3} eventos {len(evs)} | sim no Vertex {sum(bool(vx[e].get('disposal')) for e in evs)} | "
              f"sim no AI Studio {sum(bool(ai[e].get('disposal')) for e in evs)} | concordam {both}")
    for s, lab in (("S2C", "confirmadas"), ("S2R", "rejeitadas")):
        fired = [e for e in D.sub if D.sub[e] == s and D.state("A nova+3.8", e) in ("sim", "nao")]
        cov = [e for e in fired if e in vx]
        if not cov:
            continue
        dets = {D.det_of[e] for e in fired}
        kept_ai = {D.det_of[e] for e in fired if ai[e].get("disposal")}
        kept_vx = {D.det_of[e] for e in fired if (vx[e] if e in vx else ai[e]).get("disposal")}
        print(f"  {lab}: deteccoes com disparo do A {len(dets)}; eventos com disparo {len(fired)}, no Vertex {len(cov)} | "
              f"mantidas pelo A com o detail no AI Studio {len(kept_ai)}, com o Vertex (AI Studio onde faltou) {len(kept_vx)}")
    lat = sorted(r["latency_ms"] for r in vx.values() if r.get("latency_ms"))
    if lat:
        print(f"  latencia do detail no Vertex, modo padrao: p50 {lat[len(lat) // 2] / 1000:.1f} s, "
              f"p90 {lat[int(0.9 * len(lat))] / 1000:.1f} s, max {lat[-1] / 1000:.1f} s; "
              f"custo medio US$ {statistics.fmean(r['cost_usd'] for r in vx.values()):.5f}/chamada")


def sec(title):
    print(f"\n== {title}")


def main():
    D = Data()
    print(f"divisao: {g54.SPLIT}")
    names = list(FUNNELS)
    ev_by = {s: [e for e in D.sub if D.sub[e] == s] for s in SUBS}

    sec("0. conjunto")
    for s in SUBS:
        evs = ev_by[s]
        print(f"  {s:<3} eventos no pass {len(evs):>3} | passam no filtro {sum(D.passes(e) for e in evs):>3} | "
              f"deteccoes {len(D.dets(s)) if s.startswith('S2') else '-'} | peso na camera {D.w[s]:.4f} | "
              f"P(passa no filtro) {D.pf[s]:.3f} ({D.n_ok[s]}/{D.n_all[s]})")

    sec("1. funil refeito com leitor proprio; filtro aplicado evento a evento")
    print("  (funnels54 conta a deteccao como mantida mesmo quando o evento que dispara seria barrado pelo filtro)")
    for f in names:
        al, pfire, cost = D.funnel(f)
        k_f = D.kept(f, "S2C")
        k_nf = D.kept(f, "S2C", filtro=False)
        r_f = D.kept(f, "S2R")
        r_nf = D.kept(f, "S2R", filtro=False)
        st = {s: Counter(D.state(f, e) for e in ev_by[s]) for s in SUBS}
        print(f"  {f:<13} confirmadas {len(k_f)}/{len(D.dets('S2C'))} (sem aplicar o filtro: {len(k_nf)}) | "
              f"rejeitadas {len(r_f)}/{len(D.dets('S2R'))} (sem filtro: {len(r_nf)}) | alertas/1.000 "
              f"{sum(al.values()):.2f} | dispara {pfire:.2%} | custo {cost:+.1%}")
        print("      alertas/1.000 por estrato: " + ", ".join(f"{s} {al[s]:.2f}" for s in SUBS))
        print("      eventos por estado: " + " | ".join(
            f"{s}: sim {st[s]['sim']}, nao {st[s]['nao']}, sem detail {st[s]['sem_detail']}, gate nao "
            f"{st[s]['gate_nao']}, barrado {st[s]['barrado']}, sem gate {st[s]['sem_gate']}" for s in SUBS))
    conf = D.dets("S2C")
    lost = [d for d in conf if not any(D.passes(e) for e in ev_by["S2C"] if D.det_of[e] == d)]
    print(f"  confirmadas sem NENHUM evento que passe no filtro: {len(lost)} de {len(conf)}")

    sec("2. pares nas deteccoes (filtro aplicado): os dois | so X | so Y | nenhum | McNemar exato bilateral")
    for s, lab in (("S2C", "confirmadas"), ("S2R", "rejeitadas")):
        alld = D.dets(s)
        for x, y in (("A nova+3.8", "B 3.1fl+3.8"), ("A nova+3.8", "hoje refeito"), ("B 3.1fl+3.8", "hoje refeito")):
            kx, ky = D.kept(x, s), D.kept(y, s)
            b, c = len(kx - ky), len(ky - kx)
            print(f"  {lab:<11} {x:<12} x {y:<12}: {len(kx & ky):>2} | {b:>2} | {c:>2} | "
                  f"{len(alld - kx - ky):>2} | p = {mcnemar(b, c):.2f}")
    for f in names:
        k = len(D.kept(f, "S2C"))
        lo, hi = wilson(k, len(conf))
        print(f"  {f:<13} confirmadas {k}/{len(conf)} = {k / len(conf):.0%} (Wilson 95%: {lo:.0%} a {hi:.0%})")

    sec("3. por periodo (config. da camera muda em 02/08) e por hora (noite = 18h a 6h)")
    cuts = {"antes de 02/08": lambda e: day_of(e) < CUT, "02/08 em diante": lambda e: day_of(e) >= CUT,
            "dia": lambda e: not night(e), "noite": night}
    for lab, fn in cuts.items():
        print(f"  -- {lab}")
        for f in names:
            out = []
            for s in ("S2C", "S2R"):
                evs = [e for e in ev_by[s] if fn(e)]
                out.append(f"{s} {len(D.kept(f, s, evs))}/{len(D.dets(s, evs))}")
            for s in ("S1", "S0"):
                evs = [e for e in ev_by[s] if fn(e) and D.passes(e)]
                st = Counter(D.state(f, e) for e in evs)
                fired = st["sim"] + st["nao"] + st["sem_detail"]
                out.append(f"{s}: dispara {fired}/{len(evs)}, sim {st['sim']}/{st['sim'] + st['nao']}")
            evs = [e for e in ev_by["S0"] if fn(e) and D.state(f, e) == "sim"]
            lt = Counter(D.leit.get(e, "sem leitura") for e in evs)
            out.append("S0 sim lidos: " + ", ".join(f"{k} {v}" for k, v in sorted(lt.items())))
            print(f"     {f:<13} " + " | ".join(out))

    sec("4. margem por reamostragem (2.000 sorteios; eventos de S0/S1 e deteccoes de S2 com reposicao; "
        "P(passa no filtro) do S0 e do S1 sorteado junto)")
    rng = random.Random(54)
    base_pool = {s: [e for e in ev_by[s] if D.passes(e)] for s in SUBS}
    by_det = {s: defaultdict(list) for s in ("S2C", "S2R", "S2X")}
    for s in by_det:
        for e in base_pool[s]:
            by_det[s][D.det_of[e]].append(e)
    samples = defaultdict(list)
    for _ in range(2000):
        pool, pf = {}, dict(D.pf)
        for s in SUBS:
            if s in by_det:
                keys = list(by_det[s])
                pool[s] = [e for k in rng.choices(keys, k=len(keys)) for e in by_det[s][k]]
            else:
                pool[s] = rng.choices(base_pool[s], k=len(base_pool[s]))
                n = D.n_all[s]
                pf[s] = sum(rng.random() < D.pf[s] for _ in range(n)) / n if n < 5000 else D.pf[s]
        res = {f: D.funnel(f, pool, pf) for f in names}
        for f in names:
            al, pfire, cost = res[f]
            samples[f, "alertas"].append(sum(al.values()))
            samples[f, "alertas_S0"].append(al["S0"])
            samples[f, "custo"].append(cost)
        for x, y in (("A nova+3.8", "B 3.1fl+3.8"), ("A nova+3.8", "hoje refeito"), ("B 3.1fl+3.8", "hoje refeito")):
            samples[(x, y), "alertas"].append(sum(res[x][0].values()) - sum(res[y][0].values()))
            samples[(x, y), "custo"].append(res[x][2] - res[y][2])

    def ci(xs):
        xs = sorted(xs)
        return xs[int(0.025 * len(xs))], xs[int(0.975 * len(xs)) - 1]

    for f in names:
        al, pfire, cost = D.funnel(f)
        a, b = ci(samples[f, "alertas"])
        a0, b0 = ci(samples[f, "alertas_S0"])
        c, d = ci(samples[f, "custo"])
        print(f"  {f:<13} alertas/1.000 {sum(al.values()):.1f} [{a:.1f} a {b:.1f}] | so S0 {al['S0']:.1f} "
              f"[{a0:.1f} a {b0:.1f}] | custo {cost:+.0%} [{c:+.0%} a {d:+.0%}]")
    for (x, y) in (("A nova+3.8", "B 3.1fl+3.8"), ("A nova+3.8", "hoje refeito"), ("B 3.1fl+3.8", "hoje refeito")):
        a, b = ci(samples[(x, y), "alertas"])
        c, d = ci(samples[(x, y), "custo"])
        frac = sum(v < 0 for v in samples[(x, y), "alertas"]) / 2000
        print(f"  {x} - {y}: alertas/1.000 [{a:+.1f} a {b:+.1f}] (X menor em {frac:.0%} dos sorteios) | "
              f"custo, pontos [{100 * c:+.0f} a {100 * d:+.0f}]")

    sec("5. leitura a olho dos S0: contagem bruta por tras das taxas e o que os indefinidos podem mudar")
    for f in names:
        al, _, _ = D.funnel(f)
        evs = [e for e in base_pool["S0"] if D.state(f, e) == "sim"]
        lt = Counter(D.leit.get(e, "sem leitura") for e in evs)
        per = al["S0"] / len(evs) if evs else 0.0
        fal, ind, real = lt["falso_provavel"], lt["indeterminado"] + lt["sem leitura"], lt["descarte_provavel"]
        print(f"  {f:<13} S0 com sim: {len(evs)} eventos ({dict(sorted(lt.items()))}); cada evento vale "
              f"{per:.2f} alerta/1.000 | falsos/1.000: {fal * per:.1f} se os indefinidos forem descarte, "
              f"{(fal + ind) * per:.1f} se forem falsos | descartes novos/1.000: {real * per:.1f} a "
              f"{(real + ind) * per:.1f}")
    sA = {e for e in base_pool["S0"] if D.state("A nova+3.8", e) == "sim"}
    sB = {e for e in base_pool["S0"] if D.state("B 3.1fl+3.8", e) == "sim"}
    sC = {e for e in base_pool["S0"] if D.state("hoje refeito", e) == "sim"}
    print(f"  S0 com sim: A {len(sA)}, B {len(sB)}, os dois {len(sA & sB)}, so A {len(sA - sB)}, so B {len(sB - sA)}; "
          f"hoje refeito {len(sC)} (em comum com A {len(sA & sC)}, com B {len(sB & sC)})")
    for lab, st in (("so A", sA - sB), ("so B", sB - sA), ("os dois", sA & sB)):
        print(f"    {lab:<8} " + str(dict(sorted(Counter(D.leit.get(e, 'sem leitura') for e in st).items()))))

    sec("6. S1 (gate de producao disparou, detail de producao disse nao; sem rotulo do operador)")
    for f in names:
        evs = base_pool["S1"]
        st = Counter(D.state(f, e) for e in evs)
        al, _, _ = D.funnel(f)
        tot = sum(al.values())
        print(f"  {f:<13} S1: dispara {st['sim'] + st['nao'] + st['sem_detail']}/{len(evs)}, detail sim {st['sim']}/"
              f"{st['sim'] + st['nao']} | alertas/1.000 vindos de S1 {al['S1']:.2f} ({al['S1'] / tot:.0%} do total); "
              f"de S2 {al['S2C'] + al['S2R'] + al['S2X']:.2f}; de S0 {al['S0']:.2f}")

    if g54.SPLIT != "dev":
        vertex_section(D)
        return
    sec(f"7. regua da medicao final (finalista >= controle - 2 nas confirmadas), {N_AVAL_CONF} confirmadas")
    conf_l = sorted(conf)
    for f in ("A nova+3.8", "B 3.1fl+3.8"):
        kf, kc = D.kept(f, "S2C"), D.kept("hoje refeito", "S2C")
        both, only_f, only_c = len(kf & kc), len(kf - kc), len(kc - kf)
        n = len(conf_l)
        probs = [both / n, only_f / n, only_c / n]
        print(f"  {f}: no desenvolvimento os dois {both}, so finalista {only_f}, so controle {only_c}, "
              f"nenhum {n - both - only_f - only_c}")
        for lab, shift in (("como no desenvolvimento", 0.0), ("finalista = controle (troca simetrica)", None),
                           ("finalista 10 pontos pior", -0.10), ("finalista 20 pontos pior", -0.20)):
            p = list(probs)
            if shift is None:
                m = (p[1] + p[2]) / 2
                p[1] = p[2] = m
            elif shift:
                m = (p[1] + p[2]) / 2
                p[1], p[2] = max(0.0, m + shift / 2), m - shift / 2
            ok = 0
            trials = 20000
            for _ in range(trials):
                a = c = 0
                for _ in range(N_AVAL_CONF):
                    u = rng.random()
                    if u < p[0]:
                        a += 1
                        c += 1
                    elif u < p[0] + p[1]:
                        a += 1
                    elif u < p[0] + p[1] + p[2]:
                        c += 1
                ok += a >= c - 2
            print(f"      {lab:<40} P(passa na regua) = {ok / trials:.0%}")


if __name__ == "__main__":
    main()
