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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np

from . import config

# Capture-time bucketing for --mix-night uses local Brazil time (frames are
# named/captured in BRT and the night window is defined in local hours).
_BRT = ZoneInfo("America/Sao_Paulo")
_HHMMSS_RE = re.compile(r"^(\d{2})[-_:](\d{2})[-_:](\d{2})")


def _pick_evenly(frames: list[Path], n: int) -> list[Path]:
    if len(frames) <= n:
        return frames
    step = len(frames) / n
    return [frames[int(i * step)] for i in range(n)]


def _hour_of(path: Path) -> int | None:
    """Best-effort capture hour (0-23, BRT). Prefer the HH-MM-SS filename;
    fall back to the file mtime converted to BRT (TZ-correct regardless of the
    container's TZ)."""
    m = _HHMMSS_RE.match(path.stem)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return h
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, _BRT).hour
    except OSError:
        return None


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


def _recent_semocorrencia_dirs(device_id: str, max_days: int) -> list[Path]:
    """Up to `max_days` most-recent YYYY/MM/DD dirs (with JPGs), newest first."""
    root = Path(config.UPLOAD_DIR) / device_id / "sem_ocorrencia"
    if not root.is_dir():
        return []
    day_dirs = sorted((p for p in root.glob("*/*/*") if p.is_dir()), reverse=True)
    out: list[Path] = []
    for d in day_dirs:
        if any(d.glob("*.jpg")):
            out.append(d)
        if len(out) >= max_days:
            break
    return out


def _pick_mixed_night(
    device_id: str, n_frames: int, *, night_hours: set[int],
    night_fraction: float, lookback_days: int,
) -> tuple[list[Path], dict]:
    """Pick frames across recent days, forcing `night_fraction` from `night_hours`.

    Falls back gracefully: if the night pool is empty it behaves like the legacy
    even pick over whatever frames exist. Returns (paths, meta)."""
    dirs = _recent_semocorrencia_dirs(device_id, lookback_days)
    all_frames = sorted(f for d in dirs for f in d.glob("*.jpg"))
    night: list[Path] = []
    day: list[Path] = []
    for f in all_frames:
        h = _hour_of(f)
        (night if (h is not None and h in night_hours) else day).append(f)

    n_night_target = int(round(n_frames * night_fraction))
    picked_night = _pick_evenly(night, min(n_night_target, len(night)))
    remaining = n_frames - len(picked_night)
    picked_day = _pick_evenly(day, min(remaining, len(day)))
    picked = sorted(set(picked_night) | set(picked_day))
    meta = {
        "mix_night": True,
        "lookback_days": lookback_days,
        "night_hours": sorted(night_hours),
        "n_days_scanned": len(dirs),
        "n_night_available": len(night),
        "n_day_available": len(day),
        "n_night_picked": len(picked_night),
        "n_day_picked": len(picked_day),
    }
    return picked, meta


def recalibrate_device(device_id: str, n_frames: int = 120, *, mix_night: bool = False) -> dict:
    out = Path(config.BGSUB_MODELS_DIR) / f"{device_id}.npz"
    rec: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "device_id": device_id,
        "ok": False,
    }

    if mix_night:
        picked, mix_meta = _pick_mixed_night(
            device_id, n_frames,
            night_hours=config.BGSUB_RECAL_NIGHT_HOURS,
            night_fraction=config.BGSUB_RECAL_NIGHT_FRACTION,
            lookback_days=config.BGSUB_RECAL_LOOKBACK_DAYS,
        )
        rec.update(mix_meta)
        if not picked:
            rec["error"] = "no sem_ocorrencia frames found (mix-night)"
            return rec
        src_dir = None
    else:
        src_dir = _latest_semocorrencia_dir(device_id)
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
        "source_dir": str(src_dir) if src_dir is not None else "(mix-night, multi-day)",
        "n_frames": int(stack.shape[0]),
        "shape": list(stack.shape),
        "output": str(out),
    })
    return rec


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Recalibrate frozen BGSUB baselines.")
    parser.add_argument(
        "--mix-night", action="store_true",
        help="Force night-frame mixing for ALL frozen devices (overrides the "
             "per-device BGSUB_RECAL_MIX_NIGHT_DEVICES env).",
    )
    parser.add_argument(
        "--device", default=None,
        help="Recalibrate only this device_id (e.g. esp32_005) instead of the "
             "full frozen/clean-zone set. Used by the frequent re-anchor cron.",
    )
    args = parser.parse_args(argv)

    if args.device:
        devices = [args.device.strip().lower()]
    else:
        # Frozen-baseline cameras AND clean-zone-adaptive cameras both need a
        # periodic fresh baseline (the latter rarely absorbs on a chronic point,
        # so it would otherwise age out between recalibrations).
        devices = sorted(
            config.BGSUB_ADAPTIVE_DISABLE_DEVICES
            | config.BGSUB_ADAPTIVE_CLEAN_ZONE_ONLY_DEVICES
        )
    if not devices:
        print("recalibrate_bgsub: no frozen/clean-zone devices configured — nothing to do.")
        return 0
    log_path = Path(config.BGSUB_MODELS_DIR) / "recalibrate_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rc = 0
    for dev in devices:
        mix_night = args.mix_night or (dev in config.BGSUB_RECAL_MIX_NIGHT_DEVICES)
        try:
            rec = recalibrate_device(dev, mix_night=mix_night)
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
