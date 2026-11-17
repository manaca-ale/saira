#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — gemini-decision-1 (API de Decisoes) como GATE da cascata.

O gate e ~80% do custo por evento na pi-cam-001 e hoje custa ~US$ 0,0011 por chamada
(2.429 tokens de entrada + ~2.000 de thinking no 2.5-flash-lite). A API de Decisoes devolve
probabilidade calibrada de sim/nao sobre texto + imagens com ZERO tokens de saida, a
US$ 0,10 por 1M de entrada. Varias perguntas na mesma requisicao dividem a mesma entrada.

Estagios:
  run     uma requisicao por evento, guarda TODAS as respostas  -> results/dgate__<tag>__r<rep>.jsonl
  sweep   offline: AUC por pergunta e tabela de limiar (recall do gate x passagem de FP/vazias)
  export  offline: grava um arquivo de gate no formato do bench53 (fire = p >= limiar), para
          `bench53.py score/matrix` combinar com qualquer braco de detail

So existe na API do AI Studio (v1beta), nao no Vertex. Precisa de credito pre-pago no projeto
`saira-tests-260520` (HTTP 402 quando esgotado). Nivel pago: o conteudo nao e usado para
melhorar produtos do Google. A chave e lida do gcloud e NUNCA e impressa.

Uso:
  python bench_decisions.py run --qset q1 --frames gate5 --res low --rep 1 --dry-run
  python bench_decisions.py run --qset q1 --frames gate5 --res low --rep 1 --max-usd 0.10
  python bench_decisions.py sweep --tag q1_gate5_low --rep 1
  python bench_decisions.py export --tag q1_gate5_low --rep 1 --question deposit --threshold 0.30
  (dataset do testspace: --dataset pi-inicial-v1 antes do subcomando)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import bench53 as b
from bench_budget import Budget, BudgetExceeded, cost_usd

MODEL = "gemini-decision-1"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/decisions"
KEY_UID = os.environ.get("BENCH_AISTUDIO_KEY_UID", "8deccfda-038c-4281-bcbb-97245f6b4082")
KEY_PROJECT = "saira-tests-260520"

CONTEXT = (
    "You are looking at a chronological sequence of frames from ONE fixed CCTV camera aimed at "
    "a known illegal-dumping hotspot on a residential street in Recife, Brazil. A waste pile is "
    "usually already present at the curb: its presence is the normal background and is never by "
    "itself evidence of a new dumping act. Frames are labelled 'Frame k of N' in time order.\n"
)

# Perguntas independentes sobre a MESMA entrada. O modelo nao ve as chaves, so `instructions`.
QSETS = {
    "q1": {
        "deposit": {
            "type": "noul",
            "instructions": (
                "Within this sequence, does a person or a vehicle occupant ADD waste or material "
                "to the pile or leave it on the ground? This includes a person on foot carrying a "
                "bag or object and placing, dropping or throwing it, and unloading from a car, "
                "truck, cart or wheelbarrow. Answer yes when the deposit act is visible, or when "
                "a new bag/object/material rests on the ground or pile in a later frame, was "
                "absent in the first frame, and an actor was at that spot in between. Answer no "
                "for people or vehicles that only pass through, vehicles parked with nobody "
                "handling material, people who only REMOVE or sort items from the pile, and "
                "changes that are only lighting or shadows."),
        },
        "actor_at_pile": {
            "type": "noul",
            "instructions": (
                "Does any person or vehicle STOP at or right next to the waste pile or deposit "
                "area and interact with it or handle material there, as opposed to only passing "
                "through or staying away from it?"),
        },
        "removal": {
            "type": "noul",
            "instructions": (
                "Is someone taking material AWAY from the pile: a waste picker rummaging, "
                "sorting, bagging or loading a handcart, or a municipal crew or truck collecting "
                "the waste, so that the actor leaves with more than they arrived with?"),
        },
        "pile_grew": {
            "type": "noul",
            "instructions": (
                "Comparing the first frame with the last frame, is there visibly MORE waste, or "
                "a NEW bag or object, on the ground or on the pile in the last frame?"),
        },
        "carrying_in": {
            "type": "noul",
            "instructions": (
                "Does any person arrive holding or carrying a bag, box, sack or other object and "
                "later appear without it, or appear putting it down?"),
        },
        "scene": {
            "type": "choice",
            "instructions": "Which label best describes what happens in this sequence?",
            "criteria": {
                "EMPTY": "No person or vehicle appears.",
                "TRAFFIC": "People or vehicles move through without interacting with the pile.",
                "PARKED": "A vehicle is stationary and nobody handles material at the pile.",
                "COLLECTION": "Someone removes, sorts or collects material from the pile.",
                "DUMPING": "Someone adds waste or material to the pile or leaves it on the ground.",
            },
        },
    },
}

FRAME_MODES = ("gate5", "even8", "even12", "even16", "all")


def pick_frames(win, mode):
    if mode == "gate5":            # exatamente o que o gate de producao ve
        return [win[0]] + (b.gate_mids(win) or []) + [win[-1]]
    if mode == "all":
        return win
    return b.even_subsample(win, int(mode.replace("even", "")))


_key = None


def get_key() -> str:
    global _key
    if _key is None:
        env = os.environ.get("GEMINI_TEST_API_KEY", "").strip()
        key_file = Path(os.environ.get("BENCH_AISTUDIO_KEY_FILE",
                                       str(Path.home() / ".saira-bench" / "aistudio_key.txt")))
        if env:
            _key = env
        elif key_file.exists():
            # chave do AI Studio entregue pelo Alexandre em 16/11/2026 (projeto no nivel pago,
            # fora do saira-tests-260520). Fica fora do repo; nunca imprimir nem commitar.
            _key = key_file.read_text(encoding="utf-8").strip()
        else:
            out = subprocess.run(
                [b._gcloud_exe(), "services", "api-keys", "get-key-string", KEY_UID,
                 f"--project={KEY_PROJECT}", "--format=value(keyString)"],
                capture_output=True, text=True, timeout=90)
            _key = (out.stdout or "").strip()
            if not _key:
                raise RuntimeError("nao consegui ler a chave de testes pelo gcloud "
                                   "(sessao expirada? ver handoff, pendencias)")
    return _key


def clean(text: str) -> str:
    return (text or "").replace(_key or "\x00", "<chave>")


class CreditDepleted(RuntimeError):
    pass


def call_decisions(frames, questions, res):
    blocks = [{"type": "text", "text": CONTEXT}]
    n = len(frames)
    for i, p in enumerate(frames, 1):
        blocks.append({"type": "text", "text": f"\nFrame {i} of {n}:\n"})
        blocks.append({"type": "image", "mime_type": "image/jpeg", "resolution": res,
                       "data": base64.b64encode(p.read_bytes()).decode("ascii")})
    body = json.dumps({"model": MODEL, "input": blocks, "questions": questions}).encode("utf-8")
    last = None
    for att in range(1, 5):
        req = urllib.request.Request(
            ENDPOINT, data=body, method="POST",
            headers={"x-goog-api-key": get_key(), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            text = clean(exc.read().decode("utf-8", "replace"))[:400]
            if exc.code == 402:
                raise CreditDepleted(text)
            last = RuntimeError(f"HTTP {exc.code}: {text}")
            if exc.code not in (429, 500, 503) or att == 4:
                raise last
        except Exception as exc:  # noqa: BLE001
            last = RuntimeError(f"{type(exc).__name__}: {clean(str(exc))[:300]}")
            if att == 4:
                raise last
        time.sleep(min(60, 5 * 2 ** (att - 1)) * (0.7 + 0.6 * random.random()))
    raise last


def input_tokens(usage) -> int:
    """`usage` informa tokens de entrada por modalidade; o formato exato nao esta na doc que
    li, entao somo o que parecer contagem de entrada e guardo o bruto no registro."""
    if not isinstance(usage, dict):
        return 0
    for k in ("total_input_tokens", "input_tokens", "prompt_token_count", "total_tokens",
              "totalInputTokens", "inputTokens", "promptTokenCount", "totalTokens"):
        v = usage.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    tot = 0
    for v in usage.values():
        if isinstance(v, (int, float)):
            tot += int(v)
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    tot += int(it.get("tokens") or it.get("token_count") or it.get("tokenCount") or 0)
        elif isinstance(v, dict):
            tot += sum(int(x) for x in v.values() if isinstance(x, (int, float)))
    return tot


def tag_of(a) -> str:
    return f"{a.qset}_{a.frames}_{a.res}"


def dgate_path(tag, rep):
    return b.out_dir() / f"dgate__{tag}__r{rep}.jsonl"


def run(a) -> None:
    questions = QSETS[a.qset]
    cats = a.cats.split(",") if a.cats else None
    events = b.load_events(cats, a.limit)
    path = dgate_path(tag_of(a), a.rep)
    done = b.latest_ok(path)
    todo = [e for e in events if e["event_id"] not in done]
    # estimativa conservadora: 1.120 tokens por frame (teto da familia Gemini 3) + texto
    per_frame = {"low": 300, "medium": 600, "high": 1150, "ultra_high": 2300}[a.res]
    n_frames = [len(pick_frames(b.build_window(e["frames"]), a.frames)) for e in todo]
    est = sum((n * per_frame + 900) for n in n_frames) / 1e6 * 0.10
    print(f"[dgate] tag={tag_of(a)} rep={a.rep} dataset={b.DS['name']} eventos={len(events)} "
          f"a_rodar={len(todo)} frames_mediana={sorted(n_frames)[len(n_frames) // 2] if n_frames else 0} "
          f"estimativa=US$ {est:.4f}")
    if a.dry_run or not todo:
        return
    budget = Budget()
    budget.run_cap = a.max_usd
    budget.require(est, f"dgate/{tag_of(a)}")
    ctx = {"campaign": "53", "stage": "dgate", "arm": tag_of(a), "rep": a.rep,
           "dataset": b.DS["name"]}

    def one(ev):
        win = b.build_window(ev["frames"])
        frames = pick_frames(win, a.frames)
        rec = {"stage": "dgate", "tag": tag_of(a), "rep": a.rep, "event_id": ev["event_id"],
               "det_id": ev["det_id"], "category": ev["category"], "model": MODEL,
               "n_window": len(win), "n_sent": len(frames), "res": a.res,
               "ts": dt.datetime.now().isoformat(timespec="seconds"), "error": ""}
        if budget.stop:
            rec["error"] = "budget_stop"
            return rec
        try:
            t0 = time.time()
            data = call_decisions(frames, questions, a.res)
            tin = input_tokens(data.get("usage"))
            budget.charge(model=MODEL, tok_in=tin, tok_out=0, ctx=dict(ctx, n_images=len(frames)))
            rec.update({"answers": data.get("answers"), "usage": data.get("usage"),
                        "tok_in": tin, "cost_usd": round(cost_usd(MODEL, tin, 0), 8),
                        "latency_ms": int((time.time() - t0) * 1000)})
        except CreditDepleted as exc:
            budget.stop = True
            rec["error"] = f"402 credito esgotado: {str(exc)[:160]}"
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        return rec

    n_ok = n_err = 0
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for i, fut in enumerate(as_completed([pool.submit(one, ev) for ev in todo]), 1):
            r = fut.result()
            b.append_jsonl(path, r)
            if r["error"]:
                n_err += 1
                print(f"  [{i}/{len(todo)}] {r['category']:10s} {r['event_id']} ERR {r['error'][:90]}",
                      flush=True)
            else:
                n_ok += 1
                ans = r.get("answers") or {}
                dep = (ans.get("deposit") or {}).get("noul")
                print(f"  [{i}/{len(todo)}] {r['category']:10s} {r['event_id']} deposit={dep} "
                      f"tok_in={r['tok_in']}", flush=True)
    print(f"  fim: ok={n_ok} erros={n_err} gasto_desta_execucao=US$ {budget.run_spent:.4f} "
          f"total_semana=US$ {budget.spent:.4f}")


def prob(rec, question):
    ans = (rec.get("answers") or {}).get(question) or {}
    if "noul" in ans:
        return float(ans["noul"])
    probs = ans.get("probabilities")
    if isinstance(probs, dict) and "DUMPING" in probs:      # pergunta de escolha
        return float(probs["DUMPING"])
    return None


def auc(pos, neg):
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def by_det(rows, cat, score):
    out: dict[str, float] = {}
    for r in rows:
        if r["category"] == cat and score(r) is not None:
            out[r["det_id"]] = max(out.get(r["det_id"], 0.0), score(r))
    return out


def sweep(a) -> None:
    rows = list(b.latest_ok(dgate_path(a.tag, a.rep)).values())
    if not rows:
        raise SystemExit("sem resultados para esse tag/rep")
    questions = sorted({q for r in rows for q in (r.get("answers") or {})})
    costs = [r["cost_usd"] for r in rows]
    toks = sorted(r["tok_in"] for r in rows)
    print(f"tag={a.tag} rep={a.rep} n={len(rows)} tokens_entrada_mediana={toks[len(toks) // 2]} "
          f"custo_medio_por_chamada=US$ {sum(costs) / len(costs):.6f}")
    print("AUC por pergunta (evento; positivos = tp, negativos = fp + baseline):")
    for q in questions:
        pos = [prob(r, q) for r in rows if r["category"] == "tp" and prob(r, q) is not None]
        neg_fp = [prob(r, q) for r in rows if r["category"] == "fp" and prob(r, q) is not None]
        neg_bl = [prob(r, q) for r in rows if r["category"] == "baseline" and prob(r, q) is not None]
        print(f"  {q:14s} tp x fp={auc(pos, neg_fp)}  tp x vazias={auc(pos, neg_bl)}  "
              f"tp x (fp+vazias)={auc(pos, neg_fp + neg_bl)}")
    q = a.question
    sc = lambda r: prob(r, q)  # noqa: E731
    tp, fp = by_det(rows, "tp", sc), by_det(rows, "fp", sc)
    bl = [sc(r) for r in rows if r["category"] == "baseline" and sc(r) is not None]
    allp = [sc(r) for r in rows if sc(r) is not None]
    print(f"\nLimiar sobre '{q}' (deteccao passa se algum evento dela tiver p >= limiar):")
    print("limiar | tp_det passa | fp_det passa | vazias passam | passagem total")
    for t in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
        print(f"  {t:.2f} | {sum(v >= t for v in tp.values())}/{len(tp)} | "
              f"{sum(v >= t for v in fp.values())}/{len(fp)} | {sum(v >= t for v in bl)}/{len(bl)} | "
              f"{100 * sum(v >= t for v in allp) / len(allp):.0f}%")


def export(a) -> None:
    rows = b.latest_ok(dgate_path(a.tag, a.rep))
    arm = f"gdec_{a.tag}_{a.question}_t{int(round(a.threshold * 100)):02d}"
    path = b.out_path("gate", arm, a.rep)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows.values():
            p = prob(r, a.question)
            if p is None:
                continue
            fh.write(json.dumps({
                "stage": "gate", "arm": arm, "rep": a.rep, "event_id": r["event_id"],
                "det_id": r["det_id"], "category": r["category"], "model": MODEL,
                "n_window": r["n_window"], "n_sent": r["n_sent"], "fire": int(p >= a.threshold),
                "conf": int(round(100 * p)), "new_litter": bool(p >= a.threshold),
                "scene_type": "", "tok_in": r["tok_in"], "tok_out": 0, "tok_think": 0,
                "cost_usd": r["cost_usd"], "latency_ms": r.get("latency_ms"), "error": "",
            }, ensure_ascii=False) + "\n")
    print(f"gravado {path.name}: use `bench53.py score --gate {arm}:{a.rep} --detail <braco>:1`")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="official")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--qset", default="q1", choices=sorted(QSETS))
    p.add_argument("--frames", default="gate5", choices=FRAME_MODES)
    p.add_argument("--res", default="low", choices=["low", "medium", "high", "ultra_high"])
    p.add_argument("--rep", type=int, default=1)
    p.add_argument("--cats", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-usd", type=float, default=0.10)
    p.add_argument("--dry-run", action="store_true")
    for name in ("sweep", "export"):
        p = sub.add_parser(name)
        p.add_argument("--tag", required=True, help="ex.: q1_gate5_low")
        p.add_argument("--rep", type=int, default=1)
        p.add_argument("--question", default="deposit")
        if name == "export":
            p.add_argument("--threshold", type=float, required=True)
    a = ap.parse_args()
    b.DS["name"] = a.dataset
    try:
        {"run": run, "sweep": sweep, "export": export}[a.cmd](a)
    except BudgetExceeded as exc:
        print(f"ORCAMENTO: {exc}")
        sys.exit(3)


if __name__ == "__main__":
    main()
