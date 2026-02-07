from flask import Flask, request, send_from_directory
from datetime import datetime
import os

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

@app.route("/upload", methods=["POST"])
def upload_file():
    # Validate that an image file was provided
    if "imageFile" not in request.files:
        # Debug info to understand why multipart parsing failed
        print(
            "Upload missing imageFile | "
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
        # Debug info to understand empty filename cases
        print(
            "Upload empty filename | "
            f"content_type={request.content_type} | "
            f"content_length={request.headers.get('Content-Length')} | "
            f"files_keys={list(request.files.keys())}",
            flush=True,
        )
        return {"error": "Empty filename"}, 400

    # Build a timestamped filename and save the image
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}.jpg"
    rel_path = _relative_path_for_now(filename)
    save_path = os.path.join(UPLOAD_ROOT, rel_path)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    file.save(save_path)

    # Log receipt for visibility in container logs
    print(f"Received image: {rel_path} ({file.content_length} bytes)", flush=True)

    base = _public_base_url()
    if base:
        image_url = f"{base}/uploads/{rel_path.replace(os.sep, '/')}"
    else:
        image_url = f"/uploads/{rel_path.replace(os.sep, '/')}"

    return {"status": "ok", "filename": rel_path.replace(os.sep, "/"), "image_url": image_url}, 200

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
