#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — sonda do Flex na API do AI Studio: a mesma chamada do gate, uma vez no nivel padrao e uma
vez com service_tier=flex, mostrando o que a resposta diz sobre o nivel usado (usage_metadata e
cabecalhos HTTP). Paga pela carteira `aistudio` (trava bench_budget); custa fracao de centavo.

Uso: python probe_flex54.py --max-usd 0.01 [--model gemini-2.5-flash-lite] [--n 1]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
C53 = HERE.parents[1] / "53-picam001-migration-post-25flash-2026-11-16" / "scripts"
sys.path.insert(0, str(C53))
sys.path.insert(0, str(HERE))
import bench53 as b          # noqa: E402
import run_gate54 as g       # noqa: E402
from bench_budget import Budget  # noqa: E402

SCHEMA = {"type": "object", "properties": {"people": {"type": "integer"}}, "required": ["people"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-flash-lite")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--max-usd", type=float, required=True)
    a = ap.parse_args()

    ev = g.build_set("tri", 0.30)[: a.n]
    b.use_backend("aistudio")
    budget = Budget(wallet="aistudio")
    budget.run_cap = a.max_usd
    budget.require(0.001 * 2 * a.n, "probe_flex54")
    b._BUDGET = budget
    b._RUN_CTX.update({"campaign": "54", "stage": "probe_flex", "arm": a.model, "rep": 1,
                       "dataset": "picam-historico", "backend": "aistudio"})
    out = []
    for flex in (False, True):
        b._FLEX["on"] = flex
        for e in ev:
            frames = [g.frame_path(n) for n in e["gate5"].split("|")]
            t0 = time.time()
            tries = {"n": 0}

            def call():
                tries["n"] += 1
                return b.dg._call_model(frames, "Count the people visible in these frames.",
                                        "Answer in JSON.", a.model, SCHEMA, 64,
                                        thinking_budget=0 if a.model.startswith("gemini-2.5") else None,
                                        thinking_level=None if a.model.startswith("gemini-2.5") else "minimal",
                                        media_resolution=None if a.model.startswith("gemini-2.5") else "low")
            try:
                resp = b.call_backoff(call, tries=6)
            except Exception as exc:  # noqa: BLE001
                out.append({"flex_requested": flex, "error": str(exc)[:200], "tries": tries["n"]})
                continue
            md = resp.usage_metadata
            hdr = dict(getattr(getattr(resp, "sdk_http_response", None), "headers", None) or {})
            keep = {k: v for k, v in hdr.items()
                    if any(t in k.lower() for t in ("tier", "flex", "traffic", "served", "x-goog", "x-gemini"))}
            out.append({"flex_requested": flex, "tries": tries["n"],
                        "latency_s": round(time.time() - t0, 1),
                        "usage_metadata": json.loads(md.model_dump_json(exclude_none=True)),
                        "response_keys": sorted(k for k, v in resp.model_dump(exclude_none=True).items()
                                                if k not in ("candidates", "sdk_http_response")),
                        "model_version": getattr(resp, "model_version", None),
                        "headers": keep})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print("chamadas:", b._CALLS, "gasto US$", round(budget.run_spent, 6))


if __name__ == "__main__":
    main()
