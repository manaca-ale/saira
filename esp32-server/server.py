from flask import Flask, request, send_from_directory
from datetime import datetime
import os
import hashlib
import re
from typing import Optional

app = Flask(__name__)

def _get_upload_root() -> str:
    # Allow overriding storage location on EC2 (e.g. /data/saira/uploads).
    # Defaults to ./uploads next to this file.
    return os.getenv(
        "UPLOAD_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads"),
    )


UPLOAD_ROOT = _get_upload_root()
os.makedirs(UPLOAD_ROOT, exist_ok=True)

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


def _admin_token() -> str:
    return os.getenv("ADMIN_TOKEN", "")


def _public_base_url() -> str:
    # Example: https://your-domain.com or http://EC2_PUBLIC_IP:5000
    return os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


def _relative_path_for_now(filename: str) -> str:
    # Partition by date so the EC2 disk doesn't end up with one huge directory.
    dt = datetime.utcnow()
    return os.path.join(dt.strftime("%Y/%m/%d"), filename)


@app.route("/uploads/<path:filepath>", methods=["GET"])
def get_uploaded_file(filepath: str):
    return send_from_directory(UPLOAD_ROOT, filepath)

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

    print(f"Received image: {rel_path} (device={device_id})", flush=True)

    base = _public_base_url()
    rel_url = rel_path.replace(os.sep, "/")
    if base:
        image_url = f"{base}/uploads/{rel_url}"
    else:
        image_url = f"/uploads/{rel_url}"

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

    return "Received", 200

if __name__ == "__main__":
    # Bind to 0.0.0.0 so the app is reachable outside the container
    app.run(host="0.0.0.0", port=5000, debug=True)
