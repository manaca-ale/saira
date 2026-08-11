#!/usr/bin/env python3
"""Campaign 19 — END-TO-END: dual gate (full b3 + pile-crop b3, lazy-OR union) -> detail.

For each esp32_002 window (TP / FP / baseline):
  1. full-frame gate (V3+B3).
  2. if it does NOT trigger -> pile-crop gate (V3+B3). union = full OR crop.
  3. if union triggers -> run the DETAIL agent (Agent-2, V1 'current') on the FULL window.

Measures the REAL pipeline: how many windows the detail actually sees, and how many
FP/baseline the detail confirms (= operator-facing false alarms) vs filters out.

Reuses prompt/gate machinery from bench_gate_esp32_b4.py and crop box from
bench_gate_pilecrop.py. Detail uses analyze_with_gemini (prompt_version='current').
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import uuid
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from PIL import Image

CAMPAIGN_DIR = Path(__file__).parent
DATASET = Path(r"c:\saira\data\datasets\official")
PILE_BOX = (480, 60, 920, 340)
UPSCALE = 2
WIN, PER_PERIOD = 12, 30
DETAIL_P_IN, DETAIL_P_OUT = 0.15 / 1e6, 0.60 / 1e6   # flash pricing


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


B4 = _load("bench_b4", CAMPAIGN_DIR / "bench_gate_esp32_b4.py")
from worker.detector_gemini import analyze_with_gemini  # noqa: E402  (worker on path via B4)

B3_PROMPT = B4.ARM_SPECS["D_v3_esp32_recall_b3"]["prompt_text"]
CAM = B4.CAMERA_CONTEXT["cam_mangabeira"]


@dataclass
class W:
    wid: str
    category: str           # tp | fp | baseline
    gate_first: Path
    gate_last: Path
    gate_mids: list
    full_frames: list       # full window for the detail
    is_tp: bool


def _mids(frames):
    return B4._sample_mid_frames(frames)


def build_windows():
    out = []
    # events from manifest
    import csv
    with (DATASET / "manifest.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("camera") != "cam_mangabeira" or row.get("category") not in {"tp", "fp"}:
                continue
            frames = sorted((DATASET / row["local_path"] / "frames").glob("*.jpg"))
            if len(frames) < 2:
                continue
            out.append(W(row["event_id"], row["category"], frames[0], frames[-1], _mids(frames),
                         frames, row["category"] == "tp"))
    # baseline chunks
    for period in ("day", "night"):
        frames = sorted((DATASET / "cam_mangabeira" / "baseline" / period).glob("*.jpg"))
        starts = list(range(0, len(frames) - WIN + 1, WIN))
        if PER_PERIOD < len(starts):
            step = len(starts) / PER_PERIOD
            starts = [starts[int(i * step)] for i in range(PER_PERIOD)]
        for s in starts:
            chunk = frames[s:s + WIN]
            out.append(W(f"baseline_{period}_{s // WIN:03d}", "baseline", chunk[0], chunk[-1],
                         _mids(chunk), chunk, False))
    return out


def _crop(p: Path, tmp: Path) -> Path:
    img = Image.open(p).convert("RGB").crop(PILE_BOX)
    if UPSCALE != 1:
        img = img.resize((img.width * UPSCALE, img.height * UPSCALE), Image.LANCZOS)
    d = tmp / p.name
    img.save(d, quality=92)
    return d


def gate_window(first, last, mids):
    return B4.Window(window_id="x", source="e", camera="cam_mangabeira", category="x",
                     first_frame=first, last_frame=last, mid_frames=mids, is_positive=False)


def run_detail(frames, wid):
    t0 = time.monotonic()
    try:
        res = analyze_with_gemini(image_paths=frames, camera_context=CAM,
                                  request_id=f"e2e-det-{wid[:8]}-{uuid.uuid4().hex[:4]}",
                                  prompt_version="current")
    except Exception as exc:  # noqa: BLE001 — fail-safe so one 503 doesn't abort the run
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "wall_ms": int((time.monotonic() - t0) * 1000), "n_frames": len(frames),
                "cost_usd": 0.0}
    rep, u = res.report, res.usage
    billable_out = max(0, u.total_tokens - u.input_tokens)
    cost = u.input_tokens * DETAIL_P_IN + billable_out * DETAIL_P_OUT
    return {
        "ok": True, "infraction_confirmed": bool(rep.infraction_confirmed),
        "confidence_0_100": int(rep.confidence_0_100), "waste_type": rep.waste_type,
        "input_tokens": u.input_tokens, "billable_output_tokens": billable_out,
        "latency_ms": res.latency_ms, "cost_usd": round(cost, 8),
        "wall_ms": int((time.monotonic() - t0) * 1000), "n_frames": len(frames),
    }


def main():
    windows = build_windows()
    print(f"windows: total={len(windows)} tp={sum(w.category=='tp' for w in windows)} "
          f"fp={sum(w.category=='fp' for w in windows)} baseline={sum(w.category=='baseline' for w in windows)}", flush=True)
    results = []
    for i, w in enumerate(windows, 1):
        if i == 1 or i % 20 == 0 or i == len(windows):
            print(f"  {i}/{len(windows)} {w.wid[:10]} ({w.category})", flush=True)
        # full gate (b3)
        full = B4.run_gate_call(gate_window(w.gate_first, w.gate_last, w.gate_mids),
                                "b3_full", B3_PROMPT, "v3")
        full_trig = bool(full.get("new_litter_detected")) and int(full.get("confidence_0_100") or 0) >= B4.worker_config.GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE
        crop = None
        crop_trig = False
        if not full_trig:
            tmp = Path(tempfile.mkdtemp(prefix="e2e_"))
            try:
                cf, cl = _crop(w.gate_first, tmp), _crop(w.gate_last, tmp)
                cm = [_crop(m, tmp) for m in w.gate_mids]
                crop = B4.run_gate_call(gate_window(cf, cl, cm), "b3_crop", B3_PROMPT, "v3")
                crop_trig = bool(crop.get("new_litter_detected")) and int(crop.get("confidence_0_100") or 0) >= B4.worker_config.GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE
            finally:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
        union = full_trig or crop_trig
        detail = run_detail(w.full_frames, w.wid) if union else None
        gcost = (full.get("cost_usd", 0) or 0) + ((crop or {}).get("cost_usd", 0) or 0)
        results.append({
            "event": w.wid, "ground_truth": ("TP" if w.category == "tp" else ("FP" if w.category == "fp" else "BASELINE")),
            "category": w.category, "source": ("baseline" if w.category == "baseline" else "event"),
            "full_trig": full_trig, "crop_trig": crop_trig, "triggered": union,
            "gate_full": full, "gate_crop": crop, "detail": detail,
            "gate_cost_usd": round(gcost, 8),
            "detail_cost_usd": round((detail or {}).get("cost_usd", 0) or 0, 8),
            "total_cost_usd": round(gcost + ((detail or {}).get("cost_usd", 0) or 0), 8),
        })
    payload = {"summary": {"windows": len(windows), "config": "dual_gate_b3_full_OR_crop + detail(current)",
                           "detail_calls": sum(1 for r in results if r["detail"]),
                           "total_cost_usd": round(sum(r["total_cost_usd"] for r in results), 6)},
               "results": results}
    out = CAMPAIGN_DIR / "results-E2E_dual_b3.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDONE -> {out.name}  detail_calls={payload['summary']['detail_calls']} cost=${payload['summary']['total_cost_usd']:.4f}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
