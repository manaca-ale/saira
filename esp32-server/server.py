from flask import Flask, request
from datetime import datetime
import os

app = Flask(__name__)

# Ensure the uploads directory exists at startup
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

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
    save_path = os.path.join(UPLOAD_DIR, filename)
    file.save(save_path)

    # Log receipt for visibility in container logs
    print(f"Received image: {filename} ({file.content_length} bytes)", flush=True)

    return {"status": "ok", "filename": filename}, 200

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
