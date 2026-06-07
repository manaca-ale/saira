"""Tests for the stopped-vehicle centroid tracker (detector_car_stopped).

Pure logic — no DB, no model files, no I/O. Just confirms Gabriel's
algorithm is preserved verbatim and that the cross-window state
serializes cleanly.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from worker.detector_car_stopped import (
    CarConfig,
    CarEvent,
    classify_comparison,
    max_level,
    process_window,
)


def _ts(seconds_offset: float) -> datetime:
    """Reproducible UTC timestamp at base + N seconds."""
    base = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=seconds_offset)


def _det(cx: float, cy: float, half: float = 20.0, conf: float = 0.9) -> dict:
    """Synthetic YOLO detection centred on (cx, cy)."""
    return {
        "class_name": "car",
        "confidence": conf,
        "bbox": [cx - half, cy - half, cx + half, cy + half],
    }


CONFIG = CarConfig(
    stationary_pixels=50.0,
    low_frames=3,
    med_frames=6,
    high_frames=12,
    track_ttl_seconds=300,
    max_buffer_frames=12,
)


# --------------------------------------------------------------------------- #
# 1. Carro estatico em 3 frames -> LOW resolvido quando some no 4o frame.    #
# --------------------------------------------------------------------------- #
def test_low_event_when_stationary_then_disappears():
    frames = [
        [_det(100, 100)],
        [_det(100, 100)],
        [_det(100, 100)],
        [],  # car disappears -> track dies, must resolve as LOW
    ]
    timestamps = [_ts(i * 5) for i in range(len(frames))]

    state, events = process_window(frames, timestamps, prior_state=None, config=CONFIG)

    assert len(events) == 1
    ev = events[0]
    assert ev.level == "LOW"
    assert ev.frames_stayed == 3
    assert ev.occurrence_id == 1
    assert state["active_tracks"] == {}
    assert state["occurrence_counter"] == 1


# --------------------------------------------------------------------------- #
# 2. Carro estatico em 12 frames -> HIGH disparado instantaneamente.          #
# --------------------------------------------------------------------------- #
def test_high_event_fires_instantly_at_12th_frame():
    frames = [[_det(200, 200)] for _ in range(12)]
    timestamps = [_ts(i * 5) for i in range(len(frames))]

    state, events = process_window(frames, timestamps, prior_state=None, config=CONFIG)

    assert len(events) == 1
    ev = events[0]
    assert ev.level == "HIGH"
    assert ev.frames_stayed == 12
    assert ev.last_bbox == [180.0, 180.0, 220.0, 220.0]
    # Track survives in state but is marked reported so it won't double-fire.
    assert len(state["active_tracks"]) == 1
    surviving = next(iter(state["active_tracks"].values()))
    assert surviving["reported"] is True


def test_high_track_does_not_double_fire_in_followup_frames():
    """Once HIGH fires, additional frames of the same car must NOT emit again."""
    frames = [[_det(200, 200)] for _ in range(15)]  # 12 to fire, 3 more
    timestamps = [_ts(i * 5) for i in range(len(frames))]

    _, events = process_window(frames, timestamps, prior_state=None, config=CONFIG)

    assert len(events) == 1
    assert events[0].level == "HIGH"


# --------------------------------------------------------------------------- #
# 3. Carro que se move >50px -> 2 tracks separados (nenhum atinge LOW se < 3).#
# --------------------------------------------------------------------------- #
def test_moving_vehicle_breaks_track_when_exceeds_threshold():
    # Same car appears in 2 distinct positions, jumps 100px between frames.
    # Each position only seen for 1 frame, so neither track reaches LOW.
    frames = [
        [_det(100, 100)],
        [_det(300, 100)],  # jumps 200px -> new track
        [],
    ]
    timestamps = [_ts(i * 5) for i in range(len(frames))]

    _, events = process_window(frames, timestamps, prior_state=None, config=CONFIG)
    assert events == []  # both tracks died before reaching LOW threshold


def test_subpixel_movement_keeps_same_track():
    # 49px shift each frame -> still within threshold, same track persists.
    frames = [
        [_det(100, 100)],
        [_det(140, 100)],  # +40px
        [_det(180, 100)],  # +40px
        [],
    ]
    timestamps = [_ts(i * 5) for i in range(len(frames))]

    _, events = process_window(frames, timestamps, prior_state=None, config=CONFIG)
    assert len(events) == 1
    assert events[0].level == "LOW"
    assert events[0].frames_stayed == 3


# --------------------------------------------------------------------------- #
# 4. Round-trip do estado via JSON.                                           #
# --------------------------------------------------------------------------- #
def test_state_survives_json_round_trip_across_windows():
    # Window 1: 5 frames of stationary car -> reaches MED threshold (6 needs
    # one more), so track is alive but unreported.
    frames_w1 = [[_det(50, 50)] for _ in range(5)]
    timestamps_w1 = [_ts(i * 5) for i in range(len(frames_w1))]
    state_w1, events_w1 = process_window(frames_w1, timestamps_w1, None, CONFIG)
    assert events_w1 == []  # 5 frames alive, not died yet, not reported
    assert len(state_w1["active_tracks"]) == 1

    # Persist state to JSON and reload (simulates STATE_DIR/{device}.json).
    serialized = json.dumps(state_w1)
    rehydrated = json.loads(serialized)

    # Window 2: car keeps being seen for 7 more frames (total 12 -> HIGH).
    frames_w2 = [[_det(50, 50)] for _ in range(7)]
    timestamps_w2 = [_ts(25 + i * 5) for i in range(len(frames_w2))]
    state_w2, events_w2 = process_window(frames_w2, timestamps_w2, rehydrated, CONFIG)

    assert len(events_w2) == 1
    assert events_w2[0].level == "HIGH"
    assert events_w2[0].frames_stayed == 12  # 5 + 7 across windows
    # occurrence_counter must continue from where it left off.
    assert events_w2[0].occurrence_id == 1
    assert state_w2["occurrence_counter"] == 1


# --------------------------------------------------------------------------- #
# 5. TTL descarta tracks velhos no inicio do proximo window.                  #
# --------------------------------------------------------------------------- #
def test_ttl_drops_stale_tracks():
    # Build a state with a track last seen 10 minutes ago.
    stale_ts = _ts(0).isoformat()
    prior = {
        "active_tracks": {
            "stale": {
                "centroid": [100, 100],
                "frames": 5,
                "first_seen_ts": stale_ts,
                "last_seen_ts": stale_ts,
                "bboxes": [[80, 80, 120, 120]],
                "confidences": [0.9],
                "reported": False,
            }
        },
        "occurrence_counter": 0,
    }

    # New window 10 min later, no detections at all.
    frames = [[]]
    timestamps = [_ts(600)]  # 10 minutes later -> beyond 300s TTL

    state, events = process_window(frames, timestamps, prior, CONFIG)

    # Stale track was TTL'd out BEFORE resolution -> no event emitted,
    # state is now empty.
    assert events == []
    assert state["active_tracks"] == {}


def test_ttl_keeps_recent_tracks():
    # Track last seen 60s ago, TTL is 300s -> survives.
    recent_ts = _ts(0).isoformat()
    prior = {
        "active_tracks": {
            "alive": {
                "centroid": [100, 100],
                "frames": 2,
                "first_seen_ts": recent_ts,
                "last_seen_ts": recent_ts,
                "bboxes": [[80, 80, 120, 120]],
                "confidences": [0.9],
                "reported": False,
            }
        },
        "occurrence_counter": 7,
    }

    frames = [[_det(100, 100)]]
    timestamps = [_ts(60)]  # only 60s later

    state, _events = process_window(frames, timestamps, prior, CONFIG)
    assert len(state["active_tracks"]) == 1
    surviving = next(iter(state["active_tracks"].values()))
    assert surviving["frames"] == 3  # 2 previous + 1 new


# --------------------------------------------------------------------------- #
# 6. classify_comparison matrix (helper used by main.py)                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "gemini,car_level,expected",
    [
        (True,  "HIGH", "both_positive"),
        (True,  "MED",  "both_positive"),
        (True,  "LOW",  "gemini_only"),   # LOW not in positive_levels
        (True,  None,   "gemini_only"),
        (False, "HIGH", "car_only"),
        (False, "MED",  "car_only"),
        (False, "LOW",  "both_negative"),
        (False, None,   "both_negative"),
    ],
)
def test_classify_comparison(gemini, car_level, expected):
    assert classify_comparison(gemini, car_level) == expected


def test_max_level_picks_highest():
    base_ts = _ts(0).isoformat()
    events = [
        CarEvent("LOW", 3, [0,0,0,0], 0.9, 1, "a", base_ts, base_ts),
        CarEvent("HIGH", 12, [0,0,0,0], 0.9, 2, "b", base_ts, base_ts),
        CarEvent("MED", 6, [0,0,0,0], 0.9, 3, "c", base_ts, base_ts),
    ]
    assert max_level(events) == "HIGH"
    assert max_level([]) is None


# --------------------------------------------------------------------------- #
# 7. Buffer cap prevents state bloat for long-parked vehicles                 #
# --------------------------------------------------------------------------- #
def test_buffer_is_capped_to_max_buffer_frames():
    # 20 frames of stationary car -> buffer must cap at max_buffer_frames=12.
    frames = [[_det(100, 100)] for _ in range(20)]
    timestamps = [_ts(i * 5) for i in range(len(frames))]

    state, _events = process_window(frames, timestamps, None, CONFIG)
    surviving = next(iter(state["active_tracks"].values()))
    assert len(surviving["bboxes"]) == CONFIG.max_buffer_frames
    assert len(surviving["confidences"]) == CONFIG.max_buffer_frames
    assert surviving["frames"] == 20  # counter is NOT truncated
