"""Stateless centroid tracker for stopped-vehicle detection.

Ported from https://github.com/GabrielCande/CarDetectionModule
(`src/detection_register.py`), with two changes for the SAIRA worker:

1. Module globals (`active_tracks`, `occurrence_counter`) are removed —
   the caller passes `prior_state` (a JSON-serializable dict loaded from
   `STATE_DIR/{device_id}.json` under the `car_tracker` key) and receives
   `new_state` back.
2. The Google Apps Script POST is removed — this is an internal audit
   only; persistence is the caller's responsibility.

The tracker logic itself is preserved verbatim: greedy centroid matching
with a fixed pixel distance threshold, frame counters per track, and
3 alert levels (LOW / MED / HIGH) based on the count of consecutive
frames a track has been alive.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


# ----------------------------- public types ---------------------------------

@dataclass(frozen=True)
class CarConfig:
    """Tunable thresholds for the tracker."""

    stationary_pixels: float = 50.0
    low_frames: int = 3
    med_frames: int = 6
    high_frames: int = 12
    track_ttl_seconds: int = 300
    # Cap the per-track bbox buffer kept in state so the JSON doesn't grow
    # unbounded for long-parked vehicles.
    max_buffer_frames: int = 12


@dataclass
class CarEvent:
    """One resolved stopped-vehicle event, returned to the caller."""

    level: str  # "LOW" | "MED" | "HIGH"
    frames_stayed: int
    last_bbox: list[float]  # [x1, y1, x2, y2]
    last_confidence: float
    occurrence_id: int
    track_id: str
    first_seen_ts: str  # ISO-8601
    last_seen_ts: str   # ISO-8601


# ----------------------------- helpers --------------------------------------

def _centroid(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _empty_state() -> dict:
    return {"active_tracks": {}, "occurrence_counter": 0}


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _now_or(ts: Optional[datetime]) -> datetime:
    return ts if ts is not None else datetime.now(timezone.utc)


# ------------------------- main pure function -------------------------------

def process_window(
    detections_per_frame: list[list[dict]],
    frame_timestamps: list[datetime],
    prior_state: Optional[dict],
    config: CarConfig,
) -> tuple[dict, list[CarEvent]]:
    """Apply Gabriel's centroid tracker across one window of frames.

    Args:
        detections_per_frame: per-frame list of YOLO detections, each
            detection a dict {"bbox": [x1,y1,x2,y2], "confidence": float, ...}.
            Must have the same length as `frame_timestamps`.
        frame_timestamps: timezone-aware datetime per frame.
        prior_state: result of a previous call (active tracks across windows),
            or None for a cold start. May be a dict loaded from disk JSON.
        config: tracker thresholds.

    Returns:
        (new_state, resolved_events): the updated state to persist, plus the
        events resolved during this window (LOW/MED when a track died,
        HIGH instantly upon reaching the threshold).
    """
    if len(detections_per_frame) != len(frame_timestamps):
        raise ValueError("detections_per_frame and frame_timestamps must align")

    state = _coerce_state(prior_state)
    active = dict(state["active_tracks"])
    occurrence_counter = int(state["occurrence_counter"])
    resolved: list[CarEvent] = []

    # Drop stale tracks before we start (TTL based on the window's first ts).
    if frame_timestamps:
        active = _apply_ttl(active, frame_timestamps[0], config.track_ttl_seconds)

    for frame_idx, (dets, ts) in enumerate(zip(detections_per_frame, frame_timestamps)):
        ts_iso = ts.isoformat()
        updated: dict[str, dict] = {}
        matched_track_ids: set[str] = set()

        # 1. Match this frame's detections to active tracks (greedy).
        for det in dets:
            bbox = det["bbox"]
            confidence = float(det.get("confidence", 0.0))
            cx, cy = _centroid(bbox)

            best_track_id: Optional[str] = None
            best_dist = math.inf
            for track_id, track in active.items():
                if track_id in matched_track_ids:
                    continue
                pcx, pcy = track["centroid"]
                dist = math.hypot(cx - pcx, cy - pcy)
                if dist < best_dist and dist <= config.stationary_pixels:
                    best_dist = dist
                    best_track_id = track_id

            if best_track_id is not None:
                track = dict(active[best_track_id])
                track["centroid"] = [cx, cy]
                track["frames"] = int(track.get("frames", 0)) + 1
                track["last_seen_ts"] = ts_iso
                buffer = list(track.get("bboxes", []))
                buf_conf = list(track.get("confidences", []))
                buffer.append(bbox)
                buf_conf.append(confidence)
                # Cap buffer to prevent state bloat for long-parked vehicles.
                if len(buffer) > config.max_buffer_frames:
                    buffer = buffer[-config.max_buffer_frames:]
                    buf_conf = buf_conf[-config.max_buffer_frames:]
                track["bboxes"] = buffer
                track["confidences"] = buf_conf

                # HIGH escalates instantly upon reaching the threshold (once).
                if not track.get("reported", False) and track["frames"] >= config.high_frames:
                    occurrence_counter += 1
                    resolved.append(
                        CarEvent(
                            level="HIGH",
                            frames_stayed=track["frames"],
                            last_bbox=bbox,
                            last_confidence=confidence,
                            occurrence_id=occurrence_counter,
                            track_id=best_track_id,
                            first_seen_ts=track.get("first_seen_ts", ts_iso),
                            last_seen_ts=ts_iso,
                        )
                    )
                    track["reported"] = True

                updated[best_track_id] = track
                matched_track_ids.add(best_track_id)
            else:
                new_id = uuid.uuid4().hex[:8]
                updated[new_id] = {
                    "centroid": [cx, cy],
                    "frames": 1,
                    "first_seen_ts": ts_iso,
                    "last_seen_ts": ts_iso,
                    "bboxes": [bbox],
                    "confidences": [confidence],
                    "reported": False,
                }

        # 2. Tracks not matched in this frame are "dead". Resolve LOW/MED if
        #    they aren't already reported (HIGH).
        for track_id, track in active.items():
            if track_id in matched_track_ids:
                continue
            if track.get("reported", False):
                continue  # already escalated to HIGH
            frames_stayed = int(track.get("frames", 0))
            if frames_stayed < config.low_frames:
                continue
            level = "MED" if frames_stayed >= config.med_frames else "LOW"
            occurrence_counter += 1
            last_bbox = (track.get("bboxes") or [[0, 0, 0, 0]])[-1]
            last_conf = (track.get("confidences") or [0.0])[-1]
            resolved.append(
                CarEvent(
                    level=level,
                    frames_stayed=frames_stayed,
                    last_bbox=list(last_bbox),
                    last_confidence=float(last_conf),
                    occurrence_id=occurrence_counter,
                    track_id=track_id,
                    first_seen_ts=str(track.get("first_seen_ts", ts_iso)),
                    last_seen_ts=str(track.get("last_seen_ts", ts_iso)),
                )
            )

        # 3. Replace active with what survived this frame.
        active = updated

    new_state = {
        "active_tracks": active,
        "occurrence_counter": occurrence_counter,
    }
    return new_state, resolved


# ------------------------- comparison classifier ----------------------------

def classify_comparison(
    gemini_disposal: bool,
    car_max_level: Optional[str],
    positive_levels: tuple[str, ...] = ("MED", "HIGH"),
) -> str:
    """Return one of {both_positive, gemini_only, car_only, both_negative}.

    `car_max_level` is the highest level resolved in this window, or None.
    A car-stopped event counts as positive only if its level is in
    `positive_levels` (default: MED + HIGH per product decision).
    """
    car_positive = car_max_level is not None and car_max_level in positive_levels
    if gemini_disposal and car_positive:
        return "both_positive"
    if gemini_disposal and not car_positive:
        return "gemini_only"
    if not gemini_disposal and car_positive:
        return "car_only"
    return "both_negative"


def max_level(events: list[CarEvent]) -> Optional[str]:
    """Return the highest-severity level present in a list of events."""
    if not events:
        return None
    rank = {"LOW": 1, "MED": 2, "HIGH": 3}
    return max(events, key=lambda e: rank.get(e.level, 0)).level


# ------------------------- state coercion helpers ---------------------------

def _coerce_state(prior_state: Optional[dict]) -> dict:
    """Accept None or a partial dict and return a fully-shaped state dict."""
    if not prior_state:
        return _empty_state()
    state = {
        "active_tracks": dict(prior_state.get("active_tracks") or {}),
        "occurrence_counter": int(prior_state.get("occurrence_counter") or 0),
    }
    return state


def _apply_ttl(
    active: dict[str, dict],
    reference_ts: datetime,
    ttl_seconds: int,
) -> dict[str, dict]:
    """Drop tracks whose last_seen_ts is older than reference_ts - ttl."""
    if ttl_seconds <= 0:
        return active
    cutoff = reference_ts - timedelta(seconds=ttl_seconds)
    out: dict[str, dict] = {}
    for track_id, track in active.items():
        last_seen = track.get("last_seen_ts")
        if not last_seen:
            continue
        try:
            last_ts = _parse_iso(last_seen)
        except (ValueError, TypeError):
            continue
        if last_ts >= cutoff:
            out[track_id] = track
    return out
