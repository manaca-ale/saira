#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — revisao independente do filtro barato da missao 1 (sem custo de API, so desenvolvimento).

Refaz por outro caminho as contas de agg_funnel54.py e procura explicacoes alternativas:
  A. constantes de custo conferidas contra o registro de chamadas da producao (14/07 a 08/09);
  B. custo por evento do funil refeito do zero, com intervalo por reamostragem de todos os estratos
     (o intervalo do agg_funnel54 so considera a margem de S0);
  C. a redacao wl_v2 foi escrita olhando 4 confirmadas fracas: comparacao com worth_look (sem ajuste)
     nas outras 28 confirmadas e em S0;
  D. limiar escolhido numa metade e aplicado na outra;
  F. eventos S2 que ficaram fora da amostra (frames divergentes): ha confirmada inteira de fora?
  G. passagem de S0 por semana e por periodo do dia (o ganho depende dela).

Uso: python review54.py [--thr 0.30]
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
from collections import Counter, defaultdict

from agg_dgate54 import BASE, C_DET_NEW, C_DET_OLD, C_GATE, N_EVT, TODAY, auc, wilson
from agg_funnel54 import STRATA, load, stratum

# Eventos das 4 confirmadas fracas usadas para escrever a redacao wl_v2 (secao 12.1 do arquivo do replay).
TUNED = {"evt-20260724_130940", "evt-20260803_094821", "evt-20260825_033529", "evt-20260905_080502"}
RAW_LOG = BASE.parent / "raw" / "gemini_call_log_picam.csv"
SAMPLE = BASE.parent / "amostra" / "sample.csv"


def ns(qset):
    return argparse.Namespace(qset=qset, res="low", rep=1, split="dev", from_day="2026-07-14", to_day="2026-12-31")


def pct(k, n):
    return f"{k}/{n} = {100 * k / n:.1f}%" if n else "0/0"


def section_a():
    print("A. constantes de custo x registro de chamadas (14/07 a 08/09)")
    agg = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for r in csv.DictReader(RAW_LOG.open(encoding="utf-8", newline="")):
        if not ("2026-07-14" <= r["call_date_brt"] <= "2026-09-08"):
            continue
        a = agg[r["agent"]]
        ok = r["success"] == "t"
        a[0] += 1
        a[1] += ok
        c = float(r["estimated_cost_usd"] or 0)
        a[2] += c
        a[3] += c if ok else 0.0
    for ag, (n, ok, c, cok) in sorted(agg.items()):
        print(f"  {ag:8s} chamadas {n:6d} | com sucesso {ok:6d} | custo total US$ {c:.4f} | custo so das com sucesso "
              f"US$ {cok:.4f} | por chamada {c / n:.6f} | por chamada com sucesso {cok / ok if ok else 0:.6f}")
    print(f"  no script: N_EVT {N_EVT} | C_GATE {C_GATE:.6f} | C_DET_OLD {C_DET_OLD:.6f} | C_DET_NEW {C_DET_NEW:.6f} "
          f"| TODAY {TODAY:.6f}")


def funnel_cost(W, frac_pass, cd, c_det):
    """custo por evento = cD + P(passa) * cGate + P(passa e disparou) * cDetail, pesos reais dos estratos."""
    n_pop = sum(W.values())
    p_pass = sum(W[s] / n_pop * frac_pass.get(s, 0.0) for s in STRATA)
    p_fired = sum(W[s] / n_pop * frac_pass.get(s, 0.0) for s in STRATA if s != "S0")
    return cd + p_pass * C_GATE + p_fired * c_det, p_pass, p_fired


def fracs(rows, key, thr):
    by = defaultdict(list)
    for r in rows:
        by[r["s"]].append(r["p"][key] >= thr)
    return {s: sum(v) / len(v) for s, v in by.items()}


def section_b(W, rows, tok, key, thr):
    print(f"\nB. custo por evento refeito (pergunta {key}, limiar {thr:.2f}, {len(rows)} eventos de desenvolvimento)")
    cd = tok * 0.10 / 1e6
    n_pop = sum(W.values())
    print(f"  populacao {n_pop}: " + ", ".join(f"{s} {W[s]} ({100 * W[s] / n_pop:.2f}%)" for s in STRATA))
    fp = fracs(rows, key, thr)
    print("  fracao que passa por estrato: " + ", ".join(f"{s} {100 * fp.get(s, 0):.1f}%" for s in STRATA))
    for label, c_det in (("detail recomendado", C_DET_NEW), ("detail de hoje", C_DET_OLD)):
        c, pp, pf = funnel_cost(W, fp, cd, c_det)
        print(f"  filtro + gate de hoje + {label}: US$ {c:.6f} por evento = {100 * (c / TODAY - 1):+.1f}% "
              f"(chegam ao gate {100 * pp:.1f}%, chegam ao detail {100 * pf:.2f}%)")
    one = {s: 1.0 for s in STRATA}
    c0, _, pf0 = funnel_cost(W, one, 0.0, C_DET_NEW)
    print(f"  sem filtro, detail recomendado: US$ {c0:.6f} = {100 * (c0 / TODAY - 1):+.1f}% (detail em {100 * pf0:.2f}%)")
    c1, _, _ = funnel_cost(W, one, 0.0, C_DET_OLD)
    print(f"  sem filtro, detail de hoje (deveria dar o custo de hoje): US$ {c1:.6f} = {100 * (c1 / TODAY - 1):+.1f}%")
    parts = (cd, funnel_cost(W, fp, 0, 0)[0], funnel_cost(W, fp, 0, C_DET_NEW)[0] - funnel_cost(W, fp, 0, 0)[0])
    tot = sum(parts)
    print("  composicao do custo com filtro: Decisions {:.0f}%, gate {:.0f}%, detail {:.0f}%".format(
        *(100 * p / tot for p in parts)))

    # reamostragem: S0 e S1 por evento, S2 por deteccao (eventos da mesma deteccao andam juntos)
    rnd = random.Random(54)
    units = defaultdict(lambda: defaultdict(list))
    for r in rows:
        units[r["s"]][r["det"] if r["s"].startswith("S2") else r["id"]].append(r["p"][key] >= thr)
    sims = []
    for _ in range(2000):
        f = {}
        for s, u in units.items():
            keys = list(u)
            picked = [x for k in rnd.choices(keys, k=len(keys)) for x in u[k]]
            f[s] = sum(picked) / len(picked)
        sims.append(100 * (funnel_cost(W, f, cd, C_DET_NEW)[0] / TODAY - 1))
    sims.sort()
    print(f"  intervalo de 95% por reamostragem de todos os estratos: {sims[50]:+.1f}% a {sims[1949]:+.1f}% "
          f"(mediana {statistics.median(sims):+.1f}%)")


def best_by_det(rows, key):
    best = {}
    for r in rows:
        if r["s"] == "S2C":
            best[r["det"]] = max(best.get(r["det"], 0.0), r["p"][key])
    return best


def section_c(data):
    print("\nC. redacao ajustada (wl_v2) x redacao sem ajuste (worth_look), fora das 4 confirmadas usadas no ajuste")
    for qset, key in (("q3", "worth_look"), ("q4", "worth_look"), ("q4", "wl_v2"), ("q5", "wl_v2")):
        _, _, rows, _ = data[qset]
        tuned_det = {r["det"] for r in rows if r["id"] in TUNED}
        best = best_by_det(rows, key)
        held = {d: v for d, v in best.items() if d not in tuned_det}
        tun = {d: v for d, v in best.items() if d in tuned_det}
        s0 = [r["p"][key] for r in rows if r["s"] == "S0"]
        pos = [r["p"][key] for r in rows if r["s"] == "S2C" and r["det"] not in tuned_det]
        t_held = min(held.values())
        k = sum(x >= t_held for x in s0)
        lo, hi = wilson(k, len(s0))
        low3 = ", ".join(f"{v:.3f}" for v in sorted(held.values())[:3])
        print(f"  {qset}/{key}: {len(held)} confirmadas de fora do ajuste, menores notas {low3}; "
              f"as {len(tun)} do ajuste: " + ", ".join(f"{v:.3f}" for v in sorted(tun.values())))
        print(f"      limiar que mantem as {len(held)} de fora = {t_held:.3f} -> S0 passa {pct(k, len(s0))} "
              f"[{100 * lo:.1f} a {100 * hi:.1f}] | AUC S0 x confirmadas de fora {auc(pos, s0):.3f}")
        for t in (0.22, 0.30, 0.35):
            print(f"      limiar {t:.2f}: de fora {sum(v >= t for v in held.values())}/{len(held)}, do ajuste "
                  f"{sum(v >= t for v in tun.values())}/{len(tun)}, S0 passa {pct(sum(x >= t for x in s0), len(s0))}")


def section_d(rows, key):
    print(f"\nD. limiar escolhido numa metade (mantem todas as confirmadas dela) aplicado na outra ({key})")
    best, hf = best_by_det(rows, key), {r["det"]: r["half"] for r in rows}
    for a, b in (("A", "B"), ("B", "A")):
        t = min(v for d, v in best.items() if hf[d] == a)
        other = [v for d, v in best.items() if hf[d] == b]
        s0 = [r["p"][key] for r in rows if r["s"] == "S0" and r["half"] == b]
        print(f"  limiar de {a} = {t:.3f} -> em {b}: confirmadas {sum(v >= t for v in other)}/{len(other)}, "
              f"S0 passa {pct(sum(x >= t for x in s0), len(s0))}")
        t2 = round(0.75 * t, 3)
        print(f"  com folga de 25% (limiar {t2:.3f}) -> em {b}: confirmadas {sum(v >= t2 for v in other)}/{len(other)}, "
              f"S0 passa {pct(sum(x >= t2 for x in s0), len(s0))}")


def section_f(base):
    print("\nF. eventos com detail 'sim' (S2) fora da amostra")
    samp = {}
    for r in csv.DictReader(SAMPLE.open(encoding="utf-8", newline="")):
        samp[r["event_id"]] = r["split"]
    det_all, det_in, out_ev = defaultdict(set), defaultdict(set), Counter()
    for ev, b in base.items():
        if not b["s"].startswith("S2"):
            continue
        det_all[b["s"]].add(b["det"])
        if ev in samp:
            det_in[(b["s"], samp[ev])].add(b["det"])
            det_in[(b["s"], "qualquer")].add(b["det"])
        else:
            out_ev[b["s"]] += 1
    for s in ("S2C", "S2R", "S2X"):
        gone = det_all[s] - det_in[(s, "qualquer")]
        print(f"  {s}: {len(det_all[s])} deteccoes na base | na amostra: desenvolvimento {len(det_in[(s, 'dev')])}, "
              f"avaliacao {len(det_in[(s, 'aval')])} | eventos fora da amostra {out_ev[s]} | "
              f"deteccoes inteiras de fora {len(gone)}")


def section_g(base, rows, key, thr):
    print(f"\nG. passagem de S0 por semana e por periodo do dia ({key} >= {thr:.2f})")
    wk, hr = {}, {}
    for r in csv.DictReader((BASE / "base_eventos.csv").open(encoding="utf-8", newline="")):
        wk[r["event_id"]], hr[r["event_id"]] = r["semana"], r["hora"]
    by_w, by_h = defaultdict(list), defaultdict(list)
    for r in rows:
        if r["s"] != "S0":
            continue
        ok = r["p"][key] >= thr
        by_w[wk[r["id"]]].append(ok)
        try:
            h = int(str(hr[r["id"]])[:2])
        except ValueError:
            h = -1
        by_h["dia (06-17h)" if 6 <= h < 18 else "noite (18-05h)"].append(ok)
    for name, by in (("semana", by_w), ("periodo", by_h)):
        for k in sorted(by):
            v = by[k]
            lo, hi = wilson(sum(v), len(v))
            print(f"  {name} {k}: {pct(sum(v), len(v))} [{100 * lo:.0f} a {100 * hi:.0f}]")
    for s in ("S2R", "S2X", "S1"):
        ev = [r for r in rows if r["s"] == s]
        dets = defaultdict(bool)
        for r in ev:
            dets[r["det"]] |= r["p"][key] >= thr
        print(f"  {s}: eventos {pct(sum(r['p'][key] >= thr for r in ev), len(ev))}; deteccoes "
              f"{pct(sum(dets.values()), len(dets))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thr", type=float, default=0.30)
    a = ap.parse_args()
    data = {q: load(ns(q)) for q in ("q3", "q4", "q5")}
    base, W, rows, tok = data["q5"]
    section_a()
    section_b(W, rows, tok, "wl_v2", a.thr)
    section_c(data)
    section_d(rows, "wl_v2")
    section_f(base)
    section_g(base, rows, "wl_v2", a.thr)


if __name__ == "__main__":
    main()
