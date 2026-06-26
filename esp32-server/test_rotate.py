"""Focused tests for the ingest-time 180° rotation (_maybe_rotate_180).

Run inside the built image where flask + Pillow are available:
    docker run --rm -e ROTATE_180_DEVICES=esp32_004 \
        -v "$PWD":/app -w /app saira-esp32-server \
        sh -c "pip install pytest >/dev/null && pytest -q test_rotate.py"
"""
import importlib

import pytest

server = importlib.import_module("server")
Image = importlib.import_module("PIL.Image")


@pytest.fixture(autouse=True)
def _rotate_set(monkeypatch):
    # Helper reads the module-level set; force a known value regardless of env.
    monkeypatch.setattr(server, "ROTATE_180_DEVICES", {"esp32_004"})


def _mean_red(img, box):
    crop = img.crop(box)
    px = list(crop.getdata())
    return sum(p[0] for p in px) / len(px)


def _make_asymmetric_jpeg(path):
    # Top half solid red, bottom half solid green. Region means survive JPEG
    # re-compression, so a 180° turn is unambiguous (the halves swap ends).
    img = Image.new("RGB", (64, 64), (0, 0, 0))
    img.paste((255, 0, 0), (0, 0, 64, 32))     # top half red
    img.paste((0, 255, 0), (0, 32, 64, 64))    # bottom half green
    img.save(path, quality=95)


def test_rotates_listed_device(tmp_path):
    p = tmp_path / "frame.jpg"
    _make_asymmetric_jpeg(p)
    # Before: red is on top.
    src = Image.open(p).convert("RGB")
    assert _mean_red(src, (0, 0, 64, 32)) > 150
    assert _mean_red(src, (0, 32, 64, 64)) < 100

    assert server._maybe_rotate_180(str(p), "esp32_004") is True

    got = Image.open(p).convert("RGB")
    assert got.size == (64, 64)
    # After 180°: red is now on the bottom, green on top.
    assert _mean_red(got, (0, 32, 64, 64)) > 150
    assert _mean_red(got, (0, 0, 64, 32)) < 100


def test_untouched_device_is_byte_identical(tmp_path):
    p = tmp_path / "frame.jpg"
    _make_asymmetric_jpeg(p)
    before = p.read_bytes()

    assert server._maybe_rotate_180(str(p), "esp32_001") is False
    assert p.read_bytes() == before


def test_case_insensitive_match(tmp_path):
    p = tmp_path / "frame.jpg"
    _make_asymmetric_jpeg(p)
    assert server._maybe_rotate_180(str(p), "ESP32_004") is True


def test_invalid_frame_does_not_raise(tmp_path):
    p = tmp_path / "bad.jpg"
    p.write_bytes(b"not a real jpeg")
    before = p.read_bytes()

    # Must swallow the decode error and leave the file untouched.
    assert server._maybe_rotate_180(str(p), "esp32_004") is False
    assert p.read_bytes() == before
