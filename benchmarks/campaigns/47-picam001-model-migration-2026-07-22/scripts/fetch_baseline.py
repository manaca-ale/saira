#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build the BASELINE (no-occurrence) set for pi-cam-001.

pi-cam-001 is event-driven: there are no "idle" frames like the ESP32 baseline.
The natural baseline is SEM-OCORRÊNCIA events — motion fired but the pipeline
classified NO dumping (true negatives). These test specificity: a candidate model
must NOT fire on them.

Source: event manifests (.tmp/events/evt-20260722_*.json) that are closed, non-transient,
>=6 frames, and NOT referenced by any labeled detection. Frames live on the esp32-server
local disk under sem_ocorrencia/2026/07/22 (today's data, not yet migrated/zipped to S3).

Two phases:
  (default) SELECT — stratify N events across the day, emit .tmp/baseline_sel.json +
            .tmp/baseline_names.txt (frame names to pull from the server).
  --place   after the frames are pulled into .tmp/basefill/, build
            data/datasets/official/cam_picam001/baseline/<event_ref>/{frames/*.jpg, label.json}
"""
import json, csv, sys, shutil
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
CAMP = Path(__file__).resolve().parents[1]
TMP = CAMP / ".tmp"
ROOT = Path(r"c:\saira")
OFF = ROOT / "data" / "datasets" / "official"
CAM = OFF / "cam_picam001"
N_SELECT = 40
DAY_GLOB = "evt-20260722_*.json"


def referenced_events():
    ref = set()
    for r in csv.DictReader((TMP / "corpus_picam001.csv").open(encoding="utf-8")):
        dfj = json.loads((TMP / "df" / f'{r["id"]}.json').read_text(encoding="utf-8"))
        ref.update(dfj.get("event_refs") or [])
        if r.get("event_ref"):
            ref.add(r["event_ref"])
    return ref


def candidates():
    ref = referenced_events()
    out = []
    for mp in (TMP / "events").glob(DAY_GLOB):
        e = mp.stem
        if e in ref:
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))
        if m.get("state") != "closed" or m.get("closed_reason") == "transient":
            continue
        names = [Path(p).name for p in m.get("frames", [])]
        if len(names) < 6:
            continue
        out.append((e, names))
    out.sort(key=lambda x: x[0])  # chronological by event id (timestamp)
    return out


def select(cands, n):
    if len(cands) <= n:
        return cands
    step = len(cands) / n
    return [cands[int(i * step)] for i in range(n)]


def main():
    if "--place" in sys.argv:
        sel = json.loads((TMP / "baseline_sel.json").read_text(encoding="utf-8"))
        rrow = next(csv.DictReader((TMP / "corpus_picam001.csv").open(encoding="utf-8")))
        placed = 0
        for ev in sel:
            ref = ev["event_id"]
            edir = CAM / "baseline" / ref / "frames"
            edir.mkdir(parents=True, exist_ok=True)
            frame_rel = []
            for n in ev["frames"]:
                src = TMP / "basefill" / n
                if not src.exists() or src.stat().st_size < 1000:
                    continue
                dst = edir / n
                if not dst.exists():
                    shutil.copy2(src, dst)
                frame_rel.append(f"cam_picam001/baseline/{ref}/frames/{n}")
                placed += 1
            if not frame_rel:
                continue
            ts = ref.replace("evt-", "").replace("_", " ")  # 20260722 HHMMSS
            dt = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}-03:00"
            label = {
                "event_id": ref, "camera": "cam_picam001", "device_id": "pi-cam-001",
                "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
                "bairro": "Imbiribeira", "rpa": "RPA-1", "datetime": dt,
                "tipo_residuo": "", "volumetria": "",
                "classificacao": "Sem Ocorrência", "category": "baseline",
                "justificativa": "Evento de movimento classificado SEM descarte pelo pipeline (negativo verdadeiro).",
                "label_source": "prod_pull_picam001", "source_campaign": "47-picam001-model-migration",
                "frame_count": len(frame_rel), "frames": frame_rel,
            }
            (edir.parent / "label.json").write_text(
                json.dumps(label, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"baseline events placed: {len(sel)} | frames: {placed}")
        return

    cands = candidates()
    print(f"candidates: {len(cands)}")
    sel = select(cands, N_SELECT)
    print(f"selected: {len(sel)} events, "
          f"{sum(len(n) for _, n in sel)} frames")
    print("by hour:", dict(sorted(Counter(e.split('_')[1][:2] for e, _ in sel).items())))
    (TMP / "baseline_sel.json").write_text(
        json.dumps([{"event_id": e, "frames": n} for e, n in sel], ensure_ascii=False, indent=2),
        encoding="utf-8")
    names = sorted({n for _, ns in sel for n in ns})
    (TMP / "baseline_names.txt").write_text("\n".join(names), encoding="utf-8")
    print(f"wrote .tmp/baseline_sel.json + .tmp/baseline_names.txt ({len(names)} names)")


if __name__ == "__main__":
    main()
