#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Larger-N: bucket cam_11 CONFIRMADO/REJEITADO + download last-3 frames from S3.

Buckets REJEITADO into B1/B2 (catador/limpeza, excluir) vs B3 (foco) via comment+notes.
CONFIRMADO=TP. Writes largeN/manifest.csv (id,label,bucket,frames=local paths).
"""
import csv
import json
import re
import sys
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
LN = Path(r"c:\saira\benchmarks\campaigns\40-mangabeira-b3-fp-2026-06-16\largeN")
FR = LN / "frames"
FR.mkdir(parents=True, exist_ok=True)
N_LAST = 3

B1 = re.compile(r"catador|revir|reviro|vasculh|mexe|mexen|recicl|caçamba|cacamba|movimenta")
B2 = re.compile(r"emlurb|prefeitura|coleta|recolhiment|limpeza|limpando|\bpoda\b|madeira")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def bucket(status, comment, notes):
    if status == "CONFIRMADO":
        return "TP"
    t = norm(comment) + " " + norm(notes)
    if B2.search(t):
        return "B1B2"
    if B1.search(t):
        return "B1B2"
    return "B3"


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
    rows = list(csv.DictReader((LN / "corpus.csv").open(encoding="utf-8")))
    jobs, manifest = [], []
    for r in rows:
        jp = LN / "df" / f"{r['id']}.json"
        if not jp.exists() or jp.stat().st_size < 10:
            continue
        try:
            frames = json.loads(jp.read_text(encoding="utf-8")).get("frames", [])
        except Exception:
            continue
        if not frames:
            continue
        b = bucket(r["status"], r.get("validity_comment", ""), r.get("notes", ""))
        sel = frames[-N_LAST:]
        local = []
        for f in sel:
            u = f.get("image_url", "")
            if not u.startswith("http"):
                continue
            dst = FR / f"{r['id'][:8]}__{f['frame_name']}"
            jobs.append((u, dst))
            local.append(str(dst))
        if local:
            manifest.append({"id": r["id"], "label": 1 if b == "TP" else 0,
                             "bucket": b, "created_at": r["created_at"],
                             "frames": "|".join(local)})

    print(f"manifest: {len(manifest)} eventos | baixando {len(jobs)} frames...")
    with ThreadPoolExecutor(max_workers=16) as ex:
        ok = sum(ex.map(dl, jobs))
    print(f"frames baixados OK: {ok}/{len(jobs)}")

    import collections
    print("buckets:", collections.Counter(m["bucket"] for m in manifest))
    with (LN / "manifest.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "label", "bucket", "created_at", "frames"])
        w.writeheader(); w.writerows(manifest)
    print(f"-> {LN / 'manifest.csv'}")


if __name__ == "__main__":
    main()
