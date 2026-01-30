# src/ingester/dashboard.py
import json
import os
import threading
import shutil
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from ingester import config

PROJECT_ROOT = config.PROJECT_ROOT
LOG_DIR = config.LOG_DIR
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CAPTURES_DIR = os.path.join(DATA_DIR, "captures")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "dashboard_static")
ARCHIVES_DIR = os.path.join(LOG_DIR, "archives")

CYCLES_PATH = config.CYCLES_JSONL_PATH
HEALTH_PATH = os.path.join(LOG_DIR, config.HEALTH_JSONL_FILENAME)
CONTROL_PATH = config.CONTROL_JSON_PATH

ALLOWED_MEDIA_ROOTS = [LOG_DIR, CAPTURES_DIR]


def _safe_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _iter_jsonl(path: str):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _read_jsonl_tail(path: str, limit: int) -> list[dict]:
    if limit <= 0 or not os.path.exists(path):
        return []
    # Read from end in chunks to avoid loading large files.
    size = os.path.getsize(path)
    if size == 0:
        return []

    chunk_size = 64 * 1024
    data = b""
    with open(path, "rb") as handle:
        pos = size
        while pos > 0 and data.count(b"\n") <= limit:
            read_size = min(chunk_size, pos)
            pos -= read_size
            handle.seek(pos)
            data = handle.read(read_size) + data

    lines = data.splitlines()
    tail = lines[-limit:]
    items: list[dict] = []
    for raw in tail:
        try:
            items.append(json.loads(raw.decode("utf-8")))
        except json.JSONDecodeError:
            continue
    return items


def _read_control_state() -> dict:
    if not os.path.exists(CONTROL_PATH):
        return {"pause": False, "stop": False, "run_once": False}
    try:
        with open(CONTROL_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"pause": False, "stop": False, "run_once": False}
    return {
        "pause": bool(data.get("pause", False)),
        "stop": bool(data.get("stop", False)),
        "run_once": bool(data.get("run_once", False)),
    }


def _write_control_state(state: dict) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(CONTROL_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=True, indent=2)


def _archive_logs() -> dict:
    os.makedirs(ARCHIVES_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = os.path.join(ARCHIVES_DIR, f"archive_{stamp}")
    os.makedirs(target, exist_ok=True)

    moved = 0
    skipped = []
    for name in os.listdir(LOG_DIR):
        if name in ("archives", os.path.basename(CONTROL_PATH), "screen_profiles.json"):
            continue
        src = os.path.join(LOG_DIR, name)
        dst = os.path.join(target, name)
        try:
            shutil.move(src, dst)
            moved += 1
        except OSError:
            skipped.append(name)
    captures_target = os.path.join(target, "captures")
    if os.path.isdir(CAPTURES_DIR):
        try:
            shutil.move(CAPTURES_DIR, captures_target)
            os.makedirs(CAPTURES_DIR, exist_ok=True)
        except OSError:
            skipped.append("captures")
    return {"moved": moved, "target": target, "skipped": skipped}


def _count_cycles(path: str) -> tuple[int, int]:
    total = 0
    errors = 0
    for item in _iter_jsonl(path):
        total += 1
        if item.get("ok") is False:
            errors += 1
    return total, errors


def _last_item(path: str) -> dict | None:
    items = _read_jsonl_tail(path, 1)
    return items[-1] if items else None


def _find_last_screenshot(cycles_path: str) -> dict | None:
    items = _read_jsonl_tail(cycles_path, 250)
    for item in reversed(items):
        screenshot = item.get("screenshot") or {}
        path = screenshot.get("path")
        if path and os.path.exists(path):
            return {
                "path": path,
                "ts_end": item.get("ts_end"),
                "cycle_id": item.get("cycle_id"),
            }
    return None


def _last_screenshot_per_camera_from_disk() -> list[dict]:
    result = []
    for name in config.CAMERAS.keys():
        camera_dir = os.path.join(CAPTURES_DIR, name)
        if not os.path.isdir(camera_dir):
            result.append({"camera": name, "path": None, "ts_end": None})
            continue
        files = [
            os.path.join(camera_dir, f)
            for f in os.listdir(camera_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        ]
        if not files:
            result.append({"camera": name, "path": None, "ts_end": None})
            continue
        latest = max(files, key=lambda p: os.path.getmtime(p))
        ts = datetime.fromtimestamp(os.path.getmtime(latest), timezone.utc).isoformat()
        result.append({"camera": name, "path": latest, "ts_end": ts})
    return result


def _active_cameras_from_cycle(cycle: dict | None) -> tuple[int, list[str]]:
    if not cycle:
        return 0, []
    steps = cycle.get("steps") or []
    active = []
    for name in config.CAMERAS.keys():
        marker = f"camera:{name}:screencap_validate"
        for step in steps:
            if step.get("name") == marker and step.get("ok") is True:
                active.append(name)
                break
    return len(active), active


def _last_action_from_cycles(cycles_path: str) -> dict | None:
    items = _read_jsonl_tail(cycles_path, 200)
    for item in reversed(items):
        steps = item.get("steps") or []
        if not steps:
            continue
        last_step = steps[-1]
        return {
            "name": last_step.get("name"),
            "ok": last_step.get("ok"),
            "details": last_step.get("details"),
            "ts_end": last_step.get("end"),
            "cycle_id": item.get("cycle_id"),
        }
    return None


def _list_error_cycles(limit: int) -> list[dict]:
    items = _read_jsonl_tail(CYCLES_PATH, max(limit * 5, limit))
    errors = []
    for item in reversed(items):
        if item.get("ok") is False:
            error = item.get("error") or {}
            errors.append(
                {
                    "cycle_id": item.get("cycle_id"),
                    "ts_end": item.get("ts_end"),
                    "message": error.get("message"),
                    "type": error.get("type"),
                    "step": error.get("step"),
                    "artifact_dir": _artifact_dir(item.get("cycle_id")),
                }
            )
        if len(errors) >= limit:
            break
    return errors


def _artifact_dir(cycle_id: str | None) -> str | None:
    if not cycle_id:
        return None
    path = os.path.join(LOG_DIR, f"cycle_{cycle_id}_artifacts")
    return path if os.path.isdir(path) else None


def _media_allowed(path: str) -> bool:
    if not path:
        return False
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    for root in ALLOWED_MEDIA_ROOTS:
        try:
            if os.path.realpath(root) == os.path.commonpath([real, os.path.realpath(root)]):
                return True
        except ValueError:
            continue
    return False


def _guess_content_type(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith(".txt") or lower.endswith(".log"):
        return "text/plain; charset=utf-8"
    if lower.endswith(".css"):
        return "text/css; charset=utf-8"
    if lower.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if lower.endswith(".html"):
        return "text/html; charset=utf-8"
    return "application/octet-stream"


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "IngesterDashboard/0.2"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionAbortedError:
            return

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionAbortedError:
            return

    def _send_text(self, text: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self._send_bytes(body, "text/plain; charset=utf-8", status)

    def _serve_static(self, path: str) -> None:
        if not os.path.exists(path) or not os.path.isfile(path):
            self._send_text("Not found", status=HTTPStatus.NOT_FOUND)
            return
        with open(path, "rb") as handle:
            data = handle.read()
        self._send_bytes(data, _guess_content_type(path))

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route == "/":
            return self._serve_static(os.path.join(STATIC_DIR, "index.html"))

        if route.startswith("/assets/"):
            rel = route.replace("/assets/", "", 1)
            return self._serve_static(os.path.join(STATIC_DIR, rel))

        if route == "/api/summary":
            total, errors = _count_cycles(CYCLES_PATH)
            last_cycle = _last_item(CYCLES_PATH)
            active_count, active_list = _active_cameras_from_cycle(last_cycle)
            last_health = _last_item(HEALTH_PATH)
            last_screenshot = _find_last_screenshot(CYCLES_PATH)
            control_state = _read_control_state()
            last_action = _last_action_from_cycles(CYCLES_PATH)
            last_cycle_age_s = None
            if last_cycle and last_cycle.get("ts_end"):
                try:
                    ts = datetime.fromisoformat(last_cycle["ts_end"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    last_cycle_age_s = int((datetime.now(timezone.utc) - ts).total_seconds())
                except ValueError:
                    last_cycle_age_s = None
            payload = {
                "cameras_configured": len(config.CAMERAS),
                "cameras_active": active_count,
                "cameras_active_list": active_list,
                "cycles_total": total,
                "cycles_ok": total - errors,
                "cycles_error": errors,
                "last_cycle": last_cycle,
                "last_health": last_health,
                "last_screenshot": last_screenshot,
                "last_screenshots": _last_screenshot_per_camera_from_disk(),
                "capture_interval_s": config.CAPTURE_INTERVAL_SECONDS,
                "control": control_state,
                "last_action": last_action,
                "last_cycle_age_s": last_cycle_age_s,
            }
            return self._send_json(payload)

        if route == "/api/cycles":
            limit = _safe_int(query.get("limit", ["200"])[0], 200)
            items = _read_jsonl_tail(CYCLES_PATH, limit)
            return self._send_json({"items": items})

        if route == "/api/cycle":
            cycle_id = query.get("id", [""])[0]
            if not cycle_id:
                return self._send_json({"error": "missing id"}, status=HTTPStatus.BAD_REQUEST)
            match = None
            for item in _iter_jsonl(CYCLES_PATH):
                if item.get("cycle_id") == cycle_id:
                    match = item
            if not match:
                return self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return self._send_json(match)

        if route == "/api/errors":
            limit = _safe_int(query.get("limit", ["50"])[0], 50)
            items = _list_error_cycles(limit)
            return self._send_json({"items": items})

        if route == "/api/health":
            limit = _safe_int(query.get("limit", ["200"])[0], 200)
            items = _read_jsonl_tail(HEALTH_PATH, limit)
            return self._send_json({"items": items})

        if route == "/api/cameras":
            return self._send_json({"items": list(config.CAMERAS.keys())})

        if route == "/api/control":
            return self._send_json(_read_control_state())

        if route == "/api/version":
            return self._send_json({"version": self.server_version, "file": __file__})

        if route == "/favicon.ico":
            return self._send_text("Not found", status=HTTPStatus.NOT_FOUND)

        if route == "/media":
            raw_path = query.get("path", [""])[0]
            if not raw_path:
                return self._send_text("missing path", status=HTTPStatus.BAD_REQUEST)
            path = unquote(raw_path)
            if not _media_allowed(path) or not os.path.exists(path):
                return self._send_text("not allowed", status=HTTPStatus.FORBIDDEN)
            with open(path, "rb") as handle:
                data = handle.read()
            return self._send_bytes(data, _guess_content_type(path))

        self._send_text("Not found", status=HTTPStatus.NOT_FOUND)

    def log_message(self, format, *args):
        # Suppress noisy HTTP logs; rely on ingester log if needed.
        return

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/archive":
            control = _read_control_state()
            if not control.get("stop"):
                return self._send_text(
                    "Arquivamento permitido apenas com o ingester parado (Stop).",
                    status=HTTPStatus.CONFLICT,
                )
            result = _archive_logs()
            return self._send_json(result)

        if route != "/api/control":
            return self._send_text("Not found", status=HTTPStatus.NOT_FOUND)

        length = _safe_int(self.headers.get("Content-Length"), 0)
        raw = self.rfile.read(length) if length > 0 else b""
        data: dict = {}
        if raw:
            try:
                data = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                try:
                    data = {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
                except UnicodeDecodeError:
                    data = {}

        action = (data.get("action") or "").lower()
        state = _read_control_state()

        if action == "pause":
            state["pause"] = True
        elif action == "resume":
            state["pause"] = False
            state["stop"] = False
        elif action == "stop":
            state["stop"] = True
        elif action == "run_once":
            state["run_once"] = True
        elif action == "clear":
            state = {"pause": False, "stop": False, "run_once": False}
        else:
            return self._send_json({"error": "invalid action"}, status=HTTPStatus.BAD_REQUEST)

        _write_control_state(state)
        return self._send_json(state)


def run_dashboard(host: str = "127.0.0.1", port: int = 8088) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Ingester dashboard listening on http://{host}:{port}")
    print(f"Dashboard file: {__file__}")
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    host = os.environ.get("INGESTER_DASHBOARD_HOST", "127.0.0.1")
    port = _safe_int(os.environ.get("INGESTER_DASHBOARD_PORT"), 8088)
    run_dashboard(host=host, port=port)
