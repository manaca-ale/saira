# gevent monkey-patching must happen before any other imports so that
# blocking stdlib calls (socket, threading, queue) become gevent-friendly.
# This enables proper SSE streaming with gunicorn gevent workers.
try:
    from gevent import monkey as _monkey
    _monkey.patch_all()
except ImportError:
    pass  # running without gevent (e.g., local dev) — SSE may not stream correctly

from flask import Flask, request, send_from_directory, render_template, Response, stream_with_context
from datetime import datetime, timedelta
import os
import hashlib
import re
import heapq
import json
import time
import threading
import queue
try:
    import gevent.queue as _gqueue
    _Queue     = _gqueue.Queue
    _QueueFull = _gqueue.Full
    _QueueEmpty = _gqueue.Empty
except ImportError:
    _Queue     = queue.Queue
    _QueueFull = queue.Full
    _QueueEmpty = queue.Empty
import struct
from collections import deque
from typing import Optional
from zoneinfo import ZoneInfo
import requests

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
DASHBOARD_CACHE_TTL_SECONDS = _int_env("DASHBOARD_CACHE_TTL_SECONDS", 8, minimum=1)
DEVICE_ACTIVE_WINDOW_SECONDS = _int_env("DEVICE_ACTIVE_WINDOW_SECONDS", 60, minimum=10)
DASHBOARD_RECENT_DAYS = _int_env("DASHBOARD_RECENT_DAYS", 2, minimum=1)
DASHBOARD_RECENT_IMAGES_CAP = _int_env("DASHBOARD_RECENT_IMAGES_CAP", 180, minimum=40)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
BRAZIL_TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Sao_Paulo"))
CAPTURE_FILENAME_TZ = ZoneInfo(os.getenv("CAPTURE_FILENAME_TZ", "America/Sao_Paulo"))
UNKNOWN_DEVICE_IDS = {"unknown", "unknown_device", "unknow", "unknow_device"}
CORE_API_BASE_URL = (os.getenv("CORE_API_BASE_URL", "") or "").strip().rstrip("/")
CORE_API_LOGIN_EMAIL = (os.getenv("CORE_API_LOGIN_EMAIL", "admin@saira.com") or "").strip()
CORE_API_LOGIN_PASSWORD = os.getenv("CORE_API_LOGIN_PASSWORD", "admin123")
CORE_API_TIMEOUT_SECONDS = max(2.0, float(os.getenv("CORE_API_TIMEOUT_SECONDS", "8") or "8"))
CORE_API_CAMERA_LIMIT = _int_env("CORE_API_CAMERA_LIMIT", 500, minimum=10)

_core_api_lock = threading.Lock()
_core_api_cached_base = ""
_core_api_cached_token = ""
_core_api_cached_expiry = 0.0

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
_dashboard_cache: dict[str, object] = {"expires_at": 0.0}
_dashboard_cache_lock = threading.Lock()
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
    dt = datetime.now(BRAZIL_TZ)
    return os.path.join(dt.strftime("%Y/%m/%d"), filename)


def _utc_now_iso() -> str:
    return datetime.now(BRAZIL_TZ).isoformat()


def _public_image_url(rel_path: str) -> str:
    base = _public_base_url()
    rel_url = rel_path.replace(os.sep, "/")
    if base:
        return f"{base}/uploads/{rel_url}"
    return f"/uploads/{rel_url}"


def _core_api_candidates() -> list[str]:
    candidates: list[str] = []
    if CORE_API_BASE_URL:
        candidates.append(CORE_API_BASE_URL)
    candidates.extend(
        [
            "http://backend:8001/api/v1",
            "http://localhost:8001/api/v1",
        ]
    )
    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        base = (item or "").strip().rstrip("/")
        if not base or base in seen:
            continue
        seen.add(base)
        ordered.append(base)
    return ordered


def _core_api_login(base_url: str, force_refresh: bool = False) -> str:
    global _core_api_cached_base, _core_api_cached_token, _core_api_cached_expiry
    now = time.time()
    with _core_api_lock:
        if (
            not force_refresh
            and _core_api_cached_token
            and _core_api_cached_base == base_url
            and now < _core_api_cached_expiry
        ):
            return _core_api_cached_token

    login_url = f"{base_url}/auth/login"
    resp = requests.post(
        login_url,
        data={
            "username": CORE_API_LOGIN_EMAIL,
            "password": CORE_API_LOGIN_PASSWORD,
        },
        timeout=CORE_API_TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"login {resp.status_code}: {resp.text[:180]}")

    payload = resp.json() if resp.content else {}
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("login sem access_token")

    with _core_api_lock:
        _core_api_cached_base = base_url
        _core_api_cached_token = token
        _core_api_cached_expiry = time.time() + 20 * 60
    return token


def _core_api_request(
    method: str,
    path: str,
    *,
    params: Optional[dict[str, object]] = None,
    json_body: Optional[dict[str, object]] = None,
) -> tuple[Optional[requests.Response], Optional[str], Optional[str]]:
    errors: list[str] = []
    for base in _core_api_candidates():
        try:
            token = _core_api_login(base)
        except Exception as exc:
            errors.append(f"{base} login: {exc}")
            continue

        url = f"{base}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        for attempt in range(2):
            try:
                resp = requests.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=CORE_API_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                errors.append(f"{base} request: {exc}")
                resp = None

            if resp is None:
                break
            if resp.status_code == 401 and attempt == 0:
                try:
                    token = _core_api_login(base, force_refresh=True)
                    headers["Authorization"] = f"Bearer {token}"
                    continue
                except Exception as exc:
                    errors.append(f"{base} relogin: {exc}")
                    break
            if resp.status_code >= 500:
                errors.append(f"{base} {resp.status_code}: {resp.text[:180]}")
                break
            return resp, base, None

    if not errors:
        errors.append("backend nao respondeu")
    return None, None, " | ".join(errors)


def _parse_cameras_list(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        raw_items = payload.get("items")
        if isinstance(raw_items, list):
            return [item for item in raw_items if isinstance(item, dict)]
    return []


def _fetch_cameras_from_core(max_items: int) -> tuple[list[dict[str, object]], Optional[str], Optional[str]]:
    cameras: list[dict[str, object]] = []
    skip = 0
    base_used: Optional[str] = None
    max_items = max(1, max_items)

    while len(cameras) < max_items:
        page_limit = min(100, max_items - len(cameras))
        resp, base, err = _core_api_request(
            "GET",
            "/cameras/",
            params={"skip": skip, "limit": page_limit},
        )
        if resp is None:
            return [], base_used or base, err or "backend indisponivel"

        base_used = base
        if resp.status_code != 200:
            return [], base_used, f"backend {resp.status_code}: {resp.text[:180]}"

        payload = resp.json() if resp.content else []
        page_items = _parse_cameras_list(payload)
        if not page_items:
            break

        cameras.extend(page_items)
        if len(page_items) < page_limit:
            break
        skip += len(page_items)

    return cameras, base_used, None


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
    safe_id = _sanitize_device_id(device_id) if device_id else None
    if not safe_id:
        safe_id = "unknown_device"
    ts = time.time()
    entry = {
        "timestamp": datetime.fromtimestamp(ts, BRAZIL_TZ).isoformat(),
        "device_id": safe_id,
        "event": event,
        "message": message,
    }
    _recent_events.append(entry)
    _device_last_seen[safe_id] = ts
    _dashboard_cache["expires_at"] = 0.0
    _append_event_to_disk(entry)
    print(f"[DEVICE] {safe_id} | {event} | {message}", flush=True)


def _iso_to_epoch(iso_text: str) -> Optional[float]:
    text = str(iso_text or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=BRAZIL_TZ)
        return parsed.timestamp()
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
        # Keep values in Brazil timezone for consistency with SAIRA operations.
        parsed_local = datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=CAPTURE_FILENAME_TZ)
        return parsed_local.astimezone(BRAZIL_TZ).isoformat()
    except ValueError:
        return datetime.fromtimestamp(mtime, BRAZIL_TZ).isoformat()


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
    today = datetime.now(BRAZIL_TZ).date()
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
    with _dashboard_cache_lock:
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
                    "last_seen_at": datetime.fromtimestamp(last_seen_ts, BRAZIL_TZ).isoformat() if last_seen_ts > 0 else None,
                    "last_event_at": datetime.fromtimestamp(last_event_ts, BRAZIL_TZ).isoformat() if last_event_ts > 0 else None,
                    "last_image_at": datetime.fromtimestamp(last_image_ts, BRAZIL_TZ).isoformat() if last_image_ts > 0 else None,
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
            "expires_at": time.time() + DASHBOARD_CACHE_TTL_SECONDS,
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
        return _dashboard_cache


def _dashboard_device_filter() -> tuple[Optional[str], Optional[tuple[dict[str, str], int]]]:
    raw_device_id = (request.args.get("device_id") or "").strip()
    if not raw_device_id:
        return None, None
    selected_device = _sanitize_device_id(raw_device_id)
    if not selected_device:
        return None, ({"error": "Invalid device_id"}, 400)
    return selected_device, None


def _dashboard_limit(name: str, default: int, max_limit: int) -> int:
    limit_str = (request.args.get(name) or str(default)).strip()
    try:
        return max(1, min(int(limit_str), max_limit))
    except ValueError:
        return default


def _dashboard_payload(
    data: dict[str, object],
    selected_device: Optional[str],
    *,
    image_limit: int,
    log_limit: int,
) -> dict[str, object]:
    recent_images = list(data.get("recent_images", []))
    devices = list(data.get("devices", []))
    logs = list(data.get("recent_logs", []))
    if selected_device:
        recent_images = [item for item in recent_images if str(item.get("device_id")) == selected_device]
        devices = [item for item in devices if str(item.get("device_id")) == selected_device]
        logs = [item for item in logs if str(item.get("device_id")) == selected_device]

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
        "selected_device": selected_device,
        "summary": {
            "total_images": filtered_total_images,
            "total_images_bytes": filtered_total_bytes,
            "total_images_scope_days": data.get("total_images_scope_days", DASHBOARD_RECENT_DAYS),
            "estimated_4g_mb_per_day": round(filtered_mb_day, 3),
            "estimated_4g_gb_per_month": round(filtered_gb_month, 4),
            "active_devices": active_devices,
            "active_devices_count": len(active_devices),
            "total_known_devices": len(devices),
            "latest_image": latest,
            "active_window_seconds": DEVICE_ACTIVE_WINDOW_SECONDS,
            "devices": devices,
        },
        "devices": {
            "count": len(devices),
            "active_count": len(active_devices),
            "devices": devices,
        },
        "recent_images": {
            "limit": image_limit,
            "count": min(len(recent_images), image_limit),
            "images": recent_images[:image_limit],
        },
        "recent_logs": {
            "limit": log_limit,
            "count": min(len(logs), log_limit),
            "logs": logs[:log_limit],
        },
    }


@app.route("/uploads/<path:filepath>", methods=["GET"])
def get_uploaded_file(filepath: str):
    return send_from_directory(UPLOAD_ROOT, filepath)


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/dashboard/summary", methods=["GET"])
def dashboard_summary():
    selected_device, error = _dashboard_device_filter()
    if error:
        return error
    data = _dashboard_snapshot()
    payload = _dashboard_payload(data, selected_device, image_limit=12, log_limit=20)
    summary = dict(payload["summary"])
    summary["updated_at"] = payload["updated_at"]
    summary["selected_device"] = payload["selected_device"]
    return summary, 200


@app.route("/api/dashboard/devices", methods=["GET"])
def dashboard_devices():
    selected_device, error = _dashboard_device_filter()
    if error:
        return error
    only_active_raw = (request.args.get("only_active") or "").strip().lower()
    only_active = only_active_raw in {"1", "true", "yes", "on"}
    data = _dashboard_snapshot()
    payload = _dashboard_payload(data, selected_device, image_limit=12, log_limit=20)
    device_payload = dict(payload["devices"])
    devices = list(device_payload.get("devices", []))
    if only_active:
        devices = [item for item in devices if bool(item.get("is_active"))]
        device_payload["count"] = len(devices)
        device_payload["active_count"] = len(devices)
        device_payload["devices"] = devices
    device_payload["updated_at"] = payload["updated_at"]
    return device_payload, 200


@app.route("/api/dashboard/recent-images", methods=["GET"])
def dashboard_recent_images():
    selected_device, error = _dashboard_device_filter()
    if error:
        return error
    limit = _dashboard_limit("limit", 12, 120)
    data = _dashboard_snapshot()
    payload = _dashboard_payload(data, selected_device, image_limit=limit, log_limit=20)
    images_payload = dict(payload["recent_images"])
    images_payload["updated_at"] = payload["updated_at"]
    images_payload["selected_device"] = payload["selected_device"]
    return images_payload, 200


@app.route("/api/dashboard/recent-logs", methods=["GET"])
def dashboard_recent_logs():
    selected_device, error = _dashboard_device_filter()
    if error:
        return error
    limit = _dashboard_limit("limit", 20, 60)
    data = _dashboard_snapshot()
    payload = _dashboard_payload(data, selected_device, image_limit=12, log_limit=limit)
    logs_payload = dict(payload["recent_logs"])
    logs_payload["updated_at"] = payload["updated_at"]
    logs_payload["selected_device"] = payload["selected_device"]
    return logs_payload, 200


@app.route("/api/dashboard/state", methods=["GET"])
def dashboard_state():
    selected_device, error = _dashboard_device_filter()
    if error:
        return error
    image_limit = _dashboard_limit("image_limit", 12, 120)
    log_limit = _dashboard_limit("log_limit", 25, 60)
    data = _dashboard_snapshot()
    return _dashboard_payload(data, selected_device, image_limit=image_limit, log_limit=log_limit), 200


@app.route("/api/dashboard/camera-latest-image", methods=["GET"])
def dashboard_camera_latest_image():
    raw_device_id = (request.args.get("device_id") or "").strip()
    device_id = _sanitize_device_id(raw_device_id)
    if not device_id:
        return {"error": "device_id invalido"}, 400

    cameras, base, err = _fetch_cameras_from_core(CORE_API_CAMERA_LIMIT)
    if err:
        return {
            "error": "nao foi possivel consultar cameras no backend",
            "backend_error": err,
            "backend_base_url": base,
        }, 502

    camera = next(
        (
            item
            for item in cameras
            if _sanitize_device_id(str(item.get("device_id") or "")) == device_id
        ),
        None,
    )
    if not camera:
        return {
            "error": "camera nao encontrada para o device_id informado",
            "device_id": device_id,
            "backend_base_url": base,
        }, 404

    camera_id = camera.get("id")
    if camera_id is None:
        return {
            "error": "camera sem id valido no backend",
            "device_id": device_id,
            "backend_base_url": base,
        }, 502

    resp, image_base, image_err = _core_api_request(
        "GET",
        f"/cameras/{camera_id}/latest-image",
    )
    if resp is None:
        return {
            "error": "nao foi possivel consultar imagem mais recente",
            "device_id": device_id,
            "camera_id": camera_id,
            "backend_error": image_err,
            "backend_base_url": image_base or base,
        }, 502
    if resp.status_code != 200:
        return {
            "error": "backend recusou consulta da imagem mais recente",
            "device_id": device_id,
            "camera_id": camera_id,
            "backend_status": resp.status_code,
            "backend_response": resp.text[:400],
            "backend_base_url": image_base or base,
        }, resp.status_code

    payload = resp.json() if resp.content else {}
    if not isinstance(payload, dict):
        payload = {}
    payload["device_id"] = device_id
    payload["camera_id"] = camera_id
    payload["backend_base_url"] = image_base or base
    return payload, 200


def _bool_from_payload(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _float_from_payload(value: object, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} invalido")
    return parsed


def _clean_text(value: object, *, limit: int) -> Optional[str]:
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    return txt[:limit]


@app.route("/api/dashboard/camera-registration/options", methods=["GET"])
def dashboard_camera_registration_options():
    data = _dashboard_snapshot()
    devices = list(data.get("devices", []))
    device_rows: list[dict[str, object]] = []
    for item in devices:
        if not isinstance(item, dict):
            continue
        did = _sanitize_device_id(str(item.get("device_id") or ""))
        if not did:
            continue
        row = dict(item)
        row["device_id"] = did
        device_rows.append(row)

    cameras, base, err = _fetch_cameras_from_core(CORE_API_CAMERA_LIMIT)
    backend_ok = False
    backend_error = None
    if err:
        backend_error = err or "backend indisponivel"
    else:
        backend_ok = True

    by_device: dict[str, dict[str, object]] = {}
    for camera in cameras:
        did = _sanitize_device_id(str(camera.get("device_id") or ""))
        if did:
            by_device[did] = camera

    enriched_devices: list[dict[str, object]] = []
    for row in device_rows:
        did = str(row.get("device_id"))
        cam = by_device.get(did)
        item = dict(row)
        item["is_registered"] = bool(cam)
        item["registered_camera_id"] = cam.get("id") if cam else None
        item["registered_camera_name"] = cam.get("name") if cam else None
        item["registered_camera_active"] = bool(cam.get("is_active")) if cam else None
        enriched_devices.append(item)

    registered_count = len([item for item in enriched_devices if bool(item.get("is_registered"))])
    unregistered_count = len(enriched_devices) - registered_count

    return {
        "updated_at": _utc_now_iso(),
        "backend": {
            "ok": backend_ok,
            "base_url": base,
            "error": backend_error,
        },
        "registered_count": registered_count,
        "unregistered_count": unregistered_count,
        "devices": enriched_devices,
    }, 200


@app.route("/api/dashboard/camera-registration", methods=["POST"])
def dashboard_camera_registration_create():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {"error": "JSON invalido"}, 400

    raw_device_id = str(payload.get("device_id") or "").strip()
    device_id = _sanitize_device_id(raw_device_id)
    if not device_id:
        return {"error": "device_id invalido"}, 400

    known_ids = {
        str(item.get("device_id"))
        for item in list(_dashboard_snapshot().get("devices", []))
        if isinstance(item, dict) and _sanitize_device_id(str(item.get("device_id") or ""))
    }
    if device_id not in known_ids:
        return {"error": "device_id nao encontrado entre dispositivos existentes"}, 404

    name = _clean_text(payload.get("name"), limit=255)
    if not name:
        return {"error": "name obrigatorio"}, 400

    try:
        latitude = _float_from_payload(payload.get("latitude"), "latitude")
        longitude = _float_from_payload(payload.get("longitude"), "longitude")
    except ValueError as exc:
        return {"error": str(exc)}, 400

    if latitude < -90 or latitude > 90:
        return {"error": "latitude fora do intervalo [-90, 90]"}, 400
    if longitude < -180 or longitude > 180:
        return {"error": "longitude fora do intervalo [-180, 180]"}, 400

    try:
        capture_interval_seconds = int(payload.get("capture_interval_seconds", 30))
    except (TypeError, ValueError):
        return {"error": "capture_interval_seconds invalido"}, 400
    if capture_interval_seconds < 1:
        return {"error": "capture_interval_seconds deve ser >= 1"}, 400

    camera_payload: dict[str, object] = {
        "name": name,
        "device_id": device_id,
        "latitude": latitude,
        "longitude": longitude,
        "capture_interval_seconds": capture_interval_seconds,
        "is_active": _bool_from_payload(payload.get("is_active"), True),
    }
    for field, limit in (
        ("logradouro", 255),
        ("bairro", 100),
        ("rpa", 10),
        ("rtsp_url", 512),
    ):
        cleaned = _clean_text(payload.get(field), limit=limit)
        if cleaned is not None:
            camera_payload[field] = cleaned

    existing_cameras, check_base, check_err = _fetch_cameras_from_core(CORE_API_CAMERA_LIMIT)
    if check_err:
        return {
            "error": "nao foi possivel consultar cameras no backend",
            "backend_error": check_err,
        }, 502
    for camera in existing_cameras:
        existing_device = _sanitize_device_id(str(camera.get("device_id") or ""))
        if existing_device == device_id:
            return {
                "error": "device_id ja cadastrado como camera",
                "camera": camera,
                "backend_base_url": check_base,
            }, 409

    create_resp, create_base, create_err = _core_api_request(
        "POST",
        "/cameras/",
        json_body=camera_payload,
    )
    if create_resp is None:
        return {
            "error": "nao foi possivel cadastrar camera no backend",
            "backend_error": create_err,
        }, 502
    if create_resp.status_code not in {200, 201}:
        return {
            "error": "backend recusou cadastro de camera",
            "backend_status": create_resp.status_code,
            "backend_response": create_resp.text[:600],
            "backend_base_url": create_base,
        }, create_resp.status_code

    created = create_resp.json() if create_resp.content else {}
    camera_id = created.get("id")
    _record_device_event(device_id, "camera_register", f"Camera cadastrada no backend (id={camera_id})")

    return {
        "status": "ok",
        "backend_base_url": create_base,
        "camera": created,
    }, 201


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
        "crop_x",
        "crop_y",
        "crop_w",
        "crop_h",
    }
    cleaned: dict[str, str] = {}
    for k, v in payload.items():
        kk = k.strip().lower()
        if kk in allowed:
            cleaned[kk] = v.strip()

    version = datetime.now(BRAZIL_TZ).strftime("%Y-%m-%d_%H-%M-%S")
    lines = [f"version={version}"]
    for k in sorted(cleaned.keys()):
        lines.append(f"{k}={cleaned[k]}")
    body = "\n".join(lines) + "\n"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)

    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


# ---------------------------------------------------------------------------
# SSE / bulk-upload (history trigger)
# ---------------------------------------------------------------------------

_sse_queues: dict[str, queue.Queue] = {}
_sse_lock = threading.Lock()

SSE_HEARTBEAT_SECONDS = _int_env("SSE_HEARTBEAT_SECONDS", 30, minimum=5)
# Use UPLOAD_DIR (same volume as regular uploads) so bulk frames land in the
# same mounted directory and are accessible via the /uploads static route.
BULK_UPLOAD_ROOT = os.path.join(
    os.getenv("UPLOAD_DIR", os.getenv("UPLOAD_ROOT", "/app/uploads")), "bulk"
)


def _get_or_create_sse_queue(device_id: str):
    with _sse_lock:
        if device_id not in _sse_queues:
            # maxsize=1: only one pending trigger per device at a time.
            # Prevents flood when device reconnects after an offline period.
            # Uses gevent.queue.Queue when available so get(timeout=N) is truly
            # cooperative and wakes immediately when an item is put().
            _sse_queues[device_id] = _Queue(maxsize=1)
        return _sse_queues[device_id]


def _push_sse_cmd(device_id: str, cmd: str) -> None:
    q = _get_or_create_sse_queue(device_id)
    try:
        q.put_nowait(cmd)
    except _QueueFull:
        pass  # already one pending — discard duplicate


@app.route("/device/<device_id>/events", methods=["GET"])
def device_events(device_id: str):
    """SSE endpoint — device keeps this connection open to receive push triggers."""
    if not _sanitize_device_id(device_id):
        return {"error": "Invalid device id"}, 400

    q = _get_or_create_sse_queue(device_id)

    def generate():
        yield ": connected\n\n"
        while True:
            try:
                cmd = q.get(timeout=SSE_HEARTBEAT_SECONDS)
                yield f"data: {cmd}\n\n"
            except _QueueEmpty:
                yield ": heartbeat\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/device/<device_id>/trigger", methods=["POST"])
def device_trigger(device_id: str):
    """Push a command to the device SSE stream (called by YOLO worker / backend)."""
    if not _sanitize_device_id(device_id):
        return {"error": "Invalid device id"}, 400

    data = request.get_json(silent=True) or {}
    cmd = str(data.get("cmd", "CMD_BULK_UPLOAD")).strip() or "CMD_BULK_UPLOAD"
    _push_sse_cmd(device_id, cmd)
    return {"status": "queued", "device_id": device_id, "cmd": cmd}, 200


@app.route("/device/<device_id>/poll", methods=["GET"])
def device_poll(device_id: str):
    """Long-polling endpoint for device command delivery.

    The device makes a GET request and this endpoint blocks for up to
    POLL_TIMEOUT_SECONDS waiting for a queued command.  When a command
    arrives it is returned immediately as JSON {"cmd": "<CMD>"}.  If no
    command arrives within the timeout, {"cmd": null} is returned.

    This is more reliable than SSE for ESP-IDF clients because it uses
    a standard HTTP request-response cycle that esp_http_client handles
    correctly (no chunked-streaming issues).
    """
    if not _sanitize_device_id(device_id):
        return {"error": "Invalid device id"}, 400

    timeout_s = _int_env("POLL_TIMEOUT_SECONDS", 25, minimum=5)
    q = _get_or_create_sse_queue(device_id)
    try:
        cmd = q.get(timeout=timeout_s)
        return {"cmd": cmd}, 200
    except _QueueEmpty:
        return {"cmd": None}, 200


@app.route("/device/<device_id>/bulk-upload", methods=["POST"])
def device_bulk_upload(device_id: str):
    """Receive TLV-framed JPEG history from device and save to disk.

    Wire format (repeated until end of stream):
        [4 bytes uint32 LE — JPEG size][JPEG bytes]
    """
    if not _sanitize_device_id(device_id):
        return {"error": "Invalid device id"}, 400

    ts_str = datetime.now(CAPTURE_FILENAME_TZ).strftime("%Y%m%d_%H%M%S")
    save_dir = os.path.join(BULK_UPLOAD_ROOT, device_id, ts_str)
    os.makedirs(save_dir, exist_ok=True)

    buf = bytearray()
    frame_index = 0
    saved_files: list[str] = []

    for chunk in request.stream:
        buf.extend(chunk)
        while len(buf) >= 4:
            frame_size = struct.unpack_from("<I", buf, 0)[0]
            if frame_size == 0 or frame_size > 600_000:
                # Corrupt or unreasonably large — skip one byte and resync
                del buf[:1]
                continue
            if len(buf) < 4 + frame_size:
                break  # wait for more data
            jpeg_bytes = bytes(buf[4 : 4 + frame_size])
            del buf[: 4 + frame_size]
            # Validate JPEG magic bytes
            if not (jpeg_bytes[:2] == b"\xff\xd8" and jpeg_bytes[-2:] == b"\xff\xd9"):
                frame_index += 1
                continue
            fname = f"frame_{frame_index:04d}.jpg"
            fpath = os.path.join(save_dir, fname)
            with open(fpath, "wb") as f:
                f.write(jpeg_bytes)
            saved_files.append(fpath)
            frame_index += 1

    print(
        f"[bulk] device={device_id} received={frame_index} saved={len(saved_files)} dir={save_dir}",
        flush=True,
    )
    return {
        "status": "ok",
        "device_id": device_id,
        "frames_received": frame_index,
        "frames_saved": len(saved_files),
        "save_dir": save_dir,
    }, 200


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
        version = datetime.now(BRAZIL_TZ).strftime("%Y-%m-%d_%H-%M-%S")

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
    dt = datetime.now(CAPTURE_FILENAME_TZ)
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
