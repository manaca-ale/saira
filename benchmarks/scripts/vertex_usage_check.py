#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confere o ledger do bench_budget contra a medicao do proprio Google (Cloud Monitoring).

O ledger e uma ESTIMATIVA: tokens devolvidos em cada resposta x preco de lista. Este script
le, no Cloud Monitoring do projeto de testes, os tokens que o Vertex contou por modelo no
mesmo periodo e compara. Nao e a fatura (que so aparece em Faturamento > Relatorios, com
atraso), mas e a contagem que origina a fatura.

Uso: python vertex_usage_check.py [--project saira-tests-260520] [--since 2026-11-16T20:00:00-03:00]
So leitura; sem custo.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, __import__("os").path.dirname(__file__))
from bench_budget import Budget, PRICES, is_separate  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def token() -> str:
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    out = subprocess.run([exe, "config", "config-helper", "--min-expiry=10m", "--format=json"],
                         capture_output=True, text=True, timeout=120)
    return json.loads(out.stdout)["credential"]["access_token"]


def get(url: str, tok: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="saira-tests-260520")
    ap.add_argument("--since", default="2026-11-16T20:00:00-03:00")
    a = ap.parse_args()
    tok = token()
    base = f"https://monitoring.googleapis.com/v3/projects/{a.project}"
    start = dt.datetime.fromisoformat(a.since).astimezone(dt.timezone.utc)
    end = dt.datetime.now(dt.timezone.utc)
    span = int((end - start).total_seconds())

    # 1) quais metricas de modelos de editor existem no projeto
    flt = 'metric.type = starts_with("aiplatform.googleapis.com/publisher/online_serving")'
    d = get(base + "/metricDescriptors?" + urllib.parse.urlencode({"filter": flt}), tok)
    names = sorted(m["type"] for m in d.get("metricDescriptors", []))
    print("metricas disponiveis:")
    for n in names:
        print("  ", n.split("online_serving/")[-1])

    def series(metric: str):
        params = {
            "filter": f'metric.type = "{metric}"',
            "interval.startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "interval.endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "aggregation.alignmentPeriod": f"{span}s",
            "aggregation.perSeriesAligner": "ALIGN_SUM",
        }
        out, page = [], None
        while True:
            q = dict(params)
            if page:
                q["pageToken"] = page
            r = get(base + "/timeSeries?" + urllib.parse.urlencode(q), tok)
            out += r.get("timeSeries", [])
            page = r.get("nextPageToken")
            if not page:
                return out

    google = collections.defaultdict(lambda: collections.Counter())
    labels_seen = set()
    for metric in [n for n in names if n.endswith("/token_count")]:
        for ts in series(metric):
            lab = {**ts.get("resource", {}).get("labels", {}), **ts.get("metric", {}).get("labels", {})}
            labels_seen |= set(lab)
            model = lab.get("model_user_id") or lab.get("model_version_id") or lab.get("model") or "?"
            kind = lab.get("type") or lab.get("token_type") or "?"
            val = sum(int(p["value"].get("int64Value", 0) or p["value"].get("doubleValue", 0) or 0)
                      for p in ts.get("points", []))
            google[model][kind] += val
    calls = collections.Counter()
    for metric in [n for n in names if n.endswith("/model_invocation_count")]:
        for ts in series(metric):
            lab = {**ts.get("resource", {}).get("labels", {}), **ts.get("metric", {}).get("labels", {})}
            model = lab.get("model_user_id") or lab.get("model") or "?"
            calls[model] += sum(int(p["value"].get("int64Value", 0) or 0) for p in ts.get("points", []))
    print("rotulos nas series:", sorted(labels_seen))

    # 2) o que o ledger registrou no mesmo periodo (so Vertex)
    b = Budget()
    led = collections.defaultdict(lambda: collections.Counter())
    since_local = dt.datetime.fromisoformat(a.since).replace(tzinfo=None)
    with b.ledger_path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if is_separate(r):
                continue
            try:
                if dt.datetime.fromisoformat(r["ts"]) < since_local:
                    continue
            except Exception:  # noqa: BLE001
                continue
            m = r.get("model", "?")
            led[m]["input"] += int(r.get("tok_in") or 0)
            led[m]["output"] += int(r.get("tok_out") or 0) + int(r.get("tok_think") or 0)
            led[m]["calls"] += 1
            led[m]["usd"] += float(r.get("cost_usd") or 0)
            led[m]["list_usd"] += float(r.get("list_usd") or r.get("cost_usd") or 0)

    print(f"\nperiodo: {start:%d/%m %H:%M} a {end:%d/%m %H:%M} UTC | projeto {a.project}")
    print("modelo | chamadas ledger / Google | entrada ledger / Google | saida+thinking ledger / Google | US$ ledger")
    tot_l = tot_g_in = tot_l_in = 0.0
    for m in sorted(set(led) | set(google)):
        g, l = google.get(m, {}), led.get(m, {})
        g_in = g.get("input", 0)
        g_out = sum(v for k, v in g.items() if k != "input")
        print(f"{m} | {int(l.get('calls', 0))} / {calls.get(m, 0)} | {int(l.get('input', 0)):,} / {g_in:,} | "
              f"{int(l.get('output', 0)):,} / {g_out:,} | {l.get('usd', 0):.4f}")
        tot_l += l.get("usd", 0)
        tot_l_in += l.get("input", 0)
        tot_g_in += g_in
    print(f"total ledger (Vertex): US$ {tot_l:.4f} | entrada ledger {int(tot_l_in):,} x Google {int(tot_g_in):,} tokens")
    print("tipos de token por modelo no Google:", {m: dict(v) for m, v in google.items()})


if __name__ == "__main__":
    main()
