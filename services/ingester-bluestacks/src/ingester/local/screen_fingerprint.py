# src/ingester/local/screen_fingerprint.py
"""
Diagnostic tool to extract visual fingerprints from device screenshots.

Usage (from the ingester root):
    python -m ingester.local.screen_fingerprint --label home
    python -m ingester.local.screen_fingerprint --label camera_list
    python -m ingester.local.screen_fingerprint --label camera_normal
    python -m ingester.local.screen_fingerprint --label camera_fullscreen

Each run captures a screenshot, extracts features, and appends to
    logs/screen_profiles.json
After capturing all 4 screens, the profiles file can be reviewed and
the thresholds copied into config.py for runtime screen detection.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

from PIL import Image, ImageStat

from . import adb_adapter
from .. import config

logger = logging.getLogger(__name__)

# Grid layout: split screen into regions for analysis
# Each region is (name, x_frac_start, y_frac_start, x_frac_end, y_frac_end)
#
# Strategy: camera content changes per camera/time-of-day, but UI chrome
# (bars, buttons, borders) stays consistent. We focus on structural regions.
REGIONS = [
    # --- System bars ---
    ("top_bar",        0.0, 0.00, 1.0, 0.04),   # Android status bar (clock, icons)
    ("bottom_bar",     0.0, 0.96, 1.0, 1.00),   # Android nav bar (back, home, recent)
    # --- App UI zones (outside the video area) ---
    ("app_header",     0.0, 0.04, 1.0, 0.12),   # App toolbar / title area
    ("app_footer",     0.0, 0.88, 1.0, 0.96),   # App bottom controls / tab bar
    # --- Edges (detect UI borders vs video filling the screen) ---
    ("left_edge",      0.0,  0.12, 0.04, 0.88),
    ("right_edge",     0.96, 0.12, 1.0,  0.88),
    # --- Content zones (will vary per camera, used for sanity only) ---
    ("center",         0.15, 0.30, 0.85, 0.70),
    # --- Full frame ---
    ("full",           0.0, 0.00, 1.0, 1.00),
]


def _region_stats(img: Image.Image, region: tuple) -> dict:
    """Extract color statistics for a rectangular region of the image."""
    name, x0f, y0f, x1f, y1f = region
    w, h = img.size
    box = (int(x0f * w), int(y0f * h), int(x1f * w), int(y1f * h))
    cropped = img.crop(box)

    # Grayscale stats
    gray = cropped.convert("L")
    gray_stat = ImageStat.Stat(gray)
    g_mean = gray_stat.mean[0]
    g_std = gray_stat.stddev[0]
    g_min, g_max = gray.getextrema()

    # Color stats (RGB)
    rgb = cropped.convert("RGB")
    rgb_stat = ImageStat.Stat(rgb)
    r_mean, g_mean_c, b_mean = rgb_stat.mean
    r_std, g_std_c, b_std = rgb_stat.stddev

    # Dominant color heuristic: mean RGB rounded
    dominant = (int(round(r_mean)), int(round(g_mean_c)), int(round(b_mean)))

    # Edge density: simple Sobel-like measure on grayscale
    small = gray.resize((64, 64))
    px = list(small.getdata())
    edge_sum = 0
    for y in range(1, 63):
        for x in range(1, 63):
            idx = y * 64 + x
            gx = abs(px[idx + 1] - px[idx - 1])
            gy = abs(px[idx + 64] - px[idx - 64])
            edge_sum += gx + gy
    edge_density = round(edge_sum / (62 * 62), 2)

    return {
        "region": name,
        "box_px": list(box),
        "gray_mean": round(g_mean, 2),
        "gray_std": round(g_std, 2),
        "gray_min": g_min,
        "gray_max": g_max,
        "rgb_mean": [round(r_mean, 2), round(g_mean_c, 2), round(b_mean, 2)],
        "rgb_std": [round(r_std, 2), round(g_std_c, 2), round(b_std, 2)],
        "dominant_rgb": list(dominant),
        "edge_density": edge_density,
    }


def _color_histogram_summary(img: Image.Image, bins: int = 8) -> dict:
    """Simplified color histogram: divide 0-255 into bins for each channel."""
    rgb = img.convert("RGB")
    r_hist = rgb.split()[0].histogram()
    g_hist = rgb.split()[1].histogram()
    b_hist = rgb.split()[2].histogram()

    def _bin(hist, n_bins):
        step = 256 // n_bins
        total = sum(hist)
        return [round(sum(hist[i * step:(i + 1) * step]) / total, 4) for i in range(n_bins)]

    return {
        "r_hist": _bin(r_hist, bins),
        "g_hist": _bin(g_hist, bins),
        "b_hist": _bin(b_hist, bins),
    }


def _aspect_and_size(img: Image.Image) -> dict:
    w, h = img.size
    return {"width": w, "height": h, "aspect": round(w / h, 4)}


def _dark_pixel_ratio(img: Image.Image, region_frac: tuple, threshold: int = 30) -> float:
    """Fraction of pixels darker than threshold in a region. Detects dark UI bars."""
    x0f, y0f, x1f, y1f = region_frac
    w, h = img.size
    box = (int(x0f * w), int(y0f * h), int(x1f * w), int(y1f * h))
    gray = img.crop(box).convert("L")
    px = list(gray.getdata())
    if not px:
        return 0.0
    return round(sum(1 for p in px if p < threshold) / len(px), 4)


def _bright_pixel_ratio(img: Image.Image, region_frac: tuple, threshold: int = 200) -> float:
    """Fraction of pixels brighter than threshold in a region."""
    x0f, y0f, x1f, y1f = region_frac
    w, h = img.size
    box = (int(x0f * w), int(y0f * h), int(x1f * w), int(y1f * h))
    gray = img.crop(box).convert("L")
    px = list(gray.getdata())
    if not px:
        return 0.0
    return round(sum(1 for p in px if p > threshold) / len(px), 4)


def _horizontal_line_score(img: Image.Image, y_frac: float, tolerance: int = 10) -> float:
    """Detect if there's a horizontal line (UI separator) at a given Y fraction.
    Returns fraction of pixels in that row that match the row's median color."""
    w, h = img.size
    y = int(y_frac * h)
    y = max(0, min(y, h - 1))
    row = list(img.convert("L").crop((0, y, w, y + 1)).getdata())
    if not row:
        return 0.0
    median = sorted(row)[len(row) // 2]
    matching = sum(1 for p in row if abs(p - median) <= tolerance)
    return round(matching / len(row), 4)


def extract_fingerprint(image_path: str) -> dict:
    """Extract a full fingerprint from a screenshot PNG.

    The indicators focus on UI chrome (bars, edges, separators) which are
    stable regardless of what the camera is showing.
    """
    img = Image.open(image_path)

    regions = [_region_stats(img, r) for r in REGIONS]
    histogram = _color_histogram_summary(img)
    size_info = _aspect_and_size(img)

    def _r(name):
        return next(r for r in regions if r["region"] == name)

    top_bar = _r("top_bar")
    bottom_bar = _r("bottom_bar")
    app_header = _r("app_header")
    app_footer = _r("app_footer")
    left = _r("left_edge")
    right = _r("right_edge")
    center = _r("center")

    # --- Structural indicators (independent of camera content) ---

    # Dark pixel ratio in chrome zones — stable across cameras
    dark_ratio_top = _dark_pixel_ratio(img, (0.0, 0.0, 1.0, 0.04))
    dark_ratio_bottom = _dark_pixel_ratio(img, (0.0, 0.96, 1.0, 1.0))
    dark_ratio_header = _dark_pixel_ratio(img, (0.0, 0.04, 1.0, 0.12))
    dark_ratio_footer = _dark_pixel_ratio(img, (0.0, 0.88, 1.0, 0.96))
    dark_ratio_left = _dark_pixel_ratio(img, (0.0, 0.12, 0.04, 0.88))
    dark_ratio_right = _dark_pixel_ratio(img, (0.96, 0.12, 1.0, 0.88))
    bright_ratio_center = _bright_pixel_ratio(img, (0.4, 0.4, 0.6, 0.6))

    # Horizontal line detection at UI boundary positions
    # These detect separators between app header/content and content/footer
    h_line_top_border = _horizontal_line_score(img, 0.12)
    h_line_bottom_border = _horizontal_line_score(img, 0.88)
    h_line_status_bottom = _horizontal_line_score(img, 0.04)

    # UI presence booleans
    has_status_bar = top_bar["gray_mean"] > 30
    has_nav_bar = bottom_bar["gray_mean"] > 30
    has_app_header = app_header["edge_density"] > 8 or app_header["gray_std"] > 20
    has_app_footer = app_footer["edge_density"] > 8 or app_footer["gray_std"] > 20
    edges_dark = dark_ratio_left > 0.7 and dark_ratio_right > 0.7

    return {
        "size": size_info,
        "regions": regions,
        "histogram": histogram,
        "indicators": {
            # UI presence
            "has_status_bar": has_status_bar,
            "has_nav_bar": has_nav_bar,
            "has_app_header": has_app_header,
            "has_app_footer": has_app_footer,
            "edges_dark": edges_dark,
            # Raw values for threshold tuning
            "top_bar_gray_mean": top_bar["gray_mean"],
            "top_bar_gray_std": top_bar["gray_std"],
            "bottom_bar_gray_mean": bottom_bar["gray_mean"],
            "bottom_bar_gray_std": bottom_bar["gray_std"],
            "app_header_gray_mean": app_header["gray_mean"],
            "app_header_edge_density": app_header["edge_density"],
            "app_footer_gray_mean": app_footer["gray_mean"],
            "app_footer_edge_density": app_footer["edge_density"],
            "left_edge_gray_mean": left["gray_mean"],
            "left_edge_gray_std": left["gray_std"],
            "right_edge_gray_mean": right["gray_mean"],
            "right_edge_gray_std": right["gray_std"],
            "center_edge_density": center["edge_density"],
            # Dark ratios (% of dark pixels in chrome zones)
            "dark_ratio_top": dark_ratio_top,
            "dark_ratio_bottom": dark_ratio_bottom,
            "dark_ratio_header": dark_ratio_header,
            "dark_ratio_footer": dark_ratio_footer,
            "dark_ratio_left": dark_ratio_left,
            "dark_ratio_right": dark_ratio_right,
            "bright_ratio_center": bright_ratio_center,
            # Horizontal line scores at UI boundaries
            "h_line_status_bottom": h_line_status_bottom,
            "h_line_top_border": h_line_top_border,
            "h_line_bottom_border": h_line_bottom_border,
        },
    }


def capture_and_fingerprint(label: str, device_id: str | None = None) -> dict:
    """Capture a screenshot from the device and extract its fingerprint."""
    if not device_id:
        devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        if not devices:
            raise RuntimeError("Nenhum dispositivo conectado.")
        device_id = devices[0]

    os.makedirs(config.LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = os.path.join(config.LOG_DIR, f"fingerprint_{label}_{timestamp}.png")

    logger.info(f"Capturando screenshot para label='{label}' ...")
    success = adb_adapter.screencap(device_id, screenshot_path, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    if not success:
        raise RuntimeError(f"Falha ao capturar screenshot para label='{label}'.")

    logger.info(f"Extraindo fingerprint de {screenshot_path} ...")
    fp = extract_fingerprint(screenshot_path)

    result = {
        "label": label,
        "timestamp": timestamp,
        "device_id": device_id,
        "screenshot_path": screenshot_path,
        "fingerprint": fp,
    }

    # Append to profiles file
    profiles_path = os.path.join(config.LOG_DIR, "screen_profiles.json")
    existing = []
    if os.path.exists(profiles_path):
        with open(profiles_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing.append(result)
    with open(profiles_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    logger.info(f"Fingerprint salvo em {profiles_path}")
    _print_summary(result)
    return result


def _print_summary(result: dict):
    """Print a human-readable summary of the fingerprint."""
    fp = result["fingerprint"]
    ind = fp["indicators"]
    print(f"\n{'='*70}")
    print(f"  Screen Fingerprint: {result['label']}")
    print(f"{'='*70}")
    print(f"  Resolution:       {fp['size']['width']}x{fp['size']['height']}")
    print()
    print("  UI Chrome Detection (stable across cameras):")
    print(f"    Status bar:     {'YES' if ind['has_status_bar'] else 'NO':4s}  gray_mean={ind['top_bar_gray_mean']:5.1f}  dark_ratio={ind['dark_ratio_top']:.2f}")
    print(f"    Nav bar:        {'YES' if ind['has_nav_bar'] else 'NO':4s}  gray_mean={ind['bottom_bar_gray_mean']:5.1f}  dark_ratio={ind['dark_ratio_bottom']:.2f}")
    print(f"    App header:     {'YES' if ind['has_app_header'] else 'NO':4s}  gray_mean={ind['app_header_gray_mean']:5.1f}  edge_density={ind['app_header_edge_density']:.1f}  dark_ratio={ind['dark_ratio_header']:.2f}")
    print(f"    App footer:     {'YES' if ind['has_app_footer'] else 'NO':4s}  gray_mean={ind['app_footer_gray_mean']:5.1f}  edge_density={ind['app_footer_edge_density']:.1f}  dark_ratio={ind['dark_ratio_footer']:.2f}")
    print(f"    Left edge:      dark_ratio={ind['dark_ratio_left']:.2f}  gray={ind['left_edge_gray_mean']:5.1f}±{ind['left_edge_gray_std']:.1f}")
    print(f"    Right edge:     dark_ratio={ind['dark_ratio_right']:.2f}  gray={ind['right_edge_gray_mean']:5.1f}±{ind['right_edge_gray_std']:.1f}")
    print(f"    Edges dark:     {'YES' if ind['edges_dark'] else 'NO'}")
    print()
    print("  Horizontal lines (UI separators):")
    print(f"    Status bottom:  {ind['h_line_status_bottom']:.2f}")
    print(f"    Header/content: {ind['h_line_top_border']:.2f}")
    print(f"    Content/footer: {ind['h_line_bottom_border']:.2f}")
    print()
    print("  Region details:")
    for r in fp["regions"]:
        print(f"    {r['region']:14s}  gray={r['gray_mean']:6.1f}±{r['gray_std']:5.1f}  "
              f"rgb=({r['rgb_mean'][0]:5.1f},{r['rgb_mean'][1]:5.1f},{r['rgb_mean'][2]:5.1f})  "
              f"edge={r['edge_density']:5.1f}")
    print(f"{'='*70}\n")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Capture and fingerprint a device screen state.")
    parser.add_argument("--label", required=True,
                        help="Label for this screen state (e.g. home, camera_list, camera_normal, camera_fullscreen)")
    parser.add_argument("--device", default=None, help="ADB device serial (auto-detected if omitted)")
    parser.add_argument("--from-file", default=None,
                        help="Analyze an existing screenshot instead of capturing a new one")
    args = parser.parse_args()

    if args.from_file:
        fp = extract_fingerprint(args.from_file)
        result = {
            "label": args.label,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "device_id": "from_file",
            "screenshot_path": args.from_file,
            "fingerprint": fp,
        }
        _print_summary(result)

        profiles_path = os.path.join(config.LOG_DIR, "screen_profiles.json")
        existing = []
        if os.path.exists(profiles_path):
            with open(profiles_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        existing.append(result)
        os.makedirs(config.LOG_DIR, exist_ok=True)
        with open(profiles_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        print(f"Salvo em {profiles_path}")
    else:
        capture_and_fingerprint(args.label, device_id=args.device)


if __name__ == "__main__":
    main()
