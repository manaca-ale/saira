#!/usr/bin/env python3
"""Camp 36 — offline window-strategy latency simulator.

Faithfully replays prod's POLL-driven cascade over full event timelines, WITHOUT
mutating any prod state. Reimplements the cascade decision (main._process_with_gemini_cascade_window)
using the SAME pure functions prod calls (analyze_new_litter_with_gemini / analyze_with_gemini),
so per-camera prompt routing, models, thresholds and thinking budget are identical.

Skipped vs prod (do NOT affect the disposal decision for the fidelity gate):
  - BGSUB pre-filter: only suppresses no-change windows (handled in Phase 2 for negatives).
  - DINOv2: shadow mode in prod -> never overrides disposal.
  - CAR_SHADOW: shadow -> no effect.
  - state persistence / audit writes: replaced by in-memory carry state.
  - detail pile-crops (esp32_002): NOT YET implemented -> Mangabeira detail runs without
    crops. Fine for the fidelity gate (Arruda + Imbiribeira). Must be added before the
    Mangabeira Phase-2 run (asserts otherwise).

Key fidelity insight: window boundaries are POLL-driven. A poll processes every currently
available unprocessed frame as windows (trailing window emitted when >= MIN_FRAMES), so we
model the poll loop explicitly rather than decomposing latency.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2

CAMPAIGN = Path(__file__).resolve().parent
REPO = CAMPAIGN.parents[2]
WORKER_SRC = REPO / "services" / "yolo-worker-vm" / "src"

# --- prod-matching config (must be set BEFORE importing worker.config) ----------
_PROD_ENV = {
    "AI_MODE": "gemini",
    "GEMINI_CASCADE_ENABLED": "true",
    "GEMINI_CASCADE_WINDOW_SECONDS": "240",
    "GEMINI_CASCADE_MIN_FRAMES": "12",
    "GEMINI_CASCADE_MAX_FRAMES": "48",
    "GEMINI_AGENT1_MODEL": "gemini-2.5-flash-lite",
    "GEMINI_AGENT1_THINKING_BUDGET": "1024",
    "GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE": "85",
    "GEMINI_MODEL": "gemini-2.5-flash",
    "GEMINI_TIMEOUT_SECONDS": "60",          # bench-only: Vertex slower on big windows (no effect on verdict)
    "GEMINI_AGENT1_TIMEOUT_SECONDS": "60",
    "GEMINI_TEMPERATURE": "0.0",
    "GEMINI_MAX_OUTPUT_TOKENS": "8192",
    "GEMINI_INPUT_TOKEN_PRICE_PER_1M": "0.30",
    "GEMINI_OUTPUT_TOKEN_PRICE_PER_1M": "2.50",
    "GEMINI_PROMPT_VERSION": "current",
    "GEMINI_DETAIL_PILECROP_ENABLED": "false",  # sim does crops manually if needed
    "GEMINI_GATE_PILECROP_ENABLED": "false",    # OFF in prod
    "BGSUB_PREFILTER_ENABLED": "false",         # handled separately (negatives)
    "DINOV2_FILTER_MODE": "off",                # shadow in prod -> no disposal override
    "CAR_SHADOW_ENABLED": "false",
}


def _load_bench_key() -> None:
    env_bench = REPO / "services" / ".env.benchmark"
    if not env_bench.exists():
        return
    for line in env_bench.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GEMINI_TEST_API_KEY="):
            os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip()
            return


# BGSUB pre-filter — faithful ONLY with recent frames matching the current adaptive
# model (drift makes old baselines flag the whole scene; verified 2026-06-05).
USE_BGSUB = os.environ.get("SIM_USE_BGSUB", "0") == "1"
_BGSUB_ENV = {
    "BGSUB_PREFILTER_ENABLED": "true",
    "BGSUB_MIN_PERSISTENCE_FRAMES": "0.4",
    "BGSUB_AREA_MIN": "400",
    "BGSUB_MORPHO_MODE": "open_close",
    "BGSUB_PERSISTENCE_THRESHOLD": "1000",
    "BGSUB_MODELS_DIR": str(CAMPAIGN / "bgsub_models"),
}


def setup_env() -> None:
    for k, v in _PROD_ENV.items():
        os.environ[k] = v
    if USE_BGSUB:
        for k, v in _BGSUB_ENV.items():
            os.environ[k] = v
    if not os.environ.get("GEMINI_API_KEY"):
        _load_bench_key()
    import sys
    if str(WORKER_SRC) not in sys.path:
        sys.path.insert(0, str(WORKER_SRC))


setup_env()
import worker.config as wconfig  # noqa: E402
import worker.detector_gemini as _dg  # noqa: E402
from worker.detector_gemini import (  # noqa: E402
    analyze_new_litter_with_gemini,
    analyze_with_gemini,
)
if USE_BGSUB:
    from worker import bgsub_filter as _bgsub  # noqa: E402
else:
    _bgsub = None

# Use Vertex AI for the bench (avoids AI Studio 503s on flash; same pricing).
# Worker hardcodes genai.Client(api_key=...), so we pre-populate the cached client.
VERTEX_KEY = r"C:/secrets/saira-bench-vertex.json"
VERTEX_PROJECT = "gen-lang-client-0841492152"


def _init_vertex_client() -> None:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = VERTEX_KEY
    from google import genai
    _dg._client = genai.Client(vertexai=True, project=VERTEX_PROJECT, location="global")


if os.environ.get("SIM_USE_VERTEX", "1") == "1" and Path(VERTEX_KEY).exists():
    _init_vertex_client()

CAMERAS = json.loads((CAMPAIGN / "cameras.json").read_text(encoding="utf-8"))
EFFECTIVE_THRESHOLD = 85  # max(GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE, 80) == 85
GEMINI_LATENCY_S = 30.0   # constant cascade gate+detail latency estimate (cancels in A/B)


# --- verbatim copies from worker.main (pure, deterministic) ---------------------
def parse_timestamp(name: str) -> datetime:
    stem = name.replace(".jpg", "")
    return datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S")


def collect_time_windows(images: list[Path], window_s: int, max_f: int,
                         min_f: int) -> list[list[Path]]:
    """Parametrized copy of worker.main._collect_time_windows."""
    if not images:
        return []
    ordered = sorted(images, key=lambda p: (parse_timestamp(p.name), p.name))
    windows: list[list[Path]] = []
    current: list[Path] = []
    window_start = parse_timestamp(ordered[0].name)
    for img in ordered:
        ts = parse_timestamp(img.name)
        exceeds_time = (ts - window_start).total_seconds() >= window_s
        exceeds_count = len(current) >= max_f
        if current and (exceeds_time or exceeds_count):
            if len(current) >= max(2, min_f):
                windows.append(current)
            current = [img]
            window_start = ts
            continue
        if not current:
            window_start = ts
        current.append(img)
    if len(current) >= max(2, min_f):
        windows.append(current)
    return windows


# --- memoized cascade evaluation ------------------------------------------------
import threading  # noqa: E402


class Memo:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict] = {}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        self._since_save = 0

    def get(self, key: str):
        with self._lock:
            v = self.data.get(key)
            if v is not None:
                self.hits += 1
            return v

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def store(self, key: str, value: dict) -> dict:
        """Memoize + periodic flush so expensive calls survive a crash (thread-safe)."""
        with self._lock:
            self.data[key] = value
            self._since_save += 1
            if self._since_save >= 20:
                self.save()
                self._since_save = 0
        return value


_GATE_MEMO = Memo(CAMPAIGN / "cache" / "gate_cache.json")
_DETAIL_MEMO = Memo(CAMPAIGN / "cache" / "detail_cache.json")


def _cam_ns(device_id: str):
    c = CAMERAS[device_id]
    return SimpleNamespace(**c)


def _cam_context(device_id: str, last_frame_name: str) -> dict:
    c = CAMERAS[device_id]
    ts = parse_timestamp(last_frame_name)
    return {
        "camera_name": c["name"], "device_id": device_id,
        "logradouro": c["logradouro"], "bairro": c["bairro"], "rpa": c["rpa"],
        "horario_local": ts.strftime("%H:%M"),
    }


def eval_gate(device_id: str, first: Path, mids: list[Path] | None, last: Path,
              prior_had_litter: bool, prior_waste: str | None) -> dict:
    mid_names = [m.name for m in mids] if mids else []
    key = f"{device_id}|{first.name}|{','.join(mid_names)}|{last.name}|{int(prior_had_litter)}|{prior_waste or ''}"
    cached = _GATE_MEMO.get(key)
    if cached is not None:
        return cached
    _GATE_MEMO.misses += 1
    prior_ctx = None
    if prior_had_litter:
        wl = f" (type: {prior_waste})" if prior_waste else ""
        prior_ctx = (f"- The previous 2-minute window ALREADY had waste at this location{wl}. "
                     "Confirm NEW_SOLID_WASTE only if a NEW object appeared or the volume visibly increased.")
    res = analyze_new_litter_with_gemini(
        first_frame=first, last_frame=last,
        camera_context=_cam_context(device_id, last.name),
        prior_window_context=prior_ctx, use_mosaic=False,
        mid_frames=mids, prompt_version=wconfig.GEMINI_PROMPT_VERSION,
    )
    r = res.report
    out = {
        "new_litter_detected": bool(r.new_litter_detected),
        "confidence_0_100": int(r.confidence_0_100),
        "last_frame_has_litter": bool(getattr(r, "last_frame_has_litter", False)),
        "waste_type": getattr(r, "waste_type", None),
        "cost_usd": float(res.usage.estimated_cost_usd or 0.0),
        "latency_ms": int(res.latency_ms or 0),
    }
    return _GATE_MEMO.store(key, out)


def _pile_bbox(polygon):
    """Verbatim copy of worker.main._pile_bbox."""
    try:
        pts = [pt for poly in polygon for pt in poly]
        xs = [int(p[0]) for p in pts]
        ys = [int(p[1]) for p in pts]
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)
    except Exception:
        return None


def _make_pile_crops(frame_paths, bbox, upscale, out_dir):
    """Verbatim copy of worker.main._make_pile_crops."""
    x0, y0, x1, y1 = bbox
    crops = []
    for fp in frame_paths:
        img = cv2.imread(str(fp))
        if img is None:
            continue
        h, w = img.shape[:2]
        cx0, cy0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
        cx1, cy1 = max(cx0 + 1, min(x1, w)), max(cy0 + 1, min(y1, h))
        crop = img[cy0:cy1, cx0:cx1]
        if crop.size == 0:
            continue
        if upscale and upscale != 1:
            crop = cv2.resize(crop, (crop.shape[1] * upscale, crop.shape[0] * upscale),
                              interpolation=cv2.INTER_LANCZOS4)
        dst = out_dir / fp.name
        cv2.imwrite(str(dst), crop)
        crops.append(dst)
    return crops


def _build_pile_crops(device_id: str, window: list[Path], tmp_dir: Path) -> list[Path]:
    """Replicates _process_with_gemini detail-side pile-crop augmentation (esp32_002)."""
    poly = CAMERAS[device_id].get("pile_zone_polygon")
    bbox = _pile_bbox(poly) if poly else None
    if not bbox or len(window) < 2:
        return []
    n_target = min(max(1, wconfig.GEMINI_DETAIL_PILECROP_N_FRAMES), len(window))
    if n_target > 1:
        idxs = [int(round(i * (len(window) - 1) / (n_target - 1))) for i in range(n_target)]
    else:
        idxs = [0]
    return _make_pile_crops([window[k] for k in idxs], bbox,
                            wconfig.GEMINI_DETAIL_PILECROP_UPSCALE, tmp_dir)


def eval_detail(device_id: str, window: list[Path], prior_had_litter: bool,
                prior_waste: str | None) -> dict:
    names = ",".join(p.name for p in window)
    key = f"{device_id}|{names}|{int(prior_had_litter)}|{prior_waste or ''}"
    cached = _DETAIL_MEMO.get(key)
    if cached is not None:
        return cached
    _DETAIL_MEMO.misses += 1
    prior_ctx = None
    if prior_had_litter:
        wl = f" (type: {prior_waste})" if prior_waste else ""
        prior_ctx = (f"- The previous 2-minute window ALREADY had waste at this location{wl}. "
                     "Confirm NEW_SOLID_WASTE only if a NEW object appeared or the volume visibly increased.")
    # Detail-side pile-crops for esp32_002 (prod GEMINI_DETAIL_PILECROP_ENABLED=true).
    pile_crops = None
    prompt_v = wconfig.GEMINI_PROMPT_VERSION
    tmp_dir = None
    if device_id in wconfig.DETAIL_PILECROP_DEVICES and len(window) >= 2:
        tmp_dir = Path(tempfile.mkdtemp(prefix="sim_pilecrop_"))
        crops = _build_pile_crops(device_id, window, tmp_dir)
        if crops:
            pile_crops = crops
            prompt_v = "mangabeira_with_pilecrops"
    try:
        res = analyze_with_gemini(
            image_paths=window, camera_context=_cam_context(device_id, window[-1].name),
            mosaic_mode=wconfig.GEMINI_MOSAIC_AGENT2, prior_window_context=prior_ctx,
            prompt_version=prompt_v, pile_crops=pile_crops,
        )
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    r = res.report
    out = {
        "disposal": bool(r.infraction_confirmed),
        "confidence_0_100": int(r.confidence_0_100),
        "cost_usd": float(res.usage.estimated_cost_usd or 0.0),
        "latency_ms": int(res.latency_ms or 0),
    }
    return _DETAIL_MEMO.store(key, out)


def cascade_decision(window: list[Path], device_id: str, carry: dict,
                     use_prev_last: bool = True) -> tuple[dict, dict]:
    """Replicates main._process_with_gemini_cascade_window (minus skipped features).

    use_prev_last=True (fixed/prod): gate's first_frame = previous window's last frame
      (Correction 2 — avoids post-deposit blindness across non-overlapping windows).
    use_prev_last=False (sliding): first_frame = window[0], i.e. compare the two ends of
      the sliding window itself (prev poll's window overlaps, so its last frame is only a
      stride away and would blind the gate).
    """
    last = window[-1]
    # BGSUB pre-filter (prod runs it before the gate) — suppress empty windows.
    if _bgsub is not None:
        cam_ns = _cam_ns(device_id)
        bg = _bgsub.evaluate(window, device_id, getattr(cam_ns, "pile_zone_polygon", None), cam_ns)
        if bg.should_suppress:
            return ({"disposal": False, "trigger": False, "cost_usd": 0.0,
                     "n_gate": 0, "n_detail": 0, "first_frame": window[0].name,
                     "last_frame": last.name, "gate_conf": 0, "bgsub_suppressed": True},
                    carry)  # carry unchanged on suppress (mirrors prod)
    prev_last = carry.get("prev_last_frame")
    first = prev_last if (use_prev_last and prev_last and prev_last.exists()) else window[0]
    prior_had = bool(carry.get("prior_had_litter", False))
    prior_waste = carry.get("prior_waste")

    n = len(window)
    mids: list[Path] | None = None
    if n >= 5:
        mids = [window[n // 4], window[n // 2], window[3 * n // 4]]
    elif n >= 4:
        mids = [window[n // 2]]

    gate = eval_gate(device_id, first, mids, last, prior_had, prior_waste)
    new_carry = {
        "prev_last_frame": last,
        "prior_had_litter": gate["last_frame_has_litter"],
        "prior_waste": gate["waste_type"],
    }
    trigger = gate["new_litter_detected"] and gate["confidence_0_100"] >= EFFECTIVE_THRESHOLD
    cost = gate["cost_usd"]
    n_gate, n_detail = 1, 0
    disposal = False
    if trigger:
        n_detail = 1
        det = eval_detail(device_id, window, prior_had, prior_waste)
        disposal = det["disposal"]
        cost += det["cost_usd"]
    return ({"disposal": disposal, "trigger": trigger, "cost_usd": cost,
             "n_gate": n_gate, "n_detail": n_detail,
             "first_frame": first.name, "last_frame": last.name,
             "gate_conf": gate["confidence_0_100"]}, new_carry)


def poll_replay(frames: list[Path], device_id: str, *, window_s: int, max_f: int,
                min_f: int, poll_interval: int, poll_phase: float,
                disposal_start_epoch: float, mode: str = "fixed") -> dict:
    """Discrete-event poll loop. Returns first-confirm info (latency, F*, cost).

    mode='fixed':   prod behavior — non-overlapping windows via collect_time_windows;
                    each poll processes every available unprocessed window.
    mode='sliding': overlapping window of the last `window_s` seconds re-evaluated every
                    `poll_interval` (= stride). Catches the disposal sooner without waiting
                    for a non-overlapping boundary.
    """
    ordered = sorted(frames, key=lambda p: (parse_timestamp(p.name), p.name))
    epochs = {p: parse_timestamp(p.name).timestamp() for p in ordered}
    t0, t_end = epochs[ordered[0]], epochs[ordered[-1]]
    processed: set[Path] = set()
    carry: dict = {}
    total_gate = total_detail = 0
    total_cost = 0.0

    def _hit(w, poll):
        return {
            "confirmed": True, "confirm_epoch": poll + GEMINI_LATENCY_S,
            "latency_s": poll + GEMINI_LATENCY_S - disposal_start_epoch,
            "data_ready_epoch": epochs[w[-1]],
            "data_ready_latency_s": epochs[w[-1]] - disposal_start_epoch,
            "f_star": w[-1].name, "window_first": w[0].name, "window_size": len(w),
            "poll_epoch": poll, "n_gate": total_gate, "n_detail": total_detail,
            "cost_usd": round(total_cost, 6),
        }

    poll = t0 + poll_phase
    while poll <= t_end + poll_interval:
        if mode == "fixed":
            available = [p for p in ordered if p not in processed and epochs[p] <= poll]
            for w in collect_time_windows(available, window_s, max_f, min_f):
                dec, carry = cascade_decision(w, device_id, carry, use_prev_last=True)
                total_gate += dec["n_gate"]; total_detail += dec["n_detail"]
                total_cost += dec["cost_usd"]
                if dec["disposal"]:
                    return _hit(w, poll)
                processed.update(w)
        else:  # sliding
            w = [p for p in ordered if (poll - window_s) < epochs[p] <= poll]
            if len(w) > max_f:
                w = w[-max_f:]
            if len(w) >= max(2, min_f):
                dec, carry = cascade_decision(w, device_id, carry, use_prev_last=False)
                total_gate += dec["n_gate"]; total_detail += dec["n_detail"]
                total_cost += dec["cost_usd"]
                if dec["disposal"]:
                    return _hit(w, poll)
        poll += poll_interval

    return {"confirmed": False, "latency_s": None, "f_star": None,
            "n_gate": total_gate, "n_detail": total_detail, "cost_usd": round(total_cost, 6)}


def fp_replay(frames: list[Path], device_id: str, *, window_s: int, max_f: int,
              min_f: int, poll_interval: int, poll_phase: float, mode: str = "fixed",
              coalesce_s: int = 600) -> dict:
    """Replay a NO-DISPOSAL sequence (baseline) and count false-positive confirmations.

    Counts every window the cascade confirms (disposal=True) = a false positive. Confirms
    within `coalesce_s` (prod EVENT_WINDOW_MIN=10min) merge to one operator-facing FP.
    Returns raw + coalesced FP counts and cost. NOTE: BGSUB pre-filter is NOT applied
    (prod has it ON for baselines) -> this is the cascade-alone FP (an upper bound); the
    relative ordering across strategies still holds.
    """
    ordered = sorted(frames, key=lambda p: (parse_timestamp(p.name), p.name))
    epochs = {p: parse_timestamp(p.name).timestamp() for p in ordered}
    t0, t_end = epochs[ordered[0]], epochs[ordered[-1]]
    processed: set[Path] = set()
    carry: dict = {}
    confirms: list[float] = []
    total_gate = total_detail = 0
    total_cost = 0.0

    def _eval(w, poll):
        nonlocal total_gate, total_detail, total_cost
        dec, c = cascade_decision(w, device_id, carry, use_prev_last=(mode == "fixed"))
        total_gate += dec["n_gate"]; total_detail += dec["n_detail"]; total_cost += dec["cost_usd"]
        if dec["disposal"]:
            confirms.append(epochs[w[-1]])
        return c

    poll = t0 + poll_phase
    while poll <= t_end + poll_interval:
        if mode == "fixed":
            available = [p for p in ordered if p not in processed and epochs[p] <= poll]
            for w in collect_time_windows(available, window_s, max_f, min_f):
                carry = _eval(w, poll)
                processed.update(w)
        else:
            w = [p for p in ordered if (poll - window_s) < epochs[p] <= poll]
            if len(w) > max_f:
                w = w[-max_f:]
            if len(w) >= max(2, min_f):
                carry = _eval(w, poll)
        poll += poll_interval

    confirms.sort()
    coalesced = 0
    last = None
    for c in confirms:
        if last is None or (c - last) > coalesce_s:
            coalesced += 1
            last = c
    hours = max(1e-9, (t_end - t0) / 3600.0)
    return {"raw_fp": len(confirms), "coalesced_fp": coalesced,
            "fp_per_hour": round(coalesced / hours, 2),
            "n_gate": total_gate, "n_detail": total_detail,
            "cost_usd": round(total_cost, 6), "hours": round(hours, 2)}


def save_caches() -> None:
    _GATE_MEMO.save()
    _DETAIL_MEMO.save()


def cache_stats() -> str:
    return (f"gate[hit={_GATE_MEMO.hits} miss={_GATE_MEMO.misses}] "
            f"detail[hit={_DETAIL_MEMO.hits} miss={_DETAIL_MEMO.misses}]")
