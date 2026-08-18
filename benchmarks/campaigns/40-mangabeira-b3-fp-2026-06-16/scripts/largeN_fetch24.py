#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download ~24 frames/event (sampled from full window) for TP+B3 large-N events."""
import csv
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
LN = Path(r"c:\saira\benchmarks\campaigns\40-mangabeira-b3-fp-2026-06-16\largeN")
FR = LN / "frames24"
FR.mkdir(parents=True, exist_ok=True)
NF = 24


def sample(lst, n):
    if len(lst) <= n:
        return lst
    return [lst[round(i * (len(lst) - 1) / (n - 1))] for i in range(n)]


def dl(args):
    url, dst = args
    if dst.exists() and dst.stat().st_size > 1000:
        return True
    try:
        urllib.request.urlretrieve(url, dst)
        return dst.stat().st_size > 1000
    except Exception:
        return False


man = {r["id"]: r["bucket"] for r in csv.DictReader((LN / "manifest.csv").open(encoding="utf-8"))}
jobs, ev = [], []
for eid, bucket in man.items():
    if bucket not in ("TP", "B3"):
        continue
    jp = LN / "df" / f"{eid}.json"
    if not jp.exists():
        continue
    frames = json.loads(jp.read_text(encoding="utf-8")).get("frames", [])
    sel = sample(frames, NF)
    paths = []
    for f in sel:
        u = f.get("image_url", "")
        if not u.startswith("http"):
            continue
        dst = FR / f"{eid[:8]}__{f['frame_name']}"
        jobs.append((u, dst)); paths.append(str(dst))
    if paths:
        ev.append({"id": eid, "bucket": bucket, "frames": "|".join(paths)})

print(f"{len(ev)} eventos, baixando {len(jobs)} frames...")
with ThreadPoolExecutor(max_workers=16) as ex:
    ok = sum(ex.map(dl, jobs))
print(f"OK {ok}/{len(jobs)}")
with (LN / "manifest24.csv").open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id", "bucket", "frames"]); w.writeheader(); w.writerows(ev)
print(f"-> {LN/'manifest24.csv'}")
