"""
Simulation script — posts test images to esp32-server mimicking ESP32 camera uploads.

Usage:
    python simulate_upload.py [image_folder] [device_id] [interval_seconds]

Defaults:
    image_folder  = ./test_images
    device_id     = test-cam-001
    interval      = 2  seconds between uploads
"""
import sys
import time
import requests
from pathlib import Path
from datetime import datetime

ESP32_SERVER = "http://localhost:5002"
IMAGE_FOLDER = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "test_images"
DEVICE_ID    = sys.argv[2] if len(sys.argv) > 2 else "test-cam-001"
INTERVAL     = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0

EXTENSIONS = {".jpg", ".jpeg", ".png"}


def upload_image(image_path: Path, device_id: str) -> bool:
    with open(image_path, "rb") as f:
        try:
            resp = requests.post(
                f"{ESP32_SERVER}/upload",
                headers={"X-Device-Id": device_id},
                files={"imageFile": (image_path.name, f, "image/jpeg")},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                print(f"  [OK] {image_path.name} -> {data.get('image_url', '?')}")
                return True
            else:
                print(f"  [ERR {resp.status_code}] {image_path.name}: {resp.text[:120]}")
                return False
        except Exception as e:
            print(f"  [FAIL] {image_path.name}: {e}")
            return False


def seed_camera(device_id: str):
    """Insert a test camera directly via the backend API if it doesn't exist."""
    backend = "http://localhost:8001/api/v1"
    try:
        # Try to get a token (local admin account)
        r = requests.post(f"{backend}/auth/login", json={"email": "admin@saira.com", "password": "admin123"}, timeout=5)
        if r.status_code != 200:
            print(f"[WARN] Could not login to backend ({r.status_code}). Camera must exist in DB already.")
            return

        token = r.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}

        # Check if camera exists
        r = requests.get(f"{backend}/cameras/", headers=headers, timeout=5)
        cameras = r.json() if r.status_code == 200 else []
        if isinstance(cameras, dict):
            cameras = cameras.get("items", [])

        existing = [c for c in cameras if c.get("device_id") == device_id]
        if existing:
            print(f"[OK] Camera '{device_id}' already exists (id={existing[0]['id']})")
            return

        # Create camera
        payload = {
            "name": f"Camera Teste ({device_id})",
            "device_id": device_id,
            "logradouro": "Av. Recife",
            "bairro": "Boa Viagem",
            "rpa": "6",
            "latitude": -8.1137,
            "longitude": -34.8947,
            "is_active": True,
        }
        r = requests.post(f"{backend}/cameras/", json=payload, headers=headers, timeout=5)
        if r.status_code in (200, 201):
            print(f"[OK] Camera created: {r.json().get('id')}")
        else:
            print(f"[WARN] Could not create camera ({r.status_code}): {r.text[:200]}")
            print("      Insert manually via pgAdmin or the backend API.")
    except Exception as e:
        print(f"[WARN] Backend not reachable: {e}")
        print("      Make sure a camera with device_id='{device_id}' exists in the DB.")


def main():
    images = sorted([p for p in IMAGE_FOLDER.iterdir() if p.suffix.lower() in EXTENSIONS])
    if not images:
        print(f"No images found in {IMAGE_FOLDER}")
        sys.exit(1)

    print(f"SAIRA Image Simulator")
    print(f"  Server  : {ESP32_SERVER}")
    print(f"  Device  : {DEVICE_ID}")
    print(f"  Images  : {len(images)} from {IMAGE_FOLDER}")
    print(f"  Interval: {INTERVAL}s\n")

    print("Checking/creating test camera in DB...")
    seed_camera(DEVICE_ID)
    print()

    ok = 0
    for i, img in enumerate(images, 1):
        print(f"[{i:03d}/{len(images)}] Uploading {img.name} ...")
        if upload_image(img, DEVICE_ID):
            ok += 1
        if i < len(images):
            time.sleep(INTERVAL)

    print(f"\nDone. {ok}/{len(images)} uploaded successfully.")
    print(f"Watch yolo-worker logs: docker logs -f saira-yolo-worker")
    print(f"Check detections:       http://localhost:8001/api/v1/detections/search")


if __name__ == "__main__":
    main()

