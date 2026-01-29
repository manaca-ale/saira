# src/ingester/local/screen_classifier.py
"""
Screen state classifier for the ICSee capture flow.

Detects which screen the device is currently showing by analyzing
UI chrome (bars, edges, headers) — NOT camera content, which varies.
"""
import logging
import os
import re
import tempfile
from enum import Enum

from . import adb_adapter, screen_fingerprint
from .. import config

logger = logging.getLogger(__name__)


class ScreenState(Enum):
    HOME = "home"
    CAMERA_LIST = "camera_list"
    CAMERA_NORMAL = "camera_normal"
    CAMERA_FULLSCREEN = "camera_fullscreen"
    UNKNOWN = "unknown"


def detect_screen_state(image_path: str) -> tuple[ScreenState, dict]:
    """Classify screen state from a screenshot.

    Returns (state, fingerprint_dict).
    """
    fp = screen_fingerprint.extract_fingerprint(image_path)
    ind = fp["indicators"]
    thresh = config.SCREEN_STATE_THRESHOLDS

    state = _classify(ind, thresh)

    logger.info(
        f"Screen state detected: {state.value} | "
        f"dark_top={ind['dark_ratio_top']:.2f} "
        f"dark_left={ind['dark_ratio_left']:.2f} "
        f"h_line_status={ind['h_line_status_bottom']:.2f} "
        f"dark_header={ind['dark_ratio_header']:.2f} "
        f"center_edge={ind['center_edge_density']:.1f}"
    )

    return state, fp


def _classify(ind: dict, thresh: dict) -> ScreenState:
    """Decision tree based on raw indicator values.

    Evaluation order (most distinctive first):
      1. camera_normal:     dark_ratio_top >= 0.5
      2. camera_fullscreen: dark_ratio_left >= 0.7
      3. home:              h_line_status_bottom <= 0.3
      4. camera_list:       h_line_status_bottom > 0.3 AND sanity checks pass
      5. UNKNOWN:           fallback when nothing fits

    Each positive match also runs a sanity check to avoid false positives.
    """
    t_norm = thresh.get("camera_normal", {})
    t_fs = thresh.get("camera_fullscreen", {})
    t_home = thresh.get("home", {})
    t_sanity = thresh.get("sanity", {})

    dark_top = ind["dark_ratio_top"]
    dark_left = ind["dark_ratio_left"]
    h_line = ind["h_line_status_bottom"]

    # Valores de referência observados:
    #   dark_ratio_top:  home=0.02, list=0.01, normal=0.76, full=0.04
    #   dark_ratio_left: home=0.004, list=0, normal=0.15, full=0.86
    #   h_line_status:   home=0.11, list=0.79, normal=0.80, full=0.3-0.6

    # 1. CAMERA_NORMAL: topo muito escuro (~0.76)
    #    Sanity: dark_left deve ser baixo (não é fullscreen)
    if dark_top >= t_norm.get("dark_ratio_top_min", 0.5):
        if dark_left < t_fs.get("dark_ratio_left_min", 0.7):
            return ScreenState.CAMERA_NORMAL
        # Topo escuro E borda escura — improvável, marcar como desconhecido
        logger.warning(f"Classificacao ambigua: dark_top={dark_top:.2f} E dark_left={dark_left:.2f} altos")
        return ScreenState.UNKNOWN

    # 2. CAMERA_FULLSCREEN: borda esquerda escura (~0.86)
    #    Sanity: topo NÃO deve ser escuro (já foi descartado acima)
    if dark_left >= t_fs.get("dark_ratio_left_min", 0.7):
        return ScreenState.CAMERA_FULLSCREEN

    # 3. HOME: sem linha de status do app (~0.11)
    #    Sanity: dark_top e dark_left devem ser baixos
    if h_line <= t_home.get("h_line_status_bottom_max", 0.3):
        if dark_top < 0.15 and dark_left < 0.15:
            return ScreenState.HOME
        logger.warning(f"Classificacao ambigua: h_line={h_line:.2f} baixo mas dark_top={dark_top:.2f} dark_left={dark_left:.2f}")
        return ScreenState.UNKNOWN

    # 4. CAMERA_LIST: h_line alto (~0.79), dark ratios baixos
    #    Sanity: tela deve ser "brilhante" — dark ratios todos baixos
    max_dark = t_sanity.get("camera_list_max_dark", 0.3)
    if dark_top < max_dark and dark_left < max_dark:
        return ScreenState.CAMERA_LIST

    # 5. Nada se encaixou
    logger.warning(
        f"Estado desconhecido: dark_top={dark_top:.2f} dark_left={dark_left:.2f} "
        f"h_line={h_line:.2f} — nenhuma regra se encaixou"
    )
    return ScreenState.UNKNOWN


def capture_and_detect(
    device_id: str,
    context: str,
) -> tuple[ScreenState, dict, str]:
    """Take a screenshot and detect the screen state.

    Args:
        device_id: ADB device serial.
        context: Label for logging / filename (e.g. "pre_cycle").

    Returns:
        (state, fingerprint, screenshot_path)
    """
    safe_context = _sanitize_filename(context)
    fd, filepath = tempfile.mkstemp(prefix=f"state_{safe_context}_", suffix=".png")
    os.close(fd)

    success = adb_adapter.screencap(
        device_id, filepath, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS
    )
    if not success:
        logger.error(f"[{context}] Screenshot failed for state detection.")
        return ScreenState.UNKNOWN, {}, filepath

    state, fp = detect_screen_state(filepath)
    return state, fp, filepath


def _sanitize_filename(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\\\|?*]+', "_", value)
    sanitized = re.sub(r"\\s+", "_", sanitized).strip("_")
    return sanitized or "state"
