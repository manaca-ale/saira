"""Background-subtraction pre-filter for the Gemini cascade gate.

Spike (tools/spike_bgsub_filter.py) validated on the official dataset:
- Threshold persistence >= 1000 px filters 73% of baseline (empty-scene) windows
  with **zero TP loss** (14/14).
- Bgsub does NOT distinguish TP from FP-trânsito (both have person near pile
  generating large visual change). The win is upstream: skip Gemini gate calls
  for genuinely-empty windows.

This module:
1. Caches MOG2 background models per device_id (lazy-loaded from disk).
   In **dual-rate mode** (config.BGSUB_DUAL_RATE_ENABLED), caches TWO models
   per camera (fast + slow) and combines as `static_fg = slow AND NOT fast`
   to isolate stationary objects from active traffic.
2. Caches the binary mask of the pile zone per camera (built from the
   `pile_zone_polygon` JSONB column).
3. Caches the polygon bounding box per camera. When BGSUB_BBOX_CROP_ENABLED,
   MOG2 only runs on the crop, saving 50-82% of CPU per frame.
4. Exposes `evaluate(frame_paths, device_id, camera)` returning a `FilterResult`
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
from typing import Any, Optional, Union

import cv2
import numpy as np

from . import config

logger = logging.getLogger(__name__)

# Frame reference dimensions used when polygons were defined (1280x720).
# We still build a mask matching the actual frame size at runtime.
_FRAME_REF_SHAPE = (720, 1280)

# Type alias: single-rate stores one BackgroundSubtractor; dual-rate stores
# a (fast, slow) tuple. The cache holds whatever matches current config mode.
_ModelEntry = Union[cv2.BackgroundSubtractor, tuple[cv2.BackgroundSubtractor, cv2.BackgroundSubtractor]]


@dataclass
class FilterResult:
    """Outcome of evaluating a window."""

    should_suppress: bool       # True = filter out, don't call Gemini
    reason: str                  # filtered | skipped_no_polygon | skipped_no_model | skipped_disabled | error | passed
    persistence: float = 0.0     # pixels with FG in >=mpf fraction of frames, within zone
    n_frames_ok: int = 0
    n_frames_total: int = 0
    mode: str = "single"         # "single" or "dual" — informational, for logs/metrics


# Persistent decision ledger (same pattern as detector_dinov2): one JSONL row per
# scored evaluation, in the models volume so the track record survives container
# recreate. Needed to validate per-camera tuning (e.g. esp32_005 shadow) — worker
# stdout does not survive and "passed" rows were previously invisible.
SHADOW_LEDGER_NAME = "shadow_decisions.jsonl"


def record_decision(
    *,
    gate_request_id: str,
    device_id: str,
    result: "FilterResult",
    shadow: bool,
    threshold: float,
    models_dir: Optional[str] = None,
) -> None:
    """Append one BGSUB decision to the persistent ledger (fail-safe).

    Records only scored evaluations (reason in filtered/passed); skipped_*/error
    rows carry no signal. Never raises — a ledger write must not break the
    pipeline.
    """
    if result.reason not in ("filtered", "passed"):
        return
    try:
        from datetime import datetime, timezone

        d = models_dir or config.BGSUB_MODELS_DIR
        Path(d).mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "gate_request_id": gate_request_id,
            "device_id": device_id,
            "should_suppress": bool(result.should_suppress),
            "shadow": bool(shadow),
            "reason": result.reason,
            "persistence": float(result.persistence),
            "n_frames_ok": int(result.n_frames_ok),
            "n_frames_total": int(result.n_frames_total),
            "threshold": float(threshold),
            "mode": result.mode,
        }
        with open(Path(d) / SHADOW_LEDGER_NAME, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("bgsub: failed to record ledger decision: %s", exc)


def _camera_attr(camera: Any, name: str, default: Any = None) -> Any:
    """Read an attribute or dict key from a camera-like object.

    Cameras can be passed as ORM objects (with attributes), dicts, or None.
    Returns default if the attribute is missing or its value is None.
    """
    if camera is None:
        return default
    if isinstance(camera, dict):
        val = camera.get(name)
    else:
        val = getattr(camera, name, None)
    return default if val is None else val


def _resolved_config(camera: Any) -> dict[str, Any]:
    """Resolve effective config values (per-camera overrides → env defaults)."""
    return {
        "lr_fast": float(_camera_attr(camera, "bgsub_lr_fast", config.BGSUB_LR_FAST)),
        "lr_slow": float(_camera_attr(camera, "bgsub_lr_slow", config.BGSUB_LR_SLOW)),
        "history_fast": int(_camera_attr(camera, "bgsub_mog2_history_fast", config.BGSUB_MOG2_HISTORY_FAST)),
        "history_slow": int(_camera_attr(camera, "bgsub_mog2_history_slow", config.BGSUB_MOG2_HISTORY_SLOW)),
        "persistence_threshold": int(_camera_attr(camera, "bgsub_persistence_threshold", config.BGSUB_PERSISTENCE_THRESHOLD)),
        "min_persistence_frames": float(_camera_attr(camera, "bgsub_min_persistence_frames", config.BGSUB_MIN_PERSISTENCE_FRAMES)),
        "min_px_active": int(_camera_attr(camera, "bgsub_min_px_active", config.BGSUB_MIN_PX_ACTIVE)),
        "history": int(config.BGSUB_MOG2_HISTORY),  # single-mode legacy
        "var_threshold": float(config.BGSUB_MOG2_VAR_THRESHOLD),
        "shadow_threshold": int(config.BGSUB_SHADOW_THRESHOLD),
        "lr_fast_adapt": float(config.BGSUB_LR_FAST_ADAPT),
        "lr_slow_adapt": float(config.BGSUB_LR_SLOW_ADAPT),
        "adaptive_lr": float(config.BGSUB_ADAPTIVE_LEARNING_RATE),
    }


class _ModelCache:
    """In-memory cache for MOG2 models, pile-zone masks, and bboxes."""

    def __init__(self) -> None:
        # _mog2 holds either a single BackgroundSubtractor or a (fast, slow)
        # tuple depending on the mode used when it was constructed.
        self._mog2: dict[str, _ModelEntry] = {}
        # Track the mode each cached entry was built for, so we rebuild if the
        # mode changes (e.g. operator flips DUAL_RATE_ENABLED at runtime).
        self._mode: dict[str, str] = {}
        self._masks: dict[str, np.ndarray] = {}  # full-frame polygon mask
        # bbox = (x, y, w, h) of the polygon's bounding rectangle, in the
        # 1280x720 reference frame. None when polygon is missing/invalid.
        self._bboxes: dict[str, Optional[tuple[int, int, int, int]]] = {}
        # Rolling buffer of frames per camera (adaptive baseline).
        self._frame_buffer: dict[str, collections.deque] = {}
        self._updates_since_save: dict[str, int] = {}

    def _current_mode(self) -> str:
        return "dual" if config.BGSUB_DUAL_RATE_ENABLED else "single"

    def get_models(self, device_id: str, cfg: dict[str, Any]) -> Optional[_ModelEntry]:
        """Get (or build) the MOG2 model(s) for this device.

        Calibration persists a stack of N "baseline" frames as a single npz
        archive (see scripts/calibrate_bgsub.py). On first use we read the
        archive and rebuild the MOG2(s) by applying the frames.

        Returns a single BackgroundSubtractor (single mode) or a tuple
        (fast, slow) (dual mode). Returns None on failure.
        """
        mode = self._current_mode()
        cached_mode = self._mode.get(device_id)
        if device_id in self._mog2 and cached_mode == mode:
            return self._mog2[device_id]
        # Mode changed (or first load) — rebuild from disk.
        if device_id in self._mog2 and cached_mode != mode:
            logger.info(
                "bgsub: mode changed for %s (%s → %s), rebuilding models",
                device_id, cached_mode, mode,
            )

        path = Path(config.BGSUB_MODELS_DIR) / f"{device_id}.npz"
        if not path.exists():
            return None
        try:
            archive = np.load(str(path))
            if "frames" not in archive.files:
                logger.warning("bgsub: invalid npz at %s (missing 'frames')", path)
                return None
            frames = archive["frames"]
            if frames.ndim != 4 or frames.shape[-1] != 3:
                logger.warning("bgsub: invalid npz shape at %s: %s", path, frames.shape)
                return None
            schema_version = int(archive["schema_version"]) if "schema_version" in archive.files else 1

            if mode == "dual":
                entry = self._build_dual_models(frames, cfg, schema_version)
            else:
                entry = self._build_single_model(frames, cfg)

            self._mog2[device_id] = entry
            self._mode[device_id] = mode
            # Seed rolling buffer with baseline frames so future persistence
            # keeps the same shape and history.
            history = cfg["history_fast"] if mode == "dual" else cfg["history"]
            buf = collections.deque(maxlen=int(history))
            for i in range(min(int(history), frames.shape[0])):
                buf.append(frames[i])
            self._frame_buffer[device_id] = buf
            self._updates_since_save[device_id] = 0
            logger.info(
                "bgsub: rebuilt MOG2 (%s) for %s from %d baseline frames in %s (schema=v%d)",
                mode, device_id, frames.shape[0], path, schema_version,
            )
            return entry
        except Exception as exc:  # noqa: BLE001
            logger.warning("bgsub: failed to load baseline frames %s: %s", path, exc)
            return None

    def _build_single_model(
        self,
        frames: np.ndarray,
        cfg: dict[str, Any],
    ) -> cv2.BackgroundSubtractor:
        """Build a single MOG2 by replaying baseline frames (legacy mode)."""
        bg = cv2.createBackgroundSubtractorMOG2(
            history=int(cfg["history"]),
            varThreshold=float(cfg["var_threshold"]),
            detectShadows=True,
        )
        for i in range(frames.shape[0]):
            bg.apply(frames[i])
        return bg

    def _build_dual_models(
        self,
        frames: np.ndarray,
        cfg: dict[str, Any],
        schema_version: int,
    ) -> tuple[cv2.BackgroundSubtractor, cv2.BackgroundSubtractor]:
        """Build (fast, slow) MOG2 pair by replaying baseline frames.

        For schema v1 npz (no dual_rate flag), the slow model needs an
        accelerated warm-up since LR=0.001 needs many more frames to converge.
        We replay the buffer N times with LR=LR_FAST during warm-up to age
        the slow model quickly, then continue normally.
        """
        fast = cv2.createBackgroundSubtractorMOG2(
            history=int(cfg["history_fast"]),
            varThreshold=float(cfg["var_threshold"]),
            detectShadows=True,
        )
        slow = cv2.createBackgroundSubtractorMOG2(
            history=int(cfg["history_slow"]),
            varThreshold=float(cfg["var_threshold"]),
            detectShadows=True,
        )
        # Replay frames into fast model (full speed).
        for i in range(frames.shape[0]):
            fast.apply(frames[i])
        # Slow model: replay N passes at fast LR to "age" it, then default rate.
        warmup_passes = int(config.BGSUB_SLOW_WARMUP_PASSES) if schema_version == 1 else 1
        warmup_passes = max(1, warmup_passes)
        for _ in range(warmup_passes):
            for i in range(frames.shape[0]):
                slow.apply(frames[i], learningRate=float(cfg["lr_fast"]))
        return (fast, slow)

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
            all_pts: list[np.ndarray] = []
            for poly in polygons:
                pts = np.array(poly, dtype=np.int32)
                if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 3:
                    logger.warning("bgsub: invalid polygon shape for %s: %s", device_id, pts.shape)
                    return None
                cv2.fillPoly(mask, [pts], 255)
                all_pts.append(pts)
            # Compute bbox covering all polygons (for crop optimization).
            if all_pts:
                concat = np.vstack(all_pts)
                x, y, w, h = cv2.boundingRect(concat)
                self._bboxes[device_id] = (int(x), int(y), int(w), int(h))
            else:
                self._bboxes[device_id] = None
            self._masks[device_id] = mask
            logger.info(
                "bgsub: built zone mask for %s (%d polygons, bbox=%s)",
                device_id, len(polygons), self._bboxes[device_id],
            )
            return mask
        except Exception as exc:  # noqa: BLE001
            logger.warning("bgsub: failed to build mask for %s: %s", device_id, exc)
            return None

    def get_bbox(self, device_id: str) -> Optional[tuple[int, int, int, int]]:
        """Return cached polygon bbox (call after get_mask)."""
        return self._bboxes.get(device_id)

    def invalidate(self, device_id: Optional[str] = None) -> None:
        """Clear cache (used by tests or after recalibration)."""
        if device_id is None:
            self._mog2.clear()
            self._mode.clear()
            self._masks.clear()
            self._bboxes.clear()
            self._frame_buffer.clear()
            self._updates_since_save.clear()
        else:
            self._mog2.pop(device_id, None)
            self._mode.pop(device_id, None)
            self._masks.pop(device_id, None)
            self._bboxes.pop(device_id, None)
            self._frame_buffer.pop(device_id, None)
            self._updates_since_save.pop(device_id, None)


_cache = _ModelCache()


def invalidate_cache(device_id: Optional[str] = None) -> None:
    _cache.invalidate(device_id)


def _scale_bbox_to_img(
    bbox_ref: tuple[int, int, int, int],
    img_shape: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Rescale a bbox from _FRAME_REF_SHAPE to img_shape.

    bbox_ref is (x, y, w, h) in 1280x720. If img has different shape, scale.
    """
    ref_h, ref_w = _FRAME_REF_SHAPE
    img_h, img_w = img_shape
    if img_h == ref_h and img_w == ref_w:
        return bbox_ref
    x, y, w, h = bbox_ref
    sx = img_w / ref_w
    sy = img_h / ref_h
    return (
        max(0, int(x * sx)),
        max(0, int(y * sy)),
        min(img_w, int(w * sx) + 1),
        min(img_h, int(h * sy) + 1),
    )


def _apply_and_combine(
    bg_entry: _ModelEntry,
    img: np.ndarray,
    mode: str,
    shadow_threshold: int,
    morph_kernel: np.ndarray,
    lr_fast: float = 0.0,
    lr_slow: float = 0.0,
) -> np.ndarray:
    """Apply MOG2 (single or dual) to `img` and return the cleaned fg mask.

    In dual mode, the fast and slow models are applied with their respective
    learning rates so that fast absorbs new stationary objects within the
    window while slow retains them — this is what makes `slow AND NOT fast`
    isolate the drop-and-go signal. The mutation of state during evaluate IS
    INTENTIONAL in dual mode; it is the substitute for a separate adaptive-
    update call (which is bypassed when DUAL_RATE_ENABLED).

    Single mode preserves the legacy snapshot semantics (LR=0).
    """
    if mode == "dual":
        fast_bg, slow_bg = bg_entry  # type: ignore[misc]
        fast = fast_bg.apply(img, learningRate=lr_fast)
        slow = slow_bg.apply(img, learningRate=lr_slow)
        fast_bin = (fast > shadow_threshold).astype(np.uint8) * 255
        slow_bin = (slow > shadow_threshold).astype(np.uint8) * 255
        # static_fg = slow AND NOT fast (pixel still seen by slow but absorbed by fast)
        fg = cv2.bitwise_and(slow_bin, cv2.bitwise_not(fast_bin))
    else:
        bg = bg_entry  # type: ignore[assignment]
        raw = bg.apply(img, learningRate=0.0)
        fg = (raw > shadow_threshold).astype(np.uint8) * 255

    morpho_mode = str(config.BGSUB_MORPHO_MODE).lower()
    if morpho_mode == 'open_close':
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, morph_kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, morph_kernel)
    elif morpho_mode == 'area_min':
        # Contour-area filter: mantém apenas blobs com area >= AREA_MIN.
        # Substitui MORPH_OPEN (que removia small objects) por filtro de área
        # bem definido. Validado no smoke test 25/05: filtra +2 FPs vs morpho
        # padrão (FP trafico esp32_001 09:30, 10:00) sem perder TPs.
        area_min = int(config.BGSUB_AREA_MIN)
        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = np.zeros_like(fg)
        for c in contours:
            if cv2.contourArea(c) >= area_min:
                cv2.drawContours(out, [c], -1, 255, thickness=cv2.FILLED)
        fg = out
    # morpho_mode == 'off' → sem pós-processamento (modo experimental).
    return fg


def evaluate(
    frame_paths: list[Path],
    device_id: str,
    pile_zone_polygon: Any,
    camera: Any = None,
) -> FilterResult:
    """Decide whether to suppress this window (no Gemini call).

    Args:
        frame_paths: list of N frame paths in chronological order.
        device_id: e.g. "esp32_001"; used to locate MOG2 file.
        pile_zone_polygon: the JSONB value from `cameras.pile_zone_polygon`
            (list of polygons of [x, y] points), or None.
        camera: optional Camera-like object/dict; when present, its
            bgsub_* fields override env globals (per-camera tuning).

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

    cfg = _resolved_config(camera)
    bg_entry = _cache.get_models(device_id, cfg)
    if bg_entry is None:
        return FilterResult(should_suppress=False, reason="skipped_no_model")

    mode = "dual" if config.BGSUB_DUAL_RATE_ENABLED else "single"
    bbox_ref = _cache.get_bbox(device_id) if config.BGSUB_BBOX_CROP_ENABLED else None

    try:
        morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        min_active = int(cfg["min_px_active"])
        shadow_threshold = int(cfg["shadow_threshold"])
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

            # Optional crop: only run MOG2 on the polygon bbox (saves 50-82% CPU).
            # NOTE: requires baseline calibrated on matching crop — currently off.
            lr_fast_eval = cfg["lr_fast"] if mode == "dual" else 0.0
            lr_slow_eval = cfg["lr_slow"] if mode == "dual" else 0.0
            if bbox_ref is not None:
                x, y, w, h = _scale_bbox_to_img(bbox_ref, img.shape[:2])
                img_crop = img[y:y + h, x:x + w]
                mask_crop = resized_mask[y:y + h, x:x + w]
                fg_crop = _apply_and_combine(
                    bg_entry, img_crop, mode, shadow_threshold, morph_kernel,
                    lr_fast=lr_fast_eval, lr_slow=lr_slow_eval,
                )
                in_zone = cv2.bitwise_and(fg_crop, mask_crop)
            else:
                fg = _apply_and_combine(
                    bg_entry, img, mode, shadow_threshold, morph_kernel,
                    lr_fast=lr_fast_eval, lr_slow=lr_slow_eval,
                )
                in_zone = cv2.bitwise_and(fg, resized_mask)

            if int(np.count_nonzero(in_zone)) >= min_active:
                fg_masks.append(in_zone)
            else:
                fg_masks.append(np.zeros_like(in_zone))

        n_total = len(fg_masks)
        n_ok = sum(1 for m in fg_masks if np.any(m))
        if n_total == 0:
            return FilterResult(should_suppress=False, reason="error", mode=mode)

        stack = np.stack(fg_masks, axis=0) > 0
        votes = stack.sum(axis=0)
        min_frames = max(1, int(round(cfg["min_persistence_frames"] * n_total)))
        persistence_mask = votes >= min_frames
        persistence_px = int(np.count_nonzero(persistence_mask))

        threshold = int(cfg["persistence_threshold"])
        if persistence_px < threshold:
            return FilterResult(
                should_suppress=True,
                reason="filtered",
                persistence=float(persistence_px),
                n_frames_ok=n_ok,
                n_frames_total=n_total,
                mode=mode,
            )

        return FilterResult(
            should_suppress=False,
            reason="passed",
            persistence=float(persistence_px),
            n_frames_ok=n_ok,
            n_frames_total=n_total,
            mode=mode,
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning("bgsub: evaluate failed for %s: %s", device_id, exc, exc_info=True)
        return FilterResult(should_suppress=False, reason="error", mode=mode)


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
    camera: Any = None,
) -> AdaptiveUpdateResult:
    """Absorb frames into the MOG2 baseline IF the Gemini gate confirmed the
    scene as "no new litter" with high confidence.

    Call this AFTER the gate returns. Caller-side check: only invoke when
    gate_report.new_litter_detected == False.

    In dual-rate mode, both fast and slow models are updated (with their
    respective LRs).

    Args:
        device_id: e.g. "esp32_001"; must match the npz/cache key.
        frame_paths: same frames passed to `evaluate()` for this window.
        gate_confidence: int 0-100, from the Gemini gate report.
        pile_zone_polygon: unused (kept for caller convenience).
        camera: optional Camera-like object; provides per-camera LR overrides.

    Returns AdaptiveUpdateResult; never raises.
    """
    if not config.BGSUB_ADAPTIVE_ENABLED:
        return AdaptiveUpdateResult(applied=False, reason="skipped_disabled")
    if gate_confidence < int(config.BGSUB_ADAPTIVE_MIN_CONFIDENCE):
        return AdaptiveUpdateResult(applied=False, reason="skipped_low_confidence")

    cfg = _resolved_config(camera)
    bg_entry = _cache.get_models(device_id, cfg)
    if bg_entry is None:
        return AdaptiveUpdateResult(applied=False, reason="skipped_no_model")

    mode = "dual" if config.BGSUB_DUAL_RATE_ENABLED else "single"

    # In dual mode, `evaluate()` already applies LRs continuously (it's how
    # the static_fg signal works). A separate adaptive call here would
    # double-update. Still useful for: rolling buffer maintenance and npz
    # persistence (snapshots survive restart). Apply with the *_adapt LRs
    # which can be tuned independently if needed (defaults = eval LRs).
    if mode == "dual":
        lr_fast = float(cfg["lr_fast_adapt"])
        lr_slow = float(cfg["lr_slow_adapt"])
    else:
        lr_single = float(cfg["adaptive_lr"])

    buf = _cache._frame_buffer.setdefault(
        device_id, collections.deque(maxlen=int(cfg["history_fast"] if mode == "dual" else cfg["history"])),
    )

    n_applied = 0
    try:
        for fp in frame_paths:
            img = cv2.imread(str(fp))
            if img is None:
                continue
            if mode == "dual":
                fast_bg, slow_bg = bg_entry  # type: ignore[misc]
                fast_bg.apply(img, learningRate=lr_fast)
                slow_bg.apply(img, learningRate=lr_slow)
            else:
                bg_entry.apply(img, learningRate=lr_single)  # type: ignore[union-attr]
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
        persisted = _persist_frames_to_npz(device_id, list(buf), mode=mode)
        if persisted:
            _cache._updates_since_save[device_id] = 0

    if mode == "dual":
        logger.info(
            "bgsub: adaptive update applied for %s (mode=dual, frames=%d, lr_fast=%.3f, lr_slow=%.4f, persisted=%s)",
            device_id, n_applied, lr_fast, lr_slow, persisted,
        )
    else:
        logger.info(
            "bgsub: adaptive update applied for %s (mode=single, frames=%d, lr=%.3f, persisted=%s)",
            device_id, n_applied, lr_single, persisted,
        )
    return AdaptiveUpdateResult(
        applied=True,
        reason="persisted" if persisted else "applied",
        n_frames=n_applied,
    )


def _persist_frames_to_npz(
    device_id: str,
    frames_list: list[np.ndarray],
    mode: str = "single",
) -> bool:
    """Save the rolling frame buffer as a fresh npz (atomic via .tmp rename).

    In dual-rate mode, marks schema_version=2 and dual_rate=True so loader
    knows to skip the slow-model warm-up boost.
    """
    if not frames_list:
        return False
    try:
        models_dir = Path(config.BGSUB_MODELS_DIR)
        models_dir.mkdir(parents=True, exist_ok=True)
        final_path = models_dir / f"{device_id}.npz"
        tmp_path = models_dir / f"{device_id}.tmp.npz"
        arr = np.stack(frames_list, axis=0)
        if mode == "dual":
            np.savez_compressed(
                str(tmp_path),
                frames=arr,
                schema_version=np.int32(2),
                dual_rate=np.bool_(True),
            )
        else:
            np.savez_compressed(str(tmp_path), frames=arr)
        tmp_path.replace(final_path)
        logger.info(
            "bgsub: persisted %d frames to %s (mode=%s, adaptive checkpoint)",
            len(frames_list), final_path, mode,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("bgsub: persist failed for %s: %s", device_id, exc, exc_info=True)
        return False
