#!/usr/bin/env python3
"""Campaign 52: does the V3 gate prompt still pay for itself on esp32_001/esp32_002?

Cost investigation (2026-08-04) found those two cameras carry a ~3.571-token system
prompt (V3 + per-camera addon) against 358 tokens (V1) on the other four — ~3.200 extra
tokens on EVERY gate call, ~R$46/month. The images are identical in size across all six
cameras (1280x720), so the delta is pure prompt. V3+B3 shipped to esp32_002 on 28/05 and
E_modality to esp32_001 via campaign 31; both are ~3 months old and frame sampling changed
since (027b33c51). Question: do the extra tokens still buy the recall they bought in May?

Arms (only the system prompt / prompt-version path differs):
  A_prod     = V3 + per-camera addon  (what prod runs today)
  B_v3_base  = V3 base, no addon
  C_v1       = V1 (short prompt)

Ground truth = operator status in manifest.csv:
  recall      = (tp + missed) that trigger      <- `missed` are real gate FNs
  specificity = 1 - (fp that trigger)
  `indefinido` runs and is reported, but is EXCLUDED from the score (campaign 44 convention).

Prod fidelity (verified against saira-yolo-worker-prod on 2026-08-04):
  model gemini-2.5-flash-lite | thinking_budget 2048 | trigger conf>=85
  frames = first + 3 EVENLY-spaced mids + last, sent INDIVIDUALLY (no mosaic:
  GEMINI_MOSAIC_AGENT1 defaults to false and is unset everywhere in prod)
  camera_context carries camera_name/device_id/logradouro/bairro/rpa/horario_local
  Auth = Vertex AI + ADC from services/.env.benchmark (project saira-tests-260520)

KNOWN DEVIATION (arm C_v1 only): the V1 branch is reached by omitting `device_id` from
camera_context, because the version dispatch is hardcoded
(detector_gemini.py:1156 `camera_device_id in ("esp32_002","esp32_001")`). Since
_new_litter_user_prompt dumps every camera_context key into the text, arm C loses the
`- device_id: esp32_00X` line (~5 tokens). This is deliberate: the alternative was
monkeypatching the V3 prompt symbols, which would leave _prompts_v3.apply_v3_gates running
over a V1-shaped report -- a configuration that exists in no environment. The V1
post-processing lives inline in the `else:` branch and is not importable, so reimplementing
it in the bench would be exactly the infidelity that invalidated campaigns 20/21.
Omitting device_id keeps the ENTIRE real V1 path: prompt, schema and post-gates.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import types
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
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
os.environ.setdefault("GEMINI_GATE_MID_FRAMES", "3")
os.environ.setdefault("GEMINI_INPUT_TOKEN_PRICE_PER_1M", "0.10")
os.environ.setdefault("GEMINI_OUTPUT_TOKEN_PRICE_PER_1M", "0.40")

if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.SimpleNamespace()

from worker import _prompts_v3  # noqa: E402
from worker import config as worker_config  # noqa: E402
from worker import detector_gemini  # noqa: E402
from worker.detector_gemini import analyze_new_litter_with_gemini  # noqa: E402

THINKING_BUDGET = int(os.environ["GEMINI_AGENT1_THINKING_BUDGET"])
MID_FRAMES = int(os.environ["GEMINI_GATE_MID_FRAMES"])
PRICE_IN = float(os.environ["GEMINI_INPUT_TOKEN_PRICE_PER_1M"])
PRICE_OUT = float(os.environ["GEMINI_OUTPUT_TOKEN_PRICE_PER_1M"])
TRIGGER_MIN_CONF = 85

# Real prod values (pulled from saira-db-prod `cameras` on 2026-08-04).
CAMERAS = {
    "cam_mangabeira": {
        "device_id": "esp32_002",
        "camera_name": "Mangabeira",
        "logradouro": "Av. Prof. José dos Anjos, 3254",
        "bairro": "Mangabeira",
        "rpa": "RPA 5",
    },
    "cam_imbiribeira": {
        "device_id": "esp32_001",
        "camera_name": "Residencial Via Mangue III - 1",
        "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
        "bairro": "Imbiribeira",
        "rpa": "RPA-1",
    },
}

ARMS = ["A_prod", "B_v3_base", "C_v1"]

# Captured BEFORE any rebind so arm A/C restore cleanly.
_LIVE_GATE_PROMPT_FN = _prompts_v3.gate_system_prompt_for_camera

# --- prompt/schema instrumentation ------------------------------------------
# _call_model is resolved as a module global inside analyze_new_litter_with_gemini,
# so wrapping the attribute captures exactly what was sent. First observation per
# (arm, camera) only -- this is the evidence that the arms really differ.
_OBSERVED: dict[tuple[str, str], dict] = {}
_OBS_LOCK = threading.Lock()
_ORIG_CALL_MODEL = detector_gemini._call_model
# Arms run strictly one at a time, so a plain global is safe here. A thread-local
# is NOT: analyze_new_litter_with_gemini submits _call_model to its own internal
# ThreadPoolExecutor, so the value would never reach the calling thread.
_CURRENT_ARM = "?"
# Camera is recovered from the prompt text, since it varies across events running
# concurrently inside one arm. Both bairros are unique across the two cameras.
_BAIRRO_TO_CAM = {"Mangabeira": "cam_mangabeira", "Imbiribeira": "cam_imbiribeira"}


def _instrumented_call_model(image_paths, system_prompt, user_prompt, model_name,
                             response_schema, *a, **kw):
    cam = next((c for b, c in _BAIRRO_TO_CAM.items() if f"bairro: {b}" in user_prompt), "?")
    key = (_CURRENT_ARM, cam)
    with _OBS_LOCK:
        if key not in _OBSERVED:
            _OBSERVED[key] = {
                "system_prompt_chars": len(system_prompt),
                "user_prompt_chars": len(user_prompt),
                "schema_title": (response_schema or {}).get("title", "?"),
                "n_images": len(image_paths),
                "model": model_name,
            }
    return _ORIG_CALL_MODEL(image_paths, system_prompt, user_prompt, model_name,
                            response_schema, *a, **kw)


detector_gemini._call_model = _instrumented_call_model


@dataclass
class Event:
    event_id: str
    camera: str
    label: str  # TP / FP / IND / MISSED
    frames: list
    meta: dict = field(default_factory=dict)


def _mid(frames: list) -> list:
    """Prod's EVENLY-spaced interior frames (main.py:1462-1469).

    NOT the legacy 25/50/75 pick -- commit 027b33c51 replaced it because the
    crouch frames of on-foot dumps sat before the 25% mark.
    """
    n = len(frames)
    if n < 3 or MID_FRAMES <= 0:
        return []
    step = (n - 1) / (MID_FRAMES + 1)
    idxs = sorted({int(round(step * (i + 1))) for i in range(MID_FRAMES)})
    idxs = [k for k in idxs if 0 < k < n - 1]
    return [frames[k] for k in idxs]


def _horario_local(raw: str) -> str:
    """HH:MM from the manifest datetime (two formats coexist in manifest.csv)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw).strftime("%H:%M")
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).strftime("%H:%M")
            except ValueError:
                continue
    return ""


CATS = [("tp", "TP"), ("missed", "MISSED"), ("fp", "FP")]


def load_events(cameras: list[str], fp_limit=None, include_ind=False) -> list[Event]:
    rows = list(csv.DictReader((DATASET_ROOT / "manifest.csv").open(encoding="utf-8")))
    cats = CATS + ([("indefinido", "IND")] if include_ind else [])
    events: list[Event] = []
    for cam in cameras:
        crows_all = [r for r in rows if r.get("camera") == cam]
        for cat, label in cats:
            crows = [r for r in crows_all if r.get("category") == cat]
            if cat == "fp" and fp_limit:
                crows = crows[:fp_limit]
            for r in crows:
                fr = sorted((DATASET_ROOT / r["local_path"] / "frames").glob("*.jpg"))
                if len(fr) >= 2:
                    events.append(Event(r["event_id"][:8], cam, label, fr, {
                        "datetime": r.get("datetime"),
                        "horario_local": _horario_local(r.get("datetime", "")),
                        "just": (r.get("justificativa") or "")[:60],
                        "source": r.get("label_source", ""),
                    }))
    return events


def _camera_context(ev: Event, arm: str) -> dict:
    base = dict(CAMERAS[ev.camera])
    ctx = {
        "camera_name": base["camera_name"],
        "device_id": base["device_id"],
        "logradouro": base["logradouro"],
        "bairro": base["bairro"],
        "rpa": base["rpa"],
        "horario_local": ev.meta.get("horario_local", ""),
    }
    if arm == "C_v1":
        # See KNOWN DEVIATION in the module docstring.
        ctx.pop("device_id")
    return ctx


def run_gate(ev: Event, arm: str) -> dict:
    try:
        mids = _mid(ev.frames)
        res = analyze_new_litter_with_gemini(
            first_frame=ev.frames[0], last_frame=ev.frames[-1],
            camera_context=_camera_context(ev, arm),
            request_id=f"b52-{arm}-{ev.event_id}-{uuid.uuid4().hex[:4]}",
            prior_window_context=None, use_mosaic=False,
            mid_frames=mids if mids else None,
            prompt_version="current",
        )
        rep, us = res.report, res.usage
        billable = max(0, us.total_tokens - us.input_tokens)
        cost = (us.input_tokens / 1e6) * PRICE_IN + (billable / 1e6) * PRICE_OUT
        conf = int(rep.confidence_0_100)
        det = bool(rep.new_litter_detected)
        return {"ok": True, "triggered": det and conf >= TRIGGER_MIN_CONF,
                "conf": conf, "scene": getattr(rep, "scene_type", "") or "",
                "in_tok": us.input_tokens, "out_tok": billable,
                "ev": (rep.evidence_summary or "")[:200], "cost": round(cost, 8)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "triggered": False,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def _score(rows: list[dict]) -> dict:
    pos = [r for r in rows if r["label"] in ("TP", "MISSED")]
    fp = [r for r in rows if r["label"] == "FP"]
    pos_t = sum(1 for r in pos if r["gate"].get("triggered"))
    fp_t = sum(1 for r in fp if r["gate"].get("triggered"))
    ok = [r for r in rows if r["gate"].get("ok")]
    recall = pos_t / max(1, len(pos))
    spec = 1 - fp_t / max(1, len(fp))
    return {
        "recall_n": f"{pos_t}/{len(pos)}", "recall": round(recall, 3),
        "fp_triggered": f"{fp_t}/{len(fp)}", "specificity": round(spec, 3),
        "score_recall_x3": round((3 * recall + spec) / 4, 4),
        "errors": sum(1 for r in rows if not r["gate"].get("ok")),
        "cost_usd": round(sum(r["gate"].get("cost", 0) or 0 for r in rows), 5),
        "avg_in_tok": round(sum(r["gate"].get("in_tok", 0) for r in ok) / max(1, len(ok))),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--cameras", default="cam_mangabeira,cam_imbiribeira")
    ap.add_argument("--fp-limit", type=int, default=None)
    ap.add_argument("--include-ind", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    worker_config.GEMINI_AGENT1_THINKING_BUDGET = THINKING_BUDGET
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    cameras = [c.strip() for c in args.cameras.split(",") if c.strip()]
    events = load_events(cameras, fp_limit=2 if args.smoke else args.fp_limit,
                         include_ind=args.include_ind)
    if args.smoke:
        picked = []
        for cam in cameras:
            ce = [e for e in events if e.camera == cam]
            picked += [e for e in ce if e.label == "TP"][:1] + [e for e in ce if e.label == "FP"][:2]
        events = picked

    n = {l: sum(1 for e in events if e.label == l) for l in ("TP", "MISSED", "FP", "IND")}
    print("Campaign 52 — gate prompt V1 vs V3: does the extra prompt still pay?", flush=True)
    print(f"Vertex={worker_config.GEMINI_USE_VERTEX} proj={worker_config.GCP_PROJECT} "
          f"model={worker_config.GEMINI_AGENT1_MODEL} thinking={THINKING_BUDGET} "
          f"mids={MID_FRAMES} trigger>={TRIGGER_MIN_CONF} mosaic=False", flush=True)
    print(f"Cameras={cameras} | TP={n['TP']} MISSED={n['MISSED']} FP={n['FP']} IND={n['IND']} "
          f"| arms={arms}", flush=True)

    out = {"meta": {"trigger_min_conf": TRIGGER_MIN_CONF, "thinking": THINKING_BUDGET,
                    "mid_frames": MID_FRAMES, "mosaic": False, "n": n, "arms": arms,
                    "cameras": cameras,
                    "deviation": "arm C_v1 omits device_id from camera_context "
                                 "(hardcoded version dispatch); costs ~5 prompt tokens"},
           "summary": [], "per_camera": {}, "observed_prompts": {}, "results": {}}

    global _CURRENT_ARM
    for arm in arms:
        _CURRENT_ARM = arm
        # Set the arm's prompt source ONCE -> constant for the whole arm, safe to thread.
        if arm == "B_v3_base":
            _prompts_v3.gate_system_prompt_for_camera = (
                lambda ctx=None: _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3)
        else:
            _prompts_v3.gate_system_prompt_for_camera = _LIVE_GATE_PROMPT_FN

        rows: list = [None] * len(events)

        def _work(i_ev):
            i, ev = i_ev
            g = run_gate(ev, arm)
            mark = "E" if not g.get("ok") else ("T" if g.get("triggered") else ".")
            print(f"  {arm:10s} {ev.camera:16s} {ev.label:6s} {ev.event_id} [{mark}] "
                  f"conf={g.get('conf','-')} in={g.get('in_tok','-')} {g.get('error','')}",
                  flush=True)
            return i, {"id": ev.event_id, "camera": ev.camera, "label": ev.label,
                       "meta": ev.meta, "gate": g}

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            for i, row in ex.map(_work, list(enumerate(events))):
                rows[i] = row

        s = {"arm": arm, **_score(rows)}
        out["summary"].append(s)
        out["results"][arm] = rows
        out["per_camera"][arm] = {
            cam: _score([r for r in rows if r["camera"] == cam]) for cam in cameras
        }
        (CAMPAIGN_DIR / f"results-{arm}.json").write_text(
            json.dumps({"summary": s, "per_camera": out["per_camera"][arm], "rows": rows},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  => [{arm}] recall {s['recall_n']}={s['recall']:.2f} | "
              f"FPtrig {s['fp_triggered']} spec={s['specificity']:.2f} | "
              f"avg_in={s['avg_in_tok']} tok | err={s['errors']} ${s['cost_usd']:.3f}",
              flush=True)

    _prompts_v3.gate_system_prompt_for_camera = _LIVE_GATE_PROMPT_FN
    out["observed_prompts"] = {f"{a}|{c}": v for (a, c), v in sorted(_OBSERVED.items())}

    (CAMPAIGN_DIR / "results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== PROMPTS OBSERVADOS (prova de que os braços diferem) ===", flush=True)
    for k, v in out["observed_prompts"].items():
        print(f"  {k:28s} sys={v['system_prompt_chars']:6d} ch  user={v['user_prompt_chars']:5d} ch  "
              f"schema={v['schema_title']:26s} imgs={v['n_images']}", flush=True)

    print("\n=== POR CÂMERA ===", flush=True)
    for cam in cameras:
        print(f"  -- {cam}", flush=True)
        for arm in arms:
            s = out["per_camera"][arm][cam]
            print(f"     {arm:10s} recall {s['recall_n']:>7s}={s['recall']:.2f}  "
                  f"FPtrig {s['fp_triggered']:>7s} spec={s['specificity']:.2f}  "
                  f"in={s['avg_in_tok']:5d} tok  ${s['cost_usd']:.3f}", flush=True)

    print("\n=== RANKING GERAL (score = (3*recall + spec)/4) ===", flush=True)
    for s in sorted(out["summary"], key=lambda x: x["score_recall_x3"], reverse=True):
        print(f"  {s['arm']:10s} score={s['score_recall_x3']:.3f} recall={s['recall']:.2f} "
              f"spec={s['specificity']:.2f} avg_in={s['avg_in_tok']} tok "
              f"(err {s['errors']}) ${s['cost_usd']:.3f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
