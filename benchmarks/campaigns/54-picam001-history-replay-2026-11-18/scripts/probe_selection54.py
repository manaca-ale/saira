#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — SEM CUSTO: camada de selecao do replay (missao 4, parte 2).

Responde, so com os arquivos locais (nada de API, nada de producao):
  1. quem ficou fora da base antes do sorteio (transientes, eventos curtos, nao avaliados);
  2. o corte da janela (subsample 48 + fit 8 MB) contra o window_size gravado pelo worker, e quem sao
     os eventos cuja janela reconstruida diverge (ficaram fora da amostra);
  3. estratos, taxa de disparo e tamanho de janela por versao do gate de movimento da Pi;
  4. o funil dos bracos _ctx refeito so com o periodo da configuracao atual (de 02/08 em diante), que
     e o que representa janeiro (so pi-cam), contra o periodo inteiro;
  5. sensibilidade: pares candidato x controle nas confirmadas, eventos do tri x fora do tri (o v1p
     foi escrito olhando o tri) e origem do contexto reconstituido (log x palpite);
  6. em quantos eventos que foram ao detail a producao mandou o contexto da janela anterior;
  7. tokens de entrada do detail, producao x replay da campanha 53 (o replay manda horario_local e
     nao manda o contexto; a producao faz o contrario).

Uso: python probe_selection54.py [--fast] > ../results/selection54__dev.txt
"""
from __future__ import annotations

import csv
import gzip
import json
import statistics
import sys
from collections import Counter, defaultdict

import draw_sample as ds
import run_gate54 as g
from agg_dgate54 import C_DET_NEW, RESULTS, wilson
from agg_funnel54 import stratum

ROOT = ds.ROOT
START = ds.START
CUR = "2026-08-02"          # a ultima versao do gate de movimento (2026-08-02_07-29-35) comeca aqui
C_D = 0.000169
ARMS = ("g25l_v1_t2048_ctx", "g31l_v1p_min_low_ctx", "nvl_v1p_low_ctx")
SUBS = ("S0", "S1", "S2C", "S2R", "S2X")


def pct(k, n):
    return f"{k}/{n} = {k / n:.1%}" if n else f"{k}/0"


def load_arm(arm, rep=1):
    out = {}
    p = RESULTS / f"gate54__{arm}__r{rep}.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error"):
                out[r["event_id"]] = r
    return out


def fire(r):
    return bool(r["new_litter"]) and r["conf"] >= 85


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    fast = "--fast" in sys.argv
    allrows = list(csv.DictReader((ROOT / "base" / "base_eventos.csv").open(encoding="utf-8", newline="")))
    base = [r for r in allrows if r["dia"] >= START]
    ev = [r for r in base if r["gate_avaliou"] == "1"]

    # ---------------------------------------------------------------- 1. fora da base
    print("== 1. Quem ficou fora antes do sorteio ==")
    print(f"manifestos no disco: {len(allrows)} | antes de {START} (worker ainda nao lia a Pi): {len(allrows) - len(base)} "
          f"| desde {START}: {len(base)} | avaliados pelo gate: {len(ev)} | nao avaliados: {len(base) - len(ev)}")
    print("motivo de fechamento (todos desde 14/07):", dict(Counter(r["closed_reason"] or "(vazio)" for r in base)))
    non = [r for r in base if r["gate_avaliou"] != "1"]
    print("nao avaliados por motivo de fechamento:", dict(Counter(r["closed_reason"] or "(vazio)" for r in non)))
    print("nao avaliados por numero de frames:", dict(sorted(Counter(
        "<3" if int(r["n_frames"] or 0) < 3 else "3 a 9" if int(r["n_frames"]) < 10 else "10+" for r in non).items())))
    print("nao avaliados por semana:", dict(sorted(Counter(r["semana"] for r in non).items())))
    print("nao avaliados por dia (os 5 maiores):", Counter(r["dia"] for r in non).most_common(5))
    short_eval = sum(1 for r in ev if int(r["n_frames"] or 0) < 3)
    print(f"avaliados com menos de 3 frames no manifesto: {short_eval} | avaliados com mais de uma linha de auditoria: "
          f"{sum(1 for r in ev if int(r['n_linhas_auditoria'] or 0) > 1)}")
    calls = Counter()
    with (ROOT / "raw" / "gemini_call_log_picam.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["call_date_brt"] >= START:
                calls[(r["agent"], r["success"])] += 1
    print("chamadas no gemini_call_log desde 14/07 (agente, sucesso):", dict(calls))

    # ---------------------------------------------------------------- 2. corte da janela
    print("\n== 2. Corte da janela (subsample 48 + fit 8 MB) contra o window_size gravado ==")
    zidx = {}
    with gzip.open(ROOT / "raw" / "zip_dirs.tsv.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            zidx[p[1].rsplit("/", 1)[-1]] = int(p[5])
    det_frames = {}
    for p in (ds.EXT / "detection_frames").glob("*.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if j.get("device_id") == "pi-cam-001":
            det_frames[j["detection_id"]] = {f["frame_name"] for f in j.get("frames") or []}
    stat = defaultdict(Counter)
    diverg = []
    for r in (() if fast else ev):      # --fast pula a leitura dos 31.706 manifestos
        s = stratum(r)
        s3 = "S2" if s.startswith("S2") else s
        m = json.loads((ds.EXT / "events" / f"{r['event_id']}.json").read_text(encoding="utf-8"))
        names = sorted(f.rsplit("/", 1)[-1] for f in m.get("frames") or [])
        last = r["window_last_frame"]
        early = last in names and last != names[-1]
        if last in names:
            names = [n for n in names if n <= last]
        rec = int(r["window_size"]) if str(r["window_size"]).isdigit() else -1
        if s3 == "S2":
            win = [n for n in names if n in (det_frames.get(r["detection_id"]) or set())]
            if not win:
                stat[s3]["sem frames no registro da deteccao"] += 1
                diverg.append((r, s, len(names), 0, rec, "sem registro"))
                continue
            sub48 = win
        else:
            if any(n not in zidx for n in names):
                stat[s3]["frames fora dos zips"] += 1
                continue
            sub48 = ds.subsample(names, ds.MAX_FRAMES)
            win = ds.fit(sub48, zidx, ds.MAX_BYTES)
            stat[s3]["mais de 48 frames (subamostra por contagem)"] += len(names) > ds.MAX_FRAMES
            stat[s3]["cortado pelo teto de 8 MB"] += len(win) < len(sub48)
        ok = rec == len(win) and win[-1] == last and win[0] == r["first_frame"]
        stat[s3]["total"] += 1
        stat[s3]["identica"] += ok
        stat[s3]["julgado antes de o evento fechar"] += early
        if s3 != "S2" and len(win) < len(sub48):
            stat[s3]["cortado pelo teto e identica"] += ok
        if not ok:
            diverg.append((r, s, len(names), len(win), rec, "difere"))
    for s3 in ("S0", "S1", "S2"):
        print(f"{s3}: " + ", ".join(f"{k} {v}" for k, v in stat[s3].items()))
    print(f"divergentes (fora da amostra): {len(diverg)}")
    print("  por estrato:", dict(Counter(d[1] for d in diverg)))
    print("  por semana:", dict(sorted(Counter(d[0]["semana"] for d in diverg).items())))
    print("  reconstruida menos gravada (frames):", dict(sorted(Counter(d[3] - d[4] for d in diverg).items())))
    dets_all, dets_div = defaultdict(set), defaultdict(set)
    for r in ev:
        s = stratum(r)
        if s.startswith("S2"):
            dets_all[s].add(r["detection_id"])
    div_ids = {d[0]["event_id"] for d in diverg}
    kept = defaultdict(set)
    for r in ev:
        s = stratum(r)
        if s.startswith("S2") and r["event_id"] not in div_ids:
            kept[s].add(r["detection_id"])
    for s in ("S2C", "S2R", "S2X"):
        n_ev = sum(1 for r in ev if stratum(r) == s)
        n_div = sum(1 for d in diverg if d[1] == s)
        print(f"  {s}: eventos {n_ev}, divergentes {n_div} ({n_div / n_ev:.0%}); deteccoes {len(dets_all[s])}, "
              f"com pelo menos um evento na amostra {len(kept[s])}, perdidas inteiras {len(dets_all[s] - kept[s])}")

    # ---------------------------------------------------------------- 3. por versao do gate de movimento
    print("\n== 3. Estratos por versao do gate de movimento da Pi (eventos avaliados) ==")
    byv = defaultdict(list)
    for r in ev:
        byv[r["gate_config_version"] or "(sem versao)"].append(r)
    print("versao | dias | eventos | S0 | S1 | S2C | S2R | S2X | gate disparou | janela mediana | frames medianos")
    for v, rs in sorted(byv.items(), key=lambda kv: min(r["dia"] for r in kv[1])):
        c = Counter(stratum(r) for r in rs)
        n = len(rs)
        ws = [int(r["window_size"]) for r in rs if str(r["window_size"]).isdigit()]
        print(f"{v} | {min(r['dia'] for r in rs)} a {max(r['dia'] for r in rs)} | {n} | "
              + " | ".join(f"{c[s] / n:.2%}" for s in SUBS)
              + f" | {(n - c['S0']) / n:.2%} | {statistics.median(ws):.0f} | "
              f"{statistics.median(int(r['n_frames'] or 0) for r in rs):.0f}")
    for lab, sel in (("14/07 a 01/08", lambda r: r["dia"] < CUR), ("02/08 a 08/09", lambda r: r["dia"] >= CUR)):
        rs = [r for r in ev if sel(r)]
        c = Counter(stratum(r) for r in rs)
        print(f"periodo {lab}: {len(rs)} eventos | " + ", ".join(f"{s} {c[s]} ({c[s] / len(rs):.2%})" for s in SUBS)
              + f" | gate disparou {(len(rs) - c['S0']) / len(rs):.2%}")

    # ---------------------------------------------------------------- 4. funil por periodo
    print("\n== 4. Funil dos bracos com contexto: periodo inteiro x configuracao atual (02/08 em diante) ==")
    rows = g.load_dev()
    dia = {r["event_id"]: r["dia"] for r in rows}
    in_pass = {r["event_id"]: r for r in g.build_set("pass", 0.30, rows)}
    in_tri = {r["event_id"] for r in g.build_set("tri", 0.30, rows)}
    # custo de hoje por periodo, direto do registro de chamadas
    cost = defaultdict(lambda: defaultdict(float))
    ncall = defaultdict(lambda: defaultdict(int))
    with (ROOT / "raw" / "gemini_call_log_picam.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            d = r["call_date_brt"]
            if d < START or r["success"] != "t":
                continue
            for lab in ("tudo", "atual" if d >= CUR else "antes"):
                cost[lab][r["agent"]] += float(r["estimated_cost_usd"] or 0)
                ncall[lab][r["agent"]] += 1
    arms = {a: load_arm(a) for a in ARMS}

    def funnel(lab, sel_day):
        pop = [r for r in ev if sel_day(r["dia"])]
        w = Counter(stratum(r) for r in pop)
        w = {s: w[s] / len(pop) for s in SUBS}
        dev = [r for r in rows if sel_day(r["dia"]) and r["score"] is not None]
        n_s, p_s = Counter(r["sub"] for r in dev), Counter(r["sub"] for r in dev if r["score"] >= 0.30)
        pf = {s: p_s[s] / n_s[s] if n_s[s] else 0.0 for s in SUBS}
        p_gate = sum(w[s] * pf[s] for s in SUBS)
        agents = cost[lab]
        n_gate = ncall[lab]["gate"]
        today = (agents["gate"] + agents["detail"]) / n_gate     # sem as chamadas de shadow
        c_det_new = C_DET_NEW
        print(f"\n[{lab}] populacao {len(pop)} | pesos " + ", ".join(f"{s} {w[s]:.4f}" for s in SUBS))
        print(f"  dev com nota do filtro: " + ", ".join(f"{s} {p_s[s]}/{n_s[s]}" for s in SUBS)
              + f" | vai ao gate {p_gate:.1%} | producao dispara {sum(w[s] for s in SUBS if s != 'S0'):.2%} dos eventos"
              f" ({sum(w[s] * pf[s] for s in SUBS if s != 'S0'):.2%} depois do filtro)")
        print(f"  custo de hoje no periodo: US$ {today:.6f}/evento (gate US$ {agents['gate'] / n_gate:.6f}/chamada, "
              f"{ncall[lab]['detail']} chamadas de detail)")
        for a in ARMS:
            recs = arms[a]
            cnt, fr = Counter(), Counter()
            dets = defaultdict(bool)
            for i, r in recs.items():
                if i not in in_pass or not sel_day(dia[i]):
                    continue
                s = in_pass[i]["sub"]
                cnt[s] += 1
                fr[s] += fire(r)
                if s == "S2C":
                    dets[r["detection_id"]] |= fire(r)
            c_call = statistics.fmean(r["cost_usd"] for i, r in recs.items() if i in in_pass and sel_day(dia[i]))
            f2 = (fr["S2C"] + fr["S2R"]) / max(1, cnt["S2C"] + cnt["S2R"])
            fx = {s: (fr[s] / cnt[s] if cnt[s] else f2) for s in SUBS}

            def c_of(f0):
                p_fire = w["S0"] * pf["S0"] * f0 + sum(w[s] * pf[s] * fx[s] for s in SUBS if s != "S0")
                return C_D + p_gate * c_call + p_fire * c_det_new, p_fire
            lo, hi = wilson(fr["S0"], cnt["S0"])
            full, p_fire = c_of(fx["S0"])
            print(f"  {a}: S0 {pct(fr['S0'], cnt['S0'])} | S1 {pct(fr['S1'], cnt['S1'])} | S2C {pct(fr['S2C'], cnt['S2C'])} "
                  f"| S2R {pct(fr['S2R'], cnt['S2R'])} | confirmadas {sum(dets.values())}/{len(dets)} | dispara {p_fire:.2%} "
                  f"({c_of(lo)[1]:.2%} a {c_of(hi)[1]:.2%}) | US$ {c_call:.6f}/chamada | funil {full / today - 1:+.0%} "
                  f"({c_of(lo)[0] / today - 1:+.0%} a {c_of(hi)[0] / today - 1:+.0%})")

    funnel("tudo", lambda d: True)
    funnel("atual", lambda d: d >= CUR)
    funnel("antes", lambda d: d < CUR)

    # ---------------------------------------------------------------- 5. sensibilidade
    print("\n== 5. Sensibilidade ==")
    ctrl = arms["g25l_v1_t2048_ctx"]
    det_of = defaultdict(dict)
    for a in ARMS:
        for i, r in arms[a].items():
            if i in in_pass and in_pass[i]["sub"] == "S2C":
                det_of[a][r["detection_id"]] = det_of[a].get(r["detection_id"], False) or fire(r)
    for a in ARMS[1:]:
        both = sorted(set(det_of[a]) & set(det_of[ARMS[0]]))
        t = Counter((det_of[ARMS[0]][d], det_of[a][d]) for d in both)
        print(f"confirmadas, {a} x controle (n={len(both)}): os dois mantem {t[(True, True)]}, so o candidato "
              f"{t[(False, True)]}, so o controle {t[(True, False)]}, nenhum {t[(False, False)]}")
    allk = sorted(set.intersection(*(set(det_of[a]) for a in ARMS)))
    print(f"confirmadas que NENHUM dos tres mantem: {sum(1 for d in allk if not any(det_of[a][d] for a in ARMS))} de {len(allk)}; "
          f"que pelo menos um candidato mantem: {sum(1 for d in allk if any(det_of[a][d] for a in ARMS[1:]))}")
    print("eventos do tri x fora do tri (o v1p foi escrito olhando as perdas do tri):")
    for a in ARMS:
        parts = []
        for s in ("S0", "S1", "S2R"):
            for lab, sel in (("tri", True), ("fora", False)):
                xs = [fire(r) for i, r in arms[a].items() if i in in_pass and in_pass[i]["sub"] == s and (i in in_tri) == sel]
                parts.append(f"{s} {lab} {pct(sum(xs), len(xs))}")
        print(f"  {a}: " + " | ".join(parts))
    print("origem do contexto reconstituido (log = contagem de tokens diz o texto; palpite = texto do mesmo tamanho):")
    for a in ARMS:
        parts = []
        for src in ("log", "log_palpite", "sem_par"):
            for s in ("S0", "S1+S2"):
                xs = [fire(r) for i, r in arms[a].items() if i in in_pass and r.get("prior_src") == src
                      and ((in_pass[i]["sub"] == "S0") == (s == "S0"))]
                if xs:
                    parts.append(f"{src} {s} {pct(sum(xs), len(xs))}")
        print(f"  {a}: " + " | ".join(parts))
    print("tipo do contexto nos eventos do pass (controle):", dict(Counter(
        "sem contexto" if r.get("prior_type") is None else (r["prior_type"] or "sem tipo") for i, r in ctrl.items() if i in in_pass)))

    # ---------------------------------------------------------------- 6. contexto no detail
    print("\n== 6. Contexto da janela anterior nos eventos que foram ao detail em producao ==")
    pc = g.prior_contexts()
    for lab, sel in (("gate disparou (detail rodou)", lambda r: r["gate_disparou"] == "1"),
                     ("S2 confirmadas", lambda r: stratum(r) == "S2C"),
                     ("gate nao disparou", lambda r: r["gate_disparou"] != "1")):
        rs = [r for r in ev if sel(r)]
        c = Counter()
        for r in rs:
            t, d, src = pc.get(r["event_id"], (None, None, "fora"))
            c["sem par no log" if src == "sem_par" else "sem contexto" if t is None else "com contexto"] += 1
        print(f"{lab}: {len(rs)} eventos | " + ", ".join(f"{k} {v} ({v / len(rs):.1%})" for k, v in c.most_common()))

    # ---------------------------------------------------------------- 7. tokens do detail
    print("\n== 7. Tokens de entrada do detail: producao x replay (campanha 53, d25f_v1, Vertex) ==")
    tok = {}
    with (ROOT / "raw" / "gemini_call_log_picam.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["agent"] == "detail" and r["success"] == "t" and r["input_tokens"]:
                tok[r["request_id"]] = int(r["input_tokens"])
    wsz = {r["agent1_request_id"]: (int(r["window_size"]), r["event_id"]) for r in ev if str(r["window_size"]).isdigit()}
    prod = {}
    with (ROOT / "raw" / "detections_cam15.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["agent2_request_id"] in tok and r["agent1_request_id"] in wsz:
                n, eid = wsz[r["agent1_request_id"]]
                prod[eid] = (n, tok[r["agent2_request_id"]])
    c53 = RESULTS.parents[1] / "53-picam001-migration-post-25flash-2026-11-16" / "results"
    bench = {}
    for rep in (1, 2):
        for line in (c53 / f"detail__d25f_v1__r{rep}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if not r.get("error") and r.get("tok_in"):
                    bench[r["event_id"]] = (r["n_sent"], r["tok_in"])

    def line_fit(pts):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        b = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x in xs)
        return my - b * mx, b
    for lab, d in (("producao (deteccoes com chamada no log)", prod), ("replay camp 53", bench)):
        a0, b0 = line_fit(list(d.values()))
        print(f"{lab}: n={len(d)} | tokens = {a0:.0f} + {b0:.1f} x frames")
    same = sorted(set(prod) & set(bench))
    diffs = [prod[e][1] - bench[e][1] for e in same if prod[e][0] == bench[e][0]]
    print(f"mesmo evento e mesmo numero de frames nos dois: {len(diffs)} | producao menos replay, em tokens: "
          f"{dict(sorted(Counter(diffs).items()))}")
    pc_t = {e: pc.get(e) for e in same}
    byt = defaultdict(list)
    for e in same:
        if prod[e][0] == bench[e][0]:
            byt[pc_t[e][0] if pc_t[e] else "?"].append(prod[e][1] - bench[e][1])
    print("por tipo do contexto que o gate recebeu:", {str(k): dict(Counter(v)) for k, v in byt.items()})


if __name__ == "__main__":
    main()
