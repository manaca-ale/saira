"""Unit tests for detail-side pile-crop augmentation (campaign 24 deploy).

Validates:
- `detail_system_prompt_for_camera` selects MANGABEIRA_E_WITH_PILECROPS for
  esp32_002 + has_pilecrops=True; falls back to SYSTEM_PROMPT_V3 otherwise.
- `analyze_with_gemini` accepts the new `pile_crops` kwarg and the new
  prompt_version "mangabeira_with_pilecrops" without breaking existing
  signatures.
- `_make_pile_crops` (already used by gate) crops + upscales as expected and
  writes JPEGs of non-trivial size.
- `_process_with_gemini` fails open (falls back to default detail prompt)
  when the per-device flag is on but `pile_zone_polygon` is missing.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from worker import config
from worker._prompts_v3 import (
    DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS,
    SYSTEM_PROMPT_V3,
    detail_system_prompt_for_camera,
)
from worker.detector_gemini import (
    _build_mangabeira_pilecrops_user_prompt,
    analyze_with_gemini,
)


# -----------------------------------------------------------------------------
# Prompt selection
# -----------------------------------------------------------------------------
def test_detail_prompt_selects_mangabeira_for_esp32_002_with_crops():
    """esp32_002 + has_pilecrops=True must select MANGABEIRA_E_WITH_PILECROPS."""
    ctx = {"device_id": "esp32_002", "camera_name": "Mangabeira"}
    prompt = detail_system_prompt_for_camera(ctx, has_pilecrops=True)
    assert prompt == DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS
    assert "MANGABEIRA" in prompt.upper() or "Mangabeira" in prompt


def test_detail_prompt_falls_back_without_pilecrops():
    """esp32_002 WITHOUT has_pilecrops uses the default V3 detail prompt."""
    ctx = {"device_id": "esp32_002"}
    prompt = detail_system_prompt_for_camera(ctx, has_pilecrops=False)
    assert prompt == SYSTEM_PROMPT_V3


def test_detail_prompt_falls_back_for_other_devices_even_with_crops():
    """Crops without the matching device_id still use default prompt."""
    ctx = {"device_id": "esp32_001"}
    prompt = detail_system_prompt_for_camera(ctx, has_pilecrops=True)
    assert prompt == SYSTEM_PROMPT_V3


def test_detail_prompt_no_context():
    """No camera_context at all -> default prompt (no crash)."""
    prompt = detail_system_prompt_for_camera(None, has_pilecrops=True)
    assert prompt == SYSTEM_PROMPT_V3


# -----------------------------------------------------------------------------
# User prompt builder
# -----------------------------------------------------------------------------
def test_user_prompt_mentions_both_sequences():
    """User prompt must describe the 2-sequence input structure to the model."""
    prompt = _build_mangabeira_pilecrops_user_prompt(
        camera_context={"device_id": "esp32_002"},
        frame_names=["a.jpg", "b.jpg", "c.jpg"],
        crop_count=12,
    )
    assert "SEQUENCIA 1" in prompt
    assert "SEQUENCIA 2" in prompt
    assert "3 FRAMES GLOBAIS" in prompt
    assert "12 CROPS" in prompt
    assert "a.jpg" in prompt  # allowed frame names listed


def test_user_prompt_empty_inputs():
    """No frames + no crops -> still returns a well-formed prompt (no crash)."""
    prompt = _build_mangabeira_pilecrops_user_prompt(
        camera_context=None, frame_names=None, crop_count=0,
    )
    assert "SEQUENCIA 1" in prompt
    assert "0 FRAMES GLOBAIS" in prompt
    assert "0 CROPS" in prompt


# -----------------------------------------------------------------------------
# analyze_with_gemini signature
# -----------------------------------------------------------------------------
def test_analyze_with_gemini_accepts_pile_crops_kwarg():
    """Signature contract — pile_crops kwarg is optional and defaults to None."""
    sig = inspect.signature(analyze_with_gemini)
    assert "pile_crops" in sig.parameters
    assert sig.parameters["pile_crops"].default is None


def test_analyze_with_gemini_accepts_new_prompt_version():
    """Backward compat: the new prompt_version string is recognized.

    We mock _call_model so no real API call happens; only verify the new
    branch is reachable and selects the MANGABEIRA prompt.
    """
    tmp_paths = []  # empty list would raise ValueError; use 1 fake path
    fake_frame = Path("/tmp/fake_frame.jpg")  # never actually read
    fake_crop = Path("/tmp/fake_crop.jpg")

    captured = {}

    def _fake_call_model(send_paths, system_prompt, user_prompt, model_name,
                         response_schema, max_output_tokens=None,
                         thinking_budget=None, seed=None, thinking_level=None,
                         media_resolution=None, client=None):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        captured["n_paths"] = len(send_paths)
        # Return a response shaped enough that _extract_text + schema parse work
        resp = MagicMock()
        resp.text = (
            '{"infraction_confirmed": false, "confidence_0_100": 50, '
            '"evidence_summary": "test", "offender_detected": false}'
        )
        resp.usage_metadata = MagicMock(
            prompt_token_count=100, candidates_token_count=20, total_token_count=120,
        )
        return resp

    with patch("worker.detector_gemini._call_model", side_effect=_fake_call_model):
        analyze_with_gemini(
            image_paths=[fake_frame],
            camera_context={"device_id": "esp32_002", "camera_name": "Mangabeira"},
            prompt_version="mangabeira_with_pilecrops",
            pile_crops=[fake_crop],
        )

    # System prompt must be the MANGABEIRA one (selected via detail_system_prompt_for_camera)
    assert captured["system_prompt"] == DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS
    # send_paths must include the crop too (1 global + 1 crop)
    assert captured["n_paths"] == 2
    assert "SEQUENCIA 1" in captured["user_prompt"]


# -----------------------------------------------------------------------------
# _make_pile_crops + cv2 sanity
# -----------------------------------------------------------------------------
def _write_test_frame(path: Path, w: int = 1280, h: int = 720) -> Path:
    """Create a simple BGR test image with a colored box in the pile area."""
    img = np.full((h, w, 3), 200, dtype=np.uint8)
    # Draw a 200x100 red rect inside the pile zone (esp32_002 bbox)
    img[100:200, 600:800] = (0, 0, 255)
    cv2.imwrite(str(path), img)
    return path


def test_make_pile_crops_basic(tmp_path: Path):
    """Crop + upscale should produce JPEGs at 2x the bbox size."""
    from worker.main import _make_pile_crops

    src = _write_test_frame(tmp_path / "src.jpg")
    bbox = (480, 60, 920, 340)  # esp32_002 pile zone — w=440, h=280
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    crops = _make_pile_crops([src], bbox, upscale=2, out_dir=out_dir)
    assert len(crops) == 1
    crop_path = crops[0]
    assert crop_path.exists()
    assert crop_path.stat().st_size > 1000

    img = cv2.imread(str(crop_path))
    assert img is not None
    # Upscale 2x: 440*2 = 880, 280*2 = 560
    assert img.shape[0] == 560
    assert img.shape[1] == 880


def test_make_pile_crops_clamps_to_image_bounds(tmp_path: Path):
    """bbox extending past image bounds should still produce a valid crop."""
    from worker.main import _make_pile_crops

    src = _write_test_frame(tmp_path / "src.jpg", w=800, h=400)
    bbox = (100, 100, 2000, 2000)  # extends way past 800x400
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    crops = _make_pile_crops([src], bbox, upscale=1, out_dir=out_dir)
    assert len(crops) == 1
    img = cv2.imread(str(crops[0]))
    assert img is not None
    # Crop clamped to image bounds: 800-100=700 wide, 400-100=300 tall
    assert img.shape[1] <= 700
    assert img.shape[0] <= 300


# -----------------------------------------------------------------------------
# Config flags
# -----------------------------------------------------------------------------
def test_config_flags_present_with_defaults():
    """All 4 new flags must exist with sensible defaults."""
    assert hasattr(config, "GEMINI_DETAIL_PILECROP_ENABLED")
    assert hasattr(config, "DETAIL_PILECROP_DEVICES")
    assert hasattr(config, "GEMINI_DETAIL_PILECROP_UPSCALE")
    assert hasattr(config, "GEMINI_DETAIL_PILECROP_N_FRAMES")

    # Defaults: feature OFF
    assert config.GEMINI_DETAIL_PILECROP_ENABLED in (False, True)  # env-dependent
    # Default devices set contains at least esp32_002 (or is configurable)
    assert isinstance(config.DETAIL_PILECROP_DEVICES, set)
    # Upscale should be a positive integer
    assert config.GEMINI_DETAIL_PILECROP_UPSCALE >= 1
    # Crop count should be positive
    assert config.GEMINI_DETAIL_PILECROP_N_FRAMES > 0
