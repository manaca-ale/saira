"""Scan-cycle shaping helpers (G3 fairness + G4 freshness, incident 2026-07-23).

_split_stale_frames drops frames older than the age limit (marked seen, no
Gemini). _cap_newest_windows caps windows per camera per cycle, newest first,
so a backlogged camera cannot starve the others.
"""
from pathlib import Path

from worker.main import _cap_newest_windows, _split_stale_frames


# --- G4 freshness -----------------------------------------------------------

def test_split_disabled_keeps_everything():
    imgs = [Path("a.jpg"), Path("b.jpg")]
    fresh, stale = _split_stale_frames(imgs, max_age_s=0, now=1000.0)
    assert fresh == imgs
    assert stale == []


def test_split_partitions_by_age():
    mtimes = {
        Path("old1.jpg"): 100.0,
        Path("old2.jpg"): 200.0,
        Path("new1.jpg"): 950.0,
        Path("new2.jpg"): 990.0,
    }
    imgs = list(mtimes)
    fresh, stale = _split_stale_frames(
        imgs, max_age_s=100, now=1000.0, mtime_fn=lambda p: mtimes[p]
    )
    # cutoff = 900 -> < 900 is stale
    assert set(stale) == {Path("old1.jpg"), Path("old2.jpg")}
    assert set(fresh) == {Path("new1.jpg"), Path("new2.jpg")}


def test_split_drops_missing_files():
    def boom(_p):
        raise FileNotFoundError

    fresh, stale = _split_stale_frames(
        [Path("gone.jpg")], max_age_s=100, now=1000.0, mtime_fn=boom
    )
    assert fresh == []
    assert stale == []


# --- G3 fairness ------------------------------------------------------------

def test_cap_disabled_keeps_all():
    windows = [[1], [2], [3]]
    kept, deferred = _cap_newest_windows(windows, max_per_cycle=0)
    assert kept == windows
    assert deferred == 0


def test_cap_under_limit_is_noop():
    windows = [[1], [2], [3]]
    kept, deferred = _cap_newest_windows(windows, max_per_cycle=5)
    assert kept == windows
    assert deferred == 0


def test_cap_keeps_newest_windows():
    # windows are chronological ascending; newest = tail
    windows = [["w1"], ["w2"], ["w3"], ["w4"], ["w5"]]
    kept, deferred = _cap_newest_windows(windows, max_per_cycle=2)
    assert kept == [["w4"], ["w5"]]
    assert deferred == 3
