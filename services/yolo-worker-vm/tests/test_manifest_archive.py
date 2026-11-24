"""Processed event manifests must not pile up in the scanned folder.

Regression (measured on the server on 2026-11-24): pi-cam-001 had 31,943
processed manifests in ``events/`` and every cycle globbed all of them (0.85 s
per glob, twice per cycle). With EVENT_MANIFEST_ARCHIVE_AFTER_SECONDS set, old
processed ones go to ``events/arquivo/AAAAMM/`` and leave the glob.
"""
import json
import os
import time

from worker import config
from worker import event_windows
from worker import main as worker_main


def _manifest(events, name, processed_age_s=None, now=None):
    m = events / f"{name}.json"
    m.write_text(json.dumps({"event_id": name, "device_id": "pi-cam-001", "state": "closed", "frames": []}))
    (events / f"{name}.json.lock").write_text("")
    if processed_age_s is not None:
        marker = events / f"{name}.json.processed"
        marker.write_text("")
        os.utime(marker, (now - processed_age_s, now - processed_age_s))
    return m


def _setup(tmp_path):
    now = time.time()
    events = tmp_path / "pi-cam-001" / "events"
    events.mkdir(parents=True)
    _manifest(events, "evt-old", processed_age_s=5 * 86400, now=now)
    _manifest(events, "evt-recent", processed_age_s=600, now=now)
    _manifest(events, "evt-open", processed_age_s=None, now=now)
    return now, tmp_path / "pi-cam-001", events


def test_scan_cycle_archives_old_processed_manifests(tmp_path, monkeypatch):
    now, device_dir, events = _setup(tmp_path)
    monkeypatch.setattr(config, "EVENT_MANIFEST_ARCHIVE_AFTER_SECONDS", 2 * 86400, raising=False)
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(worker_main, "_last_manifest_archive", {}, raising=False)

    worker_main._process_event_device(device_dir, "pi-cam-001", camera={"id": 1})

    left = sorted(p.name for p in events.glob("*.json"))
    assert left == ["evt-open.json", "evt-recent.json"]
    archived = list((events / "arquivo").rglob("evt-old.json*"))
    assert sorted(p.name for p in archived) == ["evt-old.json", "evt-old.json.lock", "evt-old.json.processed"]
    # O arquivado não volta a ser lido pela descoberta.
    assert all(m.event_id != "evt-old" for m in event_windows.discover_ready_manifests(device_dir, worker_main.datetime.now(worker_main.BRASILIA)))


def test_disabled_keeps_everything(tmp_path):
    now, _device_dir, events = _setup(tmp_path)
    assert event_windows.archive_processed_manifests(events.parent, now, 0) == 0
    assert len(list(events.glob("*.json"))) == 3


def test_runs_at_most_once_an_hour(tmp_path, monkeypatch):
    now, device_dir, events = _setup(tmp_path)
    monkeypatch.setattr(config, "EVENT_MANIFEST_ARCHIVE_AFTER_SECONDS", 2 * 86400, raising=False)
    monkeypatch.setattr(worker_main, "_last_manifest_archive", {}, raising=False)
    assert worker_main._maybe_archive_manifests(device_dir, "pi-cam-001", now=now) == 1
    _manifest(events, "evt-old2", processed_age_s=5 * 86400, now=now)
    assert worker_main._maybe_archive_manifests(device_dir, "pi-cam-001", now=now + 60) == 0
    assert worker_main._maybe_archive_manifests(device_dir, "pi-cam-001", now=now + 3601) == 1
