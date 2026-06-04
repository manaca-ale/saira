#!/usr/bin/env python3
"""Weekly recalibration of the BGSUB baseline for frozen-baseline cameras.

Cameras in BGSUB_ADAPTIVE_DISABLE_DEVICES run a STATIC (non-adaptive) MOG2
baseline to avoid adaptive drift (see config + camp 33). A static baseline,
left untouched, slowly desyncs from seasonal lighting. This module rebuilds it
periodically from recent empty-scene frames — the same `sem_ocorrencia` archive
the worker files no-disposal windows into — and atomically swaps the .npz.

Flow (per device in BGSUB_ADAPTIVE_DISABLE_DEVICES):
  1. Resolve the most recent `uploads/{device}/sem_ocorrencia/YYYY/MM/DD` dir.
  2. Pick N evenly-spaced frames (consistent shape).
  3. Stack -> write {device}.npz.tmp -> back up old to .bak -> atomic rename.
  4. Append a line to {STATE_DIR}/bgsub_models/recalibrate_log.jsonl.

Fail-safe: any device error is logged and skipped; others continue. The npz
format matches scripts/calibrate_bgsub.py (single `frames` array), so
worker.bgsub_filter rebuilds the MOG2 on next load. The cron wrapper restarts
the worker so the fresh baseline takes effect (the in-memory cache is not
hot-reloaded).

Run:  python -m worker.recalibrate_bgsub
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from . import config


def _pick_evenly(frames: list[Path], n: int) -> list[Path]:
    if len(frames) <= n:
        return frames
    step = len(frames) / n
    return [frames[int(i * step)] for i in range(n)]


def _latest_semocorrencia_dir(device_id: str) -> Path | None:
    """Deepest YYYY/MM/DD dir under uploads/{device}/sem_ocorrencia with JPGs."""
    root = Path(config.UPLOAD_DIR) / device_id / "sem_ocorrencia"
    if not root.is_dir():
        return None
    # Day dirs are YYYY/MM/DD — lexicographic sort == chronological.
    day_dirs = sorted(
        (p for p in root.glob("*/*/*") if p.is_dir()),
        reverse=True,
    )
    for d in day_dirs:
        if any(d.glob("*.jpg")):
            return d
    return None


def recalibrate_device(device_id: str, n_frames: int = 120) -> dict:
    out = Path(config.BGSUB_MODELS_DIR) / f"{device_id}.npz"
    src_dir = _latest_semocorrencia_dir(device_id)
    rec: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "device_id": device_id,
        "ok": False,
    }
    if src_dir is None:
        rec["error"] = "no sem_ocorrencia frames found"
        return rec
    frames = sorted(src_dir.glob("*.jpg"))
    picked = _pick_evenly(frames, n_frames)
    arrays = []
    for fp in picked:
        img = cv2.imread(str(fp))
        if img is not None:
            arrays.append(img)
    if not arrays:
        rec["error"] = "no readable frames"
        return rec
    shapes = {a.shape for a in arrays}
    if len(shapes) > 1:
        # Keep the majority shape only (camera resolution should be stable).
        from collections import Counter
        common = Counter(a.shape for a in arrays).most_common(1)[0][0]
        arrays = [a for a in arrays if a.shape == common]
    stack = np.stack(arrays, axis=0)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    # Write via file handle: np.savez_compressed appends ".npz" to string paths
    # that don't end in ".npz", which would break the atomic rename.
    with tmp.open("wb") as fh:
        np.savez_compressed(fh, frames=stack)
    if out.exists():
        bak = out.with_suffix(".npz.bak")
        bak.unlink(missing_ok=True)
        out.replace(bak)
    tmp.replace(out)

    rec.update({
        "ok": True,
        "source_dir": str(src_dir),
        "n_frames": int(stack.shape[0]),
        "shape": list(stack.shape),
        "output": str(out),
    })
    return rec


def main() -> int:
    devices = sorted(config.BGSUB_ADAPTIVE_DISABLE_DEVICES)
    if not devices:
        print("recalibrate_bgsub: BGSUB_ADAPTIVE_DISABLE_DEVICES empty — nothing to do.")
        return 0
    log_path = Path(config.BGSUB_MODELS_DIR) / "recalibrate_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rc = 0
    for dev in devices:
        try:
            rec = recalibrate_device(dev)
        except Exception as exc:  # noqa: BLE001
            rec = {"ts": datetime.now(timezone.utc).isoformat(), "device_id": dev,
                   "ok": False, "error": repr(exc)}
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        status = "OK" if rec.get("ok") else f"FAIL ({rec.get('error')})"
        print(f"  {dev}: {status}"
              + (f" n={rec.get('n_frames')} src={rec.get('source_dir')}" if rec.get("ok") else ""),
              flush=True)
        if not rec.get("ok"):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
