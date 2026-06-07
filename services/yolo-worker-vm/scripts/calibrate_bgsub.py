#!/usr/bin/env python3
"""Calibrate the BGSUB pre-filter for a given camera (device_id).

Reads N baseline frames from a directory (cena vazia, sem ocorrência) and
persists them as a single .npz to STATE_DIR/bgsub_models/{device_id}.npz.

At runtime, worker.bgsub_filter rebuilds the MOG2 background model from these
frames on first use. This avoids OpenCV's non-portable serialization of the
MOG2 internal state.

USAGE
-----

    python -m scripts.calibrate_bgsub \\
        --device-id esp32_001 \\
        --frames-dir /path/to/baseline/day \\
        [--n-frames 80] \\
        [--output /app/state/bgsub_models/esp32_001.npz] \\
        [--mix-night /path/to/baseline/night]

By default the script picks N frames evenly spaced over the input directory.
If --mix-night is given, half the frames come from each (light variation).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np


def _pick_evenly(frames: list[Path], n: int) -> list[Path]:
    if len(frames) <= n:
        return frames
    step = len(frames) / n
    return [frames[int(i * step)] for i in range(n)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True,
                        help="Device id (e.g. esp32_001). Used to name the output file.")
    parser.add_argument("--frames-dir", required=True, type=Path,
                        help="Directory with baseline JPGs (empty-scene frames).")
    parser.add_argument("--mix-night", type=Path, default=None,
                        help="Optional second directory; half the frames come from each.")
    parser.add_argument("--n-frames", type=int, default=80,
                        help="Total frames to use (default: 80).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output .npz path (default: $STATE_DIR/bgsub_models/{device_id}.npz).")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing output file without prompting.")
    args = parser.parse_args()

    # Resolve output path.
    if args.output is None:
        state_dir = os.environ.get("STATE_DIR", "/app/state")
        out_path = Path(state_dir) / "bgsub_models" / f"{args.device_id}.npz"
    else:
        out_path = args.output

    if out_path.exists() and not args.force:
        print(f"ERR: {out_path} already exists. Use --force to overwrite.",
              file=sys.stderr)
        return 2

    # Collect frames.
    if not args.frames_dir.is_dir():
        print(f"ERR: {args.frames_dir} is not a directory.", file=sys.stderr)
        return 2
    day_frames = sorted(args.frames_dir.glob("*.jpg"))
    if not day_frames:
        print(f"ERR: no .jpg files in {args.frames_dir}", file=sys.stderr)
        return 2

    if args.mix_night and args.mix_night.is_dir():
        night_frames = sorted(args.mix_night.glob("*.jpg"))
        half = args.n_frames // 2
        picked = _pick_evenly(day_frames, half) + _pick_evenly(night_frames, args.n_frames - half)
    else:
        picked = _pick_evenly(day_frames, args.n_frames)

    print(f"Calibrating bgsub for {args.device_id}")
    print(f"  frames-dir: {args.frames_dir} ({len(day_frames)} JPGs)")
    if args.mix_night:
        print(f"  mix-night:  {args.mix_night} ({len(night_frames)} JPGs)")
    print(f"  picked:     {len(picked)} frames")
    print(f"  output:     {out_path}")

    # Load and stack.
    arrays = []
    for fp in picked:
        img = cv2.imread(str(fp))
        if img is None:
            print(f"  WARN: failed to read {fp}", file=sys.stderr)
            continue
        arrays.append(img)

    if not arrays:
        print("ERR: no readable frames", file=sys.stderr)
        return 2

    # Verify all same shape.
    shapes = {a.shape for a in arrays}
    if len(shapes) > 1:
        print(f"ERR: frames have inconsistent shapes: {shapes}", file=sys.stderr)
        return 2

    stack = np.stack(arrays, axis=0)
    print(f"  stack shape: {stack.shape} dtype={stack.dtype}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(str(out_path), frames=stack)
    size_mb = out_path.stat().st_size / 1e6
    print(f"  saved: {out_path} ({size_mb:.2f} MB)")

    # Verify it loads back.
    archive = np.load(str(out_path))
    assert archive["frames"].shape == stack.shape, "round-trip mismatch"
    print("OK — calibration persisted.")
    print()
    print("Next steps:")
    print(f"  1. Update DB: UPDATE cameras SET bgsub_calibrated_at = NOW() WHERE device_id = '{args.device_id}';")
    print(f"  2. Ensure pile_zone_polygon is set for this camera.")
    print(f"  3. Set BGSUB_PREFILTER_ENABLED=true in the worker environment.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
