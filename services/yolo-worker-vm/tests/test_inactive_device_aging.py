"""Raw frames of a device with no active camera must not pile up forever.

Regression (disk at 91% on 2026-11-24): the scan skips devices whose camera is
inactive or unregistered, but the esp32-server keeps accepting their uploads.
esp32_002 left 14 GB of raw ``AAAA/MM/DD`` frames that nothing ever moved, so the
daily S3 sync (which only looks at ``sem_ocorrencia``/``ocorrencias``) never
freed them. With INACTIVE_DEVICE_MAX_FRAME_AGE_SECONDS set, the scan moves the
old ones to ``sem_ocorrencia`` without calling any model.
"""
import os
import time
from pathlib import Path

from worker import config
from worker import main as worker_main


def _frame(root: Path, rel: str, age_s: float, now: float) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xff\xd8jpg")
    os.utime(p, (now - age_s, now - age_s))
    return p


def test_disabled_leaves_frames_in_place(tmp_path):
    now = time.time()
    old = _frame(tmp_path, "2026/10/05/a.jpg", 10 * 86400, now)
    assert worker_main._age_out_unregistered_frames(tmp_path, 0, now) == 0
    assert old.exists()


def test_moves_only_old_raw_frames(tmp_path):
    now = time.time()
    old = _frame(tmp_path, "2026/10/05/old.jpg", 7200, now)
    new = _frame(tmp_path, "2026/11/24/new.jpg", 60, now)
    # Fora do layout bruto AAAA/MM/DD: não é da conta desta regra.
    labeled = _frame(tmp_path, "labeled/2026/10/05/l.jpg", 10 * 86400, now)
    occ = _frame(tmp_path, "ocorrencias/2026/10/05/o.jpg", 10 * 86400, now)

    moved = worker_main._age_out_unregistered_frames(tmp_path, 3600, now)

    assert moved == 1
    assert not old.exists()
    assert (tmp_path / "sem_ocorrencia/2026/10/05/old.jpg").exists()
    assert new.exists() and labeled.exists() and occ.exists()


def test_caps_moves_per_call(tmp_path):
    now = time.time()
    for i in range(5):
        _frame(tmp_path, f"2026/10/05/f{i}.jpg", 7200, now)
    assert worker_main._age_out_unregistered_frames(tmp_path, 3600, now, max_moves=2) == 2
    assert len(list((tmp_path / "2026/10/05").glob("*.jpg"))) == 3


def test_scan_ages_out_frames_of_inactive_camera(tmp_path, monkeypatch):
    """End to end through scan_and_process: inactive camera, old frame moved,
    no model called (resolve_camera returns None before any AI path)."""
    now = time.time()
    dev = tmp_path / "esp32_002"
    old = _frame(dev, "2026/10/05/old.jpg", 7200, now)

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(config, "INACTIVE_DEVICE_MAX_FRAME_AGE_SECONDS", 3600, raising=False)
    monkeypatch.setattr(worker_main, "resolve_camera", lambda _d: None)

    assert worker_main.scan_and_process() == 0
    assert not old.exists()
    assert (dev / "sem_ocorrencia/2026/10/05/old.jpg").exists()
