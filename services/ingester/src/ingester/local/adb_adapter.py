# src/ingester/local/adb_adapter.py
import logging
import subprocess
import re
import time
from typing import Any

from .. import config

logger = logging.getLogger(__name__)


class AdbCommandError(RuntimeError):
    def __init__(self, cmd: str, returncode: int, stdout: str, stderr: str):
        super().__init__(f"ADB command failed (code={returncode}): {cmd}")
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class AdbTimeoutError(TimeoutError):
    def __init__(self, cmd: str, timeout_s: float):
        super().__init__(f"ADB command timed out after {timeout_s}s: {cmd}")
        self.cmd = cmd
        self.timeout_s = timeout_s


def _run_command(
    command: list[str],
    timeout_s: float | None = None,
    check: bool = True,
    retry_on_timeout: bool = False,
) -> subprocess.CompletedProcess:
    """Run an adb command list with timeout and duration logging."""
    full_command = ["adb"] + command
    cmd_str = " ".join(full_command)
    start = time.monotonic()
    if timeout_s is None:
        timeout_s = config.CAPTURE_ADB_TIMEOUT_SECONDS

    try:
        process = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        duration_s = time.monotonic() - start
        logger.warning(f"ADB timeout duration={duration_s:.3f}s cmd={cmd_str}")
        if retry_on_timeout:
            logger.warning("ADB retry on timeout: restarting server and retrying once.")
            _restart_adb_server()
            return _run_command(
                command,
                timeout_s=timeout_s,
                check=check,
                retry_on_timeout=False,
            )
        raise AdbTimeoutError(cmd_str, timeout_s if timeout_s is not None else -1)

    duration_s = time.monotonic() - start
    logger.info(f"ADB done duration={duration_s:.3f}s exit_code={process.returncode} cmd={cmd_str}")

    if process.stdout:
        logger.debug(f"ADB stdout: {process.stdout.strip()}")
    if process.stderr:
        logger.debug(f"ADB stderr: {process.stderr.strip()}")

    if check and process.returncode != 0:
        stdout_tail = _tail_text(process.stdout or "", config.ADB_ERROR_OUTPUT_TAIL_CHARS)
        stderr_tail = _tail_text(process.stderr or "", config.ADB_ERROR_OUTPUT_TAIL_CHARS)
        logger.warning(
            "ADB command failed; stdout_tail=%s stderr_tail=%s",
            stdout_tail,
            stderr_tail,
        )
        raise AdbCommandError(cmd_str, process.returncode, process.stdout or "", process.stderr or "")

    return process


def run_shell(cmd: str, timeout_s: float) -> str:
    """Run an adb shell command on the first connected device."""
    devices = list_devices(timeout_s=timeout_s)
    if not devices:
        raise AdbCommandError("adb devices", 1, "", "No devices")
    result = _run_shell_cmd(devices[0], cmd, timeout_s=timeout_s, check=True)
    return (result.stdout or "").strip()


def _run_shell_cmd(
    device_id: str,
    cmd: str,
    timeout_s: float | None = None,
    check: bool = True,
    retry_on_timeout: bool = False,
) -> subprocess.CompletedProcess:
    # Use sh -c only for commands with shell metacharacters (pipes, redirects, etc.)
    _shell_meta = set("|&;<>()$`\\\"'")
    needs_shell = any(c in _shell_meta for c in cmd)
    if needs_shell:
        args = ["-s", device_id, "shell", "sh", "-c", cmd]
    else:
        args = ["-s", device_id, "shell"] + cmd.split()
    return _run_command(
        args,
        timeout_s=timeout_s,
        check=check,
        retry_on_timeout=retry_on_timeout,
    )


def list_devices(timeout_s: float | None = None) -> list[str]:
    """List connected adb device serials."""
    logger.info("Listing ADB devices...")
    _run_command(["start-server"], timeout_s=timeout_s, check=False)
    result = _run_command(["devices"], timeout_s=timeout_s, check=True)
    device_lines = re.findall(r"^(.+?)\s+device$", result.stdout, re.MULTILINE)
    if not device_lines:
        logger.warning("No ADB devices found.")
        return []
    logger.info(f"Devices found: {device_lines}")
    return device_lines


def go_home_monkey(device_id: str, timeout_s: float | None = None):
    logger.info(f"Going Home via monkey on device {device_id}...")
    _run_command(["-s", device_id, "shell", "monkey", "-c", "android.intent.category.LAUNCHER", "1"], timeout_s=timeout_s)


def go_home_keyevent(device_id: str, timeout_s: float | None = None):
    logger.info(f"Going Home via KEYCODE_HOME on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "keyevent", "3"], timeout_s=timeout_s)


def close_app(device_id: str, package_name: str, timeout_s: float | None = None):
    logger.info(f"Force-stopping '{package_name}' on device {device_id}...")
    _run_command(["-s", device_id, "shell", "am", "force-stop", package_name], timeout_s=timeout_s)


def tap(device_id: str, x: int, y: int, timeout_s: float | None = None):
    logger.info(f"Tap (X={x}, Y={y}) on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "tap", str(x), str(y)], timeout_s=timeout_s)


def press_key(device_id: str, keycode: str, timeout_s: float | None = None):
    logger.info(f"Keyevent '{keycode}' on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "keyevent", keycode], timeout_s=timeout_s)


def swipe(device_id: str, x1: int, y1: int, x2: int, y2: int, duration: int = 300, timeout_s: float | None = None):
    logger.info(f"Swipe ({x1},{y1}) -> ({x2},{y2}) on device {device_id}...")
    _run_command(["-s", device_id, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)], timeout_s=timeout_s)


def screencap(device_id: str, local_path: str, timeout_s: float | None = None) -> bool:
    remote_path = "/sdcard/saira_capture.png"
    logger.info(f"Screencap device {device_id} to {local_path}...")
    try:
        _run_command(["-s", device_id, "shell", "screencap", remote_path], timeout_s=timeout_s)
        _run_command(["-s", device_id, "pull", remote_path, local_path], timeout_s=timeout_s)
        _run_command(["-s", device_id, "shell", "rm", remote_path], timeout_s=timeout_s)
        logger.info(f"Screenshot saved: {local_path}")
        return True
    except (AdbCommandError, AdbTimeoutError):
        logger.error(f"Failed to screencap device {device_id}.")
        return False


def launch_app(device_id: str, timeout_s: float | None = None) -> bool:
    """Launch the ICSee app by tapping its icon on the home screen.

    Assumes the device is already on the HOME screen.
    """
    coords = config.APP_ICON_TAP_COORDS
    if not coords:
        logger.error("APP_ICON_TAP_COORDS nao configurado.")
        return False

    logger.info(f"Abrindo app: tap no icone em ({coords['x']}, {coords['y']})")
    try:
        tap(device_id, coords["x"], coords["y"], timeout_s=timeout_s)
        time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
        return True
    except Exception as exc:
        logger.error(f"Falha ao abrir app via tap: {exc}")
        return False


def get_device_state(device_id: str, timeout_s: float | None = None) -> str:
    result = _run_command(["-s", device_id, "get-state"], timeout_s=timeout_s, check=False)
    return (result.stdout or "").strip()


def get_health_snapshot(device_id: str, timeout_s: float) -> dict[str, Any]:
    if not config.ENABLE_HEALTHCHECK:
        logger.info("Health check disabled by config; skipping device health collection.")
        return {"disabled": True, "device_id": device_id}

    errors: list[str] = []
    snapshot: dict[str, Any] = {"device_id": device_id}
    warn_exc = logger.isEnabledFor(logging.DEBUG)

    try:
        snapshot["adb_state"] = get_device_state(device_id, timeout_s=timeout_s)
        snapshot["adb_ok"] = True
    except Exception as exc:
        errors.append(f"adb_state: {exc}")
        snapshot["adb_ok"] = False
        logger.warning(f"ADB state check failed: {exc}", exc_info=warn_exc)

    try:
        snapshot.update(get_battery_info(device_id, timeout_s))
    except Exception as exc:
        errors.append(f"battery: {exc}")
        logger.warning(f"Battery check failed: {exc}", exc_info=warn_exc)

    try:
        snapshot.update(get_uptime_info(device_id, timeout_s))
    except Exception as exc:
        errors.append(f"uptime: {exc}")
        logger.warning(f"Uptime check failed: {exc}", exc_info=warn_exc)

    try:
        snapshot.update(get_storage_info(device_id, timeout_s, "/data"))
    except Exception as exc:
        errors.append(f"storage: {exc}")
        logger.warning(f"Storage check failed: {exc}", exc_info=warn_exc)

    try:
        snapshot.update(get_network_info(device_id, timeout_s))
    except Exception as exc:
        errors.append(f"network: {exc}")
        logger.warning(f"Network check failed: {exc}", exc_info=warn_exc)

    try:
        snapshot.update(get_mem_info(device_id, timeout_s))
    except Exception as exc:
        errors.append(f"mem: {exc}")
        logger.warning(f"Mem check failed: {exc}", exc_info=warn_exc)

    if config.ENABLE_CONNECTIVITY_DUMPSYS:
        try:
            result = _run_shell_cmd(device_id, "dumpsys connectivity | head -n 80", timeout_s=timeout_s, check=False)
            snapshot["connectivity_dumpsys"] = (result.stdout or "").splitlines()
        except Exception as exc:
            errors.append(f"connectivity_dumpsys: {exc}")
            logger.warning(f"Connectivity dumpsys failed: {exc}", exc_info=warn_exc)

    snapshot["_errors"] = errors
    return snapshot


def get_battery_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    battery_timeout = max(timeout_s, config.BATTERY_DUMPSYS_TIMEOUT_SECONDS)
    result = _run_shell_cmd(
        device_id,
        "dumpsys battery",
        timeout_s=battery_timeout,
        check=True,
        retry_on_timeout=True,
    )
    text = result.stdout or ""
    level = _extract_int(text, r"level:\s*(\d+)")
    status = _extract_int(text, r"status:\s*(\d+)")
    temperature = _extract_int(text, r"temperature:\s*(\d+)")
    voltage = _extract_int(text, r"voltage:\s*(\d+)")
    usb_powered = _extract_bool(text, r"USB powered:\s*(\w+)")
    ac_powered = _extract_bool(text, r"AC powered:\s*(\w+)")

    battery_temp_c = None
    if temperature is not None:
        battery_temp_c = temperature / 10.0

    return {
        "battery_level": level,
        "battery_status": status,
        "battery_temp_c": battery_temp_c,
        "battery_voltage_mv": voltage,
        "battery_usb_powered": usb_powered,
        "battery_ac_powered": ac_powered,
    }


def get_uptime_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, "cat /proc/uptime", timeout_s=timeout_s, check=True)
    uptime_s = _extract_float(result.stdout or "", r"^([\d\.]+)")
    return {"uptime_s": uptime_s}


def get_storage_info(device_id: str, timeout_s: float, mount_point: str) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, f"df {mount_point}", timeout_s=timeout_s, check=True)
    available_kb = _parse_df_available_kb(result.stdout or "", mount_point)
    return {"storage_available_kb": available_kb}


def get_network_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, "ip -f inet addr show wlan0", timeout_s=timeout_s, check=False)
    wlan0_ip = _extract_ip_addr(result.stdout or "")

    routes_result = _run_shell_cmd(device_id, "ip route", timeout_s=timeout_s, check=False)
    routes_raw = (routes_result.stdout or "").splitlines()
    default_route = _has_default_route(routes_raw)

    internet_ok = False
    method = None
    ping_result = _run_shell_cmd(device_id, "ping -c 1 -W 2 1.1.1.1", timeout_s=timeout_s, check=False)
    if ping_result.returncode == 0:
        internet_ok = True
        method = "ping"
    else:
        http_ok = _http_connectivity_check(device_id, timeout_s)
        if http_ok:
            internet_ok = True
            method = "http"

    info: dict[str, Any] = {
        "wlan0_ip": wlan0_ip,
        "internet_ok": internet_ok,
        "method": method,
        "default_route": default_route,
    }

    if not default_route:
        info["routes_raw"] = routes_raw[:5]

    return info


def get_mem_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    result = _run_shell_cmd(device_id, "cat /proc/meminfo", timeout_s=timeout_s, check=False)
    mem_available_kb = _extract_int(result.stdout or "", r"MemAvailable:\s*(\d+)\s*kB")
    return {"mem_available_kb": mem_available_kb}


def get_window_dump(device_id: str, timeout_s: float) -> str:
    result = _run_shell_cmd(device_id, "dumpsys window", timeout_s=timeout_s, check=False)
    return result.stdout or ""


def get_focus_info(device_id: str, timeout_s: float) -> dict[str, Any]:
    raw = get_window_dump(device_id, timeout_s=timeout_s)
    focus = parse_window_dump(raw)
    logger.info(f"Focus detected source={focus.get('raw_match_source')} component={focus.get('component')}")
    return focus


def get_logcat_tail(device_id: str, lines: int, timeout_s: float) -> str:
    cmd = f"logcat -d -t {lines}"
    result = _run_shell_cmd(device_id, cmd, timeout_s=timeout_s, check=False)
    return result.stdout or ""


def _http_connectivity_check(device_id: str, timeout_s: float) -> bool:
    cmd = (
        "(command -v curl >/dev/null 2>&1 && curl -s --max-time 3 -o /dev/null "
        "http://connectivitycheck.gstatic.com/generate_204) "
        "|| (command -v wget >/dev/null 2>&1 && wget -q --spider --timeout=3 "
        "http://connectivitycheck.gstatic.com/generate_204) "
        "|| (command -v toybox >/dev/null 2>&1 && toybox wget -q --spider --timeout=3 "
        "http://connectivitycheck.gstatic.com/generate_204)"
    )
    result = _run_shell_cmd(device_id, cmd, timeout_s=timeout_s, check=False)
    return result.returncode == 0


def _has_default_route(routes: list[str]) -> bool:
    for line in routes:
        if not line:
            continue
        if line.startswith("default"):
            return True
        if "0.0.0.0/0" in line:
            return True
    return False


def _extract_ip_addr(text: str) -> str | None:
    match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", text or "")
    if match:
        return match.group(1)
    return None


def _extract_first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if match:
        return match.group(0)
    return None


def _window_excerpt(text: str, max_lines: int = 5) -> str:
    lines = []
    for line in (text or "").splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line or "mObscuringWindow" in line:
            lines.append(line.strip())
        if len(lines) >= max_lines:
            break
    return " | ".join(lines)


def parse_window_dump(raw: str) -> dict[str, Any]:
    component, source, raw_line = _find_focus_component(raw)
    pkg, activity = _split_component(component)
    insets = _extract_insets(raw)
    obscuring = _extract_first_match(raw, r"mObscuringWindow=Window\{[^}]+\}")
    return {
        "package": pkg,
        "activity": activity,
        "component": component,
        "insets": insets,
        "raw_match_source": source,
        "raw": raw_line,
        "wm_obscuring_window": obscuring,
        "window_dump_excerpt": _window_excerpt(raw),
    }


def _find_focus_component(raw: str) -> tuple[str | None, str, str]:
    patterns = [
        ("imeTarget", r"imeLayeringTarget.*?([\w.]+/[\w.$]+)"),
        ("imeInputTarget", r"imeInputTarget.*?([\w.]+/[\w.$]+)"),
        ("currentFocus", r"mCurrentFocus=.*?([\w.]+/[\w.$]+)"),
        ("focusedApp", r"mFocusedApp=.*?([\w.]+/[\w.$]+)"),
        ("resumedActivity", r"mResumedActivity:.*?([\w.]+/[\w.$]+)"),
        ("lastWakeLockObscuringWindow", r"mLastWakeLockObscuringWindow=.*?([\w.]+/[\w.$]+)"),
        ("obscuringWindow", r"mObscuringWindow=.*?([\w.]+/[\w.$]+)"),
    ]
    for name, pattern in patterns:
        match = re.search(pattern, raw or "", re.MULTILINE)
        if match:
            return match.group(1), name, match.group(0)
    fallback = re.search(r"([\w.]+/[\w.$]+)", raw or "", re.MULTILINE)
    if fallback:
        return fallback.group(1), "fallback", fallback.group(0)
    return None, "unknown", ""


def _split_component(component: str | None) -> tuple[str | None, str | None]:
    if not component:
        return None, None
    parts = component.split("/", 1)
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1]


def _extract_insets(raw: str) -> dict[str, int] | None:
    match = re.search(r"mContentInsets=\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw or "")
    if not match:
        return None
    left, top, right, bottom = [int(value) for value in match.groups()]
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _extract_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _extract_bool(text: str, pattern: str) -> bool | None:
    match = re.search(pattern, text or "", re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    return None


def _parse_df_available_kb(text: str, mount_point: str) -> int | None:
    for line in (text or "").splitlines():
        if line.endswith(mount_point):
            parts = re.split(r"\s+", line.strip())
            if len(parts) >= 4:
                try:
                    return int(parts[3])
                except ValueError:
                    return None
    return None


def _tail_text(text: str, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text.strip()
    return text[-max_chars:].strip()


def _restart_adb_server() -> None:
    try:
        subprocess.run(["adb", "kill-server"], capture_output=True, text=True, check=False)
        time.sleep(config.ADB_TIMEOUT_RETRY_DELAY_SECONDS)
        subprocess.run(["adb", "start-server"], capture_output=True, text=True, check=False)
    except Exception:
        logger.warning("Failed to restart adb server.")
