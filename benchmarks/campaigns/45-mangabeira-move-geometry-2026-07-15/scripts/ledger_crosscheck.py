#!/usr/bin/env python3
"""Camp 45 — cross-check do ledger BGSUB shadow de PROD vs status do operador.

Evidência ao vivo (não replay): o worker grava TODA avaliação do BGSUB em
`/app/state/bgsub_models/shadow_decisions.jsonl` mesmo em shadow. Cada registro
traz `gate_request_id` + `persistence`, que ligam ao audit (`agent1_request_id`)
e daí ao `detection_id` → status do operador.

Responde, com dados de produção e o POLÍGONO ATUAL (stale): qual threshold de
persistence teria matado quais rejeitados sem perder confirmados?
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
DATA = ROOT / "tmp" / "mangabeira_move"
HERE = Path(__file__).resolve().parent.parent
RESULTS = HERE / "results"

THR_GRID = [50, 100, 200, 300, 500, 700, 1000, 1500, 2000, 3000, 5000]


def main() -> int:
    # 1. labels: detection_id -> status
    status = {}
    with (DATA / "labels.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            status[r["id"]] = r["status"]

    # 2. audit: agent1_request_id -> (detection_id, triggered)
    req2det = {}
    for aud in sorted(DATA.glob("audit/*.jsonl")):
        for line in aud.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rid = r.get("agent1_request_id")
            if rid:
                req2det[rid] = (r.get("detection_id") or "", bool(r.get("agent1_triggered")))

    # 3. ledger de prod (pós-mudança)
    rows = []
    with (DATA / "state" / "shadow_decisions.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("device_id") != "esp32_002" or r.get("ts", "") < "2026-07-09":
                continue
            det, trig = req2det.get(r.get("gate_request_id", ""), ("", False))
            lab = status.get(det, "")
            rows.append({"persistence": float(r.get("persistence") or 0),
                         "reason": r.get("reason"), "det": det[:8],
                         "trig": trig, "label": lab or ("TRIG" if trig else "NEG"),
                         "ts": r.get("ts")})

    matched = sum(1 for r in rows if r["det"])
    print(f"ledger pós-mudança: {len(rows)} decisões | com detection_id: {matched} | "
          f"labels: {dict(Counter(r['label'] for r in rows))}\n")

    groups = defaultdict(list)
    for r in rows:
        groups[r["label"]].append(r["persistence"])

    print("=== persistence por grupo (polígono ATUAL, dados de prod) ===")
    for g in ("CONFIRMADO", "REJEITADO", "PENDENTE", "INDETERMINADO", "TRIG", "NEG"):
        v = sorted(groups.get(g, []))
        if not v:
            continue
        p = lambda q: v[min(len(v) - 1, int(len(v) * q))]  # noqa: E731
        print(f"  {g:14} n={len(v):5}  min={v[0]:8.0f}  p10={p(0.1):8.0f}  "
              f"p50={p(0.5):8.0f}  p90={p(0.9):8.0f}  max={v[-1]:9.0f}")

    print("\n=== sweep de threshold (suprime se persistence < thr) ===")
    conf = groups.get("CONFIRMADO", [])
    rej = groups.get("REJEITADO", [])
    print(f"{'thr':>6} {'CONF mortos':>12} {'REJ mortos':>16} {'NEG suprimidos':>16}")
    neg = groups.get("NEG", [])
    for thr in THR_GRID:
        cs = sum(1 for v in conf if v < thr)
        rs = sum(1 for v in rej if v < thr)
        ns = sum(1 for v in neg if v < thr)
        flag = "  <-- viola criterio" if cs else ""
        print(f"{thr:>6} {cs:>5}/{len(conf):<6} {rs:>7}/{len(rej):<7} ({rs/max(1,len(rej)):>4.0%}) "
              f"{ns:>6}/{len(neg):<6} ({ns/max(1,len(neg)):>4.0%}){flag}")

    if conf:
        print(f"\nmenor persistence entre CONFIRMADOS: {min(conf):.0f} "
              f"→ teto seguro do threshold (polígono atual)")
    (RESULTS / "ledger_crosscheck.json").write_text(
        json.dumps({"n": len(rows), "by_label": {k: sorted(v) for k, v in groups.items()}},
                   indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
