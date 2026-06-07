#!/usr/bin/env python3
"""Camp 22+23+24 unified: compare V1 baseline / MANGABEIRA orig / E / E2 / E+CROPS
on cam_11 single-call cohort. Identifies which specific FN/FP each arm
recovered or introduced vs V1.
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
        "V1 baseline":              load_cache("/tmp/flash_baseline_v1_cache.json"),
        "MANGABEIRA orig":          load_cache("/tmp/flash_per_camera_cache.json"),
        "MANGABEIRA_E":             load_cache("/tmp/flash_mangabeira_E_cache.json"),
        "MANGABEIRA_E2 (camp 23)":  load_cache("/tmp/flash_mangabeira_E2_cache.json"),
        "E+CROPS (camp 24)":        load_cache("/tmp/flash_mangabeira_E_CROPS_cache.json"),
    }

    for label, cohort in [
        ("=== Full cam_11 ===", None),
        ("=== Single-call cam_11 (prod parity, n=29) ===", single_call),
    ]:
        print()
        print(label)
        for name, cache in runs.items():
            if cohort is None:
                sub = [v for k, v in cache.items() if v.get("cam") == 11]
            else:
                sub = [v for k, v in cache.items()
                       if v.get("cam") == 11 and k in cohort]
            if sub:
                s = score(sub)
                print(f"  {name:<28s} n={s['n']:<3} acc={s['acc']:.1%}  "
                      f"TP={s['tp']} TN={s['tn']} FP={s['fp']} FN={s['fn']}  "
                      f"recall={s['recall']:.1%}  spec={s['spec']:.1%}")

    # Cross-bucket vs V1 baseline (single-call cohort) for each new arm
    v1 = runs["V1 baseline"]
    arms_to_check = ["MANGABEIRA_E", "MANGABEIRA_E2 (camp 23)", "E+CROPS (camp 24)"]
    print()
    print("=" * 80)
    print("=== Cross-bucket vs V1 (single-call cohort) ===")
    print("=" * 80)
    for arm_name in arms_to_check:
        cache = runs[arm_name]
        common = set(v1) & set(cache) & single_call
        buckets = {
            "TP_NEW (V1 FN -> CON)":      [],
            "FN_NEW (V1 CON -> REJ)":     [],
            "FP_FIXED (V1 FP -> REJ)":    [],
            "FP_NEW (V1 TN -> CON)":      [],
            "FP_PERSIST (V1 CON on REJ)": [],
            "FN_BOTH":                    [],
        }
        for kid in common:
            a, b = v1[kid], cache[kid]
            if a.get("cam") != 11 or b.get("cam") != 11:
                continue
            gt = a["gt"]
            pv, pa = a["pred"], b["pred"]
            if gt == "CON":
                if pv == "CON" and pa == "REJ":
                    buckets["FN_NEW (V1 CON -> REJ)"].append(kid)
                elif pv == "REJ" and pa == "CON":
                    buckets["TP_NEW (V1 FN -> CON)"].append(kid)
                elif pv == "REJ" and pa == "REJ":
                    buckets["FN_BOTH"].append(kid)
            else:
                if pv == "CON" and pa == "REJ":
                    buckets["FP_FIXED (V1 FP -> REJ)"].append(kid)
                elif pv == "REJ" and pa == "CON":
                    buckets["FP_NEW (V1 TN -> CON)"].append(kid)
                elif pv == "CON" and pa == "CON":
                    buckets["FP_PERSIST (V1 CON on REJ)"].append(kid)

        print(f"\n>>> {arm_name}")
        for name, ids in buckets.items():
            arrow = ("+" if ("FIXED" in name or "TP_NEW" in name)
                     else "-" if ("FN_NEW" in name or "FP_NEW" in name) else "·")
            print(f"  {arrow} [{len(ids):>2}] {name}")
            for kid in ids[:3]:
                ts = cache[kid].get("ts", "?")[:16]
                print(f"      {kid[:8]} {ts}")

    # Check the 2 specific FN_NEW from camp 22 (motivated camp 23) and 1 FP_NEW
    target_ids = {
        "d59d5309-60c5-4ce9-8a64-2c68342c07c5": "FN_NEW E (CON real, AP3 over-applied)",
        "3c840ac4-b0f7-4fec-b696-dd7e68725b49": "FN_NEW E (CON real carrinho, AP2 over-applied)",
        "5520e0c7-918b-4619-9820-c2c230edef1c": "FP_NEW E (REJ, agachado 2:30, AP4 under-applied)",
    }
    print()
    print("=" * 80)
    print("=== Target events (motivated camp 23 refinements) ===")
    print("=" * 80)
    for tid, desc in target_ids.items():
        print(f"\n[{desc}]")
        gt = v1.get(tid, {}).get("gt", "?")
        print(f"  GT: {gt}")
        for arm_name, cache in runs.items():
            row = cache.get(tid)
            if not row:
                print(f"  {arm_name:<28s} (not in cache)")
                continue
            pred = row["pred"]
            mark = "OK" if pred == gt else "MISS"
            print(f"  {arm_name:<28s} pred={pred} {mark}")


if __name__ == "__main__":
    main()
