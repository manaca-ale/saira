#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build the OFFICIAL per-camera dataset for pi-cam-001 (event-driven).

UNIT = EVENT (manifest). pi-cam-001 runs the cascade once per event; a detections
row may coalesce 2+ events. We therefore split each labeled detection into its
component events (event_refs[]) and write ONE folder per event_ref, so each folder
is exactly one real cascade window.

Inputs (produced by the prod pull, all under .tmp/):
  corpus_picam001.csv         one row per detection (cols from sql/pull_picam001.sql)
  df/<id>.json                detection_frames: frames[{frame_name,image_url}], event_refs[]
  events/<event_ref>.json     esp32-server event manifest: frames[] (rel paths, ordered)

Output:
  data/datasets/official/cam_picam001/<cat>/<event_ref>/{frames/*.jpg, label.json}
  where cat = tp|fp|indefinido  (CONFIRMADO->tp, REJEITADO->fp, INDETERMINADO->indefinido)

Label is inherited from the parent detection status. Frames are downloaded from S3
(public ocorrencias/ URLs) via urlretrieve. Idempotent: existing frames are skipped.
Run with --apply to write; default is dry-run (counts only, no download).
"""
import collections
import csv
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CAMP = Path(__file__).resolve().parents[1]
TMP = CAMP / ".tmp"
ROOT = Path(r"c:\saira")
OFFICIAL = ROOT / "data" / "datasets" / "official"
CAM = OFFICIAL / "cam_picam001"

CAMERA = "cam_picam001"
DEVICE = "pi-cam-001"
STATUS_TO_CAT = {"CONFIRMADO": "tp", "REJEITADO": "fp", "INDETERMINADO": "indefinido"}
CLASSIF = {"tp": "Descarte", "fp": "Falso Positivo", "indefinido": "Indefinido"}


def dl(args):
    url, dst = args
    if dst.exists() and dst.stat().st_size > 1000:
        return True
    try:
        urllib.request.urlretrieve(url, dst)
        return dst.stat().st_size > 1000
    except Exception as e:  # noqa
        return False


def main():
    apply = "--apply" in sys.argv
    rows = list(csv.DictReader((TMP / "corpus_picam001.csv").open(encoding="utf-8")))
    print(f"corpus: {len(rows)} detections")

    jobs = []            # (url, dst) download jobs
    events = []          # per-event records (become label.json)
    stats = collections.Counter()
    missing_df = missing_manifest = 0

    for r in rows:
        det_id = r["id"]
        cat = STATUS_TO_CAT.get((r.get("status") or "").strip().upper())
        if not cat:
            continue
        jp = TMP / "df" / f"{det_id}.json"
        if not jp.exists():
            missing_df += 1
            continue
        dfj = json.loads(jp.read_text(encoding="utf-8"))
        urlmap = {f["frame_name"]: (f.get("image_url") or "").strip()
                  for f in dfj.get("frames", [])}
        refs = dfj.get("event_refs") or ([r["event_ref"]] if r.get("event_ref") else [])
        if not refs:
            # No event_ref anywhere: treat the whole detection window as one pseudo-event.
            refs = [f"det-{det_id[:8]}"]
            manifests = {refs[0]: list(urlmap.keys())}
        else:
            manifests = {}
            for ref in refs:
                mp = TMP / "events" / f"{ref}.json"
                if mp.exists():
                    m = json.loads(mp.read_text(encoding="utf-8"))
                    manifests[ref] = [Path(p).name for p in m.get("frames", [])]
                else:
                    missing_manifest += 1
                    manifests[ref] = None  # will fall back below

        for ref in refs:
            names = manifests.get(ref)
            if not names:
                # manifest missing: fall back to all df frames not claimed by a sibling manifest
                claimed = {n for k, v in manifests.items() if k != ref and v for n in v}
                names = [n for n in urlmap if n not in claimed]
            names = [n for n in names if urlmap.get(n, "").startswith("http")]
            if not names:
                continue
            edir = CAM / cat / ref / "frames"
            frame_rel, local = [], []
            for n in names:
                dst = edir / n
                jobs.append((urlmap[n], dst))
                local.append(dst)
                frame_rel.append(f"{CAMERA}/{cat}/{ref}/frames/{n}")
            events.append({
                "event_id": ref,
                "camera": CAMERA, "device_id": DEVICE,
                "logradouro": (r.get("logradouro") or "").strip(),
                "bairro": (r.get("bairro") or "").strip(),
                "rpa": (r.get("rpa") or "").strip(),
                "datetime": r.get("created_at", ""),
                "tipo_residuo": (r.get("waste_type") or "").strip(),
                "volumetria": (r.get("volume_m3") or "").strip(),
                "classificacao": CLASSIF[cat], "category": cat,
                "justificativa": (r.get("validity_comment") or "").strip(),
                "agent1_confidence": (r.get("agent1_confidence") or "").strip(),
                "confidence_score": (r.get("confidence_score") or "").strip(),
                "waste_bbox": (r.get("waste_bbox") or "").strip(),
                "selected_frame_name": dfj.get("selected_frame_name", ""),
                "evidence_summary": dfj.get("evidence_summary", ""),
                "label_source": "prod_pull_picam001",
                "source_campaign": "47-picam001-model-migration",
                "source_detection_id": det_id,
                "coalesced": len(refs) > 1,
                "coalesced_with": [x for x in refs if x != ref],
                "frame_count": len(frame_rel),
                "frames": frame_rel,
                "_edir": edir,
            })
            stats[cat] += 1

    print(f"events to write: {sum(stats.values())} {dict(stats)}")
    print(f"missing df json: {missing_df} | missing event manifests: {missing_manifest}")
    print(f"download jobs: {len(jobs)} frames")
    if not apply:
        print("DRY-RUN (use --apply to download + write)")
        return

    for ev in events:
        ev["_edir"].mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        ok = sum(ex.map(dl, jobs))
    print(f"frames downloaded OK: {ok}/{len(jobs)} (miss {len(jobs)-ok})")

    for ev in events:
        edir = ev.pop("_edir")
        # keep only frames that actually landed on disk (>1KB), preserve order
        present = [rel for rel in ev["frames"] if (ROOT / "data" / "datasets" / "official" / rel).exists()]
        ev["frames"] = present
        ev["frame_count"] = len(present)
        if not present:
            continue
        (edir.parent / "label.json").write_text(
            json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"labels written for {sum(stats.values())} events -> {CAM}")


if __name__ == "__main__":
    main()
