#!/usr/bin/env python3
"""Camp 22: comparativo dos 4 arms cam_11 (Flash V1 baseline, MANGABEIRA orig,
MANGABEIRA_C checklist, MANGABEIRA_E negative-first).

Roda dentro do worker. Usa audit log pra filtrar single-call cohort (= prod
parity, sem coalesced events).

Sai com:
- Tabela resumo dos 4 arms (full + single-call)
- Bucketização cruzada vs baseline V1 (FN_NEW, FP_FIXED, FP_NEW, etc)
- IDs dos casos mais problemáticos por arm
"""
from __future__ import annotations
import json
from pathlib import Path

import psycopg2

AUDIT_DIR = Path("/app/state/gemini_cascade_audit")


def n_audits(det_id):
    n = 0
    for date_dir in AUDIT_DIR.iterdir():
        for fp in date_dir.glob("*.jsonl"):
            try:
                with fp.open(encoding="utf-8") as fh:
                    for line in fh:
                        if det_id not in line:
                            continue
                        d = json.loads(line)
                        if d.get("detection_id") == det_id and d.get("agent2_ran"):
                            n += 1
            except Exception:
                pass
    return n


def load_cache(path):
    p = Path(path)
    if not p.exists():
        print(f"  MISSING: {path}")
        return {}
    raw = json.loads(p.read_text())
    if isinstance(raw, dict) and "results" in raw:
        return {r["id"]: r for r in raw["results"]}
    return raw


def score(items):
    n = len(items)
    tp = sum(1 for v in items if v["pred"] == "CON" and v["gt"] == "CON")
    tn = sum(1 for v in items if v["pred"] == "REJ" and v["gt"] == "REJ")
    fp = sum(1 for v in items if v["pred"] == "CON" and v["gt"] == "REJ")
    fn = sum(1 for v in items if v["pred"] == "REJ" and v["gt"] == "CON")
    return {"n": n, "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "acc": (tp + tn) / max(n, 1),
            "recall": tp / max(tp + fn, 1),
            "spec": tn / max(tn + fp, 1)}


def print_row(label, s):
    print(f"  {label:<35s} n={s['n']:<3} acc={s['acc']:.1%}  "
          f"TP={s['tp']} TN={s['tn']} FP={s['fp']} FN={s['fn']}  "
          f"recall={s['recall']:.1%}  spec={s['spec']:.1%}")


def main():
    conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                            password="postgres", dbname="saira_db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id::text FROM detections
        WHERE status IN ('REJEITADO', 'CONFIRMADO') AND camera_id = 11
    """)
    cam11_ids = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()

    audit_cnt = {i: n_audits(i) for i in cam11_ids}
    single_call = {i for i, n in audit_cnt.items() if n == 1}
    coalesced = {i for i, n in audit_cnt.items() if n > 1}
    no_audit = {i for i, n in audit_cnt.items() if n == 0}

    print(f"cam_11 cohort: total={len(cam11_ids)}  single={len(single_call)}  "
          f"coalesced={len(coalesced)}  no_audit={len(no_audit)}")

    runs = {
        "Flash V1 baseline":      load_cache("/tmp/flash_baseline_v1_cache.json"),
        "MANGABEIRA orig":         load_cache("/tmp/flash_per_camera_cache.json"),
        "MANGABEIRA_C checklist":  load_cache("/tmp/flash_mangabeira_C_cache.json"),
        "MANGABEIRA_E neg-first":  load_cache("/tmp/flash_mangabeira_E_cache.json"),
    }

    print()
    print("=" * 80)
    print("=== Full cam_11 cohort (all events with results) ===")
    print("=" * 80)
    for name, cache in runs.items():
        sub = [v for k, v in cache.items() if v.get("cam") == 11]
        if sub:
            print_row(name, score(sub))

    print()
    print("=" * 80)
    print("=== Single-call cam_11 cohort (prod parity) ===")
    print("=" * 80)
    for name, cache in runs.items():
        sub = [v for k, v in cache.items()
               if v.get("cam") == 11 and k in single_call]
        if sub:
            print_row(name, score(sub))

    # Cross-bucket vs baseline V1 (single-call cohort)
    v1 = runs["Flash V1 baseline"]
    print()
    print("=" * 80)
    print("=== Cross-bucket vs V1 baseline (single-call cohort) ===")
    print("=" * 80)
    for arm_name, cache in runs.items():
        if arm_name == "Flash V1 baseline":
            continue
        common = set(v1) & set(cache) & single_call
        buckets = {
            "TP_NEW (V1 FN -> arm CON)":      [],
            "FN_NEW (V1 CON -> arm REJ)":     [],
            "FP_FIXED (V1 FP -> arm REJ)":    [],
            "FP_NEW (V1 TN -> arm CON)":      [],
            "FN_BOTH (V1 REJ, arm REJ on CON)":[],
            "FP_PERSIST (V1 CON, arm CON on REJ)":[],
        }
        for kid in common:
            a, b = v1[kid], cache[kid]
            if a.get("cam") != 11 or b.get("cam") != 11:
                continue
            gt = a["gt"]
            pv, pa = a["pred"], b["pred"]
            if gt == "CON":
                if pv == "CON" and pa == "REJ":
                    buckets["FN_NEW (V1 CON -> arm REJ)"].append(kid)
                elif pv == "REJ" and pa == "CON":
                    buckets["TP_NEW (V1 FN -> arm CON)"].append(kid)
                elif pv == "REJ" and pa == "REJ":
                    buckets["FN_BOTH (V1 REJ, arm REJ on CON)"].append(kid)
            else:  # REJ
                if pv == "CON" and pa == "REJ":
                    buckets["FP_FIXED (V1 FP -> arm REJ)"].append(kid)
                elif pv == "REJ" and pa == "CON":
                    buckets["FP_NEW (V1 TN -> arm CON)"].append(kid)
                elif pv == "CON" and pa == "CON":
                    buckets["FP_PERSIST (V1 CON, arm CON on REJ)"].append(kid)
        print(f"\n>>> {arm_name}")
        for name, ids in buckets.items():
            arrow = "+" if "FIXED" in name or "TP_NEW" in name else (
                "-" if "FN_NEW" in name or "FP_NEW" in name else "·")
            print(f"  {arrow} [{len(ids):>2}] {name}")
            for kid in ids[:5]:
                ts = cache[kid].get("ts", "?")[:16]
                ev = (cache[kid].get("evidence_summary") or "")[:160]
                print(f"      {kid[:8]} {ts}  ev: {ev}")
            if len(ids) > 5:
                print(f"      ... +{len(ids)-5} more")


if __name__ == "__main__":
    main()
