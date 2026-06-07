"""Tests for storage_s3 fixes:
- _cleanup_ocorrencias_originals respects ocorrencias/ files referenced by
  detection_frames JSONs of detections that have NOT been migrated yet.
- _update_detection_frames drops orphan frames (no local file, no S3 object)
  from the JSON instead of leaving the URL pointing to a 404.
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

# Stub out heavy native deps that the worker package transitively imports.
for name, stub in {
    "cv2": types.SimpleNamespace(imread=lambda *a, **k: None, imwrite=lambda *a, **k: True),
}.items():
    sys.modules.setdefault(name, stub)

if "psycopg2" not in sys.modules:
    psycopg2_mod = types.ModuleType("psycopg2")
    extras_mod = types.ModuleType("psycopg2.extras")
    pool_mod = types.ModuleType("psycopg2.pool")
    extras_mod.register_uuid = lambda *a, **k: None
    pool_mod.ThreadedConnectionPool = object
    psycopg2_mod.extras = extras_mod
    psycopg2_mod.pool = pool_mod
    sys.modules["psycopg2"] = psycopg2_mod
    sys.modules["psycopg2.extras"] = extras_mod
    sys.modules["psycopg2.pool"] = pool_mod


@pytest.fixture
def temp_dirs(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    state_dir = tmp_path / "state"
    (state_dir / "detection_frames").mkdir(parents=True)
    upload_dir.mkdir()

    from worker import config

    monkeypatch.setattr(config, "UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(config, "STATE_DIR", str(state_dir))
    return upload_dir, state_dir


def _write_frames_json(state_dir: Path, det_id: str, urls: list[str], default_idx: int = 0):
    payload = {
        "detection_id": det_id,
        "device_id": "esp32_002",
        "selected_frame_name": Path(urls[default_idx]).name,
        "frames": [
            {
                "frame_name": Path(u).name,
                "image_url": u,
                "is_default": i == default_idx,
            }
            for i, u in enumerate(urls)
        ],
    }
    (state_dir / "detection_frames" / f"{det_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _make_jpg(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"jpg-bytes" * 10)


def test_cleanup_skips_files_referenced_by_orphan_detection(temp_dirs):
    """When a detection has NOT been migrated (JSON still points to /uploads/),
    cleanup must NOT delete its frames."""
    from worker import storage_s3

    upload_dir, state_dir = temp_dirs
    device = "esp32_002"
    date_str = "2026-05-18"
    date_parts = "2026/05/18"

    occ_dir = upload_dir / device / "ocorrencias" / date_parts
    # 3 referenced (orphan detection), 2 unreferenced (true cleanup targets)
    referenced_files = ["a.jpg", "b.jpg", "c.jpg"]
    unreferenced_files = ["x.jpg", "y.jpg"]
    for name in referenced_files + unreferenced_files:
        _make_jpg(occ_dir / name)

    _write_frames_json(
        state_dir,
        "det-orphan",
        [
            f"http://localhost:5005/uploads/{device}/ocorrencias/{date_parts}/{n}"
            for n in referenced_files
        ],
    )

    removed = storage_s3._cleanup_ocorrencias_originals(date_str)

    assert removed == 2, "should delete only the 2 unreferenced files"
    for name in referenced_files:
        assert (occ_dir / name).exists(), f"{name} should be preserved"
    for name in unreferenced_files:
        assert not (occ_dir / name).exists(), f"{name} should be removed"


def test_cleanup_ignores_already_migrated_detection_frames(temp_dirs):
    """A detection whose JSON already points to S3 (migrated) doesn't lock files."""
    from worker import storage_s3

    upload_dir, state_dir = temp_dirs
    device = "esp32_002"
    date_str = "2026-05-18"
    date_parts = "2026/05/18"

    occ_dir = upload_dir / device / "ocorrencias" / date_parts
    _make_jpg(occ_dir / "stale.jpg")  # leftover after partial cleanup
    _write_frames_json(
        state_dir,
        "det-migrated",
        ["https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/x/2026/05/18/stale.jpg"],
    )

    removed = storage_s3._cleanup_ocorrencias_originals(date_str)
    assert removed == 1
    assert not (occ_dir / "stale.jpg").exists()


class _FakeS3:
    """Minimal boto3 stand-in supporting upload_file + head_object."""

    def __init__(self, *, existing_keys: set[str] | None = None):
        self.uploaded: list[tuple[str, str]] = []  # (bucket, key)
        self.existing_keys = set(existing_keys or [])

    def upload_file(self, local_path, bucket, key, ExtraArgs=None):
        self.uploaded.append((bucket, key))
        self.existing_keys.add(key)

    def head_object(self, Bucket, Key):
        if Key in self.existing_keys:
            return {}
        raise Exception("NoSuchKey")


def test_update_frames_drops_orphan_when_file_gone_and_not_in_s3(temp_dirs, monkeypatch):
    """If a frame's local file was deleted by the cleanup bug AND it never
    made it to S3, the frame must be removed from the JSON (otherwise the
    UI shows a permanently broken thumbnail)."""
    from worker import storage_s3

    upload_dir, state_dir = temp_dirs
    device = "esp32_002"
    date_parts = "2026/05/18"

    occ_dir = upload_dir / device / "ocorrencias" / date_parts
    _make_jpg(occ_dir / "alive.jpg")  # this one still exists locally
    # "dead.jpg" was deleted by the cleanup bug → not on disk, not on S3

    _write_frames_json(
        state_dir,
        "det-mixed",
        [
            f"http://localhost:5005/uploads/{device}/ocorrencias/{date_parts}/alive.jpg",
            f"http://localhost:5005/uploads/{device}/ocorrencias/{date_parts}/dead.jpg",
        ],
        default_idx=0,
    )

    fake_s3 = _FakeS3()
    changed = storage_s3._update_detection_frames(
        fake_s3, "saira-images", "sa-east-1",
        state_dir, upload_dir, "det-mixed", device, date_parts,
    )

    assert changed is True
    out = json.loads((state_dir / "detection_frames" / "det-mixed.json").read_text())
    names = [f["frame_name"] for f in out["frames"]]
    assert names == ["alive.jpg"], "dead frame should be dropped from index"
    # alive.jpg uploaded + url rewritten to S3
    assert out["frames"][0]["image_url"].startswith("https://saira-images.s3.sa-east-1.amazonaws.com/")
    assert ("saira-images", f"ocorrencias/{device}/{date_parts}/alive.jpg") in fake_s3.uploaded


def test_update_frames_recovers_when_local_gone_but_already_in_s3(temp_dirs):
    """Partial prior run left S3 object behind — keep the frame, just rewrite URL."""
    from worker import storage_s3

    upload_dir, state_dir = temp_dirs
    device = "esp32_002"
    date_parts = "2026/05/18"

    _write_frames_json(
        state_dir,
        "det-partial",
        [f"http://localhost:5005/uploads/{device}/ocorrencias/{date_parts}/x.jpg"],
    )
    # local file does NOT exist, but S3 has it already
    fake_s3 = _FakeS3(existing_keys={f"ocorrencias/{device}/{date_parts}/x.jpg"})

    changed = storage_s3._update_detection_frames(
        fake_s3, "saira-images", "sa-east-1",
        state_dir, upload_dir, "det-partial", device, date_parts,
    )

    assert changed is True
    out = json.loads((state_dir / "detection_frames" / "det-partial.json").read_text())
    assert len(out["frames"]) == 1
    assert out["frames"][0]["image_url"].endswith(f"ocorrencias/{device}/{date_parts}/x.jpg")
    assert fake_s3.uploaded == []  # no re-upload needed
