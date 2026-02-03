# src/ingester/local/capture.py
import concurrent.futures
import logging
from logging.handlers import RotatingFileHandler
import os
import time
import json
import traceback
import shutil
from datetime import datetime

from PIL import Image

from . import adb_adapter, screen_classifier, screen_fingerprint
from .screen_classifier import ScreenState
from .. import config

logger = logging.getLogger(__name__)


def _ensure_logging() -> None:
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


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _append_jsonl(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _read_control_state() -> dict:
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


def _write_control_state(state: dict) -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    with open(config.CONTROL_JSON_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=True, indent=2)


def _step_start(name: str) -> dict:
    return {"name": name, "ok": False, "start": _now_iso(), "end": None, "duration_ms": None, "details": None}


def _step_end(step: dict, ok: bool, details: str | None = None) -> dict:
    step["ok"] = ok
    step["end"] = _now_iso()
    step["duration_ms"] = _duration_ms(step["start"], step["end"])
    if details:
        step["details"] = details
    return step


def _duration_ms(start_iso: str, end_iso: str) -> int:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    return int((end - start).total_seconds() * 1000)


def _validate_focus(focus: dict) -> tuple[bool, str]:
    pkg = focus.get("package")
    activity = focus.get("activity")
    if pkg != config.EXPECTED_PACKAGE:
        return False, f"focus_package_mismatch:{pkg}"
    if activity not in config.EXPECTED_ACTIVITIES:
        return False, f"focus_activity_mismatch:{activity}"
    return True, "ok"


def _analyze_image(path: str) -> dict:
    with Image.open(path) as img:
        gray = img.convert("L").resize((64, 64))
        pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    min_v = min(pixels)
    max_v = max(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    std = variance ** 0.5
    return {"mean": round(mean, 2), "std": round(std, 2), "min": min_v, "max": max_v}


def _validate_screenshot(stats: dict) -> tuple[bool, str]:
    mean = stats["mean"]
    std = stats["std"]
    if mean <= config.BLACK_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_black_screen"
    if mean >= config.WHITE_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_white_screen"
    return True, "ok"


def _write_error_artifacts(cycle_id: str, device_id: str, health: dict | None, screenshot_path: str | None) -> str:
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

    screenshot_dest = os.path.join(base_dir, "screenshot.png")
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            shutil.copyfile(screenshot_path, screenshot_dest)
        except Exception as exc:
            logger.error(f"Failed to copy screenshot: {exc}", exc_info=True)
    else:
        # No existing screenshot — capture a fresh one for diagnostics
        try:
            fresh_path = adb_adapter.screencap(device_id, screenshot_dest, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            logger.info(f"Fresh error screenshot saved: {fresh_path}")
        except Exception as exc:
            logger.error(f"Failed to capture error screenshot: {exc}", exc_info=True)

    return base_dir


def _error_obj(error_message: str | None, error_type: str | None, steps: list[dict], trace: str | None = None) -> dict | None:
    if not error_message:
        return None
    step_name = steps[-1]["name"] if steps else None
    return {
        "type": error_type or "CycleError",
        "message": error_message,
        "step": step_name,
        "trace": trace,
    }


def _capture_with_validation(device_id: str, camera_name: str) -> dict:
    last_focus = None
    last_stats = None
    last_path = None
    validation_reason = None

    attempts = config.MAX_SCREEN_RETRIES + 1
    for attempt in range(1, attempts + 1):
        if config.ENABLE_FOCUS_VALIDATION:
            focus = adb_adapter.get_focus_info(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            last_focus = focus
            focus_ok, focus_reason = _validate_focus(focus)
            if not focus_ok:
                validation_reason = focus_reason
                if attempt < attempts:
                    time.sleep(config.RETRY_DELAY_SEC)
                    continue
                return {
                    "path": None,
                    "validated": False,
                    "validation_reason": validation_reason,
                    "stats": None,
                    "attempts": attempt,
                    "focus": last_focus,
                }
        else:
            if attempt == 1:
                logger.info("Focus validation disabled by config; skipping.")

        camera_dir = os.path.join(config.OUTPUT_DIR, camera_name)
        os.makedirs(camera_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"capture_{device_id}_{timestamp}_attempt{attempt}.png"
        filepath = os.path.join(camera_dir, filename)
        last_path = filepath

        success = adb_adapter.screencap(
            device_id,
            filepath,
            timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
        )
        if not success:
            validation_reason = "screencap_failed"
            if attempt < attempts:
                time.sleep(config.RETRY_DELAY_SEC)
                continue
            return {
                "path": filepath,
                "validated": False,
                "validation_reason": validation_reason,
                "stats": None,
                "attempts": attempt,
                "focus": last_focus,
            }

        stats = _analyze_image(filepath)
        last_stats = stats
        valid, reason = _validate_screenshot(stats)
        validation_reason = reason
        if valid:
            return {
                "path": filepath,
                "validated": True,
                "validation_reason": "ok",
                "stats": stats,
                "attempts": attempt,
                "focus": last_focus,
            }

        if attempt < attempts:
            try:
                os.remove(filepath)
            except OSError:
                pass
            time.sleep(config.RETRY_DELAY_SEC)

    return {
        "path": last_path,
        "validated": False,
        "validation_reason": validation_reason,
        "stats": last_stats,
        "attempts": attempts,
        "focus": last_focus,
    }


def _check_screen(device_id: str, expected: ScreenState, context: str) -> tuple[bool, ScreenState, str | None]:
    """Take a screenshot, classify screen state, compare to expected.

    Returns (match, actual_state, screenshot_path).
    Screenshot is deleted if state matches.
    """
    if not config.ENABLE_SCREEN_STATE_DETECTION:
        logger.info(f"[{context}] Deteccao de tela desabilitada; pulando verificacao.")
        return True, ScreenState.UNKNOWN, None

    state, _fp, path = screen_classifier.capture_and_detect(device_id, context)
    match = state == expected
    if match:
        logger.info(f"[{context}] Tela OK: {state.value}")
    else:
        logger.warning(f"[{context}] Tela inesperada: esperado={expected.value} detectado={state.value}")
    # Cleanup temp screenshot
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    return match, state, path


def _recover_to_camera_list(device_id: str, current: ScreenState) -> bool:
    """Try to navigate back to the CAMERA_LIST screen."""
    logger.info(f"Recuperacao: estado atual={current.value}, objetivo=camera_list")

    if current == ScreenState.HOME:
        logger.info("Recuperacao: HOME detectado, abrindo app...")
        for attempt in range(1, config.MAX_STATE_RECOVERY_ATTEMPTS + 1):
            logger.info(f"Recuperacao: tentativa {attempt}/{config.MAX_STATE_RECOVERY_ATTEMPTS} de abrir o app...")
            if not adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS):
                continue
            time.sleep(config.STATE_CHECK_WAIT_SECONDS)
            ok, state, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, f"recovery_post_launch_attempt{attempt}")
            if ok:
                return True
            # Se caiu numa sub-tela do app (não HOME), tenta BACK
            if state != ScreenState.HOME:
                adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                time.sleep(config.STATE_CHECK_WAIT_SECONDS)
                ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, f"recovery_post_back_attempt{attempt}")
                if ok:
                    return True
            # Ainda HOME — esperar mais antes de tentar de novo
            logger.warning(f"Recuperacao: ainda em {state.value} apos tentativa {attempt}, aguardando antes de tentar novamente...")
            time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
        return False

    if current == ScreenState.CAMERA_NORMAL:
        adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        time.sleep(config.STATE_CHECK_WAIT_SECONDS)
        ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_normal")
        return ok

    if current == ScreenState.CAMERA_FULLSCREEN:
        for _ in range(2):
            adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(config.POST_BACK_DELAY_SECONDS)
        time.sleep(config.STATE_CHECK_WAIT_SECONDS)
        ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_fullscreen")
        return ok

    # UNKNOWN — try HOME + launch
    logger.info("Recuperacao: estado desconhecido, tentando HOME + launch_app...")
    adb_adapter.go_home_keyevent(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
    if not adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS):
        return False
    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
    ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_unknown")
    return ok


def _run_pre_capture_sequence(device_id: str, camera_name: str) -> None:
    """Try to enter fullscreen: direct tap, then menu + fullscreen if needed."""
    fs = config.FULLSCREEN_TAP_COORDS
    menu = config.MENU_TAP_COORDS

    logger.info(f"[{camera_name}] Tap direto fullscreen (X={fs['x']}, Y={fs['y']})...")
    adb_adapter.tap(device_id, fs["x"], fs["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)

    if not config.ENABLE_SCREEN_STATE_DETECTION:
        return

    state, _fp, path = screen_classifier.capture_and_detect(
        device_id, f"pre_capture_fullscreen_direct:{camera_name}"
    )
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

    if state == ScreenState.CAMERA_FULLSCREEN:
        return

    logger.info(f"[{camera_name}] Fullscreen direto falhou (estado={state.value}), abrindo menu...")
    adb_adapter.tap(device_id, menu["x"], menu["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    adb_adapter.tap(device_id, fs["x"], fs["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)


def _is_loading_screen(screenshot_path: str) -> bool:
    """Check if the screenshot is a loading/black screen (stream not ready yet)."""
    stats = _analyze_image(screenshot_path)
    if stats["mean"] <= config.BLACK_MEAN_THRESHOLD and stats["std"] <= config.LOW_STD_THRESHOLD:
        return True

    fp = screen_fingerprint.extract_fingerprint(screenshot_path)
    ind = fp["indicators"]
    return (
        stats["mean"] <= config.LOADING_MEAN_MAX
        and ind.get("bright_ratio_center", 0.0) >= config.LOADING_BRIGHT_CENTER_MIN
    )


def _wait_for_stream(device_id: str, camera_name: str, cam_coords: dict) -> bool:
    """Poll the screen until the stream loads or timeout is reached.

    Checks:
      1. If CAMERA_LIST → tap didn't register, retry.
      2. If CAMERA_FULLSCREEN + black screen → loading, wait and retry.
      3. Otherwise → stream is ready.

    Returns True if stream loaded, False if timed out.
    """
    timeout = config.WAIT_STREAM_LOAD_SECONDS
    poll_interval = 5
    elapsed = 0.0

    def _cleanup(p):
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass

    while elapsed < timeout:
        state, _fp, path = screen_classifier.capture_and_detect(device_id, f"stream_poll:{camera_name}")

        # If we're back on camera list, the tap didn't register — retry
        if state == ScreenState.CAMERA_LIST:
            logger.warning(f"[{camera_name}] Ainda na lista de cameras, repetindo tap...")
            _cleanup(path)
            adb_adapter.tap(device_id, cam_coords["x"], cam_coords["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(poll_interval)
            elapsed += poll_interval
            continue

        # Loading check: only in CAMERA_FULLSCREEN (black screen with loading bar)
        if state == ScreenState.CAMERA_FULLSCREEN:
            if path and os.path.exists(path) and _is_loading_screen(path):
                logger.info(f"[{camera_name}] Tela de carregamento detectada, aguardando {poll_interval}s... ({elapsed:.0f}/{timeout}s)")
                _cleanup(path)
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue

        # Not camera_list, not loading — stream is ready
        _cleanup(path)
        logger.info(f"[{camera_name}] Stream carregado (estado={state.value}, elapsed={elapsed:.0f}s)")
        return True

    logger.error(f"[{camera_name}] Timeout aguardando stream ({timeout}s)")
    return False


class CameraBatteryMonitor:
    """Per-camera battery level tracking with warning/critical state management.

    States:
        NORMAL  (>15%): capture at normal interval
        WARNING (≤15%): capture at 2× interval
        CRITICAL(≤10%): pause capture, check battery every 30min
    """

    def __init__(self):
        self._levels: dict[str, int | None] = {}
        self._last_check: dict[str, float] = {}
        self._state: dict[str, str] = {}  # "normal", "warning", "critical"

    def should_check(self, camera_name: str) -> bool:
        last = self._last_check.get(camera_name)
        if last is None:
            return True  # never checked
        state = self._state.get(camera_name, "normal")
        interval = (
            config.BATTERY_CHECK_INTERVAL_LOW_SECONDS
            if state == "critical"
            else config.BATTERY_CHECK_INTERVAL_SECONDS
        )
        return (time.monotonic() - last) >= interval

    def any_needs_check(self) -> bool:
        for cam_name in config.CAMERAS:
            if self.should_check(cam_name):
                return True
        return False

    def update(self, camera_name: str, level: int | None) -> None:
        self._levels[camera_name] = level
        self._last_check[camera_name] = time.monotonic()
        if level is None:
            return

        old_state = self._state.get(camera_name, "normal")

        if level <= config.CAMERA_BATTERY_CRITICAL_LEVEL:
            new_state = "critical"
        elif level <= config.CAMERA_BATTERY_WARNING_LEVEL:
            new_state = "warning"
        else:
            new_state = "normal"

        # Transition from critical/warning back to normal only when ≥ RESUME level
        if old_state in ("critical", "warning") and level < config.CAMERA_BATTERY_RESUME_LEVEL:
            if new_state == "normal":
                new_state = old_state  # keep current state until resume level reached

        if new_state != old_state:
            logger.info(
                f"[BATTERY] {camera_name}: {old_state} -> {new_state} (level={level}%)"
            )
        self._state[camera_name] = new_state

    def is_capture_paused(self, camera_name: str) -> bool:
        # Block capture if battery is critical OR if we never got a reading
        if camera_name not in self._levels:
            return True  # no reading yet — block until first check succeeds
        return self._state.get(camera_name) == "critical"

    def get_interval_multiplier(self) -> int:
        """Return 2 if any active camera is in warning state, else 1."""
        for cam_name in config.CAMERAS:
            state = self._state.get(cam_name, "normal")
            if state == "warning":
                return 2
        return 1

    def status(self) -> dict:
        return {
            cam: {
                "level": self._levels.get(cam),
                "state": self._state.get(cam, "unknown"),
            }
            for cam in config.CAMERAS
        }


class CameraCircuitBreaker:
    """Per-camera circuit breaker. Disables a camera after N consecutive failures for a cooldown period."""

    def __init__(self, threshold: int, cooldown_s: float):
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._failures: dict[str, int] = {}
        self._disabled_until: dict[str, float] = {}

    def record_success(self, camera_name: str) -> None:
        self._failures[camera_name] = 0
        self._disabled_until.pop(camera_name, None)

    def record_failure(self, camera_name: str) -> None:
        count = self._failures.get(camera_name, 0) + 1
        self._failures[camera_name] = count
        if count >= self._threshold:
            until = time.monotonic() + self._cooldown_s
            self._disabled_until[camera_name] = until
            logger.warning(
                f"[CB] {camera_name} desabilitada por {self._cooldown_s}s "
                f"apos {count} falhas consecutivas"
            )

    def is_available(self, camera_name: str) -> bool:
        until = self._disabled_until.get(camera_name)
        if until is None:
            return True
        if time.monotonic() >= until:
            self._disabled_until.pop(camera_name, None)
            self._failures[camera_name] = 0
            logger.info(f"[CB] {camera_name} reabilitada apos cooldown")
            return True
        remaining = until - time.monotonic()
        logger.info(f"[CB] {camera_name} ainda desabilitada ({remaining:.0f}s restantes)")
        return False

    def status(self) -> dict:
        return {
            "failures": dict(self._failures),
            "disabled": {k: round(v - time.monotonic(), 1) for k, v in self._disabled_until.items()},
        }


def _check_cameras_battery(
    device_id: str,
    battery_monitor: CameraBatteryMonitor,
    steps: list[dict],
) -> None:
    """Navigate to each camera's settings screen and read the battery level via uiautomator dump.

    Flow per camera (from camera_list):
      0. Verify we are on camera_list (recover if not)
      1. Tap camera thumbnail → enters preview
      2. Tap settings icon (X:1015, Y:150)
      3. Wait for settings screen to load
      4. uiautomator dump → parse battery
      5. BACK → BACK → back to camera_list
      6. Verify we returned to camera_list (recover if not)
    """
    settings_coords = config.CAMERA_SETTINGS_TAP_COORDS

    # --- Verify starting screen ---
    ok, state, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "battery_pre_check")
    if not ok:
        logger.warning(f"[BATTERY] Not on camera_list (state={state.value}), recovering...")
        if not _recover_to_camera_list(device_id, state):
            logger.error("[BATTERY] Failed to recover to camera_list, aborting battery check.")
            steps.append(_step_end(_step_start("battery_pre_check"), False, f"recovery_failed:{state.value}"))
            return

    for camera_name, camera_conf in config.CAMERAS.items():
        if not battery_monitor.should_check(camera_name):
            continue

        step = _step_start(f"battery_check:{camera_name}")
        level = None
        try:
            cam_coords = camera_conf["tap_coords"]

            # 1. Tap camera thumbnail
            logger.info(f"[BATTERY] {camera_name}: tap camera at ({cam_coords['x']}, {cam_coords['y']})")
            adb_adapter.tap(device_id, cam_coords["x"], cam_coords["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(config.BATTERY_CHECK_SETTINGS_WAIT_SECONDS)

            # 2. Tap settings icon
            logger.info(f"[BATTERY] {camera_name}: tap settings at ({settings_coords['x']}, {settings_coords['y']})")
            adb_adapter.tap(device_id, settings_coords["x"], settings_coords["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(config.BATTERY_CHECK_SETTINGS_WAIT_SECONDS)

            # 3. UI dump and parse
            logger.info(f"[BATTERY] {camera_name}: running uiautomator dump...")
            xml_content = adb_adapter.dump_ui_hierarchy(device_id, timeout_s=config.UIAUTOMATOR_DUMP_TIMEOUT_SECONDS)
            level = adb_adapter.parse_camera_battery_from_settings(xml_content)

            if level is not None:
                logger.info(f"[BATTERY] {camera_name}: battery level = {level}%")
            else:
                logger.warning(f"[BATTERY] {camera_name}: could not read battery level from settings screen")

            battery_monitor.update(camera_name, level)
            steps.append(_step_end(step, True, f"level={level}%"))

        except Exception as exc:
            logger.error(f"[BATTERY] {camera_name}: battery check failed: {exc}", exc_info=True)
            battery_monitor.update(camera_name, level)
            steps.append(_step_end(step, False, str(exc)))
        finally:
            # 4. Navigate back to camera_list (BACK × 2)
            try:
                for _ in range(2):
                    adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                    time.sleep(config.POST_BACK_DELAY_SECONDS)
            except Exception as exc:
                logger.warning(f"[BATTERY] {camera_name}: failed to navigate back: {exc}")

            # 5. Verify we returned to camera_list
            ok, state, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, f"battery_post:{camera_name}")
            if not ok:
                logger.warning(f"[BATTERY] {camera_name}: not on camera_list after BACK (state={state.value}), recovering...")
                if not _recover_to_camera_list(device_id, state):
                    logger.error(f"[BATTERY] {camera_name}: recovery failed, aborting remaining cameras.")
                    break

    logger.info(f"[BATTERY] Check complete: {battery_monitor.status()}")


def run_capture_batch(
    device_id: str | None = None,
    steps: list[dict] | None = None,
    camera_cb: CameraCircuitBreaker | None = None,
    battery_monitor: CameraBatteryMonitor | None = None,
) -> dict | None:
    """
    Executa um fluxo de captura para todas as cameras configuradas no app ICSee.
    Inclui verificacao de estado de tela e recuperacao automatica quando habilitado.
    """
    logger.info("Iniciando fluxo de captura para todas as cameras...")

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    active_device_id = device_id

    try:
        if not active_device_id:
            devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise RuntimeError("Nenhum dispositivo encontrado para captura.")
            active_device_id = devices[0]

        logger.info(f"Usando o dispositivo: {active_device_id}")

        # --- CHECKPOINT A: verificar se estamos na tela de lista de cameras ---
        if config.ENABLE_SCREEN_STATE_DETECTION:
            step = _step_start("checkpoint_a:verify_camera_list")
            ok, state, _ = _check_screen(active_device_id, ScreenState.CAMERA_LIST, "pre_cycle")
            if not ok:
                logger.warning(f"Checkpoint A: tela errada ({state.value}), tentando recuperar...")
                recovery_ok = _recover_to_camera_list(active_device_id, state)
                if steps is not None:
                    steps.append(_step_end(step, recovery_ok, f"recovery_from={state.value}"))
                if not recovery_ok:
                    raise RuntimeError(f"Checkpoint A falhou: nao conseguiu voltar para camera_list (estado={state.value})")
                logger.info("Checkpoint A: recuperacao bem-sucedida.")
            else:
                if steps is not None:
                    steps.append(_step_end(step, True, "camera_list_ok"))

        total_cameras = len(config.CAMERAS)
        logger.info(f"Encontradas {total_cameras} cameras para capturar.")

        last_screenshot_info = None
        cameras_skipped = 0
        cameras_failed = 0
        for i, (camera_name, camera_conf) in enumerate(config.CAMERAS.items()):
            # --- Battery: skip cameras without reading or with critically low battery ---
            if battery_monitor and battery_monitor.is_capture_paused(camera_name):
                cameras_skipped += 1
                cam_status = battery_monitor.status().get(camera_name, {})
                level = cam_status.get("level")
                if level is None:
                    reason = "no_battery_reading"
                    logger.warning(f"[{camera_name}] Captura bloqueada: sem leitura de bateria ainda")
                else:
                    reason = f"battery_critical:{level}%"
                    logger.warning(f"[{camera_name}] Captura pausada: bateria critica ({level}%)")
                if steps is not None:
                    steps.append(_step_end(_step_start(f"camera:{camera_name}:skipped_battery"), True, reason))
                continue

            # --- Circuit breaker: skip disabled cameras ---
            if camera_cb and not camera_cb.is_available(camera_name):
                cameras_skipped += 1
                if steps is not None:
                    steps.append(_step_end(_step_start(f"camera:{camera_name}:skipped_cb"), True, "circuit_breaker_open"))
                continue

            logger.info(f"--- [Camera {i+1}/{total_cameras}] Iniciando captura para: {camera_name} ---")

            try:
                # --- Etapa 1: Navegar ate a camera ---
                step = _step_start(f"camera:{camera_name}:tap")
                cam_coords = camera_conf["tap_coords"]
                logger.info(f"[{camera_name}] Acessando camera em (X={cam_coords['x']}, Y={cam_coords['y']})...")
                adb_adapter.tap(
                    active_device_id,
                    cam_coords["x"],
                    cam_coords["y"],
                    timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                )
                if steps is not None:
                    steps.append(_step_end(step, True))

                # --- Etapa 2: Aguardar stream carregar (polling) ---
                # Em vez de esperar um tempo fixo, verificamos se a tela ainda
                # esta carregando (preta) ou se voltou para a lista de cameras.
                step = _step_start(f"camera:{camera_name}:wait_stream")
                stream_ready = _wait_for_stream(active_device_id, camera_name, cam_coords)
                if steps is not None:
                    steps.append(_step_end(step, stream_ready))
                if not stream_ready:
                    logger.warning(f"[{camera_name}] Stream timeout, voltando para HOME...")
                    adb_adapter.go_home_keyevent(active_device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
                    raise RuntimeError(f"Stream nao carregou para {camera_name} dentro de {config.WAIT_STREAM_LOAD_SECONDS}s")

                # --- Etapa 3: Ritual de Estabilizacao Pre-Captura ---
                logger.info(f"[{camera_name}] Iniciando ritual de estabilizacao pre-captura...")
                step = _step_start(f"camera:{camera_name}:pre_capture")
                _run_pre_capture_sequence(active_device_id, camera_name)
                logger.info(f"[{camera_name}] Ritual de estabilizacao concluido.")
                if steps is not None:
                    steps.append(_step_end(step, True))

                # --- Etapa 4: Verificacao pre-captura ---
                # Conferir que estamos em fullscreen (nao em camera_list, loading, ou camera_normal)
                if config.ENABLE_SCREEN_STATE_DETECTION:
                    step = _step_start(f"camera:{camera_name}:pre_capture_check")
                    for retry in range(config.PRE_CAPTURE_RETRY_MAX + 1):
                        state, _fp, path = screen_classifier.capture_and_detect(
                            active_device_id, f"pre_capture_check:{camera_name}:r{retry}"
                        )
                        is_loading = (
                            state == ScreenState.CAMERA_FULLSCREEN
                            and path and os.path.exists(path)
                            and _is_loading_screen(path)
                        )
                        # Cleanup temp screenshot
                        try:
                            if path and os.path.exists(path):
                                os.remove(path)
                        except OSError:
                            pass

                        if state == ScreenState.CAMERA_LIST:
                            if steps is not None:
                                steps.append(_step_end(step, False, "voltou_para_camera_list"))
                            raise RuntimeError(f"[{camera_name}] Voltou para camera_list antes da captura")

                        if is_loading:
                            logger.warning(f"[{camera_name}] Tela de loading detectada antes da captura, aguardando 5s...")
                            time.sleep(5)
                            continue

                        if state == ScreenState.CAMERA_NORMAL:
                            if retry < config.PRE_CAPTURE_RETRY_MAX:
                                logger.warning(f"[{camera_name}] Ainda em camera_normal apos ritual (tentativa {retry+1}), repetindo ritual...")
                                _run_pre_capture_sequence(active_device_id, camera_name)
                                continue
                            else:
                                logger.error(f"[{camera_name}] Nao entrou em fullscreen apos {config.PRE_CAPTURE_RETRY_MAX+1} tentativas")
                                if steps is not None:
                                    steps.append(_step_end(step, False, "stuck_in_camera_normal"))
                                raise RuntimeError(f"[{camera_name}] Nao entrou em fullscreen apos ritual")

                        # CAMERA_FULLSCREEN (not loading) or UNKNOWN — proceed
                        break

                    if steps is not None and step.get("end") is None:
                        steps.append(_step_end(step, True, f"state={state.value}"))

                # --- Etapa 5: Capturar o Screenshot ---
                step = _step_start(f"camera:{camera_name}:screencap_validate")
                logger.info(f"[{camera_name}] Iniciando captura de screenshot com validacao...")
                screenshot_info = _capture_with_validation(active_device_id, camera_name)
                last_screenshot_info = screenshot_info
                if steps is not None:
                    steps.append(_step_end(step, screenshot_info.get("validated", False), screenshot_info.get("validation_reason")))
                if not screenshot_info.get("validated"):
                    raise RuntimeError(f"Screenshot invalid: {screenshot_info.get('validation_reason')}")

                # --- Etapa 4: Acoes Pos-Captura (Retornar N Niveis) ---
                logger.info(f"[{camera_name}] Iniciando sequencia de retorno pos-captura...")
                post_step = _step_start(f"camera:{camera_name}:post_back")
                for j in range(config.POST_CAPTURE_BACK_COUNT):
                    back_index = j + 1
                    logger.info(f"[{camera_name}] Executando BACK ({back_index}/{config.POST_CAPTURE_BACK_COUNT})...")
                    adb_adapter.press_key(
                        active_device_id,
                        "KEYCODE_BACK",
                        timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                    )
                    if back_index < config.POST_CAPTURE_BACK_COUNT:
                        logger.info(f"[{camera_name}] Aguardando {config.POST_BACK_DELAY_SECONDS}s...")
                        time.sleep(config.POST_BACK_DELAY_SECONDS)
                if steps is not None:
                    steps.append(_step_end(post_step, True))

                logger.info(f"--- [Camera {i+1}/{total_cameras}] Captura para {camera_name} concluida. ---")
                if camera_cb:
                    camera_cb.record_success(camera_name)

            except Exception as e:
                logger.error(f"--- [Camera {i+1}/{total_cameras}] Erro ao processar '{camera_name}': {e} ---", exc_info=True)
                cameras_failed += 1
                if camera_cb:
                    camera_cb.record_failure(camera_name)
                continue

            # Adiciona um delay entre as cameras para estabilizacao da UI, exceto apos a ultima.
            if i < total_cameras - 1:
                logger.info(f"Aguardando {config.INTER_CAMERA_DELAY_SECONDS}s antes de prosseguir para a proxima camera...")
                time.sleep(config.INTER_CAMERA_DELAY_SECONDS)

        # --- Check: at least one camera must have succeeded ---
        if last_screenshot_info is None:
            if cameras_skipped == total_cameras:
                raise RuntimeError(f"Todas as {total_cameras} cameras desabilitadas pelo circuit breaker")
            raise RuntimeError(f"Nenhuma camera capturada com sucesso ({cameras_failed} falhas, {cameras_skipped} puladas)")

        # --- CHECKPOINT C: verificar se voltamos para a lista de cameras ---
        if config.ENABLE_SCREEN_STATE_DETECTION:
            step = _step_start("checkpoint_c:verify_camera_list")
            ok, state, _ = _check_screen(active_device_id, ScreenState.CAMERA_LIST, "post_cycle")
            if steps is not None:
                steps.append(_step_end(step, ok, f"state={state.value}"))
            if not ok:
                logger.warning(f"Checkpoint C: ciclo terminou em estado inesperado ({state.value}). Informativo apenas.")

        return last_screenshot_info

    except Exception as e:
        logger.critical(f"Ocorreu um erro critico no fluxo de captura principal: {e}", exc_info=True)
        raise

    finally:
        if active_device_id:
            logger.info("Fluxo de captura para todas as cameras finalizado.")


def _restart_app(device_id: str, reason: str, steps: list[dict]) -> None:
    """Force-stop and relaunch the ICSee app.

    After relaunch, presses BACK to dismiss any overlay (CloudWebActivity,
    ads, webviews) that ICSee may show on cold start.
    """
    step = _step_start(f"app_restart:{reason}")
    logger.info(f"Reiniciando app: {reason}...")
    try:
        adb_adapter.close_app(device_id, config.ICSEE_PACKAGE_NAME, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        time.sleep(2)
        adb_adapter.go_home_keyevent(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        time.sleep(1)
        adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)

        # Dismiss overlays (CloudWebActivity) that appear after cold start
        for i in range(config.APP_LAUNCH_DISMISS_BACK_PRESSES):
            logger.info(f"Dismiss overlay: BACK ({i+1}/{config.APP_LAUNCH_DISMISS_BACK_PRESSES})")
            adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(config.APP_LAUNCH_DISMISS_DELAY_SECONDS)

        steps.append(_step_end(step, True))
        logger.info("App reiniciado com sucesso.")
    except Exception as exc:
        steps.append(_step_end(step, False, str(exc)))
        logger.error(f"Falha ao reiniciar app: {exc}", exc_info=True)


def _detect_and_recover_app(device_id: str, reason: str, steps: list[dict]) -> bool:
    """Detect if ICSee is in a bad state (OOM/ANR/crash) and force-restart if needed."""
    try:
        focus = adb_adapter.get_focus_info(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
        pkg = focus.get("package", "") or ""

        is_launcher = any(lp in pkg for lp in config.LAUNCHER_PACKAGES)
        is_anr = "Application Not Responding" in focus.get("raw", "") or (pkg == "android")

        if is_launcher or is_anr:
            logger.warning(f"App em estado ruim detectado: pkg={pkg}, launcher={is_launcher}, anr={is_anr}. Motivo: {reason}")
            _restart_app(device_id, f"recovery:{reason}:pkg={pkg}", steps)
            return True
        return False
    except Exception as exc:
        logger.warning(f"Nao foi possivel verificar estado do app para recovery: {exc}")
        return False


def _run_cycle_body(
    cycle_id: int,
    steps: list[dict],
    camera_cb: CameraCircuitBreaker,
    consecutive_failures: int,
    battery_monitor: CameraBatteryMonitor | None = None,
) -> tuple:
    """Cycle body extracted for watchdog wrapping. Returns (health_snapshot, screenshot_info, focus_info, device_id)."""
    step = _step_start("health_check")
    devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    if not devices:
        raise RuntimeError("Nenhum dispositivo encontrado para captura.")
    device_id = devices[0]

    # --- Memory pre-check before starting cycle ---
    if config.MEMORY_CHECK_ENABLED:
        mem_step = _step_start("memory_pre_check")
        try:
            mem_info = adb_adapter.get_mem_info(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            mem_kb = mem_info.get("mem_available_kb")
            if mem_kb is not None:
                if mem_kb < config.MEMORY_CRITICAL_THRESHOLD_KB:
                    logger.critical(
                        f"[cycle_id={cycle_id}] MEMORY CRITICAL pre-check: {mem_kb}KB. "
                        f"Rebooting device before cycle."
                    )
                    adb_adapter.reboot_device(device_id)
                    adb_adapter.wait_for_device(device_id, max_wait_s=config.MEMORY_POST_REBOOT_WAIT_SECONDS)
                    time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
                    adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                    time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
                    steps.append(_step_end(mem_step, True, f"rebooted:mem={mem_kb}KB"))
                elif mem_kb < config.MEMORY_WARNING_THRESHOLD_KB:
                    logger.warning(
                        f"[cycle_id={cycle_id}] MEMORY WARNING pre-check: {mem_kb}KB. "
                        f"Restarting app to free memory."
                    )
                    _restart_app(device_id, f"memory_warning:{mem_kb}KB", steps)
                    time.sleep(5)
                    steps.append(_step_end(mem_step, True, f"app_restarted:mem={mem_kb}KB"))
                else:
                    steps.append(_step_end(mem_step, True, f"ok:mem={mem_kb}KB"))
            else:
                steps.append(_step_end(mem_step, True, "mem_unavailable"))
        except Exception as exc:
            logger.warning(f"[cycle_id={cycle_id}] Memory pre-check failed: {exc}")
            steps.append(_step_end(mem_step, False, str(exc)))

    # --- Periodic app restart ---
    if config.APP_RESTART_EVERY_N_CYCLES > 0 and cycle_id % config.APP_RESTART_EVERY_N_CYCLES == 0:
        _restart_app(device_id, f"periodic_every_{config.APP_RESTART_EVERY_N_CYCLES}_cycles", steps)

    # --- Circuit breaker: restart app after N consecutive failures ---
    if consecutive_failures > 0 and consecutive_failures % config.CIRCUIT_BREAKER_THRESHOLD == 0:
        _restart_app(device_id, f"circuit_breaker_after_{consecutive_failures}_failures", steps)

    health_snapshot: dict | None = None
    if config.ENABLE_HEALTHCHECK:
        try:
            health_snapshot = adb_adapter.get_health_snapshot(
                device_id,
                timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS,
            )
            steps.append(_step_end(step, True))
        except Exception as exc:
            steps.append(_step_end(step, False, f"health_error:{exc}"))
            health_snapshot = {"error": str(exc)}
            logger.exception("Health check failed.")
    else:
        logger.info("Health check desabilitado por config; pulando coleta.")
        health_snapshot = {"disabled": True}
        steps.append(_step_end(step, True, "disabled_by_config"))

    # --- Camera battery check ---
    if battery_monitor and battery_monitor.any_needs_check():
        logger.info(f"[cycle_id={cycle_id}] Running camera battery check...")
        _check_cameras_battery(device_id, battery_monitor, steps)

    step = _step_start("capture_batch")
    screenshot_info = run_capture_batch(
        device_id=device_id, steps=steps, camera_cb=camera_cb,
        battery_monitor=battery_monitor,
    )
    focus_info = screenshot_info.get("focus") if screenshot_info else None
    steps.append(_step_end(step, True))

    return health_snapshot, screenshot_info, focus_info, device_id


def run_forever_loop():
    _ensure_logging()
    cycle_id = 0
    consecutive_failures = 0
    max_cycles = config.MAX_CYCLES
    if max_cycles == 0:
        max_cycles = None

    camera_cb = CameraCircuitBreaker(
        threshold=config.CAMERA_CB_FAILURE_THRESHOLD,
        cooldown_s=config.CAMERA_CB_COOLDOWN_SECONDS,
    )
    battery_monitor = CameraBatteryMonitor()

    while True:
        control = _read_control_state()
        if control.get("stop"):
            logger.info("Controle: stop solicitado. Encerrando loop.")
            break
        if control.get("pause") and not control.get("run_once"):
            logger.info("Controle: pausa ativa. Aguardando para retomar...")
            time.sleep(5)
            continue
        run_once = control.get("run_once", False)

        cycle_id += 1
        cycle_start = time.time()
        cycle_id_str = f"{cycle_id}"
        ts_start = _now_iso()
        logger.info(f"[cycle_id={cycle_id}] Ciclo iniciado.")
        cycle_error = None
        cycle_error_type = None
        cycle_trace = None
        steps: list[dict] = []
        focus_info: dict | None = None
        health_snapshot: dict | None = None
        screenshot_info: dict | None = None
        device_id = None

        try:
            # --- Watchdog: run cycle body with global timeout ---
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _run_cycle_body, cycle_id, steps, camera_cb, consecutive_failures,
                    battery_monitor,
                )
                try:
                    health_snapshot, screenshot_info, focus_info, device_id = future.result(
                        timeout=config.CYCLE_TIMEOUT_SECONDS,
                    )
                except concurrent.futures.TimeoutError:
                    logger.error(
                        f"[cycle_id={cycle_id}] Watchdog timeout! Ciclo excedeu {config.CYCLE_TIMEOUT_SECONDS}s. "
                        f"Reiniciando ADB server para desbloquear."
                    )
                    adb_adapter._restart_adb_server()
                    raise RuntimeError(f"Watchdog timeout apos {config.CYCLE_TIMEOUT_SECONDS}s")

            consecutive_failures = 0

        except Exception as exc:
            cycle_error = str(exc)
            cycle_error_type = type(exc).__name__
            cycle_trace = traceback.format_exc()
            consecutive_failures += 1
            logger.error(f"[cycle_id={cycle_id}] Erro no ciclo (falha consecutiva #{consecutive_failures}): {exc}", exc_info=True)

            # --- App recovery: detect OOM/ANR/crash and force-restart ---
            if device_id:
                _detect_and_recover_app(device_id, f"cycle_error:{cycle_error_type}", steps)

            # Exponential backoff
            backoff = min(
                config.ERROR_BACKOFF_BASE_SECONDS * (2 ** (consecutive_failures - 1)),
                config.ERROR_BACKOFF_MAX_SECONDS,
            )
            logger.info(f"[cycle_id={cycle_id}] Aplicando backoff exponencial de {backoff:.0f}s.")

            if device_id:
                _write_error_artifacts(cycle_id_str, device_id, health_snapshot, screenshot_info.get("path") if screenshot_info else None)
            time.sleep(backoff)
        finally:
            cycle_end = time.time()
            cycle_duration_s = round(cycle_end - cycle_start, 3)
            ts_end = _now_iso()

            event = {
                "cycle_id": cycle_id_str,
                "ts_start": ts_start,
                "ts_end": ts_end,
                "duration_ms": int(cycle_duration_s * 1000),
                "ok": cycle_error is None,
                "error": _error_obj(cycle_error, cycle_error_type, steps, cycle_trace),
                "steps": steps,
                "focus": focus_info,
                "health": health_snapshot,
                "screenshot": screenshot_info,
                "camera_cb": camera_cb.status(),
                "camera_battery": battery_monitor.status(),
            }
            _append_jsonl(config.CYCLES_JSONL_PATH, event)

            logger.info(f"[cycle_id={cycle_id}] Ciclo finalizado em {cycle_duration_s}s.")

            if not cycle_error:
                elapsed = cycle_end - cycle_start
                interval = config.CAPTURE_INTERVAL_SECONDS * battery_monitor.get_interval_multiplier()
                sleep_seconds = max(0, interval - elapsed)
                if battery_monitor.get_interval_multiplier() > 1:
                    logger.info(
                        f"[cycle_id={cycle_id}] Intervalo dobrado por bateria baixa "
                        f"({config.CAPTURE_INTERVAL_SECONDS}s -> {interval}s)"
                    )
                if sleep_seconds > 0:
                    logger.info(f"[cycle_id={cycle_id}] Dormindo {sleep_seconds:.1f}s ate o proximo ciclo.")
                    time.sleep(sleep_seconds)

        # --- Max consecutive failures: stop loop entirely ---
        if consecutive_failures >= config.MAX_CONSECUTIVE_FAILURES:
            logger.critical(
                f"[cycle_id={cycle_id}] {consecutive_failures} falhas consecutivas atingiram o limite "
                f"de {config.MAX_CONSECUTIVE_FAILURES}. Encerrando loop para evitar danos ao dispositivo."
            )
            break

        if run_once:
            control["run_once"] = False
            _write_control_state(control)

        if not config.RUN_FOREVER and max_cycles and cycle_id >= max_cycles:
            logger.info(f"[cycle_id={cycle_id}] Encerrando loop (MAX_CYCLES atingido).")
            break


def run_capture():
    """Executa o fluxo de captura para todas as cameras configuradas."""
    run_capture_batch()


if __name__ == "__main__":
    run_capture()
