# src/ingester/local/image_validator.py
"""Image analysis, screenshot validation, and loading screen detection."""
import logging

from PIL import Image

from . import screen_fingerprint
from .. import config

logger = logging.getLogger(__name__)


def analyze_image(path: str) -> dict:
    """Compute basic grayscale statistics for a screenshot."""
    with Image.open(path) as img:
        gray = img.convert("L").resize((64, 64))
        pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    min_v = min(pixels)
    max_v = max(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    std = variance ** 0.5
    return {"mean": round(mean, 2), "std": round(std, 2), "min": min_v, "max": max_v}


def validate_screenshot(stats: dict) -> tuple[bool, str]:
    """Reject screenshots that are probably black or white screens."""
    mean = stats["mean"]
    std = stats["std"]
    if mean <= config.BLACK_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_black_screen"
    if mean >= config.WHITE_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_white_screen"
    return True, "ok"


def validate_focus(focus: dict) -> tuple[bool, str]:
    """Check whether the expected app/activity has window focus."""
    pkg = focus.get("package")
    activity = focus.get("activity")
    if pkg != config.EXPECTED_PACKAGE:
        return False, f"focus_package_mismatch:{pkg}"
    if activity not in config.EXPECTED_ACTIVITIES:
        return False, f"focus_activity_mismatch:{activity}"
    return True, "ok"


def is_loading_screen(screenshot_path: str) -> bool:
    """Check if the screenshot is a loading/black screen (stream not ready yet)."""
    stats = analyze_image(screenshot_path)
    if stats["mean"] <= config.BLACK_MEAN_THRESHOLD and stats["std"] <= config.LOW_STD_THRESHOLD:
        return True

    fp = screen_fingerprint.extract_fingerprint(screenshot_path)
    ind = fp["indicators"]
    return (
        stats["mean"] <= config.LOADING_MEAN_MAX
        and ind.get("bright_ratio_center", 0.0) >= config.LOADING_BRIGHT_CENTER_MIN
    )
