#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase B — build labeling/index.json for tools/tp_marker.html.

Lists every cam_imbiribeira TP event with ONE representative frame so the user can
mark, per TP, where the disposal happens (x,y in 1280x720 ref) + vehicle yes/no.

Frame URLs are root-relative (served from c:\\saira via `python -m http.server`), so
<img src> loads cleanly with no file:// CORS pain. Representative frame = the worker's
selected_frame_name when its file is present, else the middle frame of the window.
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
CAMP = Path(__file__).resolve().parents[1]
OFFICIAL = ROOT / "data" / "datasets" / "official"
TP_DIR = OFFICIAL / "cam_imbiribeira" / "tp"
OUT = CAMP / "labeling" / "index.json"


def all_frames(event_dir: Path) -> list[dict]:
    """Every frame on disk for this event, chronological (filename = timestamp)."""
    out = []
    for p in sorted((event_dir / "frames").glob("*.jpg")):
        rel = f"cam_imbiribeira/tp/{event_dir.name}/frames/{p.name}"
        out.append({"url": "/data/datasets/official/" + rel, "name": p.name})
    return out


def main():
    events = []
    for ev in sorted(TP_DIR.iterdir()):
        lj = ev / "label.json"
        if not lj.exists():
            continue
        label = json.loads(lj.read_text(encoding="utf-8"))
        frames = all_frames(ev)
        if not frames:
            print(f"  WARN no frames for {ev.name}")
            continue
        sel = (label.get("selected_frame_name") or "").strip()
        default_idx = next((i for i, f in enumerate(frames) if f["name"] == sel),
                           len(frames) // 2)
        events.append({
            "event_id": label.get("event_id", ev.name),
            "label": "tp",
            "frames": frames,                 # ALL frames, chronological
            "default_idx": default_idx,       # selected_frame_name or middle
            "datetime": label.get("datetime", ""),
            "justificativa": label.get("justificativa", ""),
            "label_source": label.get("label_source", ""),
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "camera": "cam_imbiribeira",
        "device_id": "esp32_001",
        "ref_w": 1280, "ref_h": 720,
        "note": "Serve c:\\saira via `python -m http.server 8009`; open "
                "http://localhost:8009/tools/tp_marker.html",
        "count": len(events),
        "events": events,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} with {len(events)} TP events")


if __name__ == "__main__":
    main()
