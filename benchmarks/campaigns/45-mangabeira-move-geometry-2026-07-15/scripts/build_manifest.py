#!/usr/bin/env python3
"""Camp 45 — manifest: audit jsonl × labels do operador × frames reconstruídos.

Junta os records do cascade audit (janelas decididas, 07-09..07-15) com o status
do operador (labels.csv) e verifica a disponibilidade dos frames de cada janela
no corpus local (tmp/mangabeira_move/day{09..15}, índice GLOBAL por nome — janelas
podem cruzar meia-noite).

Saída: results/manifest.csv — uma linha por janela do audit:
  request_id, day, first, last, window_size, n_found, label, det_id8, brt,
  agent1_conf, agent1_litter, comment
label ∈ {CONF, REJ, INDETERMINADO, PENDENTE, TRIG_NOLABEL, NEG}
(NEG = janela sem trigger do gate; TRIG_NOLABEL = gate positivo sem detecção persistida)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
DATA = ROOT / "tmp" / "mangabeira_move"
HERE = Path(__file__).resolve().parent.parent
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

STATUS_MAP = {"CONFIRMADO": "CONF", "REJEITADO": "REJ"}


def load_labels() -> dict[str, dict]:
    labels = {}
    with (DATA / "labels.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            labels[row["id"]] = row
    return labels


def frame_index() -> dict[str, Path]:
    idx = {}
    for d in sorted(DATA.glob("day*")):
        if d.is_dir():
            for p in d.rglob("*.jpg"):
                idx[p.name] = p
    return idx


def main() -> int:
    labels = load_labels()
    fidx = frame_index()
    print(f"labels: {len(labels)} | frames indexados: {len(fidx)}", flush=True)

    names_sorted = sorted(fidx)
    rows = []
    for aud_file in sorted(DATA.glob("audit/esp32_002_2026-07-*.jsonl")):
        day = aud_file.stem[-2:]
        for line in aud_file.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            lo, hi = r["window_first_frame"], r["window_last_frame"]
            # janela = todos os frames com lo <= nome <= hi (nomes = timestamps 5s)
            import bisect
            i0 = bisect.bisect_left(names_sorted, lo)
            i1 = bisect.bisect_right(names_sorted, hi)
            n_found = i1 - i0

            det_id = r.get("detection_id") or ""
            lab_row = labels.get(det_id)
            if lab_row:
                label = STATUS_MAP.get(lab_row["status"], lab_row["status"])
            elif r.get("agent1_triggered"):
                label = "TRIG_NOLABEL"
            else:
                label = "NEG"

            rows.append({
                "request_id": r.get("agent1_request_id", ""),
                "day": day,
                "first": lo,
                "last": hi,
                "window_size": r.get("window_size", ""),
                "n_found": n_found,
                "label": label,
                "det_id8": det_id[:8],
                "brt": (lab_row or {}).get("brt", ""),
                "agent1_conf": r.get("agent1_confidence", ""),
                "agent1_litter": r.get("agent1_new_litter_detected", ""),
                "comment": (lab_row or {}).get("validity_comment", ""),
            })

    out = RESULTS / "manifest.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # resumo + sanidade
    from collections import Counter
    by_label = Counter(r["label"] for r in rows)
    print(f"janelas: {len(rows)} | {dict(by_label)}", flush=True)
    missing = [r for r in rows if r["label"] in ("CONF", "REJ")
               and (r["n_found"] < 5 or abs(r["n_found"] - int(r["window_size"] or 0)) > 2)]
    for r in missing:
        print(f"  ATENCAO frames incompletos: {r['label']} {r['det_id8']} "
              f"[{r['first']}..{r['last']}] size={r['window_size']} found={r['n_found']}", flush=True)
    conf_missing = sum(1 for r in missing if r["label"] == "CONF")
    print(f"incompletas: {len(missing)} (CONF: {conf_missing}) -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
