#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Precos oficiais do Vertex AI no catalogo do Google Cloud (Cloud Billing Catalog API).

Confere a tabela `bench_budget.PRICES`, que veio da pagina publica de precos da API do
AI Studio. So leitura, sem custo. Usa o token do gcloud SEM cabecalho de projeto de cota.

Uso: python vertex_sku_prices.py ["Gemini 3.8 Flash" "Gemini 3.5 Flash Lite" ...]
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SERVICE = "C7E2-9256-1C43"      # Vertex AI
WANT = sys.argv[1:] or ["Gemini 2.5 Flash", "Gemini 3.5 Flash Lite", "Gemini 3.8 Flash",
                        "Gemini 3.1 Flash Lite"]


def token() -> str:
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    out = subprocess.run([exe, "config", "config-helper", "--min-expiry=10m", "--format=json"],
                         capture_output=True, text=True, timeout=120)
    return json.loads(out.stdout)["credential"]["access_token"]


def main():
    tok = token()
    skus, page = [], None
    while True:
        q = {"pageSize": "5000", "currencyCode": "USD"}
        if page:
            q["pageToken"] = page
        req = urllib.request.Request(
            f"https://cloudbilling.googleapis.com/v1/services/{SERVICE}/skus?" + urllib.parse.urlencode(q),
            headers={"Authorization": "Bearer " + tok})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.load(r)
        skus += d.get("skus", [])
        page = d.get("nextPageToken")
        if not page:
            break
    print("SKUs do Vertex AI no catalogo:", len(skus))
    pat = re.compile("|".join(re.escape(w) for w in WANT), re.I)
    rows = []
    for s in skus:
        desc = s.get("description", "")
        if not pat.search(desc) or "global" not in desc.lower():
            continue
        if re.search(r"image|audio|video|live|tts|cach|tuning|grounding|priority|computer", desc, re.I):
            continue
        for pi in s.get("pricingInfo", [])[:1]:
            pe = pi.get("pricingExpression", {})
            rates = pe.get("tieredRates", [])
            if not rates:
                continue
            up = rates[-1].get("unitPrice", {})
            usd = float(up.get("units", 0) or 0) + float(up.get("nanos", 0) or 0) / 1e9
            unit = pe.get("usageUnitDescription", pe.get("usageUnit", ""))
            base = float(pe.get("baseUnitConversionFactor", 1) or 1)
            disp = float(pe.get("displayQuantity", 1) or 1)
            rows.append((desc, usd, unit, disp, base))
    for desc, usd, unit, disp, base in sorted(rows):
        # normaliza para US$ por 1M tokens quando a unidade for contagem
        per_m = usd / disp * 1e6 if disp else None
        print(f"{desc} | {usd:.6f} USD por {disp:g} {unit} | por 1M: {per_m:.4f}" if per_m is not None
              else f"{desc} | {usd} por {unit}")


if __name__ == "__main__":
    main()
