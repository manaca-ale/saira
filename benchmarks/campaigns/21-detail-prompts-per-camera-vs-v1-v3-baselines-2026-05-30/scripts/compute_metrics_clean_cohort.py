#!/usr/bin/env python3
"""Compute camp 21 final comparison on clean single-call cohort.

Loads each run's cache + the coalesced flag per event, then computes:
- Full 64 (raw)
- 49 single-call clean (production-parity comparable)
- Per-camera within each cohort
"""
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
        return {}
    return json.loads(p.read_text())


# Build coalesced classification
conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                        password="postgres", dbname="saira_db")
cur = conn.cursor()
cur.execute("""
    SELECT id::text FROM detections
    WHERE status IN ('REJEITADO', 'CONFIRMADO') AND camera_id IN (10, 11)
""")
all_ids = [r[0] for r in cur.fetchall()]
cur.close()
conn.close()

audit_cnt = {i: n_audits(i) for i in all_ids}
single_call = {i for i, n in audit_cnt.items() if n == 1}
coalesced = {i for i, n in audit_cnt.items() if n > 1}
no_audit = {i for i, n in audit_cnt.items() if n == 0}

print(f"Cohort sizes: single_call={len(single_call)}  coalesced={len(coalesced)}  "
      f"no_audit={len(no_audit)}")

runs = {
    "Flash V1 prod (baseline)": load_cache("/tmp/flash_baseline_v1_cache.json"),
    "Flash + per-camera":        load_cache("/tmp/flash_per_camera_cache.json"),
    "Pro + per-camera":          load_cache("/tmp/pro_per_camera_cache.json"),
    "Sonnet + per-camera":       load_cache("/tmp/sonnet_per_camera_cache.json"),
}


def score(name, cache, cohort, label):
    items = [v for k, v in cache.items() if k in cohort]
    if not items:
        return
    n = len(items)
    tp = sum(1 for v in items if v["pred"] == "CON" and v["gt"] == "CON")
    tn = sum(1 for v in items if v["pred"] == "REJ" and v["gt"] == "REJ")
    fp = sum(1 for v in items if v["pred"] == "CON" and v["gt"] == "REJ")
    fn = sum(1 for v in items if v["pred"] == "REJ" and v["gt"] == "CON")
    acc = (tp + tn) / n
    rec = tp / max(tp + fn, 1)
    spec = tn / max(tn + fp, 1)
    print(f"  {name:<32s} n={n:<3} acc={acc:.2%} TP={tp} TN={tn} FP={fp} FN={fn} "
          f"recall={rec:.2%} spec={spec:.2%}")


for label, cohort in [
    ("=== Full (all events with results) ===", None),
    ("=== Single-call cohort (clean prod parity) ===", single_call),
    ("=== Coalesced cohort (bench input != prod) ===", coalesced),
]:
    print()
    print(label)
    for name, cache in runs.items():
        used = set(cache.keys()) if cohort is None else cohort
        score(name, cache, used, label)


# Per-camera on the clean 49 cohort
print()
print("=== Per-camera on SINGLE-CALL cohort ===")
for name, cache in runs.items():
    items = [v for k, v in cache.items() if k in single_call]
    for cam in (10, 11):
        sub = [v for v in items if v["cam"] == cam]
        if not sub:
            continue
        n = len(sub)
        tp = sum(1 for v in sub if v["pred"] == "CON" and v["gt"] == "CON")
        tn = sum(1 for v in sub if v["pred"] == "REJ" and v["gt"] == "REJ")
        fp = sum(1 for v in sub if v["pred"] == "CON" and v["gt"] == "REJ")
        fn = sum(1 for v in sub if v["pred"] == "REJ" and v["gt"] == "CON")
        rec = tp / max(tp + fn, 1)
        print(f"  {name:<32s} cam_{cam} n={n:<3} acc={(tp+tn)/n:.2%} TP={tp} TN={tn} "
              f"FP={fp} FN={fn} recall={rec:.2%}")
