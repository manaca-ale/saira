"""Background-subtraction pre-filter for the Gemini cascade gate.

Spike (tools/spike_bgsub_filter.py) validated on the official dataset:
- Threshold persistence >= 1000 px filters 73% of baseline (empty-scene) windows
  with **zero TP loss** (14/14).
- Bgsub does NOT distinguish TP from FP-trânsito (both have person near pile
  generating large visual change). The win is upstream: skip Gemini gate calls
  for genuinely-empty windows.

This module:
1. Caches MOG2 background models per device_id (lazy-loaded from disk).
2. Caches the binary mask of the pile zone per camera (built from the
   `pile_zone_polygon` JSONB column).
3. Exposes `evaluate(frame_paths, device_id, camera)` returning a `FilterResult`
   indicating whether the window should be suppressed.

All failure modes return `should_suppress=False` (fail-open). The caller MUST
still respect the global `BGSUB_PREFILTER_ENABLED` flag from config.
"""
from __future__ import annotations

import collections
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from . import config

logger = logging.getLogger(__name__)

# Frame reference dimensions used when polygons were defined (1280x720).
# We still build a mask matching the actual frame size at runtime.
_FRAME_REF_SHAPE = (720, 1280)


@dataclass
class FilterResult:
    """Outcome of evaluating a window."""

    should_suppress: bool       # True = filter out, don't call Gemini
    reason: str                  # filtered | skipped_no_polygon | skipped_no_model | skipped_disabled | error | passed
    persistence: float = 0.0     # pixels with FG in >=60% of frames, within zone
    n_frames_ok: int = 0
    n_frames_total: int = 0


class _ModelCache:
    """In-memory cache for MOG2 models and pile-zone masks."""

    def __init__(self) -> None:
        self._mog2: dict[str, cv2.BackgroundSubtractor] = {}
        self._masks: dict[str, np.ndarray] = {}
        # Rolling buffer of frames per camera (adaptive baseline).
        # Sized to BGSUB_MOG2_HISTORY so persisting matches calibrate output shape.
        self._frame_buffer: dict[str, collections.deque] = {}
        self._updates_since_save: dict[str, int] = {}

    def get_mog2(self, device_id: str) -> Optional[cv2.BackgroundSubtractor]:
        """Get (or build) the MOG2 model for this device.

        Calibration persists a stack of N "baseline" frames as a single npz
        archive (see scripts/calibrate_bgsub.py). On first use we read the
        archive and rebuild the MOG2 by applying the frames. This avoids
        OpenCV's non-portable FileStorage serialization of MOG2 state.
        """
        if device_id in self._mog2:
            return self._mog2[device_id]
        path = Path(config.BGSUB_MODELS_DIR) / f"{device_id}.npz"
        if not path.exists():
            return None
        try:
            archive = np.load(str(path))
            if "frames" not in archive.files:
                logger.warning("bgsub: invalid npz at %s (missing 'frames')", path)
                return None
            frames = archive["frames"]  # shape (N, H, W, 3) uint8
            if frames.ndim != 4 or frames.shape[-1] != 3:
                logger.warning("bgsub: invalid npz shape at %s: %s", path, frames.shape)
                return None
            bg = cv2.createBackgroundSubtractorMOG2(
                history=int(config.BGSUB_MOG2_HISTORY),
                varThreshold=float(config.BGSUB_MOG2_VAR_THRESHOLD),
                detectShadows=True,
            )
            for i in range(frames.shape[0]):
                bg.apply(frames[i])
            self._mog2[device_id] = bg
            # Seed rolling buffer with the baseline frames so future
            # persistence keeps the same shape and history.
            buf = collections.deque(maxlen=int(config.BGSUB_MOG2_HISTORY))
            for i in range(min(int(config.BGSUB_MOG2_HISTORY), frames.shape[0])):
                buf.append(frames[i])
            self._frame_buffer[device_id] = buf
            self._updates_since_save[device_id] = 0
            logger.info(
                "bgsub: rebuilt MOG2 for %s from %d baseline frames in %s",
                device_id, frames.shape[0], path,
            )
            return bg
        except Exception as exc:  # noqa: BLE001
            logger.warning("bgsub: failed to load baseline frames %s: %s", path, exc)
            return None

    def get_mask(self, device_id: str, polygon_json: Any) -> Optional[np.ndarray]:
        """Build (and cache) a binary mask from the JSONB polygon column."""
        if device_id in self._masks:
            return self._masks[device_id]
        try:
            polygons = polygon_json
            if isinstance(polygons, str):
                polygons = json.loads(polygons)
            if not polygons or not isinstance(polygons, list):
                return None
            mask = np.zeros(_FRAME_REF_SHAPE, dtype=np.uint8)
            for poly in polygons:
                pts = np.array(poly, dtype=np.int32)
                if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 3:
                    logger.warning("bgsub: invalid polygon shape for %s: %s", device_id, pts.shape)
                    return None
                cv2.fillPoly(mask, [pts], 255)
            self._masks[device_id] = mask
            logger.info("bgsub: built zone mask for %s (%d polygons)", device_id, len(polygons))
            return mask
        except Exception as exc:  # noqa: BLE001
            logger.warning("bgsub: failed to build mask for %s: %s", device_id, exc)
            return None

    def invalidate(self, device_id: Optional[str] = None) -> None:
        """Clear cache (used by tests or after recalibration)."""
        if device_id is None:
            self._mog2.clear()
            self._masks.clear()
            self._frame_buffer.clear()
            self._updates_since_save.clear()
        else:
            self._mog2.pop(device_id, None)
            self._masks.pop(device_id, None)
            self._frame_buffer.pop(device_id, None)
            self._updates_since_save.pop(device_id, None)


_cache = _ModelCache()


def invalidate_cache(device_id: Optional[str] = None) -> None:
    _cache.invalidate(device_id)


def evaluate(
    frame_paths: list[Path],
    device_id: str,
    pile_zone_polygon: Any,
) -> FilterResult:
    """Decide whether to suppress this window (no Gemini call).

    Args:
        frame_paths: list of N frame paths in chronological order.
        device_id: e.g. "esp32_001"; used to locate MOG2 file.
        pile_zone_polygon: the JSONB value from `cameras.pile_zone_polygon`
            (list of polygons of [x, y] points), or None.

    Returns FilterResult. On any failure → should_suppress=False (fail-open).
    """
    if not config.BGSUB_PREFILTER_ENABLED:
        return FilterResult(should_suppress=False, reason="skipped_disabled")
    if not frame_paths:
        return FilterResult(should_suppress=False, reason="skipped_disabled")

    if not pile_zone_polygon:
        return FilterResult(should_suppress=False, reason="skipped_no_polygon")

    mask = _cache.get_mask(device_id, pile_zone_polygon)
    if mask is None:
        return FilterResult(should_suppress=False, reason="skipped_no_polygon")

    bg = _cache.get_mog2(device_id)
    if bg is None:
        return FilterResult(should_suppress=False, reason="skipped_no_model")

    try:
        morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        min_active = int(config.BGSUB_MIN_PX_ACTIVE)
        fg_masks: list[np.ndarray] = []
        for fp in frame_paths:
            img = cv2.imread(str(fp))
            if img is None:
                continue
            # Resize mask if frame shape differs from reference.
            if img.shape[:2] != mask.shape:
                resized_mask = cv2.resize(
                    mask, (img.shape[1], img.shape[0]),
                    interpolation=cv2.INTER_NEAREST,
                )
            else:
                resized_mask = mask

            fg = bg.apply(img, learningRate=0.0)
            # MOG2 with detectShadows=True marks shadows as 127; keep only hard FG.
            fg = (fg > 200).astype(np.uint8) * 255
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, morph_kernel)
            fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, morph_kernel)
            in_zone = cv2.bitwise_and(fg, resized_mask)
            # Only count if the frame has at least min_active pixels in zone.
            if int(np.count_nonzero(in_zone)) >= min_active:
                fg_masks.append(in_zone)
            else:
                fg_masks.append(np.zeros_like(in_zone))

        n_total = len(fg_masks)
        n_ok = sum(1 for m in fg_masks if np.any(m))
        if n_total == 0:
            return FilterResult(should_suppress=False, reason="error")

        # Persistence: pixels marked FG in >= MIN_PERSISTENCE_FRAMES fraction of frames.
        stack = np.stack(fg_masks, axis=0) > 0
        votes = stack.sum(axis=0)
        min_frames = max(1, int(round(config.BGSUB_MIN_PERSISTENCE_FRAMES * n_total)))
        persistence_mask = votes >= min_frames
        persistence_px = int(np.count_nonzero(persistence_mask))

        threshold = int(config.BGSUB_PERSISTENCE_THRESHOLD)
        if persistence_px < threshold:
            return FilterResult(
                should_suppress=True,
                reason="filtered",
                persistence=float(persistence_px),
                n_frames_ok=n_ok,
                n_frames_total=n_total,
            )

        return FilterResult(
            should_suppress=False,
            reason="passed",
            persistence=float(persistence_px),
            n_frames_ok=n_ok,
            n_frames_total=n_total,
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning("bgsub: evaluate failed for %s: %s", device_id, exc, exc_info=True)
        return FilterResult(should_suppress=False, reason="error")


# =============================================================================
# Adaptive baseline — Gemini-supervised MOG2 update.
# =============================================================================
@dataclass
class AdaptiveUpdateResult:
    """Outcome of an adaptive-baseline update attempt."""

    applied: bool
    reason: str         # applied | skipped_disabled | skipped_low_confidence
                        # | skipped_no_model | persisted | error
    n_frames: int = 0


def update_baseline_with_frames(
    device_id: str,
    frame_paths: list[Path],
    gate_confidence: int,
    pile_zone_polygon: Any = None,  # noqa: ARG001 — accepted for API symmetry
) -> AdaptiveUpdateResult:
    """Absorb frames into the MOG2 baseline IF the Gemini gate confirmed the
    scene as "no new litter" with high confidence.

    Call this AFTER the gate returns. Caller-side check: only invoke when
    gate_report.new_litter_detected == False.

    Args:
        device_id: e.g. "esp32_001"; must match the npz/cache key.
        frame_paths: same frames passed to `evaluate()` for this window.
        gate_confidence: int 0-100, from the Gemini gate report.
        pile_zone_polygon: unused (kept for caller convenience).

    Returns AdaptiveUpdateResult; never raises.
    """
    if not config.BGSUB_ADAPTIVE_ENABLED:
        return AdaptiveUpdateResult(applied=False, reason="skipped_disabled")
    if gate_confidence < int(config.BGSUB_ADAPTIVE_MIN_CONFIDENCE):
        return AdaptiveUpdateResult(applied=False, reason="skipped_low_confidence")

    bg = _cache.get_mog2(device_id)
    if bg is None:
        return AdaptiveUpdateResult(applied=False, reason="skipped_no_model")

    lr = float(config.BGSUB_ADAPTIVE_LEARNING_RATE)
    buf = _cache._frame_buffer.setdefault(
        device_id, collections.deque(maxlen=int(config.BGSUB_MOG2_HISTORY)),
    )

    n_applied = 0
    try:
        for fp in frame_paths:
            img = cv2.imread(str(fp))
            if img is None:
                continue
            bg.apply(img, learningRate=lr)
            buf.append(img)
            n_applied += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("bgsub: adaptive update failed for %s: %s", device_id, exc, exc_info=True)
        return AdaptiveUpdateResult(applied=False, reason="error", n_frames=n_applied)

    if n_applied == 0:
        return AdaptiveUpdateResult(applied=False, reason="error")

    _cache._updates_since_save[device_id] = (
        _cache._updates_since_save.get(device_id, 0) + n_applied
    )

    persisted = False
    if _cache._updates_since_save[device_id] >= int(config.BGSUB_ADAPTIVE_SAVE_EVERY_N):
        persisted = _persist_frames_to_npz(device_id, list(buf))
        if persisted:
            _cache._updates_since_save[device_id] = 0

    logger.info(
        "bgsub: adaptive update applied for %s (frames=%d, lr=%.3f, persisted=%s)",
        device_id, n_applied, lr, persisted,
    )
    return AdaptiveUpdateResult(
        applied=True,
        reason="persisted" if persisted else "applied",
        n_frames=n_applied,
    )


def _persist_frames_to_npz(device_id: str, frames_list: list[np.ndarray]) -> bool:
    """Save the rolling frame buffer as a fresh npz (atomic via .tmp rename).

    On next worker restart, get_mog2() will rebuild from this npz, preserving
    the adaptation across restarts.
    """
    if not frames_list:
        return False
    try:
        models_dir = Path(config.BGSUB_MODELS_DIR)
        models_dir.mkdir(parents=True, exist_ok=True)
        final_path = models_dir / f"{device_id}.npz"
        # np.savez_compressed appends ".npz" if missing — so we use
        # "<device>.tmp.npz" (ends with .npz, won't get duplicated).
        tmp_path = models_dir / f"{device_id}.tmp.npz"
        arr = np.stack(frames_list, axis=0)
        np.savez_compressed(str(tmp_path), frames=arr)
        tmp_path.replace(final_path)
        logger.info(
            "bgsub: persisted %d frames to %s (adaptive checkpoint)",
            len(frames_list), final_path,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("bgsub: persist failed for %s: %s", device_id, exc, exc_info=True)
        return False
