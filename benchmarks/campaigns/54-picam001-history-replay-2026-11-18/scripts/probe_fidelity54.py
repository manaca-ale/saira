"""Fidelidade do replay com a producao: sondas sem custo (missao 4, camada "entrada").

Subcomandos:
  tokens-prod    input_tokens do gate em producao por dia (gemini_call_log_picam.csv)
  tokens-bench   tok_in dos registros de gate das campanhas 53 (Vertex) e 54 (AI Studio)
  first-frame    o frame de referencia do gate e o 1o frame do proprio evento?
  params-prod    limiar, tokens de pensamento, falhas e impressao digital do contexto
                 da janela anterior (input_tokens - 2429) nas chamadas de producao
"""
import argparse
import csv
import glob
import json
import os
import statistics as st
from collections import Counter, defaultdict

ROOT = "C:/Saira/data/historico-picam"
HERE = os.path.dirname(os.path.abspath(__file__))
C54 = os.path.dirname(HERE)
C53 = glob.glob(os.path.join(os.path.dirname(C54), "53-*"))[0]


def tokens_prod(_a):
    by_day = defaultdict(list)
    models = defaultdict(Counter)
    with open(f"{ROOT}/raw/gemini_call_log_picam.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["agent"] != "gate" or r["success"] != "t" or not r["input_tokens"]:
                continue
            by_day[r["call_date_brt"]].append(int(r["input_tokens"]))
            models[r["call_date_brt"]][r["model"]] += 1
    print("dia         n     min   p50   max   modas(top3)                modelos")
    for d in sorted(by_day):
        v = by_day[d]
        top = ", ".join(f"{k}x{c}" for k, c in Counter(v).most_common(3))
        print(f"{d} {len(v):5d} {min(v):5d} {int(st.median(v)):5d} {max(v):5d}   {top:26s} "
              f"{dict(models[d])}")


def tokens_bench(_a):
    for pat in (os.path.join(C53, "results", "gate__g25l_v1__r*.jsonl"),
                os.path.join(C54, "results", "gate54__g25l_*__r*.jsonl")):
        for p in sorted(glob.glob(pat)):
            v, be = [], Counter()
            with open(p, encoding="utf-8") as f:
                for ln in f:
                    r = json.loads(ln)
                    t = r.get("tok_in") or (r.get("usage") or {}).get("input_tokens")
                    if t:
                        v.append(int(t))
                        be[r.get("backend", "?")] += 1
            if v:
                top = ", ".join(f"{k}x{c}" for k, c in Counter(v).most_common(3))
                print(f"{os.path.basename(p):40s} n={len(v):5d} min={min(v)} p50={int(st.median(v))} "
                      f"max={max(v)} modas={top} backend={dict(be)}")
            else:
                print(f"{os.path.basename(p):40s} sem tok_in")


def _audit_picam():
    for p in sorted(glob.glob(f"{ROOT}/extraido/gemini_cascade_audit/*/pi-cam-001.jsonl")):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    yield json.loads(ln)


def first_frame(_a):
    """O frame de referencia do gate (window_first_frame da auditoria = first_frame do
    worker, que pode ser herdado do evento anterior) e o 1o frame do proprio evento?"""
    by_last, order = {}, []
    for p in glob.glob(f"{ROOT}/extraido/events/evt-*.json"):
        try:
            with open(p, encoding="utf-8") as f:
                m = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        fr = [os.path.basename(x) for x in m.get("frames") or []]
        if fr:
            order.append((m["event_id"], fr))
    order.sort()
    pos = {}
    for i, (eid, fr) in enumerate(order):
        for k, name in enumerate(fr):
            pos[name] = (i, k, len(fr))
    c = Counter()
    ex = defaultdict(list)
    for r in _audit_picam():
        f1, f2 = r["window_first_frame"], r["window_last_frame"]
        if f2 not in pos:
            c["ultimo frame fora dos manifestos"] += 1
            continue
        i2, k2, n2 = pos[f2]
        if f1 not in pos:
            kind = "1o frame fora dos manifestos"
        else:
            i1, k1, n1 = pos[f1]
            if i1 == i2:
                kind = "mesmo evento, 1o frame" if k1 == 0 else "mesmo evento, frame interno"
            elif i1 == i2 - 1 and k1 == n1 - 1:
                kind = "HERDADO: ultimo frame do evento anterior"
            else:
                kind = f"outro evento (dist {i2 - i1})"
        c[kind] += 1
        if len(ex[kind]) < 1:
            ex[kind].append((f1, f2, r.get("created_at")))
    tot = sum(c.values())
    for k, v in c.most_common():
        print(f"{v:6d} {100 * v / tot:6.2f}%  {k}")
        if not k.startswith("mesmo evento, 1o"):
            for e in ex[k]:
                print("         ex:", e)


def params_prod(_a):
    lo, hi = "2026-07-14", "2026-09-08"
    thr, conf = Counter(), Counter()
    for p in sorted(glob.glob(f"{ROOT}/extraido/gemini_cascade_audit/*/pi-cam-001.jsonl")):
        if not (lo <= os.path.basename(os.path.dirname(p)) <= hi):
            continue
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    r = json.loads(ln)
                    thr[r["agent1_threshold"]] += 1
                    if r["agent1_triggered"]:
                        conf[r["agent1_confidence"]] += 1
    print("limiar na auditoria:", dict(thr))
    print("confianca dos disparos:", dict(sorted(conf.items())))
    think, out, delta, errs = [], [], Counter(), Counter()
    with open(f"{ROOT}/raw/gemini_call_log_picam.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["agent"] != "gate" or not (lo <= r["call_date_brt"] <= hi):
                continue
            if r["success"] != "t":
                errs[(r["error_message"] or "")[:60]] += 1
                continue
            i, o, t = int(r["input_tokens"]), int(r["output_tokens"]), int(r["total_tokens"])
            think.append(t - i - o)
            out.append(o)
            delta[i - 2429] += 1
    n = len(think)
    q = st.quantiles(think, n=20)
    print(f"gate ok {n}, falhas {sum(errs.values())}: {errs.most_common(4)}")
    print(f"pensamento: media {st.mean(think):.0f} p50 {st.median(think):.0f} p5 {q[0]:.0f} "
          f"p95 {q[-1]:.0f} max {max(think)} | saida: media {st.mean(out):.0f} max {max(out)}")
    print("input_tokens - 2429 (0 = sem contexto da janela anterior):")
    for k, v in sorted(delta.items()):
        if v >= 20:
            print(f"  {k:+4d}  {v:6d}  {100 * v / n:5.2f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tokens-prod").set_defaults(fn=tokens_prod)
    sub.add_parser("tokens-bench").set_defaults(fn=tokens_bench)
    sub.add_parser("first-frame").set_defaults(fn=first_frame)
    sub.add_parser("params-prod").set_defaults(fn=params_prod)
    a = ap.parse_args()
    a.fn(a)
