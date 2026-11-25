#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — sonda de conectividade da API de Decisoes (gemini-decision-1).

So existe na API do AI Studio (v1beta), nao no Vertex. Esta sonda manda UMA pergunta de
texto (sem imagem) para saber se a chave de testes consegue chamar o modelo. Custo quando
funciona: dezenas de tokens a US$ 0,10 por 1M (fracao de centavo de centavo).

A chave vem da variavel de ambiente GEMINI_TEST_API_KEY e NUNCA e impressa.

Uso (bash):
  KEY=$(gcloud services api-keys get-key-string <uid> --project=saira-tests-260520 \
        --format='value(keyString)')
  GEMINI_TEST_API_KEY="$KEY" python probe_decisions.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

KEY = os.environ.get("GEMINI_TEST_API_KEY", "").strip()
if not KEY:
    sys.exit("defina GEMINI_TEST_API_KEY (chave AI Studio da conta Saira - Testes)")


def clean(text: str) -> str:
    return (text or "").replace(KEY, "<chave>")[:600]


body = {
    "model": "gemini-decision-1",
    "input": "Teste de conectividade. Este texto esta escrito em portugues.",
    "questions": {
        "pt": {"type": "noul", "instructions": "Is the text written in Portuguese?"},
    },
}
req = urllib.request.Request(
    "https://generativelanguage.googleapis.com/v1beta/decisions",
    data=json.dumps(body).encode("utf-8"),
    headers={"x-goog-api-key": KEY, "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print("HTTP", resp.status)
        print(clean(json.dumps(data, ensure_ascii=False)))
except urllib.error.HTTPError as exc:
    print("HTTP", exc.code)
    print(clean(exc.read().decode("utf-8", "replace")))
except Exception as exc:  # noqa: BLE001
    print("erro", type(exc).__name__, clean(str(exc)))
