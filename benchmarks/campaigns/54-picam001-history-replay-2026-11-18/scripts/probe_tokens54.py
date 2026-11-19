# -*- coding: utf-8 -*-
"""Sonda sem custo: tokens de entrada do gate em produção (gemini_call_log) contra os do controle do replay
(gate de hoje, V1, thinking 2048) nos mesmos eventos. Só leitura de arquivos locais."""
import collections
import csv
import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"C:\Saira\data\historico-picam")
RES = Path(r"C:\Saira-migracao\benchmarks\campaigns\54-picam001-history-replay-2026-11-18\results")

base = {}
with open(ROOT / "base" / "base_eventos.csv", encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        base[r["event_id"]] = r
log = {}
with open(ROOT / "raw" / "gemini_call_log_picam.csv", encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        if r["agent"] == "gate":
            log[r["request_id"]] = r

for name in sys.argv[1:] or ["gate54__g25l_v1_t2048__r1.jsonl"]:
    rows = [json.loads(l) for l in (RES / name).read_text(encoding="utf-8").splitlines() if l.strip()]
    print(name, "| linhas", len(rows), "| campos", sorted(rows[0].keys()))
    difs = []
    por_estrato = collections.defaultdict(list)
    sem = 0
    for r in rows:
        b = base.get(r.get("event_id"))
        pl = log.get(b["agent1_request_id"]) if b else None
        tin = r.get("tok_in")
        if not pl or tin in (None, "", 0, "0") or r.get("error"):
            sem += 1
            continue
        d = int(tin) - int(pl["input_tokens"])
        difs.append(d)
        por_estrato[r.get("estrato")].append(d)
    print("  pareados", len(difs), "| sem par", sem)
    if difs:
        c = collections.Counter(difs)
        print("  diferença (replay - produção) em tokens de entrada: mediana", statistics.median(difs),
              "| min", min(difs), "| max", max(difs), "| iguais", c.get(0, 0))
        print("  mais comuns:", c.most_common(8))
        for e, v in sorted(por_estrato.items()):
            print("   ", e, "n", len(v), "mediana", statistics.median(v), "iguais", sum(1 for x in v if x == 0),
                  "|dif|>50:", sum(1 for x in v if abs(x) > 50))
