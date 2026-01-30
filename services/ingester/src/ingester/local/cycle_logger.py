# src/ingester/local/cycle_logger.py
"""Cycle logging, step tracking, control state, and error artifact collection."""
import json
import logging
import os
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler

from . import adb_adapter
from .. import config

logger = logging.getLogger(__name__)


def ensure_logging() -> None:
    """Set up rotating file + console logging if not already configured."""
    if logging.getLogger().handlers:
        return
    os.makedirs(config.LOG_DIR, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        os.path.join(config.LOG_DIR, "ingester.log"),
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def append_jsonl(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def read_control_state() -> dict:
    path = config.CONTROL_JSON_PATH
    if not os.path.exists(path):
        return {"pause": False, "stop": False, "run_once": False}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"pause": False, "stop": False, "run_once": False}
    return {
        "pause": bool(data.get("pause", False)),
        "stop": bool(data.get("stop", False)),
        "run_once": bool(data.get("run_once", False)),
    }


def write_control_state(state: dict) -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    with open(config.CONTROL_JSON_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=True, indent=2)


def step_start(name: str) -> dict:
    return {"name": name, "ok": False, "start": now_iso(), "end": None, "duration_ms": None, "details": None}


def step_end(step: dict, ok: bool, details: str | None = None) -> dict:
    step["ok"] = ok
    step["end"] = now_iso()
    step["duration_ms"] = _duration_ms(step["start"], step["end"])
    if details:
        step["details"] = details
    return step


def _duration_ms(start_iso: str, end_iso: str) -> int:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    return int((end - start).total_seconds() * 1000)


def error_obj(error_message: str | None, error_type: str | None, steps: list[dict], trace: str | None = None) -> dict | None:
    if not error_message:
        return None
    step_name = steps[-1]["name"] if steps else None
    return {
        "type": error_type or "CycleError",
        "message": error_message,
        "step": step_name,
        "trace": trace,
    }


def write_error_artifacts(cycle_id: str, device_id: str, health: dict | None, screenshot_path: str | None) -> str:
    base_dir = os.path.join(config.LOG_DIR, f"cycle_{cycle_id}_artifacts")
    os.makedirs(base_dir, exist_ok=True)

    window_txt = os.path.join(base_dir, "window.txt")
    logcat_txt = os.path.join(base_dir, "logcat.txt")
    health_json = os.path.join(base_dir, "health.json")

    if config.ENABLE_FOCUS_VALIDATION:
        try:
            window_dump = adb_adapter.get_window_dump(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            with open(window_txt, "w", encoding="utf-8") as handle:
                handle.write(window_dump)
        except Exception as exc:
            logger.error(f"Failed to write window.txt: {exc}", exc_info=True)
    else:
        logger.info("Skipping window.txt artifact (focus validation disabled).")

    try:
        logcat = adb_adapter.get_logcat_tail(device_id, config.LOGCAT_LINES_ON_ERROR, config.HEALTH_ADB_TIMEOUT_SECONDS)
        with open(logcat_txt, "w", encoding="utf-8") as handle:
            handle.write(logcat)
    except Exception as exc:
        logger.error(f"Failed to write logcat.txt: {exc}", exc_info=True)

    try:
        with open(health_json, "w", encoding="utf-8") as handle:
            json.dump(health or {}, handle, ensure_ascii=True, indent=2)
    except Exception as exc:
        logger.error(f"Failed to write health.json: {exc}", exc_info=True)

    if screenshot_path and os.path.exists(screenshot_path):
        try:
            shutil.copyfile(screenshot_path, os.path.join(base_dir, "screenshot.png"))
        except Exception as exc:
            logger.error(f"Failed to copy screenshot: {exc}", exc_info=True)

    return base_dir
