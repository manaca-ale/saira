#!/usr/bin/env python3
"""Count how many of the 64 bench events are coalesced (= multiple Agent-2 calls
mixed into one detection_frames.json)."""
import json
from pathlib import Path
import psycopg2

AUDIT_DIR = Path("/app/state/gemini_cascade_audit")
FRAMES_DIR = Path("/app/state/detection_frames")


def audit_count(det_id):
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


conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                        password="postgres", dbname="saira_db")
cur = conn.cursor()
cur.execute("""
    SELECT id::text, camera_id, status::text
    FROM detections
    WHERE status IN ('REJEITADO', 'CONFIRMADO')
      AND camera_id IN (10, 11)
    ORDER BY timestamp DESC
""")
rows = cur.fetchall()
cur.close()
conn.close()

single = 0
coalesced = 0
no_audit = 0
by_status = {"single": {"CON": 0, "REJ": 0}, "coalesced": {"CON": 0, "REJ": 0}}
for r in rows:
    det_id, cam, status = r
    n = audit_count(det_id)
    gt = "CON" if status == "CONFIRMADO" else "REJ"
    if n == 0:
        no_audit += 1
    elif n == 1:
        single += 1
        by_status["single"][gt] += 1
    else:
        coalesced += 1
        by_status["coalesced"][gt] += 1

print(f"Total events: {len(rows)}")
print(f"  single-call (1 audit): {single}")
print(f"  coalesced (>1 audit):  {coalesced}")
print(f"  no audit found:        {no_audit}")
print()
print("Coalesced events skew:")
print(f"  single: {by_status['single']}")
print(f"  coalesced: {by_status['coalesced']}")
