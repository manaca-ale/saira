#!/usr/bin/env python3
"""Campaign 44: Imbiribeira (esp32_001) vehicle-focused gate A/B/C.

Tests whether requiring a VEHICLE to escalate cuts pedestrian FP without breaking recall.
Ground truth = operator status from the FULL platform pull (manifest.csv):
  recall  = CONFIRMADO (tp) triggered
  specificity = 1 - REJEITADO (fp) triggered
INDETERMINADO is tracked but excluded from the score.

Arms (only the modality gating differs — same V3 base + scene preamble):
  A_baseline      = live ESP32_001_IMBIRIBEIRA_E_ADDON (camp-31 winner, prod today)
  B_vehicle_hard  = only vehicle deposits escalate
  C_vehicle_soft  = vehicle escalates freely; on-foot needs a high bar

Prod-faithful: device_id=esp32_001 -> detector uses gate_system_prompt_for_camera; we
rebind the addon per arm. Frames = first + last + 3 mid (camp-31 _mid). trigger conf>=85.
Auth = Vertex AI + ADC from services/.env.benchmark (GEMINI_USE_VERTEX=true).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import types
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(r"c:\saira")
WORKER_SRC = PROJECT_ROOT / "services" / "yolo-worker-vm" / "src"
DATASET_ROOT = PROJECT_ROOT / "data" / "datasets" / "official"
CAMPAIGN_DIR = Path(__file__).resolve().parents[1]

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if v and not v.startswith("<"):
            os.environ.setdefault(k.strip(), v)


# Vertex AI + ADC (keyless), matching prod. From services/.env.benchmark.
_load_env(PROJECT_ROOT / "services" / ".env.benchmark")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://stub@localhost/stub")
os.environ.setdefault("GEMINI_AGENT1_MODEL", "gemini-2.5-flash-lite")
os.environ.setdefault("GEMINI_AGENT1_THINKING_BUDGET", "2048")
os.environ.setdefault("GEMINI_INPUT_TOKEN_PRICE_PER_1M", "0.10")
os.environ.setdefault("GEMINI_OUTPUT_TOKEN_PRICE_PER_1M", "0.40")

if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.SimpleNamespace()

from worker import _prompts_v3  # noqa: E402
from worker import config as worker_config  # noqa: E402
from worker.detector_gemini import analyze_new_litter_with_gemini  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompts_vehicle import ARM_ADDONS  # noqa: E402

THINKING_BUDGET = int(os.environ.get("GEMINI_AGENT1_THINKING_BUDGET", "2048"))
PRICE_IN = float(os.environ["GEMINI_INPUT_TOKEN_PRICE_PER_1M"])
PRICE_OUT = float(os.environ["GEMINI_OUTPUT_TOKEN_PRICE_PER_1M"])
TRIGGER_MIN_CONF = 85

# esp32_001 camera context (prod camera has no gemini_context_notes field -> omit it).
CAMERA_CONTEXT = {
    "device_id": "esp32_001",
    "camera_name": "ESP32-001 - Imbiribeira",
    "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
    "bairro": "Imbiribeira",
    "rpa": "RPA 2",
}

ARMS = ["A_baseline", "B_vehicle_hard", "C_vehicle_soft"]
# Capture the live (prod) E_modality addon BEFORE any swap -> arm A_baseline.
_ADDON_BASELINE = _prompts_v3.ESP32_001_IMBIRIBEIRA_E_ADDON


@dataclass
class Event:
    event_id: str
    label: str  # TP / FP / IND
    frames: list
    meta: dict = field(default_factory=dict)


def _mid(frames):
    n = len(frames)
    if n < 5:
        return frames[1:-1]
    picked = []
    for idx in [int(n * 0.25), int(n * 0.5), int(n * 0.75)]:
        idx = max(1, min(n - 2, idx))
        if idx not in picked:
            picked.append(idx)
    return [frames[i] for i in picked]


CAT_LABEL = {"tp": "TP", "fp": "FP", "indefinido": "IND"}


def load_events(fp_limit=None, include_ind=False):
    rows = [r for r in csv.DictReader((DATASET_ROOT / "manifest.csv").open(encoding="utf-8"))
            if r.get("camera") == "cam_imbiribeira"]
    events = []
    cats = [("tp", "TP"), ("fp", "FP")] + ([("indefinido", "IND")] if include_ind else [])
    for cat, label in cats:
        crows = [r for r in rows if r.get("category") == cat]
        if cat == "fp" and fp_limit:
            crows = crows[:fp_limit]
        for r in crows:
            fr = sorted((DATASET_ROOT / r["local_path"] / "frames").glob("*.jpg"))
            if len(fr) >= 2:
                events.append(Event(r["event_id"][:8], label, fr, {
                    "datetime": r.get("datetime"),
                    "just": (r.get("justificativa") or "")[:60],
                    "source": r.get("label_source", ""),
                }))
    return events


def run_gate(ev: Event, arm: str) -> dict:
    """Run the gate for one event. The arm's addon is set once per arm in main()
    (thread-safe: the global addon is constant for the whole arm)."""
    try:
        mids = _mid(ev.frames)
        res = analyze_new_litter_with_gemini(
            first_frame=ev.frames[0], last_frame=ev.frames[-1],
            camera_context=CAMERA_CONTEXT,
            request_id=f"b44-{arm}-{ev.event_id}-{uuid.uuid4().hex[:4]}",
            prior_window_context=None, use_mosaic=False,
            mid_frames=mids if mids else None, prompt_version="v3")
        rep, us = res.report, res.usage
        billable = max(0, us.total_tokens - us.input_tokens)
        cost = (us.input_tokens / 1e6) * PRICE_IN + (billable / 1e6) * PRICE_OUT
        conf = int(rep.confidence_0_100)
        det = bool(rep.new_litter_detected)
        return {"ok": True, "triggered": det and conf >= TRIGGER_MIN_CONF,
                "conf": conf, "scene": getattr(rep, "scene_type", "") or "",
                "vehicle_stopped": bool(getattr(rep, "vehicle_stopped", False)),
                "ev": (rep.evidence_summary or "")[:200], "cost": round(cost, 8)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "triggered": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--fp-limit", type=int, default=None)
    ap.add_argument("--include-ind", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    worker_config.GEMINI_AGENT1_THINKING_BUDGET = THINKING_BUDGET
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    events = load_events(fp_limit=2 if args.smoke else args.fp_limit, include_ind=args.include_ind)
    if args.smoke:
        events = ([e for e in events if e.label == "TP"][:1]
                  + [e for e in events if e.label == "FP"][:2])
        arms = arms[:2]

    n = {l: sum(1 for e in events if e.label == l) for l in ("TP", "FP", "IND")}
    print(f"Campaign 44 — Imbiribeira vehicle-focused gate", flush=True)
    print(f"Vertex={worker_config.GEMINI_USE_VERTEX} proj={worker_config.GCP_PROJECT} "
          f"model={worker_config.GEMINI_AGENT1_MODEL} thinking={THINKING_BUDGET} trigger>={TRIGGER_MIN_CONF}", flush=True)
    print(f"Events: TP={n['TP']} FP={n['FP']} IND={n['IND']} | arms={arms}", flush=True)

    out = {"meta": {"trigger_min_conf": TRIGGER_MIN_CONF, "thinking": THINKING_BUDGET,
                    "n": n, "arms": arms}, "summary": [], "results": {}}
    for arm in arms:
        # Set the arm's addon ONCE (constant for the whole arm -> safe to thread events).
        _prompts_v3.ESP32_001_IMBIRIBEIRA_E_ADDON = ARM_ADDONS.get(arm, _ADDON_BASELINE)
        rows = [None] * len(events)

        def _work(i_ev):
            i, ev = i_ev
            g = run_gate(ev, arm)
            mark = "E" if not g.get("ok") else ("T" if g.get("triggered") else ".")
            print(f"  {arm:16s} {ev.label:3s} {ev.event_id} [{mark}] conf={g.get('conf','-')} "
                  f"veh={g.get('vehicle_stopped','-')} {g.get('error','')}", flush=True)
            return i, {"id": ev.event_id, "label": ev.label, "meta": ev.meta, "gate": g}

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            for i, row in ex.map(_work, list(enumerate(events))):
                rows[i] = row
        tp = [r for r in rows if r["label"] == "TP"]
        fp = [r for r in rows if r["label"] == "FP"]
        tp_c = sum(1 for r in tp if r["gate"].get("triggered"))
        fp_t = sum(1 for r in fp if r["gate"].get("triggered"))
        errs = sum(1 for r in rows if not r["gate"].get("ok"))
        recall = tp_c / max(1, len(tp))
        spec = 1 - fp_t / max(1, len(fp))
        score = round((3 * recall + spec) / 4, 4)
        cost = sum(r["gate"].get("cost", 0) or 0 for r in rows)
        s = {"arm": arm, "tp_recall": f"{tp_c}/{len(tp)}", "fp_triggered": f"{fp_t}/{len(fp)}",
             "recall": round(recall, 3), "specificity": round(spec, 3),
             "score_recall_x3": score, "fp_cut_vs_baseline": None,
             "errors": errs, "cost_usd": round(cost, 5)}
        out["summary"].append(s)
        out["results"][arm] = rows
        (CAMPAIGN_DIR / f"results-{arm}.json").write_text(
            json.dumps({"summary": s, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  => [{arm}] recall {tp_c}/{len(tp)}={recall:.2f} | FP trig {fp_t}/{len(fp)} "
              f"spec={spec:.2f} | score={score} | err={errs} ${cost:.3f}", flush=True)

    # fp_cut vs baseline
    base = next((s for s in out["summary"] if s["arm"] == "A_baseline"), None)
    if base:
        base_fp = int(base["fp_triggered"].split("/")[0])
        for s in out["summary"]:
            cur_fp = int(s["fp_triggered"].split("/")[0])
            s["fp_cut_vs_baseline"] = base_fp - cur_fp

    (CAMPAIGN_DIR / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== RANKING (score = (3*recall + spec)/4) ===", flush=True)
    for s in sorted(out["summary"], key=lambda x: x["score_recall_x3"], reverse=True):
        print(f"  {s['arm']:16s} score={s['score_recall_x3']:.3f} recall={s['recall']:.2f} "
              f"spec={s['specificity']:.2f} (TP {s['tp_recall']}, FPtrig {s['fp_triggered']}, "
              f"FPcut {s['fp_cut_vs_baseline']}, err {s['errors']})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
