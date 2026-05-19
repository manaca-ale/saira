# src/ingester/local/test_classifier.py
"""
Quick test: captures a screenshot and prints the detected screen state.

Usage (from ingester root):
    python -m ingester.local.test_classifier
"""
import logging

from . import adb_adapter, screen_classifier
from .. import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    if not devices:
        print("Nenhum dispositivo conectado.")
        return
    device_id = devices[0]
    print(f"Dispositivo: {device_id}\n")

    state, fp, path = screen_classifier.capture_and_detect(device_id, "test")
    ind = fp.get("indicators", {})

    dark_top = ind.get("dark_ratio_top", 0)
    dark_left = ind.get("dark_ratio_left", 0)
    h_line = ind.get("h_line_status_bottom", 0)

    t = config.SCREEN_STATE_THRESHOLDS
    t_top = t.get("camera_normal", {}).get("dark_ratio_top_min", 0.5)
    t_left = t.get("camera_fullscreen", {}).get("dark_ratio_left_min", 0.7)
    t_hline = t.get("home", {}).get("h_line_status_bottom_max", 0.3)
    t_sanity = t.get("sanity", {}).get("camera_list_max_dark", 0.3)

    def _mark(hit):
        return "<<< MATCH" if hit else ""

    r1 = dark_top >= t_top
    r2 = (not r1) and dark_left >= t_left
    r3 = (not r1 and not r2) and h_line <= t_hline
    r4 = (not r1 and not r2 and not r3) and dark_top < t_sanity and dark_left < t_sanity
    r5 = not (r1 or r2 or r3 or r4)

    print(f"\n{'='*60}")
    print(f"  ESTADO DETECTADO:  {state.value.upper()}")
    print(f"{'='*60}")
    print(f"  Regras (avaliadas em ordem):")
    print(f"    1. dark_ratio_top  = {dark_top:.4f}  >= {t_top}  → camera_normal     {_mark(r1)}")
    print(f"    2. dark_ratio_left = {dark_left:.4f}  >= {t_left}  → camera_fullscreen {_mark(r2)}")
    print(f"    3. h_line_status   = {h_line:.4f}  <= {t_hline}  → home              {_mark(r3)}")
    print(f"    4. dark_top & left < {t_sanity}          → camera_list        {_mark(r4)}")
    print(f"    5. nenhuma regra                  → UNKNOWN            {_mark(r5)}")
    print(f"\n  Screenshot: {path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
