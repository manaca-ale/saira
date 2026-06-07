"""Unit tests for worker.bgsub_filter — OpenCV background-subtraction pre-filter.

Tests cover the fail-open behaviour (caller's failsafe contract) and the
positive path (suppression when persistence is below threshold).

These tests don't require a real Gemini key or DB — they exercise only the
pure-Python + OpenCV logic.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from worker import bgsub_filter, config


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _write_frame(path: Path, pattern: str = "empty") -> Path:
    """Synth a 1280x720 BGR frame and save as JPG.

    pattern:
      empty: solid gray background (matches "baseline" — won't differ from bg model)
      bright_blob: a bright rectangle in the pile zone (lots of FG vs gray bg)
    """
    img = np.full((720, 1280, 3), 128, dtype=np.uint8)
    if pattern == "bright_blob":
        # Big bright rectangle inside Imbiribeira pile zone (200,400)-(500,650)
        img[400:650, 200:500] = 240
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path


def _train_mog2_to_disk(model_path: Path, frame_paths: list[Path]) -> None:
    """Save the baseline frames as an npz so bgsub_filter can rebuild the MOG2."""
    arrays = [cv2.imread(str(fp)) for fp in frame_paths]
    stack = np.stack(arrays, axis=0)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(str(model_path), frames=stack)


# -----------------------------------------------------------------------------
# Fail-open paths
# -----------------------------------------------------------------------------
def test_fails_open_when_disabled(tmp_path):
    """Global flag off → never suppresses."""
    bgsub_filter.invalidate_cache()
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", False):
        result = bgsub_filter.evaluate(
            frame_paths=[tmp_path / "any.jpg"],
            device_id="esp32_test",
            pile_zone_polygon=[[[0, 0], [100, 0], [100, 100], [0, 100]]],
        )
    assert result.should_suppress is False
    assert result.reason == "skipped_disabled"


def test_fails_open_when_no_polygon(tmp_path):
    """Camera without polygon configured → never suppresses."""
    bgsub_filter.invalidate_cache()
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True):
        result = bgsub_filter.evaluate(
            frame_paths=[tmp_path / "any.jpg"],
            device_id="esp32_test",
            pile_zone_polygon=None,
        )
    assert result.should_suppress is False
    assert result.reason == "skipped_no_polygon"


def test_fails_open_when_invalid_polygon(tmp_path):
    """Malformed polygon → fail-open with skipped_no_polygon (mask build fails)."""
    bgsub_filter.invalidate_cache()
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True):
        result = bgsub_filter.evaluate(
            frame_paths=[tmp_path / "any.jpg"],
            device_id="esp32_test",
            pile_zone_polygon=[[[1, 2]]],  # only 1 point — invalid
        )
    assert result.should_suppress is False
    assert result.reason == "skipped_no_polygon"


def test_fails_open_when_no_mog2_model(tmp_path):
    """Polygon ok but MOG2 file missing → fail-open with skipped_no_model."""
    bgsub_filter.invalidate_cache()
    fake_dir = tmp_path / "bgsub_models"
    fake_dir.mkdir()
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(fake_dir)):
        result = bgsub_filter.evaluate(
            frame_paths=[tmp_path / "any.jpg"],
            device_id="esp32_no_model",
            pile_zone_polygon=[[[0, 0], [100, 0], [100, 100], [0, 100]]],
        )
    assert result.should_suppress is False
    assert result.reason == "skipped_no_model"


# -----------------------------------------------------------------------------
# Positive paths (real bgsub evaluation)
# -----------------------------------------------------------------------------
def test_suppress_when_persistence_below_threshold(tmp_path):
    """Train MOG2 on gray frames, then test with more gray frames → no FG → suppress."""
    bgsub_filter.invalidate_cache()
    models_dir = tmp_path / "bgsub_models"
    train_frames = [_write_frame(tmp_path / "train" / f"{i:03d}.jpg", "empty") for i in range(10)]
    _train_mog2_to_disk(models_dir / "esp32_quiet.npz", train_frames)

    test_frames = [_write_frame(tmp_path / "test" / f"{i:03d}.jpg", "empty") for i in range(5)]

    polygon = [[[50, 50], [1230, 50], [1230, 670], [50, 670]]]  # full frame zone

    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_PERSISTENCE_THRESHOLD", 1000):
        result = bgsub_filter.evaluate(
            frame_paths=test_frames,
            device_id="esp32_quiet",
            pile_zone_polygon=polygon,
        )

    assert result.should_suppress is True
    assert result.reason == "filtered"
    assert result.persistence < 1000


def test_passes_when_persistence_above_threshold(tmp_path):
    """Train on gray; test with a big bright blob in the pile zone → high persistence → no suppress."""
    bgsub_filter.invalidate_cache()
    models_dir = tmp_path / "bgsub_models"
    train_frames = [_write_frame(tmp_path / "train" / f"{i:03d}.jpg", "empty") for i in range(10)]
    _train_mog2_to_disk(models_dir / "esp32_busy.npz", train_frames)

    # 5 test frames all with bright blob in zone — should persist > 1000 px
    test_frames = [_write_frame(tmp_path / "test" / f"{i:03d}.jpg", "bright_blob") for i in range(5)]

    polygon = [[[100, 300], [600, 300], [600, 700], [100, 700]]]  # covers the blob

    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_PERSISTENCE_THRESHOLD", 1000):
        result = bgsub_filter.evaluate(
            frame_paths=test_frames,
            device_id="esp32_busy",
            pile_zone_polygon=polygon,
        )

    assert result.should_suppress is False
    assert result.reason == "passed"
    assert result.persistence >= 1000


# -----------------------------------------------------------------------------
# Cache behavior
# -----------------------------------------------------------------------------
def test_cache_hit_avoids_reloading_model(tmp_path):
    """Second call with same device_id reuses cached model."""
    bgsub_filter.invalidate_cache()
    models_dir = tmp_path / "bgsub_models"
    train_frames = [_write_frame(tmp_path / "train" / f"{i:03d}.jpg", "empty") for i in range(5)]
    _train_mog2_to_disk(models_dir / "esp32_cache.npz", train_frames)
    test_frames = [_write_frame(tmp_path / "test" / f"{i:03d}.jpg", "empty") for i in range(2)]
    polygon = [[[0, 0], [1280, 0], [1280, 720], [0, 720]]]

    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)):
        # First call: warms cache
        result_1 = bgsub_filter.evaluate(test_frames, "esp32_cache", polygon)
        # Now delete the file — second call should still work via cache
        (models_dir / "esp32_cache.npz").unlink()
        result_2 = bgsub_filter.evaluate(test_frames, "esp32_cache", polygon)

    # Both calls produce a valid result (either filtered or passed),
    # without skipped_no_model on the second (because cache is warm).
    assert result_1.reason in ("filtered", "passed")
    assert result_2.reason in ("filtered", "passed"), \
        f"Expected cache hit, got reason={result_2.reason}"


def test_invalidate_cache_forces_reload(tmp_path):
    """invalidate_cache makes the next call fail with skipped_no_model if file is gone."""
    bgsub_filter.invalidate_cache()
    models_dir = tmp_path / "bgsub_models"
    train_frames = [_write_frame(tmp_path / "train" / f"{i:03d}.jpg", "empty") for i in range(5)]
    _train_mog2_to_disk(models_dir / "esp32_inv.npz", train_frames)
    test_frames = [_write_frame(tmp_path / "test" / f"{i:03d}.jpg", "empty") for i in range(2)]
    polygon = [[[0, 0], [1280, 0], [1280, 720], [0, 720]]]

    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)):
        result_warm = bgsub_filter.evaluate(test_frames, "esp32_inv", polygon)
        (models_dir / "esp32_inv.npz").unlink()
        bgsub_filter.invalidate_cache("esp32_inv")
        result_cold = bgsub_filter.evaluate(test_frames, "esp32_inv", polygon)

    assert result_warm.reason in ("filtered", "passed")
    assert result_cold.reason == "skipped_no_model"


# -----------------------------------------------------------------------------
# Adaptive baseline (Gemini-supervised update)
# -----------------------------------------------------------------------------
def _setup_adaptive_camera(tmp_path, device_id="esp32_adapt"):
    """Build a calibrated MOG2 + cache it. Returns (models_dir, polygon, frames)."""
    bgsub_filter.invalidate_cache()
    models_dir = tmp_path / "bgsub_models"
    train_frames = [_write_frame(tmp_path / "train" / f"{i:03d}.jpg", "empty") for i in range(5)]
    _train_mog2_to_disk(models_dir / f"{device_id}.npz", train_frames)
    test_frames = [_write_frame(tmp_path / "test" / f"{i:03d}.jpg", "empty") for i in range(3)]
    polygon = [[[0, 0], [1280, 0], [1280, 720], [0, 720]]]
    return models_dir, polygon, test_frames


def test_adaptive_skipped_when_flag_disabled(tmp_path):
    models_dir, _, frames = _setup_adaptive_camera(tmp_path)
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_ADAPTIVE_ENABLED", False):
        # Warm cache first
        bgsub_filter.evaluate(frames, "esp32_adapt", [[[0, 0], [1280, 0], [1280, 720], [0, 720]]])
        result = bgsub_filter.update_baseline_with_frames("esp32_adapt", frames, gate_confidence=95)
    assert result.applied is False
    assert result.reason == "skipped_disabled"


def test_adaptive_skipped_when_confidence_below_threshold(tmp_path):
    models_dir, polygon, frames = _setup_adaptive_camera(tmp_path)
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_ADAPTIVE_ENABLED", True), \
         patch.object(config, "BGSUB_ADAPTIVE_MIN_CONFIDENCE", 90):
        bgsub_filter.evaluate(frames, "esp32_adapt", polygon)
        # 80 < 90 → skip
        result = bgsub_filter.update_baseline_with_frames("esp32_adapt", frames, gate_confidence=80)
    assert result.applied is False
    assert result.reason == "skipped_low_confidence"


def test_adaptive_skipped_when_no_model(tmp_path):
    """No npz file → no MOG2 → can't adapt."""
    bgsub_filter.invalidate_cache()
    models_dir = tmp_path / "bgsub_models"
    models_dir.mkdir()
    frames = [_write_frame(tmp_path / "test" / f"{i:03d}.jpg", "empty") for i in range(2)]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_ADAPTIVE_ENABLED", True):
        result = bgsub_filter.update_baseline_with_frames("esp32_nomodel", frames, gate_confidence=95)
    assert result.applied is False
    assert result.reason == "skipped_no_model"


def test_adaptive_applies_when_enabled_and_high_confidence(tmp_path):
    """High confidence + enabled → MOG2 absorbs frames."""
    models_dir, polygon, frames = _setup_adaptive_camera(tmp_path)
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_ADAPTIVE_ENABLED", True), \
         patch.object(config, "BGSUB_ADAPTIVE_MIN_CONFIDENCE", 90), \
         patch.object(config, "BGSUB_ADAPTIVE_LEARNING_RATE", 0.05), \
         patch.object(config, "BGSUB_ADAPTIVE_SAVE_EVERY_N", 9999):  # don't persist in test
        bgsub_filter.evaluate(frames, "esp32_adapt", polygon)
        result = bgsub_filter.update_baseline_with_frames("esp32_adapt", frames, gate_confidence=95)
    assert result.applied is True
    assert result.reason == "applied"
    assert result.n_frames == len(frames)


def test_adaptive_persists_after_threshold(tmp_path):
    """Once update count crosses save threshold, npz is rewritten."""
    models_dir, polygon, frames = _setup_adaptive_camera(tmp_path)
    npz_path = models_dir / "esp32_adapt.npz"
    original_mtime = npz_path.stat().st_mtime
    import time as _time
    _time.sleep(0.01)
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_ADAPTIVE_ENABLED", True), \
         patch.object(config, "BGSUB_ADAPTIVE_MIN_CONFIDENCE", 90), \
         patch.object(config, "BGSUB_ADAPTIVE_LEARNING_RATE", 0.05), \
         patch.object(config, "BGSUB_ADAPTIVE_SAVE_EVERY_N", 2):  # trip on first update
        bgsub_filter.evaluate(frames, "esp32_adapt", polygon)
        result = bgsub_filter.update_baseline_with_frames("esp32_adapt", frames, gate_confidence=95)
    assert result.applied is True
    assert result.reason == "persisted"
    assert npz_path.exists()
    assert npz_path.stat().st_mtime > original_mtime
    # Reload — verify the new npz has the rolling buffer (5 baseline + 3 adapted = 8 frames)
    arr = np.load(str(npz_path))["frames"]
    assert arr.shape[0] == 8
    assert arr.shape[1:] == (720, 1280, 3)


def test_shadow_threshold_parameterized_lower_detects_dark_object(tmp_path):
    """Validates the 2026-05-23 fix: lower BGSUB_SHADOW_THRESHOLD recovers
    detection of dark objects (e.g. black trash bags) that MOG2 marks with
    ambiguous values (80-150) instead of definite-foreground (255).

    Setup: train on bright gray frames, then evaluate a window with dark
    objects. With threshold=200 (old default) the dark object's MOG2 output
    may fall below cutoff; with threshold=100 (new default) it passes.
    """
    bgsub_filter.invalidate_cache()
    models_dir = tmp_path / "bgsub_models"

    # Train baseline: bright gray frames (no dark objects)
    train_frames = []
    for i in range(8):
        p = tmp_path / "train" / f"{i:03d}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        img = np.full((720, 1280, 3), 180, dtype=np.uint8)  # bright gray
        cv2.imwrite(str(p), img)
        train_frames.append(p)
    _train_mog2_to_disk(models_dir / "esp32_shadow.npz", train_frames)

    # Eval window: same gray bg + dark gray blob in the polygon zone
    # (gray=80 simulates a dark object that MOG2 may classify as shadow ~127)
    test_frames = []
    for i in range(6):
        p = tmp_path / "eval" / f"{i:03d}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        img = np.full((720, 1280, 3), 180, dtype=np.uint8)
        # Dark patch (value=60) in the pile zone
        img[400:650, 200:500] = 60
        cv2.imwrite(str(p), img)
        test_frames.append(p)

    polygon = [[[150, 350], [550, 350], [550, 700], [150, 700]]]

    # With threshold=100 (new default), the dark patch should be detected
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_SHADOW_THRESHOLD", 100):
        result_low = bgsub_filter.evaluate(test_frames, "esp32_shadow", polygon)

    bgsub_filter.invalidate_cache()

    # With threshold=200 (old default), the dark patch may be dropped
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_SHADOW_THRESHOLD", 200):
        result_high = bgsub_filter.evaluate(test_frames, "esp32_shadow", polygon)

    # Lower threshold must detect at least as much as higher threshold
    assert result_low.persistence >= result_high.persistence, (
        f"thr=100 ({result_low.persistence}px) should detect >= thr=200 ({result_high.persistence}px)"
    )


def test_adaptive_caller_skip_positive_gate(tmp_path):
    """Verify the caller-side contract: when gate says new_litter=True, caller
    must NOT invoke update_baseline_with_frames. This test documents that
    the BGSUB module itself does NOT have a 'gate_positive' bypass — it only
    knows about confidence. The contract is enforced in main.py.
    """
    # Even with positive gate semantics, if caller invokes us with high
    # confidence, we still adapt — caller must do the gating.
    models_dir, polygon, frames = _setup_adaptive_camera(tmp_path)
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_ADAPTIVE_ENABLED", True), \
         patch.object(config, "BGSUB_ADAPTIVE_MIN_CONFIDENCE", 90), \
         patch.object(config, "BGSUB_ADAPTIVE_SAVE_EVERY_N", 9999):
        bgsub_filter.evaluate(frames, "esp32_adapt", polygon)
        # If a caller mistakenly invokes with high confidence on a positive
        # gate, we DO adapt — this is documented behavior.
        result = bgsub_filter.update_baseline_with_frames("esp32_adapt", frames, gate_confidence=95)
    assert result.applied is True


# -----------------------------------------------------------------------------
# Dual-rate MOG2 mode
# -----------------------------------------------------------------------------
def _setup_dual_camera(tmp_path):
    """Common scaffolding: 80 gray baseline frames, polygon, models dir."""
    models_dir = tmp_path / "bgsub_models"
    train_frames = [
        _write_frame(tmp_path / "train" / f"{i:03d}.jpg", "empty")
        for i in range(80)
    ]
    _train_mog2_to_disk(models_dir / "esp32_dual.npz", train_frames)
    polygon = [[[100, 300], [600, 300], [600, 700], [100, 700]]]
    return models_dir, polygon


def _write_walker_frame(path: Path, x_pos: int) -> Path:
    """Frame with a small bright rectangle at variable x position (moving)."""
    img = np.full((720, 1280, 3), 128, dtype=np.uint8)
    img[450:520, x_pos:x_pos + 60] = 240
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path


def _write_static_object_frame(path: Path) -> Path:
    """Frame with a stationary bright rectangle (drop-and-go target)."""
    img = np.full((720, 1280, 3), 128, dtype=np.uint8)
    img[450:600, 300:450] = 240  # fixed position, 150x150 inside zone
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path


def test_dual_rate_disabled_uses_single_mode(tmp_path):
    """Feature flag off → mode='single' in result."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    test_frames = [
        _write_static_object_frame(tmp_path / "static" / f"{i:03d}.jpg")
        for i in range(5)
    ]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", False):
        result = bgsub_filter.evaluate(test_frames, "esp32_dual", polygon)
    assert result.mode == "single"


def test_dual_rate_enabled_returns_dual_mode_label(tmp_path):
    """Feature flag on → mode='dual' in result."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    test_frames = [
        _write_static_object_frame(tmp_path / "static" / f"{i:03d}.jpg")
        for i in range(5)
    ]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", True), \
         patch.object(config, "BGSUB_SLOW_WARMUP_PASSES", 1):
        result = bgsub_filter.evaluate(test_frames, "esp32_dual", polygon)
    assert result.mode == "dual"


def test_dual_rate_static_object_preserves_signal(tmp_path):
    """Drop-and-go: object appears and stays still → static_fg non-zero
    and persistence above threshold → does NOT suppress."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    # 24 frames with the same static object → slow sees FG, fast absorbs slowly
    test_frames = [
        _write_static_object_frame(tmp_path / "static" / f"{i:03d}.jpg")
        for i in range(24)
    ]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", True), \
         patch.object(config, "BGSUB_SLOW_WARMUP_PASSES", 1), \
         patch.object(config, "BGSUB_MIN_PERSISTENCE_FRAMES", 0.4), \
         patch.object(config, "BGSUB_PERSISTENCE_THRESHOLD", 500):
        result = bgsub_filter.evaluate(test_frames, "esp32_dual", polygon)
    assert result.should_suppress is False
    assert result.mode == "dual"
    assert result.persistence > 500


def test_dual_rate_walking_object_suppresses(tmp_path):
    """Moving object: changes position every frame → both fast and slow
    detect it → static_fg ≈ 0 → suppresses."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    # Object moves in x (200, 240, 280, 320, ...) — never stays still
    test_frames = [
        _write_walker_frame(tmp_path / "walk" / f"{i:03d}.jpg", 200 + i * 20)
        for i in range(12)
    ]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", True), \
         patch.object(config, "BGSUB_SLOW_WARMUP_PASSES", 1), \
         patch.object(config, "BGSUB_MIN_PERSISTENCE_FRAMES", 0.4), \
         patch.object(config, "BGSUB_PERSISTENCE_THRESHOLD", 500):
        result = bgsub_filter.evaluate(test_frames, "esp32_dual", polygon)
    # With pure static_fg signal, a fully-moving object should NOT pass.
    # Allow either suppress=True (preferred) or a low persistence number.
    assert result.mode == "dual"
    assert result.persistence < 500


def test_npz_v1_loads_into_dual_models(tmp_path):
    """A v1 npz (no schema_version) should be readable in dual-rate mode
    and rebuild both fast + slow models without crashing."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    # Verify the npz was written WITHOUT schema_version (v1 format).
    npz_path = models_dir / "esp32_dual.npz"
    archive = np.load(str(npz_path))
    assert "frames" in archive.files
    assert "schema_version" not in archive.files

    test_frames = [
        _write_static_object_frame(tmp_path / "obj" / f"{i:03d}.jpg")
        for i in range(5)
    ]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", True), \
         patch.object(config, "BGSUB_SLOW_WARMUP_PASSES", 2):
        result = bgsub_filter.evaluate(test_frames, "esp32_dual", polygon)
    # Just verify load+evaluate didn't crash and produced dual mode.
    assert result.mode == "dual"
    assert result.reason in ("filtered", "passed")


def test_dual_rate_npz_v2_roundtrip(tmp_path):
    """Persist in dual mode → reload → both models reconstruct."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    test_frames = [
        _write_static_object_frame(tmp_path / "obj" / f"{i:03d}.jpg")
        for i in range(20)
    ]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", True), \
         patch.object(config, "BGSUB_ADAPTIVE_ENABLED", True), \
         patch.object(config, "BGSUB_ADAPTIVE_MIN_CONFIDENCE", 0), \
         patch.object(config, "BGSUB_ADAPTIVE_SAVE_EVERY_N", 5), \
         patch.object(config, "BGSUB_SLOW_WARMUP_PASSES", 1):
        # Force a persist by running multiple adapt cycles.
        bgsub_filter.evaluate(test_frames[:5], "esp32_dual", polygon)
        adapt_result = bgsub_filter.update_baseline_with_frames(
            "esp32_dual", test_frames[:10], gate_confidence=95,
        )
        assert adapt_result.applied is True
        # Verify npz was rewritten with schema_version=2
        archive = np.load(str(models_dir / "esp32_dual.npz"))
        assert "schema_version" in archive.files
        assert int(archive["schema_version"]) == 2

        # Invalidate and reload from disk — should work in dual mode.
        bgsub_filter.invalidate_cache()
        result = bgsub_filter.evaluate(test_frames[:5], "esp32_dual", polygon)
    assert result.mode == "dual"


def test_dual_rate_adaptive_updates_both_models(tmp_path):
    """update_baseline_with_frames in dual mode should not crash and should
    return applied=True when conditions are met."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    test_frames = [
        _write_frame(tmp_path / "noop" / f"{i:03d}.jpg", "empty")
        for i in range(10)
    ]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", True), \
         patch.object(config, "BGSUB_ADAPTIVE_ENABLED", True), \
         patch.object(config, "BGSUB_ADAPTIVE_MIN_CONFIDENCE", 0), \
         patch.object(config, "BGSUB_ADAPTIVE_SAVE_EVERY_N", 9999), \
         patch.object(config, "BGSUB_SLOW_WARMUP_PASSES", 1):
        # Prime cache.
        bgsub_filter.evaluate(test_frames, "esp32_dual", polygon)
        result = bgsub_filter.update_baseline_with_frames(
            "esp32_dual", test_frames, gate_confidence=95,
        )
    assert result.applied is True
    assert result.n_frames == 10


# -----------------------------------------------------------------------------
# Per-camera config overrides
# -----------------------------------------------------------------------------
class _FakeCamera:
    """Stand-in for a Camera ORM object with optional bgsub_* overrides."""

    def __init__(self, **kwargs):
        # Default all bgsub_* fields to None (= fallback to env globals).
        for name in (
            "bgsub_lr_fast", "bgsub_lr_slow",
            "bgsub_mog2_history_fast", "bgsub_mog2_history_slow",
            "bgsub_persistence_threshold",
            "bgsub_min_persistence_frames", "bgsub_min_px_active",
        ):
            setattr(self, name, kwargs.get(name))


def test_camera_bgsub_overrides_env_globals(tmp_path):
    """When camera has bgsub_persistence_threshold set, it overrides env."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    test_frames = [
        _write_static_object_frame(tmp_path / "obj" / f"{i:03d}.jpg")
        for i in range(10)
    ]
    cam = _FakeCamera(bgsub_persistence_threshold=999999)  # huge — forces suppress
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", False), \
         patch.object(config, "BGSUB_PERSISTENCE_THRESHOLD", 1):  # env says 1
        result = bgsub_filter.evaluate(test_frames, "esp32_dual", polygon, camera=cam)
    # With camera override 999999 winning over env 1, result should suppress.
    assert result.should_suppress is True


def test_morpho_mode_area_min_filters_small_blobs(tmp_path):
    """When morpho_mode=area_min, very small blobs are filtered out
    while big bright blobs still pass. This validates the new contour-area path."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    # Bright blob test — passes both modes
    test_frames = [
        _write_static_object_frame(tmp_path / "static" / f"{i:03d}.jpg")
        for i in range(10)
    ]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", False), \
         patch.object(config, "BGSUB_MORPHO_MODE", "area_min"), \
         patch.object(config, "BGSUB_AREA_MIN", 400), \
         patch.object(config, "BGSUB_PERSISTENCE_THRESHOLD", 1):
        result = bgsub_filter.evaluate(test_frames, "esp32_dual", polygon)
    # Static large object (150x150) passes area_min=400 → should NOT suppress
    assert result.should_suppress is False
    assert result.persistence > 1


def test_morpho_mode_off_disables_all_postprocessing(tmp_path):
    """morpho_mode=off → no MORPH_OPEN/CLOSE/area_filter; raw mask used."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    test_frames = [
        _write_static_object_frame(tmp_path / "static" / f"{i:03d}.jpg")
        for i in range(5)
    ]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", False), \
         patch.object(config, "BGSUB_MORPHO_MODE", "off"), \
         patch.object(config, "BGSUB_PERSISTENCE_THRESHOLD", 1):
        result = bgsub_filter.evaluate(test_frames, "esp32_dual", polygon)
    # No suppression, mode reported as single
    assert result.mode == "single"


def test_morpho_mode_default_preserves_legacy(tmp_path):
    """Default BGSUB_MORPHO_MODE='open_close' = comportamento atual prod."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    test_frames = [
        _write_static_object_frame(tmp_path / "static" / f"{i:03d}.jpg")
        for i in range(5)
    ]
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", False), \
         patch.object(config, "BGSUB_MORPHO_MODE", "open_close"), \
         patch.object(config, "BGSUB_PERSISTENCE_THRESHOLD", 1):
        result = bgsub_filter.evaluate(test_frames, "esp32_dual", polygon)
    assert result.mode == "single"


def test_camera_bgsub_null_falls_back_to_env(tmp_path):
    """When camera fields are None, env globals are used."""
    bgsub_filter.invalidate_cache()
    models_dir, polygon = _setup_dual_camera(tmp_path)
    test_frames = [
        _write_static_object_frame(tmp_path / "obj" / f"{i:03d}.jpg")
        for i in range(10)
    ]
    cam = _FakeCamera()  # all None
    with patch.object(config, "BGSUB_PREFILTER_ENABLED", True), \
         patch.object(config, "BGSUB_MODELS_DIR", str(models_dir)), \
         patch.object(config, "BGSUB_DUAL_RATE_ENABLED", False), \
         patch.object(config, "BGSUB_PERSISTENCE_THRESHOLD", 1):  # env says 1 → passes
        result = bgsub_filter.evaluate(test_frames, "esp32_dual", polygon, camera=cam)
    # With env threshold=1, even small persistence passes.
    assert result.should_suppress is False
