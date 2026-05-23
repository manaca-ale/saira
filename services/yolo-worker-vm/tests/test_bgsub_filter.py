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
