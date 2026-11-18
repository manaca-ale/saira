#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — roda o Decisions (gemini-decision-1) na amostra do historico da pi-cam-001, com os MESMOS 5
frames que o gate de producao viu (sample.csv, coluna gate5).

Paga pela carteira `aistudio` (trava bench_budget). Sempre --dry-run antes. Retoma de onde parou.
A chave e lida do arquivo fora do repo e nunca e impressa (bench_decisions.get_key).

Regra da campanha: perguntas, limiares e estruturas so se ajustam no conjunto de DESENVOLVIMENTO
(--split dev). O conjunto de avaliacao (--split aval) roda uma vez, no fim.

Uso:
  python run_dgate54.py --qset q1 --split dev --dry-run
  python run_dgate54.py --qset q1 --split dev --max-usd 0.60
Saida: ../results/dgate54__<qset>_gate5_<res>__r<rep>.jsonl (um registro por evento, com `split` e `estrato`).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
C53 = HERE.parents[1] / "53-picam001-migration-post-25flash-2026-11-16" / "scripts"
sys.path.insert(0, str(C53))
sys.path.insert(0, str(HERE))
import bench53 as b          # noqa: E402
import bench_decisions as d  # noqa: E402
from bench_budget import Budget, cost_usd  # noqa: E402

try:
    from qsets54 import QSETS as QSETS54     # perguntas novas da camp 54 (opcional)
except ImportError:
    QSETS54 = {}

ROOT = Path(r"C:\Saira\data\historico-picam")
FRAMES = ROOT / "frames" / "gate5"
RESULTS = HERE.parent / "results"
QSETS = {**d.QSETS, **QSETS54}


def load_sample(split: str, strata):
    rows = []
    with (ROOT / "amostra" / "sample.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if split != "all" and r["split"] != split:
                continue
            if strata and r["estrato"] not in strata:
                continue
            rows.append(r)
    return rows


def out_path(qset, res, rep) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    return RESULTS / f"dgate54__{qset}_gate5_{res}__r{rep}.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qset", default="q1", choices=sorted(QSETS))
    ap.add_argument("--res", default="low", choices=["low", "medium", "high"])
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--split", default="dev", choices=["dev", "aval", "all"])
    ap.add_argument("--strata", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    questions = QSETS[a.qset]
    events = load_sample(a.split, set(a.strata.split(",")) if a.strata else None)
    path = out_path(a.qset, a.res, a.rep)
    done = b.latest_ok(path) if path.exists() else {}
    todo = [e for e in events if e["event_id"] not in done]
    if a.limit:
        todo = todo[: a.limit]
    missing = [e["event_id"] for e in todo if any(not (FRAMES / n).is_file() for n in e["gate5"].split("|"))]
    per_frame = {"low": 300, "medium": 600, "high": 1150}[a.res]
    est = sum(len(e["gate5"].split("|")) * per_frame + 900 + 150 * len(questions) for e in todo) / 1e6 * 0.10
    print(f"[dgate54] qset={a.qset} ({len(questions)} perguntas) res={a.res} rep={a.rep} split={a.split} "
          f"eventos={len(events)} ja_feitos={len(events) - len(todo)} a_rodar={len(todo)} "
          f"sem_frames={len(missing)} estimativa=US$ {est:.4f}")
    if missing:
        print("  eventos sem todos os frames (ficam de fora):", missing[:5], "..." if len(missing) > 5 else "")
        todo = [e for e in todo if e["event_id"] not in set(missing)]
    if a.dry_run or not todo:
        return
    if a.max_usd <= 0:
        raise SystemExit("informe --max-usd")
    budget = Budget(wallet="aistudio")
    budget.run_cap = a.max_usd
    budget.require(est, f"dgate54/{a.qset}")
    ctx = {"campaign": "54", "stage": "dgate", "arm": f"{a.qset}_gate5_{a.res}", "rep": a.rep,
           "dataset": "picam-historico"}

    def one(ev):
        frames = [FRAMES / n for n in ev["gate5"].split("|")]
        rec = {"stage": "dgate54", "qset": a.qset, "rep": a.rep, "event_id": ev["event_id"],
               "estrato": ev["estrato"], "split": ev["split"], "status": ev["status"],
               "detection_id": ev["detection_id"], "model": d.MODEL, "n_sent": len(frames), "res": a.res,
               "ts": dt.datetime.now().isoformat(timespec="seconds"), "error": ""}
        if budget.stop:
            rec["error"] = "budget_stop"
            return rec
        try:
            t0 = time.time()
            data = d.call_decisions(frames, questions, a.res)
            tin = d.input_tokens(data.get("usage"))
            budget.charge(model=d.MODEL, tok_in=tin, tok_out=0, ctx=dict(ctx, n_images=len(frames)))
            rec.update({"answers": data.get("answers"), "usage": data.get("usage"), "tok_in": tin,
                        "cost_usd": round(cost_usd(d.MODEL, tin, 0), 8),
                        "latency_ms": int((time.time() - t0) * 1000)})
        except d.CreditDepleted as exc:
            budget.stop = True
            rec["error"] = f"402 credito esgotado: {str(exc)[:160]}"
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        return rec

    n_ok = n_err = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for i, fut in enumerate(as_completed([pool.submit(one, ev) for ev in todo]), 1):
            r = fut.result()
            b.append_jsonl(path, r)
            if r["error"]:
                n_err += 1
                print(f"  [{i}/{len(todo)}] {r['estrato']} {r['event_id']} ERR {r['error'][:100]}", flush=True)
            else:
                n_ok += 1
                if i % 100 == 0 or i == len(todo):
                    print(f"  [{i}/{len(todo)}] ok={n_ok} erros={n_err} gasto=US$ {budget.run_spent:.4f} "
                          f"({int(time.time() - t0)} s)", flush=True)
    print(f"  fim: ok={n_ok} erros={n_err} gasto_desta_execucao=US$ {budget.run_spent:.4f} "
          f"total_carteira=US$ {budget.spent:.4f} ({int(time.time() - t0)} s)")


if __name__ == "__main__":
    main()
