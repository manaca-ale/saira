#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Campaign 40 — build the Mangabeira eval set, split B3 (focus) vs B1/B2.

B1/B2 (remoção/limpeza, EXCLUIR do foco): justificativa casa retirando|limpando|
limpeza|poda|coleta. B3 (foco) = resto dos FP (passando/estacionado/veículo/animal).
Asserts n_B3==20 and n_B1B2==28. Outputs results/b3_split.csv.
"""
import csv
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
DATASET = ROOT / "data" / "datasets" / "official"
OUT = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "results"
OUT.mkdir(parents=True, exist_ok=True)

B1B2_KW = ["retirando", "limpando", "limpeza", "poda", "coleta"]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def bucket(category: str, justificativa: str) -> str:
    if category == "tp":
        return "TP"
    if category == "missed":
        return "MISSED"
    if category == "indefinido":
        return "INDEF"
    # fp:
    j = norm(justificativa)
    if any(k in j for k in B1B2_KW):
        return "B1B2"
    return "B3"


def main() -> int:
    rows = [
        r for r in csv.DictReader((DATASET / "manifest.csv").open(encoding="utf-8"))
        if r.get("camera") == "cam_mangabeira"
    ]
    out = []
    for r in rows:
        b = bucket(r["category"], r.get("justificativa", ""))
        frames_dir = DATASET / r["local_path"] / "frames"
        n_frames = len(list(frames_dir.glob("*.jpg"))) if frames_dir.exists() else 0
        out.append({
            "event_id": r["event_id"],
            "bucket": b,
            "category": r["category"],
            "datetime": r.get("datetime", ""),
            "volumetria": r.get("volumetria", ""),
            "justificativa": r.get("justificativa", ""),
            "local_path": r["local_path"],
            "n_frames": n_frames,
        })

    counts = {}
    for o in out:
        counts[o["bucket"]] = counts.get(o["bucket"], 0) + 1
    print("Buckets:", counts)

    n_b3 = counts.get("B3", 0)
    n_b1b2 = counts.get("B1B2", 0)
    assert n_b3 == 20, f"esperado 20 B3, veio {n_b3}"
    assert n_b1b2 == 28, f"esperado 28 B1/B2, veio {n_b1b2}"
    assert counts.get("TP") == 13, f"esperado 13 TP, veio {counts.get('TP')}"

    with (OUT / "b3_split.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"OK -> {OUT / 'b3_split.csv'} ({len(out)} eventos)")
    print("B3 ids:", sorted(o["event_id"][:8] for o in out if o["bucket"] == "B3"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
