#!/usr/bin/env python3
"""Sanity-check: do the frames I'm passing to Agent-2 in bench == what prod sent?

For each sample event:
- Print n_frames in detection_frames.json (what bench reads)
- Find all cascade_audit entries with matching detection_id (= each Agent-2 call
  that contributed to this detection)
- Print window_size + first/last frame of each call
- Compute: if multiple audit entries exist, the detection_frames.json is COALESCED
  and my bench is mixing frames across multiple actual Agent-2 calls.
"""
import json
import os
from pathlib import Path

SAMPLE_IDS = [
    "8367f372-247b-42fd-886d-61bfc600b303",  # 12:46 cam_11 (carrinho)
    "ae3d87cb-189c-4d80-b56e-d202d92b4e59",  # 12:03 cam_11
    "8bfe0a1f-da31-4ddd-9455-de0d6a5ef652",  # 18:45 cam_10
    "a447ff19-068a-4460-855c-3f6d02937860",  # 02:46 cam_10
    "01948367-8228-4824-b3ce-b54365d93daf",  # 07:02 cam_10 (recent REJ)
]
AUDIT_DIR = Path("/app/state/gemini_cascade_audit")
FRAMES_DIR = Path("/app/state/detection_frames")


def audit_for(det_id):
    """Find cascade_audit entries with matching detection_id."""
    out = []
    if not AUDIT_DIR.exists():
        return out
    for date_dir in AUDIT_DIR.iterdir():
        for fp in date_dir.glob("*.jsonl"):
            try:
                with fp.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if det_id not in line:
                            continue
                        d = json.loads(line)
                        if d.get("detection_id") == det_id:
                            out.append({
                                "date": date_dir.name,
                                "device": fp.stem,
                                "agent2_ran": d.get("agent2_ran"),
                                "agent2_disposal": d.get("agent2_disposal"),
                                "window_size": d.get("window_size"),
                                "window_first": d.get("window_first_frame"),
                                "window_last": d.get("window_last_frame"),
                                "agent2_request_id": d.get("agent2_request_id"),
                                "created_at": d.get("created_at"),
                            })
            except Exception as exc:
                print(f"  [warn] {fp}: {exc}")
    return out


for det_id in SAMPLE_IDS:
    print(f"\n=== {det_id} ===")
    df_path = FRAMES_DIR / f"{det_id}.json"
    if df_path.exists():
        d = json.loads(df_path.read_text())
        frames = d["frames"]
        print(f"detection_frames.json: n={len(frames)}  "
              f"span [{frames[0]['frame_name']} -> {frames[-1]['frame_name']}]")
    else:
        print("detection_frames.json: MISSING")
    audits = audit_for(det_id)
    if not audits:
        print("audit: no entries found")
        continue
    print(f"audit: {len(audits)} entries (Agent-2 calls that contributed)")
    for a in audits:
        print(f"  - {a['created_at']}  window_size={a['window_size']}  "
              f"first={a['window_first']}  last={a['window_last']}  "
              f"disposal={a['agent2_disposal']}")
    coalesced = len(audits) > 1
    df_len = len(d["frames"]) if df_path.exists() else None
    total_audit = sum(a["window_size"] for a in audits if a["window_size"])
    print(f"  --> coalesced={coalesced}  audit_sum_window_size={total_audit}  "
          f"df_n_frames={df_len}")
