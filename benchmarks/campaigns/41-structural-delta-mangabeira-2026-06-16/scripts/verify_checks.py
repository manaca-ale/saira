#!/usr/bin/env python3
"""Phase 1 verification: (A) visual before/after montages, (B) reproduce camp-20 proto.

(A) Saves viz/pair_<bucket>_<id>.jpg montages of before|after with the census-changed
    overlay, so we can eyeball whether 'before' is person-free and 'after' is settled.
(B) Reproduces the camp-20 pilezone_delta_proto metrics on the 4 cam_11 events that are
    present in our manifest (the 4 cam_10 ones need S3, unavailable locally), first-vs-last
    frame, camp-20 rectangle polygon, to confirm the structural metric still separates.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(r"c:\saira")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding="utf-8")
from census import census_hamming  # noqa: E402

CAMP = ROOT / "benchmarks" / "campaigns" / "41-structural-delta-mangabeira-2026-06-16"
LARGEN = ROOT / "benchmarks" / "campaigns" / "40-mangabeira-b3-fp-2026-06-16" / "largeN"
FRAMES24 = LARGEN / "frames24"
RES, VIZ = CAMP / "results", CAMP / "viz"

PILE_POLY = np.array([[461, 154], [704, 66], [939, 299], [617, 416]], dtype=np.int32)
# camp-20 used the OLD axis-aligned rectangle:
CAMP20_POLY = np.array([[480, 60], [920, 60], [920, 340], [480, 340]], dtype=np.int32)

# camp-20 cam_11 events present in our manifest (gt from pilezone_delta_proto.TEST)
CAMP20_CAM11 = [
    ("90c05405-10a3-4d14-923b-3ce8b683eded", "REJ", "13:41"),
    ("c4224caf-6cb9-48df-846d-b7ad0ea7d141", "REJ", "13:14"),
    ("8367f372-247b-42fd-886d-61bfc600b303", "CON", "12:46"),
    ("ae3d87cb-189c-4d80-b56e-d202d92b4e59", "CON", "12:03"),
]


def mask_for(poly, shape=(720, 1280)):
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [poly], 255)
    return m


def frames_of(eid):
    return sorted(FRAMES24.glob(f"{eid[:8]}__*.jpg"))


def montage_pairs():
    VIZ.mkdir(exist_ok=True)
    ba = {r["event_id"]: r for r in csv.DictReader((RES / "before_after.csv").open(encoding="utf-8"))}
    # sample 4 TP + 4 B3
    tp = [e for e, r in ba.items() if r["bucket"] == "TP"][:4]
    b3 = [e for e, r in ba.items() if r["bucket"] == "B3"][:4]
    mask = mask_for(PILE_POLY)
    for eid in tp + b3:
        r = ba[eid]
        bp, ap = FRAMES24 / r["before_frame"], FRAMES24 / r["after_frame"]
        ia, ib = cv2.imread(str(bp)), cv2.imread(str(ap))
        if ia is None or ib is None:
            continue
        gp = cv2.cvtColor(ia, cv2.COLOR_BGR2GRAY)
        gq = cv2.cvtColor(ib, cv2.COLOR_BGR2GRAY)
        ham = census_hamming(gp, gq)
        changed = ((ham >= 3) & (mask > 0)).astype(np.uint8) * 255
        overlay = ib.copy()
        overlay[changed > 0] = (0, 0, 255)
        ib2 = cv2.addWeighted(ib, 0.6, overlay, 0.4, 0)
        for im in (ia, ib2):
            cv2.polylines(im, [PILE_POLY], True, (0, 255, 0), 2)
        cv2.putText(ia, f"BEFORE {r['before_frame'][9:]}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(ib2, f"AFTER+census {r['after_frame'][9:]}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        combo = np.hstack([ia, ib2])
        out = VIZ / f"pair_{r['bucket']}_{eid[:8]}.jpg"
        cv2.imwrite(str(out), combo)
        print(f"  wrote {out.name}")


def camp20_metrics(ia, ib, mask):
    gray_a = cv2.cvtColor(ia, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(ib, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray_a, gray_b)
    area = int(np.count_nonzero(mask))
    changed_pct = float(np.count_nonzero(cv2.bitwise_and(diff, diff, mask=mask) > 25)) / area * 100
    ea, eb = cv2.Canny(gray_a, 60, 180), cv2.Canny(gray_b, 60, 180)
    eap = float(np.count_nonzero(cv2.bitwise_and(ea, ea, mask=mask))) / area * 100
    ebp = float(np.count_nonzero(cv2.bitwise_and(eb, eb, mask=mask))) / area * 100
    an = gray_a[mask > 0] - gray_a[mask > 0].mean()
    bn = gray_b[mask > 0] - gray_b[mask > 0].mean()
    den = float(np.sqrt((an * an).sum() * (bn * bn).sum()))
    ncc = float((an * bn).sum() / den) if den > 0 else 1.0
    return changed_pct, ebp - eap, ncc


def reproduce_camp20():
    print("\n=== Reproduce camp-20 proto on 4 cam_11 events (first-vs-last, camp20 poly) ===")
    mask = mask_for(CAMP20_POLY)
    res = []
    for eid, gt, descr in CAMP20_CAM11:
        fr = frames_of(eid)
        if len(fr) < 2:
            print(f"  {eid[:8]} {descr}: frames missing")
            continue
        ia, ib = cv2.imread(str(fr[0])), cv2.imread(str(fr[-1]))
        chg, edged, ncc = camp20_metrics(ia, ib, mask)
        res.append((eid, gt, descr, chg, edged, ncc))
        print(f"  {eid[:8]} {descr:<6s} gt={gt}  chg={chg:5.1f}%  edgeD={edged:+5.2f}  ncc={ncc:5.3f}")
    # camp-20 best rule was roughly changed_pct>3 / edge_delta>0.5 separating CON from REJ
    print("  rule changed_pct>3.0 :",
          {f"{e[:8]}": ("CON" if c > 3.0 else "REJ") + f"/gt={g}" for e, g, d, c, ed, n in res})


if __name__ == "__main__":
    montage_pairs()
    reproduce_camp20()
