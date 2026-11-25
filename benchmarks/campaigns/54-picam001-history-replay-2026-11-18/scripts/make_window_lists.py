#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — listas para buscar a JANELA COMPLETA (o que o detail ve) dos eventos da amostra em que o gate
de producao disparou: S1 (frames nos zips diarios do S3, pelo worker) e S2 (frames de deteccao, URL publica).
Pula o que ja esta em frames/gate5 ou frames/janela.

Uso: python make_window_lists.py [--estratos S1,S2] [--eventos arquivo_com_ids.txt]
Saida: amostra/fetch_zip_janelas.json e amostra/fetch_public_janelas.tsv
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Saira\data\historico-picam")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--estratos", default="S1,S2")
    ap.add_argument("--eventos", default="")
    a = ap.parse_args()
    strata = set(a.estratos.split(","))
    only = set(Path(a.eventos).read_text(encoding="utf-8").split()) if a.eventos else None
    have = {p.name for d in ("gate5", "janela") if (ROOT / "frames" / d).is_dir()
            for p in (ROOT / "frames" / d).iterdir()}
    zidx = {}
    with gzip.open(ROOT / "raw" / "zip_dirs.tsv.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            day, name, method, crc, csize, size, off, nlen = line.rstrip("\n").split("\t")
            zidx[name.rsplit("/", 1)[-1]] = [day, name, int(off), int(csize), int(size), int(method), int(crc), int(nlen)]
    zips, pubs, nbytes, n_ev = [], [], 0, 0
    miss = 0
    for r in csv.DictReader((ROOT / "amostra" / "sample.csv").open(encoding="utf-8", newline="")):
        if only is not None:
            if r["event_id"] not in only:
                continue
        elif r["estrato"] not in strata:
            continue
        n_ev += 1
        win = [n for n in r["window"].split("|") if n and n not in have]
        if r["fonte"] == "zip":
            for n in win:
                if n in zidx:
                    zips.append(zidx[n])
                    nbytes += zidx[n][3]
                else:
                    miss += 1
        else:
            j = json.loads((ROOT / "extraido" / "detection_frames" / f"{r['detection_id']}.json").read_text(encoding="utf-8"))
            url = {f["frame_name"]: f.get("image_url") or "" for f in j.get("frames") or []}
            for n in win:
                if url.get(n):
                    pubs.append((n, url[n]))
                else:
                    miss += 1
    zips = sorted({tuple(z) for z in zips})
    pubs = sorted(set(pubs))
    (ROOT / "amostra" / "fetch_zip_janelas.json").write_text(json.dumps(zips), encoding="utf-8")
    with (ROOT / "amostra" / "fetch_public_janelas.tsv").open("w", encoding="utf-8", newline="") as fh:
        for n, u in pubs:
            fh.write(f"{n}\t{u}\n")
    print(f"eventos: {n_ev} | frames novos nos zips: {len(zips)} ({nbytes / 1e9:.2f} GB comprimidos) | "
          f"frames novos publicos: {len(pubs)} | sem origem: {miss} | ja presentes: {len(have)}")


if __name__ == "__main__":
    main()
