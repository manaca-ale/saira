"""Event-manifest discovery for event-driven devices (Pi relay).

Event-driven devices (config.EVENT_DRIVEN_DEVICES) tag their uploads with an
event_id; the esp32-server maintains one JSON manifest per event under
{UPLOAD_DIR}/{device_id}/events/{event_id}.json (shared volume). The worker
consumes CLOSED manifests (or stale ones — the device may die mid-event) and
processes the exact frame set of the event immediately, instead of waiting
for the fixed 120s time window. Frames not referenced by any manifest
(heartbeats / late spool retries) are garbage-collected without Gemini calls.

This module holds the pure manifest/frame logic; orchestration (cascade call,
detection persistence) stays in main.py.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import config

logger = logging.getLogger(__name__)

PROCESSED_SUFFIX = ".processed"


@dataclass
class EventManifest:
    path: Path
    event_id: str
    device_id: str
    state: str  # open | closed
    closed_reason: Optional[str]
    frames: list[str]  # rel paths under UPLOAD_DIR (as written by esp32-server)
    updated_at: Optional[datetime]

    @property
    def is_warmup(self) -> bool:
        return self.event_id.startswith("evt-warmup-")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _load_manifest(path: Path) -> Optional[EventManifest]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    event_id = str(data.get("event_id") or path.stem)
    return EventManifest(
        path=path,
        event_id=event_id,
        device_id=str(data.get("device_id") or ""),
        state=str(data.get("state") or "open"),
        closed_reason=data.get("closed_reason"),
        frames=[str(f) for f in (data.get("frames") or [])],
        updated_at=_parse_iso(data.get("updated_at")),
    )


def is_manifest_processed(path: Path) -> bool:
    return path.with_name(path.name + PROCESSED_SUFFIX).exists()


def mark_manifest_processed(path: Path) -> None:
    path.with_name(path.name + PROCESSED_SUFFIX).touch()


def discover_ready_manifests(device_dir: Path, now: datetime) -> list[EventManifest]:
    """Return unprocessed manifests that are closed — or stale-open.

    A manifest stuck in state=open whose updated_at is older than
    EVENT_STALE_SECONDS is treated as closed (device died mid-event, lost
    end-frame, WireGuard drop): the frames it references are still worth
    judging.
    """
    events_dir = device_dir / "events"
    if not events_dir.is_dir():
        return []
    stale_cutoff = now - timedelta(seconds=config.EVENT_STALE_SECONDS)
    ready: list[EventManifest] = []
    for path in sorted(events_dir.glob("*.json")):
        if is_manifest_processed(path):
            continue
        manifest = _load_manifest(path)
        if manifest is None:
            continue
        if manifest.state == "closed":
            ready.append(manifest)
        elif manifest.updated_at is not None and manifest.updated_at < stale_cutoff:
            manifest.closed_reason = "stale"
            ready.append(manifest)
    return ready


def pending_manifest_frames(device_dir: Path) -> set[str]:
    """Frame names referenced by ANY unprocessed manifest (open or closed).

    Used by the orphan GC so it never collects a frame that an event still
    owns (e.g. an open event in progress).
    """
    events_dir = device_dir / "events"
    names: set[str] = set()
    if not events_dir.is_dir():
        return names
    for path in events_dir.glob("*.json"):
        if is_manifest_processed(path):
            continue
        manifest = _load_manifest(path)
        if manifest is None:
            continue
        names.update(Path(f).name for f in manifest.frames)
    return names


def resolve_manifest_frames(manifest: EventManifest, upload_dir: Path) -> list[Path]:
    """Map manifest rel-paths to existing files, in chronological order."""
    out: list[Path] = []
    for rel in manifest.frames:
        p = upload_dir / rel
        if p.is_file():
            out.append(p)
    out.sort(key=lambda p: p.name)
    return out


def subsample_frames(paths: list[Path], max_frames: int) -> list[Path]:
    """Evenly subsample to max_frames keeping first and last frames.

    Warm-up/synthetic events can carry far more frames than the cascade
    needs (GEMINI_CASCADE_MAX_FRAMES); even sampling preserves the temporal
    span the gate prompt relies on (first vs last frame comparison).
    """
    if max_frames <= 0 or len(paths) <= max_frames:
        return paths
    if max_frames == 1:
        return [paths[-1]]
    step = (len(paths) - 1) / (max_frames - 1)
    idxs = sorted({round(i * step) for i in range(max_frames)})
    return [paths[i] for i in idxs]
