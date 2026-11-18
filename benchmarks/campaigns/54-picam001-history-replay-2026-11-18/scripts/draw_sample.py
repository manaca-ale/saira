#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — sorteia a amostra do reprocessamento e reconstroi, para cada evento, a janela que o gate de
producao viu (sem custo de API).

Estratos (decisao GRAVADA em producao, base_eventos.csv):
  S0  gate nao disparou            -> sorteio de N_S0 eventos, semente fixa
  S1  gate disparou, detail nao    -> todos
  S2  detail sim (deteccao)        -> todos
Janela = subsample_frames(frames, 48) + fit_frames_to_payload(., 8 MB), como no worker; os tamanhos dos
frames vem do indice dos zips diarios do S3 (S0/S1). Em S2 os frames guardados no S3 ja sao a janela.
A reconstrucao e conferida contra o que o worker gravou: ultimo frame e tamanho da janela.
Gate: primeira, 3 do meio igualmente espacadas, ultima (gate_mids).

Divisao desenvolvimento/avaliacao por hash (40% / 60%), por deteccao em S2 e por evento no resto: os
prompts e limiares so podem ser ajustados no conjunto de desenvolvimento.

Saida em C:\\Saira\\data\\historico-picam\\amostra: sample.csv, fetch_zip.json, fetch_public.tsv.
Uso: python draw_sample.py
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"C:\Saira\data\historico-picam")
EXT, RAW, OUT = ROOT / "extraido", ROOT / "raw", ROOT / "amostra"
START = "2026-07-14"
N_S0, SEED = 4000, 54
MAX_FRAMES, MAX_BYTES, MIDS = 48, 8_000_000, 3
DEV_PCT = 40


def subsample(names, k):                      # event_windows.subsample_frames
    if k <= 0 or len(names) <= k:
        return names
    if k == 1:
        return [names[-1]]
    step = (len(names) - 1) / (k - 1)
    return [names[i] for i in sorted({round(i * step) for i in range(k)})]


def fit(names, size, max_bytes):              # event_windows.fit_frames_to_payload
    while len(names) > 1:
        total = sum(size[n] for n in names)
        if total <= max_bytes:
            return names
        target = min(len(names) - 1, max(1, int(len(names) * max_bytes // total)))
        names = subsample(names, target)
    return names


def gate5(win):                               # main.py:1461-1470 / bench53.gate_mids
    n = len(win)
    mids = []
    if n >= 3 and MIDS:
        step = (n - 1) / (MIDS + 1)
        ks = sorted({int(round(step * (i + 1))) for i in range(MIDS)})
        mids = [win[k] for k in ks if 0 < k < n - 1]
    out = [win[0]] + mids + [win[-1]]
    seen, res = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return res


def bucket(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % 100


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    base = [r for r in csv.DictReader((ROOT / "base" / "base_eventos.csv").open(encoding="utf-8", newline=""))
            if r["dia"] >= START and r["gate_avaliou"] == "1"]

    zidx = {}
    with gzip.open(RAW / "zip_dirs.tsv.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            day, name, method, crc, csize, size, off, nlen = line.rstrip("\n").split("\t")
            zidx[name.rsplit("/", 1)[-1]] = (day, int(method), int(crc), int(csize), int(size), int(off), int(nlen), name)
    sizes = [v[4] for v in zidx.values()]
    print(f"indice dos zips: {len(zidx)} frames | tamanho mediano {statistics.median(sizes) / 1e3:.0f} KB "
          f"(p10 {sorted(sizes)[len(sizes) // 10] / 1e3:.0f}, p90 {sorted(sizes)[9 * len(sizes) // 10] / 1e3:.0f})")

    det_frames = {}
    for p in (EXT / "detection_frames").glob("*.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if j.get("device_id") == "pi-cam-001":
            det_frames[j["detection_id"]] = {f["frame_name"]: f.get("image_url") or "" for f in j.get("frames") or []}

    def stratum(r):
        if r["gate_disparou"] != "1":
            return "S0"
        return "S2" if r["detail_sim"] == "1" else "S1"

    rows, why = [], Counter()
    for r in base:
        s = stratum(r)
        m = json.loads((EXT / "events" / f"{r['event_id']}.json").read_text(encoding="utf-8"))
        names = sorted(f.rsplit("/", 1)[-1] for f in m.get("frames") or [])
        last = r["window_last_frame"]
        if last in names:
            names = [n for n in names if n <= last]       # o worker pode ter julgado antes de o evento fechar
        src = "zip"
        if s == "S2":
            df = det_frames.get(r["detection_id"]) or {}
            win = [n for n in names if n in df]
            src = "publico"
            if not win:
                why[(s, "sem frames no registro da deteccao")] += 1
                continue
        else:
            if any(n not in zidx for n in names):
                why[(s, "frames fora dos zips")] += 1
                continue
            win = fit(subsample(names, MAX_FRAMES), {n: zidx[n][4] for n in names}, MAX_BYTES)
        ok = int(str(r["window_size"]).isdigit() and len(win) == int(r["window_size"]) and win[-1] == last
                 and win[0] == r["first_frame"])
        if not ok:
            why[(s, "janela reconstruida difere da gravada")] += 1
        rows.append({"event_id": r["event_id"], "estrato": s, "dia": r["dia"], "status": r["status"],
                     "detection_id": r["detection_id"], "gate_conf": r["gate_conf"],
                     "janela_ok": ok, "window_size": len(win), "fonte": src,
                     "gate5": gate5(win), "window": win})
    tot = Counter(stratum(r) for r in base)
    got = Counter(r["estrato"] for r in rows)
    okc = Counter(r["estrato"] for r in rows if r["janela_ok"])
    print("populacao (avaliados desde 14/07):", dict(tot))
    print("com frames localizados:", dict(got), "| janela identica a gravada pelo worker:", dict(okc))
    print("motivos de exclusao ou divergencia:", {f"{k[0]}: {k[1]}": v for k, v in sorted(why.items())})

    rng = random.Random(SEED)
    pool0 = sorted(r["event_id"] for r in rows if r["estrato"] == "S0" and r["janela_ok"])
    pick0 = set(rng.sample(pool0, min(N_S0, len(pool0))))
    sample = [r for r in rows if (r["estrato"] == "S0" and r["event_id"] in pick0)
              or (r["estrato"] in ("S1", "S2") and r["janela_ok"])]
    for r in sample:
        key = r["detection_id"] if r["estrato"] == "S2" and r["detection_id"] else r["event_id"]
        r["split"] = "dev" if bucket(key) < DEV_PCT else "aval"
    print(f"\namostra: {len(sample)} eventos |",
          ", ".join(f"{s}/{sp} {n}" for (s, sp), n in sorted(Counter((r['estrato'], r['split']) for r in sample).items())))
    print("S2 por estado:", dict(Counter((r["status"], r["split"]) for r in sample if r["estrato"] == "S2")))
    print("S0 sorteados por semana:", dict(sorted(Counter(r["dia"][:7] for r in sample if r["estrato"] == "S0").items())))

    zip_list, pub_list, nbytes = [], [], 0
    for r in sample:
        for n in r["gate5"]:
            if r["fonte"] == "zip":
                day, method, crc, csize, size, off, nlen, full = zidx[n]
                zip_list.append([day, full, off, csize, size, method, crc, nlen])
                nbytes += csize
            else:
                pub_list.append((n, det_frames[r["detection_id"]][n]))
    with (OUT / "sample.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "estrato", "split", "dia", "status", "detection_id", "gate_conf_producao",
                    "window_size", "fonte", "gate5", "window"])
        for r in sample:
            w.writerow([r["event_id"], r["estrato"], r["split"], r["dia"], r["status"], r["detection_id"],
                        r["gate_conf"], r["window_size"], r["fonte"], "|".join(r["gate5"]), "|".join(r["window"])])
    (OUT / "fetch_zip.json").write_text(json.dumps(sorted(set(map(tuple, zip_list)))), encoding="utf-8")
    with (OUT / "fetch_public.tsv").open("w", encoding="utf-8", newline="") as fh:
        for n, u in sorted(set(pub_list)):
            fh.write(f"{n}\t{u}\n")
    print(f"\nframes do gate a buscar: {len(set(map(tuple, zip_list)))} nos zips ({nbytes / 1e9:.2f} GB comprimidos) "
          f"+ {len(set(pub_list))} publicos")
    n5 = Counter(len(r["gate5"]) for r in sample)
    print("frames por evento enviados ao gate:", dict(sorted(n5.items())))


if __name__ == "__main__":
    main()
