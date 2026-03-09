from flask import Flask, request, send_from_directory, render_template
from datetime import datetime, timedelta, timezone
import os
import hashlib
import re
import heapq
import json
import time
from collections import deque
from typing import Optional
from zoneinfo import ZoneInfo

app = Flask(__name__)


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return max(default, minimum)
    try:
        val = int(raw)
    except ValueError:
        return max(default, minimum)
    return max(val, minimum)


UPLOAD_LOG_EVERY = _int_env("UPLOAD_LOG_EVERY", 20, minimum=1)
_upload_ok_count = 0
UPLOAD_EVENT_PRINT_EVERY = _int_env("UPLOAD_EVENT_PRINT_EVERY", 0, minimum=0)
_upload_event_print_count = 0
DASHBOARD_CACHE_TTL_SECONDS = _int_env("DASHBOARD_CACHE_TTL_SECONDS", 8, minimum=1)
DEVICE_ACTIVE_WINDOW_SECONDS = _int_env("DEVICE_ACTIVE_WINDOW_SECONDS", 60, minimum=10)
DASHBOARD_RECENT_DAYS = _int_env("DASHBOARD_RECENT_DAYS", 2, minimum=1)
DASHBOARD_RECENT_IMAGES_CAP = _int_env("DASHBOARD_RECENT_IMAGES_CAP", 180, minimum=40)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
CAPTURE_FILENAME_TZ = ZoneInfo(os.getenv("CAPTURE_FILENAME_TZ", "UTC"))
UNKNOWN_DEVICE_IDS = {"unknown", "unknown_device", "unknow", "unknow_device"}

def _get_upload_root() -> str:
    # Allow overriding storage location on EC2 (e.g. /data/saira/uploads).
    # Defaults to ./uploads next to this file.
    return os.getenv(
        "UPLOAD_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads"),
    )


UPLOAD_ROOT = _get_upload_root()
os.makedirs(UPLOAD_ROOT, exist_ok=True)
EVENT_LOG_PATH = os.path.join(UPLOAD_ROOT, "server-events.jsonl")

def _get_ota_root() -> str:
    return os.getenv(
        "OTA_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ota"),
    )


OTA_ROOT = _get_ota_root()
os.makedirs(OTA_ROOT, exist_ok=True)

def _get_config_root() -> str:
    return os.getenv(
        "CONFIG_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config"),
    )


CONFIG_ROOT = _get_config_root()
os.makedirs(CONFIG_ROOT, exist_ok=True)
DEFAULT_CONFIG_BASENAME = os.path.basename(
    (os.getenv("DEFAULT_CONFIG_FILE", "default.txt") or "default.txt").strip()
) or "default.txt"
_dashboard_cache: dict[str, object] = {"expires_at": 0.0}
_recent_events = deque(maxlen=300)
_device_last_seen: dict[str, float] = {}
_last_event_log_mtime = 0.0


def _admin_token() -> str:
    return os.getenv("ADMIN_TOKEN", "")


def _public_base_url() -> str:
    # Example: https://your-domain.com or http://EC2_PUBLIC_IP:5000
    return os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


def _relative_path_for_now(filename: str) -> str:
    # Partition by date so the EC2 disk doesn't end up with one huge directory.
    dt = datetime.utcnow()
    return os.path.join(dt.strftime("%Y/%m/%d"), filename)


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _public_image_url(rel_path: str) -> str:
    base = _public_base_url()
    rel_url = rel_path.replace(os.sep, "/")
    if base:
        return f"{base}/uploads/{rel_url}"
    return f"/uploads/{rel_url}"


def _device_id_from_request_fallback() -> str:
    raw = request.headers.get("X-Device-Id", "").strip()
    if raw:
        safe = _sanitize_device_id(raw)
        if safe:
            return safe
    form_raw = (request.form.get("device_id") or "").strip()
    if form_raw:
        safe = _sanitize_device_id(form_raw)
        if safe:
            return safe
    return "unknown_device"


def _device_id_from_status_message(message: str) -> Optional[str]:
    match = re.search(r"\bdev=([A-Za-z0-9_.-]{1,64})\b", message or "")
    if not match:
        return None
    return _sanitize_device_id(match.group(1))


def _append_event_to_disk(entry: dict[str, object]) -> None:
    try:
        with open(EVENT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except OSError:
        pass


def _record_device_event(device_id: str, event: str, message: str) -> None:
    global _upload_event_print_count
    safe_id = _sanitize_device_id(device_id) if device_id else None
    if not safe_id:
        safe_id = "unknown_device"
    ts = time.time()
    entry = {
        "timestamp": datetime.utcfromtimestamp(ts).isoformat() + "Z",
        "device_id": safe_id,
        "event": event,
        "message": message,
    }
    _recent_events.append(entry)
    _device_last_seen[safe_id] = ts
    _dashboard_cache["expires_at"] = 0.0
    _append_event_to_disk(entry)
    should_print = True
    if event == "upload":
        _upload_event_print_count += 1
        if UPLOAD_EVENT_PRINT_EVERY <= 0:
            should_print = False
        else:
            should_print = (_upload_event_print_count % UPLOAD_EVENT_PRINT_EVERY) == 0
    if should_print:
        print(f"[DEVICE] {safe_id} | {event} | {message}", flush=True)


def _iso_to_epoch(iso_text: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(iso_text.replace("Z", "")).timestamp()
    except ValueError:
        return None


def _load_recent_events() -> None:
    global _last_event_log_mtime
    if not os.path.isfile(EVENT_LOG_PATH):
        return
    try:
        mtime = os.path.getmtime(EVENT_LOG_PATH)
    except OSError:
        return
    if mtime <= _last_event_log_mtime:
        return
    _last_event_log_mtime = mtime
    try:
        with open(EVENT_LOG_PATH, "r", encoding="utf-8") as f:
            lines = deque(f, maxlen=400)
    except OSError:
        return
    seen = {
        (
            str(ev.get("timestamp") or ""),
            str(ev.get("device_id") or ""),
            str(ev.get("event") or ""),
            str(ev.get("message") or ""),
        )
        for ev in _recent_events
    }
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ts_txt = str(obj.get("timestamp") or "").strip()
        device_id = str(obj.get("device_id") or "unknown_device").strip() or "unknown_device"
        event = str(obj.get("event") or "event").strip() or "event"
        message = str(obj.get("message") or "").strip()
        ts_epoch = _iso_to_epoch(ts_txt)
        entry = {
            "timestamp": ts_txt or _utc_now_iso(),
            "device_id": device_id,
            "event": event,
            "message": message,
        }
        key = (entry["timestamp"], entry["device_id"], entry["event"], entry["message"])
        if key in seen:
            continue
        seen.add(key)
        _recent_events.append(entry)
        if ts_epoch is not None:
            prev = _device_last_seen.get(device_id, 0.0)
            if ts_epoch > prev:
                _device_last_seen[device_id] = ts_epoch


def _guess_device_id_from_rel_path(rel_path: str) -> str:
    parts = rel_path.replace("\\", "/").split("/")
    if not parts:
        return "unknown_device"
    if re.fullmatch(r"\d{4}", parts[0]):
        return "unknown_device"
    return parts[0] or "unknown_device"


def _guess_captured_at(name: str, mtime: float) -> str:
    stem = os.path.splitext(os.path.basename(name))[0]
    try:
        # Upload endpoint names files on the server, using a fixed timezone.
        # Normalize to UTC for consistent APIs consumed by the dashboard.
        parsed_local = datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=CAPTURE_FILENAME_TZ)
        return parsed_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return datetime.utcfromtimestamp(mtime).isoformat() + "Z"


def _is_unknown_device_id(device_id: str) -> bool:
    return (device_id or "").strip().lower() in UNKNOWN_DEVICE_IDS


def _drop_unknown_device_stats(
    device_last_image_ts: dict[str, float],
    device_image_counts: dict[str, int],
    device_image_bytes: dict[str, int],
) -> None:
    unknown_ids = {
        str(key)
        for key in set(device_last_image_ts.keys())
        .union(set(device_image_counts.keys()))
        .union(set(device_image_bytes.keys()))
        if _is_unknown_device_id(str(key))
    }
    for device_id in unknown_ids:
        device_last_image_ts.pop(device_id, None)
        device_image_counts.pop(device_id, None)
        device_image_bytes.pop(device_id, None)


def _iter_recent_day_tokens(days: int) -> list[str]:
    today = datetime.utcnow().date()
    tokens: list[str] = []
    for offset in range(days):
        d = today - timedelta(days=offset)
        tokens.append(d.strftime("%Y/%m/%d"))
    return tokens


def _scan_day_directory(
    day_dir: str,
    recent_heap: list[tuple[float, dict[str, object]]],
    heap_cap: int,
    image_devices: set[str],
    device_last_image_ts: dict[str, float],
    device_image_counts: dict[str, int],
    device_image_bytes: dict[str, int],
) -> int:
    scanned = 0
    if not os.path.isdir(day_dir):
        return scanned

    try:
        with os.scandir(day_dir) as entries:
            for file_entry in entries:
                if not file_entry.is_file():
                    continue
                ext = os.path.splitext(file_entry.name)[1].lower()
                if ext not in IMAGE_EXTENSIONS:
                    continue
                try:
                    st = file_entry.stat()
                    mtime = st.st_mtime
                    size_bytes = int(st.st_size)
                except OSError:
                    continue

                rel_path = os.path.relpath(file_entry.path, UPLOAD_ROOT)
                device_id = _guess_device_id_from_rel_path(rel_path)
                image_devices.add(device_id)
                scanned += 1
                prev = device_last_image_ts.get(device_id, 0.0)
                if mtime > prev:
                    device_last_image_ts[device_id] = mtime
                device_image_counts[device_id] = int(device_image_counts.get(device_id, 0)) + 1
                device_image_bytes[device_id] = int(device_image_bytes.get(device_id, 0)) + size_bytes

                item = {
                    "device_id": device_id,
                    "filename": rel_path.replace(os.sep, "/"),
                    "image_url": _public_image_url(rel_path),
                    "captured_at": _guess_captured_at(file_entry.name, mtime),
                    "captured_at_epoch": mtime,
                    "size_bytes": size_bytes,
                }
                if len(recent_heap) < heap_cap:
                    heapq.heappush(recent_heap, (mtime, item))
                else:
                    heapq.heappushpop(recent_heap, (mtime, item))
    except OSError:
        return scanned
    return scanned


def _scan_recent_image_window(cap: int) -> dict[str, object]:
    day_tokens = _iter_recent_day_tokens(DASHBOARD_RECENT_DAYS)
    recent_heap: list[tuple[float, dict[str, object]]] = []
    image_devices: set[str] = set()
    device_last_image_ts: dict[str, float] = {}
    device_image_counts: dict[str, int] = {}
    device_image_bytes: dict[str, int] = {}
    total_images = 0

    device_dirs: list[str] = []
    has_legacy_layout = False
    try:
        with os.scandir(UPLOAD_ROOT) as root_entries:
            for entry in root_entries:
                if not entry.is_dir():
                    continue
                if entry.name.startswith("."):
                    continue
                # Legacy layout without device folder at root: uploads/YYYY/MM/DD
                if re.fullmatch(r"\d{4}", entry.name):
                    has_legacy_layout = True
                    continue
                device_dirs.append(entry.path)
    except OSError:
        return {
            "total_images": 0,
            "image_devices": set(),
            "recent_images": [],
            "device_last_image_ts": {},
            "device_image_counts": {},
            "device_image_bytes": {},
            "total_bytes": 0,
        }

    for device_dir in device_dirs:
        for token in day_tokens:
            total_images += _scan_day_directory(
                os.path.join(device_dir, token),
                recent_heap,
                cap,
                image_devices,
                device_last_image_ts,
                device_image_counts,
                device_image_bytes,
            )

    if has_legacy_layout:
        for token in day_tokens:
            total_images += _scan_day_directory(
                os.path.join(UPLOAD_ROOT, token),
                recent_heap,
                cap,
                image_devices,
                device_last_image_ts,
                device_image_counts,
                device_image_bytes,
            )

    recent_images = [item for _, item in sorted(recent_heap, key=lambda it: it[0], reverse=True)]
    for item in recent_images:
        item.pop("captured_at_epoch", None)
    total_bytes = sum(int(v) for v in device_image_bytes.values())

    return {
        "total_images": total_images,
        "total_bytes": total_bytes,
        "image_devices": image_devices,
        "recent_images": recent_images,
        "device_last_image_ts": device_last_image_ts,
        "device_image_counts": device_image_counts,
        "device_image_bytes": device_image_bytes,
    }


def _dashboard_snapshot() -> dict[str, object]:
    _load_recent_events()
    now = time.time()
    if now < float(_dashboard_cache.get("expires_at", 0.0)):
        return _dashboard_cache

    recent_scan = _scan_recent_image_window(max(DASHBOARD_RECENT_IMAGES_CAP, 40))
    active_cutoff = now - DEVICE_ACTIVE_WINDOW_SECONDS
    image_devices = {
        str(device_id)
        for device_id in set(recent_scan["image_devices"])
        if not _is_unknown_device_id(str(device_id))
    }
    device_last_image_ts = dict(recent_scan["device_last_image_ts"])
    device_image_counts = dict(recent_scan["device_image_counts"])
    device_image_bytes = dict(recent_scan["device_image_bytes"])
    _drop_unknown_device_stats(device_last_image_ts, device_image_counts, device_image_bytes)
    total_images = int(sum(int(v) for v in device_image_counts.values()))
    total_images_bytes = int(sum(int(v) for v in device_image_bytes.values()))
    scope_days = max(int(DASHBOARD_RECENT_DAYS), 1)
    estimated_4g_mb_per_day = (total_images_bytes / scope_days) / (1024 * 1024)
    estimated_4g_gb_per_month = ((total_images_bytes / scope_days) * 30.0) / (1024 * 1024 * 1024)
    event_devices = {
        str(device_id)
        for device_id in set(_device_last_seen.keys())
        if not _is_unknown_device_id(str(device_id))
    }
    all_devices = image_devices.union(event_devices)
    device_rows: list[dict[str, object]] = []

    for device_id in all_devices:
        last_event_ts = float(_device_last_seen.get(device_id, 0.0))
        last_image_ts = float(device_last_image_ts.get(device_id, 0.0))
        last_seen_ts = max(last_event_ts, last_image_ts)
        is_active = last_seen_ts >= active_cutoff if last_seen_ts > 0 else False
        dev_bytes = int(device_image_bytes.get(device_id, 0))
        dev_mb_day = (dev_bytes / scope_days) / (1024 * 1024)
        dev_gb_month = ((dev_bytes / scope_days) * 30.0) / (1024 * 1024 * 1024)
        device_rows.append(
            {
                "device_id": device_id,
                "is_active": is_active,
                "last_seen_at": datetime.utcfromtimestamp(last_seen_ts).isoformat() + "Z" if last_seen_ts > 0 else None,
                "last_event_at": datetime.utcfromtimestamp(last_event_ts).isoformat() + "Z" if last_event_ts > 0 else None,
                "last_image_at": datetime.utcfromtimestamp(last_image_ts).isoformat() + "Z" if last_image_ts > 0 else None,
                "recent_images_count": int(device_image_counts.get(device_id, 0)),
                "recent_images_bytes": dev_bytes,
                "estimated_4g_mb_per_day": round(dev_mb_day, 3),
                "estimated_4g_gb_per_month": round(dev_gb_month, 4),
            }
        )

    device_rows.sort(
        key=lambda item: (
            0 if bool(item["is_active"]) else 1,
            -(_iso_to_epoch(str(item["last_seen_at"])) or 0.0),
            str(item["device_id"]),
        )
    )
    active_devices = [str(item["device_id"]) for item in device_rows if bool(item["is_active"])]

    recent_images = [
        item
        for item in list(recent_scan["recent_images"])
        if not _is_unknown_device_id(str(item.get("device_id") or ""))
    ]
    recent_logs = [
        item
        for item in list(_recent_events)
        if not _is_unknown_device_id(str(item.get("device_id") or ""))
    ][-60:]
    recent_logs.reverse()
    if not recent_logs:
        recent_logs = [
            {
                "timestamp": str(item.get("captured_at") or _utc_now_iso()),
                "device_id": str(item.get("device_id") or "unknown_device"),
                "event": "upload",
                "message": f"Imagem recebida: {item.get('filename') or ''}",
            }
            for item in recent_images[:60]
        ]

    snapshot = {
        "expires_at": now + DASHBOARD_CACHE_TTL_SECONDS,
        "updated_at": _utc_now_iso(),
        "total_images": total_images,
        "total_images_bytes": total_images_bytes,
        "total_images_scope_days": DASHBOARD_RECENT_DAYS,
        "estimated_4g_mb_per_day": round(estimated_4g_mb_per_day, 3),
        "estimated_4g_gb_per_month": round(estimated_4g_gb_per_month, 4),
        "total_known_devices": len(all_devices),
        "active_devices": active_devices,
        "devices": device_rows,
        "recent_logs": recent_logs,
        "recent_images": recent_images,
    }
    _dashboard_cache.clear()
    _dashboard_cache.update(snapshot)
    return snapshot


@app.route("/uploads/<path:filepath>", methods=["GET"])
def get_uploaded_file(filepath: str):
    return send_from_directory(UPLOAD_ROOT, filepath)


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/dashboard/summary", methods=["GET"])
def dashboard_summary():
    raw_device_id = (request.args.get("device_id") or "").strip()
    selected_device = None
    if raw_device_id:
        selected_device = _sanitize_device_id(raw_device_id)
        if not selected_device:
            return {"error": "Invalid device_id"}, 400

    data = _dashboard_snapshot()
    recent_images = list(data.get("recent_images", []))
    devices = list(data.get("devices", []))
    if selected_device:
        recent_images = [item for item in recent_images if str(item.get("device_id")) == selected_device]
        devices = [item for item in devices if str(item.get("device_id")) == selected_device]

    latest = recent_images[0] if recent_images else None
    active_devices = [item["device_id"] for item in devices if bool(item.get("is_active"))]
    scope_days = max(int(data.get("total_images_scope_days", DASHBOARD_RECENT_DAYS)), 1)
    if selected_device:
        filtered_total_images = int(sum(int(item.get("recent_images_count") or 0) for item in devices))
        filtered_total_bytes = int(sum(int(item.get("recent_images_bytes") or 0) for item in devices))
        filtered_mb_day = (filtered_total_bytes / scope_days) / (1024 * 1024)
        filtered_gb_month = ((filtered_total_bytes / scope_days) * 30.0) / (1024 * 1024 * 1024)
    else:
        filtered_total_images = int(data.get("total_images", 0))
        filtered_total_bytes = int(data.get("total_images_bytes", 0))
        filtered_mb_day = float(data.get("estimated_4g_mb_per_day", 0.0))
        filtered_gb_month = float(data.get("estimated_4g_gb_per_month", 0.0))

    return {
        "updated_at": data["updated_at"],
        "total_images": filtered_total_images,
        "total_images_bytes": filtered_total_bytes,
        "total_images_scope_days": data.get("total_images_scope_days", DASHBOARD_RECENT_DAYS),
        "estimated_4g_mb_per_day": round(filtered_mb_day, 3),
        "estimated_4g_gb_per_month": round(filtered_gb_month, 4),
        "active_devices": active_devices,
        "active_devices_count": len(active_devices),
        "total_known_devices": len(devices),
        "selected_device": selected_device,
        "latest_image": latest,
        "active_window_seconds": DEVICE_ACTIVE_WINDOW_SECONDS,
        "devices": devices,
    }, 200


@app.route("/api/dashboard/devices", methods=["GET"])
def dashboard_devices():
    only_active_raw = (request.args.get("only_active") or "").strip().lower()
    only_active = only_active_raw in {"1", "true", "yes", "on"}
    data = _dashboard_snapshot()
    devices = list(data.get("devices", []))
    if only_active:
        devices = [item for item in devices if bool(item.get("is_active"))]
    return {
        "updated_at": data["updated_at"],
        "count": len(devices),
        "active_count": len([item for item in devices if bool(item.get("is_active"))]),
        "devices": devices,
    }, 200


@app.route("/api/dashboard/recent-images", methods=["GET"])
def dashboard_recent_images():
    raw_device_id = (request.args.get("device_id") or "").strip()
    selected_device = None
    if raw_device_id:
        selected_device = _sanitize_device_id(raw_device_id)
        if not selected_device:
            return {"error": "Invalid device_id"}, 400

    limit_str = (request.args.get("limit") or "12").strip()
    try:
        limit = max(1, min(int(limit_str), 120))
    except ValueError:
        limit = 12
    data = _dashboard_snapshot()
    recent = list(data.get("recent_images", []))
    if selected_device:
        recent = [item for item in recent if str(item.get("device_id")) == selected_device]
    recent = recent[:limit]
    return {
        "updated_at": data["updated_at"],
        "limit": limit,
        "count": len(recent),
        "selected_device": selected_device,
        "images": recent,
    }, 200


@app.route("/api/dashboard/recent-logs", methods=["GET"])
def dashboard_recent_logs():
    raw_device_id = (request.args.get("device_id") or "").strip()
    selected_device = None
    if raw_device_id:
        selected_device = _sanitize_device_id(raw_device_id)
        if not selected_device:
            return {"error": "Invalid device_id"}, 400

    limit_str = (request.args.get("limit") or "20").strip()
    try:
        limit = max(1, min(int(limit_str), 60))
    except ValueError:
        limit = 20
    data = _dashboard_snapshot()
    logs = list(data.get("recent_logs", []))
    if selected_device:
        logs = [item for item in logs if str(item.get("device_id")) == selected_device]
    logs = logs[:limit]
    return {
        "updated_at": data["updated_at"],
        "limit": limit,
        "count": len(logs),
        "selected_device": selected_device,
        "logs": logs,
    }, 200

def _sanitize_device_id(device_id: str) -> Optional[str]:
    # Keep filesystem access safe.
    if not device_id:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", device_id):
        return None
    return device_id


def _config_path_for(device_id: str) -> str:
    safe = _sanitize_device_id(device_id)
    if not safe:
        raise ValueError("invalid device id")
    return os.path.join(CONFIG_ROOT, f"{safe}.txt")


def _default_config_path() -> str:
    return os.path.join(CONFIG_ROOT, DEFAULT_CONFIG_BASENAME)


def _default_config_bytes() -> Optional[bytes]:
    default_path = _default_config_path()
    if os.path.isfile(default_path):
        try:
            with open(default_path, "rb") as f:
                return f.read()
        except OSError:
            pass

    raw_timer = os.getenv("DEFAULT_TIMER_DELAY_MS", "").strip()
    if not raw_timer:
        return None
    try:
        timer_ms = int(raw_timer)
    except ValueError:
        return None
    if timer_ms < 1000:
        return None

    version = (os.getenv("DEFAULT_CONFIG_VERSION", "default") or "default").strip() or "default"
    body = f"version={version}\ntimer_delay_ms={timer_ms}\n"
    return body.encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


@app.route("/device/<device_id>/config.txt", methods=["GET"])
def get_device_config(device_id: str):
    try:
        path = _config_path_for(device_id)
    except ValueError:
        return {"error": "Invalid device id"}, 400

    if os.path.isfile(path):
        with open(path, "rb") as f:
            body_bytes = f.read()
    else:
        default_bytes = _default_config_bytes()
        if default_bytes is not None:
            body_bytes = default_bytes
        else:
            body_bytes = b"version=0\n"

    etag = _sha256_bytes(body_bytes)
    inm = request.headers.get("If-None-Match", "")
    if inm and inm.strip("\"") == etag:
        return "", 304, {"ETag": f"\"{etag}\""}
    _record_device_event(device_id, "config_get", "GET /device/<id>/config.txt")

    return (
        body_bytes,
        200,
        {
            "Content-Type": "text/plain; charset=utf-8",
            "ETag": f"\"{etag}\"",
            "Cache-Control": "no-store",
        },
    )


@app.route("/device/<device_id>/config", methods=["POST"])
def set_device_config(device_id: str):
    # Protected endpoint (admin only)
    token = _admin_token()
    if token:
        got = request.headers.get("X-Admin-Token", "")
        if got != token:
            return {"error": "Unauthorized"}, 401

    try:
        path = _config_path_for(device_id)
    except ValueError:
        return {"error": "Invalid device id"}, 400

    payload: dict[str, str] = {}
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return {"error": "Invalid JSON"}, 400
        for k, v in data.items():
            payload[str(k)] = "" if v is None else str(v)
    else:
        for k in request.form.keys():
            payload[str(k)] = str(request.form.get(k) or "")

    allowed = {
        "timer_delay_ms",
        "heartbeat_interval_ms",
        "recovery_wifi_reset_ms",
        "recovery_restart_ms",
        "ip_cam_url",
        "ip_cam_user",
        "ip_cam_pass",
        "tls_insecure",
        "ota_enabled",
        "ota_check_interval_ms",
    }
    cleaned: dict[str, str] = {}
    for k, v in payload.items():
        kk = k.strip().lower()
        if kk in allowed:
            cleaned[kk] = v.strip()

    version = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    lines = [f"version={version}"]
    for k in sorted(cleaned.keys()):
        lines.append(f"{k}={cleaned[k]}")
    body = "\n".join(lines) + "\n"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)

    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ota_bin_path() -> str:
    return os.path.join(OTA_ROOT, "latest.bin")


def _ota_version_path() -> str:
    return os.path.join(OTA_ROOT, "version.txt")


def _ota_version() -> str:
    # Prefer explicit version file, fallback to env var, else "0".
    vp = _ota_version_path()
    if os.path.isfile(vp):
        try:
            with open(vp, "r", encoding="utf-8") as f:
                return (f.read() or "").strip() or "0"
        except OSError:
            pass
    return (os.getenv("OTA_VERSION", "") or "0").strip()


@app.route("/ota/latest.bin", methods=["GET"])
def get_ota_firmware():
    bin_path = _ota_bin_path()
    if not os.path.isfile(bin_path):
        return {"error": "No firmware uploaded"}, 404
    return send_from_directory(OTA_ROOT, "latest.bin", mimetype="application/octet-stream")


@app.route("/ota/manifest.txt", methods=["GET"])
def get_ota_manifest():
    bin_path = _ota_bin_path()
    version = _ota_version()
    base = _public_base_url()
    if base:
        bin_url = f"{base}/ota/latest.bin"
        manifest_url = f"{base}/ota/manifest.txt"
    else:
        bin_url = "/ota/latest.bin"
        manifest_url = "/ota/manifest.txt"

    sha = _sha256_file(bin_path) if os.path.isfile(bin_path) else ""
    body = (
        f"version={version}\n"
        f"bin_url={bin_url}\n"
        f"sha256={sha}\n"
        f"manifest_url={manifest_url}\n"
    )
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/ota/upload", methods=["POST"])
def upload_ota_firmware():
    token = _admin_token()
    if token:
        got = request.headers.get("X-Admin-Token", "")
        if got != token:
            return {"error": "Unauthorized"}, 401

    if "firmware" not in request.files:
        return {"error": "Missing firmware file field"}, 400

    fw = request.files["firmware"]
    if fw.filename == "":
        return {"error": "Empty filename"}, 400

    bin_path = _ota_bin_path()
    fw.save(bin_path)

    version = (request.form.get("version") or "").strip()
    if not version:
        version = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")

    try:
        with open(_ota_version_path(), "w", encoding="utf-8") as f:
            f.write(version)
    except OSError:
        pass

    # Return the updated manifest for convenience
    return get_ota_manifest()

@app.route("/upload", methods=["POST"])
def upload_file():
    global _upload_ok_count

    # Identify the device
    raw_device_id = request.headers.get("X-Device-Id", "").strip()
    device_id = _sanitize_device_id(raw_device_id) if raw_device_id else None
    if not device_id:
        device_id = "unknown_device"
        if raw_device_id:
            print(f"WARNING: X-Device-Id invalido: {raw_device_id!r}", flush=True)
        else:
            print("WARNING: upload sem header X-Device-Id, usando fallback", flush=True)

    # Validate that an image file was provided
    if "imageFile" not in request.files:
        print(
            "Upload missing imageFile | "
            f"device_id={device_id} | "
            f"content_type={request.content_type} | "
            f"content_length={request.headers.get('Content-Length')} | "
            f"files_keys={list(request.files.keys())} | "
            f"form_keys={list(request.form.keys())} | "
            f"data_len={len(request.get_data() or b'')}",
            flush=True,
        )
        return {"error": "Missing imageFile"}, 400

    file = request.files["imageFile"]
    if file.filename == "":
        print(
            "Upload empty filename | "
            f"device_id={device_id} | "
            f"content_type={request.content_type} | "
            f"content_length={request.headers.get('Content-Length')} | "
            f"files_keys={list(request.files.keys())}",
            flush=True,
        )
        return {"error": "Empty filename"}, 400

    # Build path: {device_id}/YYYY/MM/DD/HH-MM-SS.jpg
    dt = datetime.utcnow()
    timestamp_str = dt.strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp_str}.jpg"
    rel_path = os.path.join(device_id, dt.strftime("%Y/%m/%d"), filename)
    save_path = os.path.join(UPLOAD_ROOT, rel_path)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    file.save(save_path)

    _upload_ok_count += 1
    if (_upload_ok_count % UPLOAD_LOG_EVERY) == 0:
        print(
            f"Received image: {rel_path} (device={device_id}, count={_upload_ok_count})",
            flush=True,
        )

    rel_url = rel_path.replace(os.sep, "/")
    _record_device_event(device_id, "upload", f"Imagem recebida: {rel_url}")
    image_url = _public_image_url(rel_path)

    return {
        "status": "ok",
        "device_id": device_id,
        "filename": rel_url,
        "image_url": image_url,
    }, 200

@app.route("/status", methods=["POST"])
def receive_status():
    # Read status message from form-encoded data
    message = request.form.get("message")
    if not message:
        return "Missing message", 400

    # Log alerts immediately for Docker visibility
    print(f"[ESP32 ALERT] {message}", flush=True)
    device_id = _device_id_from_request_fallback()
    if device_id == "unknown_device":
        inferred = _device_id_from_status_message(message)
        if inferred:
            device_id = inferred
    _record_device_event(device_id, "status", message.strip())

    return "Received", 200

if __name__ == "__main__":
    # Local/dev fallback when running "python server.py".
    # Production container runs via gunicorn (see Dockerfile).
    debug = os.getenv("FLASK_DEBUG", "0").strip() == "1"
    port = _int_env("PORT", 5000, minimum=1)
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)

