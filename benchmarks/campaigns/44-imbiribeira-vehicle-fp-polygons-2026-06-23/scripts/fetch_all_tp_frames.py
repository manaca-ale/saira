#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download the FULL frame sequence of every cam_imbiribeira TP from S3.

The labeling tool needs ALL frames per TP (not just one representative) so the user can
scrub to the exact disposal moment. Reads .tmp/df/<id>.json (full detection_frames pulled
off prod) and downloads every frame into the official dataset frames dir. Idempotent.
"""
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CAMP = Path(__file__).resolve().parents[1]
DF = CAMP / ".tmp" / "df"
TP = Path(r"c:\saira\data\datasets\official\cam_imbiribeira\tp")


def dl(args):
    url, dst = args
    if dst.exists() and dst.stat().st_size > 1000:
        return True
    try:
        urllib.request.urlretrieve(url, dst)
        return dst.stat().st_size > 1000
    except Exception:
        return False


def main():
    jobs = []
    for ev in sorted(TP.iterdir()):
        if not ev.is_dir():
            continue
        jp = DF / f"{ev.name}.json"
        if not jp.exists():
            continue
        frames = json.loads(jp.read_text(encoding="utf-8")).get("frames", []) or []
        fdir = ev / "frames"
        fdir.mkdir(parents=True, exist_ok=True)
        for f in frames:
            u = (f.get("image_url") or "").strip()
            name = (f.get("frame_name") or "").strip()
            if u.startswith("http") and name:
                jobs.append((u, fdir / name))
    print(f"downloading {len(jobs)} TP frames (16 threads)...")
    with ThreadPoolExecutor(max_workers=16) as ex:
        ok = sum(ex.map(dl, jobs))
    print(f"OK {ok}/{len(jobs)} (miss {len(jobs)-ok})")


if __name__ == "__main__":
    main()
