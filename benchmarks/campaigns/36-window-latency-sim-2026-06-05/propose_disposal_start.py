#!/usr/bin/env python3
"""Camp 36 Phase 0a — auto-propose disposal_start (free CV onset) + contact sheets.

For each positive event:
  - Estimate a clean background from the first frames.
  - Score each frame by foreground change in the lower (ground) region.
  - Propose disposal_start = onset of sustained change.
  - Render a contact sheet (all frames, labeled idx + HH:MM:SS) with the proposed
    frame highlighted ORANGE and, for the 2 known anchors, the ground-truth GREEN.
  - Write labels.csv for the operator to confirm/correct.

No Gemini calls. Run from repo root:
  python -X utf8 benchmarks/campaigns/36-window-latency-sim-2026-06-05/propose_disposal_start.py
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CAMPAIGN = Path(__file__).resolve().parent
CORPUS = CAMPAIGN / "corpus" / "positives"
SHEETS = CAMPAIGN / "corpus" / "contact_sheets"
SHEETS.mkdir(parents=True, exist_ok=True)

# Known ground-truth disposal_start (BRT HH:MM:SS) from manual user labels (anchors).
ANCHORS = {
    "a5a72209-6f36-44c2-b3b2-69dab4445103": "20:44:49",  # Arruda
    "c9c2c83e-b5e3-495c-99b7-93ef0b387c63": "19:32:44",  # Imbiribeira
}

THUMB_W, THUMB_H = 192, 108
COLS = 6
PROC_W, PROC_H = 96, 54  # analysis resolution


def _load_gray(path: Path) -> np.ndarray:
    img = Image.open(path).convert("L").resize((PROC_W, PROC_H))
    return np.asarray(img, dtype=np.float32)


def cv_onset(frame_paths: list[Path]) -> int:
    """Propose disposal_start by anchoring on the END state.

    A deposited object persists to the end of the clip. We find WHERE litter ends up
    (final-state footprint vs clean background) and then the first frame where that
    footprint starts getting filled. This is robust to subtle dumps (small bags) and
    to transient passing motion that does not leave persistent material.
    """
    n = len(frame_paths)
    if n < 3:
        return 0
    grays = [_load_gray(p) for p in frame_paths]
    lower = slice(int(PROC_H * 0.30), PROC_H)  # ground region (drop sky/top)
    g = np.stack([x[lower] for x in grays])     # (n, h, w)
    k = max(3, n // 6)
    bg = np.median(g[:k], axis=0)
    final = np.median(g[-k:], axis=0)

    # footprint = pixels that are persistently different at the end (the deposited litter)
    footprint = np.abs(final - bg) > 22
    if footprint.sum() < 8:                     # near-empty: relax threshold
        footprint = np.abs(final - bg) > 12
    if footprint.sum() < 4:                     # truly no end-state change: fall back
        diff = (np.abs(g - bg) > 25).reshape(n, -1).mean(axis=1)
        return int(np.argmax(diff))

    # occ[i] = fraction of the final litter footprint already present at frame i
    changed = np.abs(g - bg) > 22               # (n, h, w)
    fp = footprint[None, :, :]
    occ = (changed & fp).reshape(n, -1).sum(axis=1) / max(1, footprint.sum())

    # onset = first frame reaching half the final footprint, sustained for 2 frames
    target = 0.5
    for i in range(n - 1):
        if occ[i] >= target and occ[i + 1] >= target * 0.7:
            return i
    # fallback: steepest rise in occupancy
    return int(np.argmax(np.diff(occ))) if n > 1 else 0


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def contact_sheet(eid: str, meta: dict, frame_paths: list[Path],
                  proposed_idx: int, anchor_idx: int | None) -> Path:
    n = len(frame_paths)
    rows = (n + COLS - 1) // COLS
    pad, label_h, header_h = 4, 16, 40
    cell_w, cell_h = THUMB_W + 2 * pad, THUMB_H + label_h + 2 * pad
    W = COLS * cell_w
    H = header_h + rows * cell_h
    sheet = Image.new("RGB", (W, H), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    f = _font(11)
    fh = _font(14)
    hdr = (f"{meta['bairro']}  {eid[:8]}  n={n}  span={meta['span_seconds']:.0f}s  "
           f"{meta['db_timestamp']}  [{meta['waste_type']}]  "
           f"PROPOSED idx={proposed_idx} ({meta['frames'][proposed_idx]['ts']})")
    draw.text((6, 12), hdr, fill=(230, 230, 230), font=fh)

    # persistent-change overlay: highlight pixels where deposited material ends up
    ov_grays = [_load_gray(p) for p in frame_paths]
    gg = np.stack(ov_grays)
    kk = max(3, n // 6)
    ov_bg = np.median(gg[:kk], axis=0)
    ov_final = np.median(gg[-kk:], axis=0)
    footprint = np.abs(ov_final - ov_bg) > 18

    frames = meta["frames"]
    for i, p in enumerate(frame_paths):
        r, c = divmod(i, COLS)
        x0 = c * cell_w + pad
        y0 = header_h + r * cell_h + pad
        try:
            thumb = Image.open(p).convert("RGB").resize((THUMB_W, THUMB_H))
        except Exception:
            thumb = Image.new("RGB", (THUMB_W, THUMB_H), (60, 0, 0))
        # tint persistent new material red so the eye finds the deposit onset
        mask = (np.abs(ov_grays[i] - ov_bg) > 22) & footprint
        if mask.any():
            m_img = Image.fromarray((mask * 255).astype(np.uint8)).resize(
                (THUMB_W, THUMB_H), Image.NEAREST)
            red = Image.new("RGB", (THUMB_W, THUMB_H), (255, 30, 30))
            thumb = Image.composite(Image.blend(thumb, red, 0.45), thumb, m_img)
        sheet.paste(thumb, (x0, y0))
        border = None
        if i == proposed_idx:
            border = (255, 140, 0)   # orange = CV proposal
        if anchor_idx is not None and i == anchor_idx:
            border = (0, 220, 0)     # green = ground truth (anchors)
        if border:
            for w in range(3):
                draw.rectangle([x0 - w, y0 - w, x0 + THUMB_W + w, y0 + THUMB_H + w],
                               outline=border)
        lbl = f"{i}  {frames[i]['ts']}"
        draw.text((x0, y0 + THUMB_H + 1), lbl, fill=(190, 190, 190), font=f)

    out = SHEETS / f"{meta['bairro']}_{eid[:8]}.png"
    sheet.save(out)
    return out


def nearest_idx(meta: dict, hhmmss: str) -> int:
    target = datetime.strptime(meta["db_timestamp"][:11] + hhmmss.replace(":", "-"),
                               "%Y-%m-%d_%H-%M-%S").timestamp()
    diffs = [abs(fr["epoch"] - target) for fr in meta["frames"]]
    return int(np.argmin(diffs))


def main() -> int:
    event_dirs = sorted([d for d in CORPUS.iterdir() if d.is_dir()],
                        key=lambda d: d.name)
    rows_out = []
    for d in event_dirs:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        frame_paths = [d / "frames" / fr["frame_name"] for fr in meta["frames"]]
        proposed_idx = cv_onset(frame_paths)
        anchor_idx = None
        anchor_ts = ANCHORS.get(meta["event_id"])
        if anchor_ts:
            anchor_idx = nearest_idx(meta, anchor_ts)

        prop = meta["frames"][proposed_idx]
        # persist proposal into meta (source flags whether anchor or cv)
        if anchor_idx is not None:
            meta["disposal_start_frame"] = meta["frames"][anchor_idx]["frame_name"]
            meta["disposal_start_ts"] = meta["frames"][anchor_idx]["ts"]
            meta["disposal_start_source"] = "anchor_manual"
        else:
            meta["disposal_start_frame"] = prop["frame_name"]
            meta["disposal_start_ts"] = prop["ts"]
            meta["disposal_start_source"] = "auto_cv_onset"
        (d / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                     encoding="utf-8")

        sheet = contact_sheet(meta["event_id"], meta, frame_paths, proposed_idx, anchor_idx)
        delta = ""
        if anchor_idx is not None:
            delta = f"{(prop['epoch'] - meta['frames'][anchor_idx]['epoch']):+.0f}s"
        rows_out.append({
            "event_id": meta["event_id"],
            "bairro": meta["bairro"],
            "n_frames": meta["n_frames"],
            "span_s": meta["span_seconds"],
            "proposed_idx": proposed_idx,
            "proposed_ts": prop["ts"],
            "proposed_frame": prop["frame_name"],
            "anchor_ts": anchor_ts or "",
            "cv_vs_anchor": delta,
            "confirmed_idx": "",   # <- operator fills this (leave blank = accept proposal)
            "sheet": sheet.name,
        })
        tag = f"  ANCHOR={anchor_ts} cvΔ={delta}" if anchor_ts else ""
        print(f"{meta['bairro']:12} {meta['event_id'][:8]} n={meta['n_frames']:3} "
              f"proposed idx={proposed_idx:2} @ {prop['ts']}{tag}")

    labels = CAMPAIGN / "corpus" / "labels.csv"
    with labels.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"\nContact sheets -> {SHEETS}")
    print(f"Labels (edit 'confirmed_idx' to correct) -> {labels}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
