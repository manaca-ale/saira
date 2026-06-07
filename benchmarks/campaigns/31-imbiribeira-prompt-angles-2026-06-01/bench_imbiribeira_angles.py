#!/usr/bin/env python3
"""Campaign 31: Imbiribeira (esp32_001) gate prompt-angle exploration.

Designs an Imbiribeira-specific gate prompt (open vacant lot, no single pile, small/
distant subjects, dominant FP = garbage collection/removal). Tests several angles vs the
V1 and V3-base references against the full local eval set:
  - recall: 7 TP (captured on platform) + 1 FN (id 18, prod missed)
  - specificity: 31 FP (operator-rejected captures — mostly collection/cleanup)

Gate-only, gemini-2.5-flash-lite, thinking 2048, first+last+3 mid, trigger conf>=85.
Arms: v1, v3_base, C_direction, D_smallsubject, E_modality, F_combined.
SAIRA weights recall heavily; primary score = recall + specificity with recall x3.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import types
import uuid
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(r"c:\saira")
WORKER_SRC = PROJECT_ROOT / "services" / "yolo-worker-vm" / "src"
DATASET_ROOT = PROJECT_ROOT / "data" / "datasets" / "official"
CAMPAIGN_DIR = Path(__file__).parent
FN18_DIR = PROJECT_ROOT / "benchmarks" / "campaigns" / "30-imbiribeira-gate-v3b3-recall-2026-06-01" / "fn18_frames"

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
        if not v.startswith("<"):
            os.environ.setdefault(k.strip(), v)


_load_env(CAMPAIGN_DIR / ".env.benchmark")
if not os.environ.get("GEMINI_API_KEY"):
    se = PROJECT_ROOT / "services" / ".env.benchmark"
    if se.exists():
        for line in se.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("GEMINI_TEST_API_KEY=") and "=" in line:
                os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip()
                break
if not os.environ.get("GEMINI_API_KEY"):
    print("ERR: GEMINI_API_KEY not set.", file=sys.stderr)
    sys.exit(2)

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

sys.path.insert(0, str(CAMPAIGN_DIR))
from prompts_imbiribeira import ANGLES  # noqa: E402

THINKING_BUDGET = int(os.environ.get("GEMINI_AGENT1_THINKING_BUDGET", "2048"))
PRICE_IN = float(os.environ["GEMINI_INPUT_TOKEN_PRICE_PER_1M"])
PRICE_OUT = float(os.environ["GEMINI_OUTPUT_TOKEN_PRICE_PER_1M"])
TRIGGER_MIN_CONF = 85

CAMERA_CONTEXT = {
    "device_id": "esp32_001",
    "camera_name": "ESP32-001 - Imbiribeira",
    "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
    "bairro": "Imbiribeira",
    "rpa": "RPA 2",
    "gemini_context_notes": (
        "Câmera em poste alto sobre TERRENO BALDIO aberto (ponto crônico de descarte). "
        "Poste vertical cruza o centro do quadro. Sem pilha única: entulho/lixo espalhado "
        "por todo o terreno. Descartes por pessoa a pé, carrinho de mão ou veículo que "
        "PARA e deposita material. Também há carros estacionados, passagem de pessoas, e "
        "às vezes equipe/caminhão REMOVENDO lixo (coleta). Sujeitos costumam aparecer "
        "pequenos/distantes. Luz varia (dia/crepúsculo/madrugada/IR)."
    ),
}

# arm -> (prompt_version, recall_block or None)
ARMS = {
    "v1": ("current", None),
    "v3_base": ("v3", None),
    **{name: ("v3", block) for name, block in ANGLES.items()},
}


@dataclass
class Event:
    event_id: str
    label: str  # TP / FN / FP
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


def load_events(fp_limit=None):
    rows = [r for r in csv.DictReader((DATASET_ROOT / "manifest.csv").open(encoding="utf-8"))
            if "imbiribeira" in (r.get("camera", "") + r.get("device_id", "")).lower()]
    events = []
    for cat, label in (("tp", "TP"), ("fp", "FP")):
        crows = [r for r in rows if r.get("category") == cat]
        if cat == "fp" and fp_limit:
            crows = crows[:fp_limit]
        for r in crows:
            fr = sorted((DATASET_ROOT / r["local_path"] / "frames").glob("*.jpg"))
            if len(fr) >= 2:
                events.append(Event(r["event_id"][:8], label, fr,
                                    {"datetime": r.get("datetime"),
                                     "just": (r.get("justificativa") or "")[:55]}))
    fn = sorted(FN18_DIR.glob("*.jpg"))
    if len(fn) >= 2:
        events.append(Event("fn18_0517", "FN", fn,
                            {"datetime": "2026-06-01T05:17", "just": "prod MISSED (dois homens)"}))
    return events


def run_gate(ev: Event, arm: str) -> dict:
    pv, block = ARMS[arm]
    prev = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    prev_b = worker_config.GEMINI_AGENT1_THINKING_BUDGET
    if pv == "v3":
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = (prev + "\n\n" + block) if block else prev
    worker_config.GEMINI_AGENT1_THINKING_BUDGET = THINKING_BUDGET
    try:
        mids = _mid(ev.frames)
        res = analyze_new_litter_with_gemini(
            first_frame=ev.frames[0], last_frame=ev.frames[-1],
            camera_context=CAMERA_CONTEXT,
            request_id=f"b31-{arm}-{ev.event_id}-{uuid.uuid4().hex[:4]}",
            prior_window_context=None, use_mosaic=False,
            mid_frames=mids if mids else None, prompt_version=pv)
        rep, us = res.report, res.usage
        billable = max(0, us.total_tokens - us.input_tokens)
        cost = (us.input_tokens / 1e6) * PRICE_IN + (billable / 1e6) * PRICE_OUT
        conf = int(rep.confidence_0_100)
        det = bool(rep.new_litter_detected)
        return {"ok": True, "triggered": det and conf >= TRIGGER_MIN_CONF,
                "conf": conf, "scene": getattr(rep, "scene_type", "") or "",
                "flow": getattr(rep, "material_flow_direction", None),
                "ev": (rep.evidence_summary or "")[:200], "cost": round(cost, 8)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "triggered": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    finally:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = prev
        worker_config.GEMINI_AGENT1_THINKING_BUDGET = prev_b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="v1,v3_base,C_direction,D_smallsubject,E_modality,F_combined")
    ap.add_argument("--fp-limit", type=int, default=None)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    events = load_events(fp_limit=2 if args.smoke else args.fp_limit)
    if args.smoke:
        events = ([e for e in events if e.label == "TP"][:1]
                  + [e for e in events if e.label == "FN"][:1]
                  + [e for e in events if e.label == "FP"][:1])
        arms = arms[:3]

    n = {l: sum(1 for e in events if e.label == l) for l in ("TP", "FN", "FP")}
    print(f"Campaign 31 - Imbiribeira gate prompt angles", flush=True)
    print(f"Model {worker_config.GEMINI_AGENT1_MODEL} thinking={THINKING_BUDGET} trigger>={TRIGGER_MIN_CONF}", flush=True)
    print(f"Events: TP={n['TP']} FN={n['FN']} FP={n['FP']} | arms={arms}", flush=True)

    out = {"summary": [], "results": {}}
    for arm in arms:
        rows = []
        for ev in events:
            g = run_gate(ev, arm)
            rows.append({"id": ev.event_id, "label": ev.label, "meta": ev.meta, "gate": g})
        tp = [r for r in rows if r["label"] == "TP"]
        fn = [r for r in rows if r["label"] == "FN"]
        fp = [r for r in rows if r["label"] == "FP"]
        tp_c = sum(1 for r in tp if r["gate"].get("triggered"))
        fn_c = sum(1 for r in fn if r["gate"].get("triggered"))
        fp_t = sum(1 for r in fp if r["gate"].get("triggered"))
        errs = sum(1 for r in rows if not r["gate"].get("ok"))
        recall = (tp_c + fn_c) / max(1, len(tp) + len(fn))
        spec = 1 - fp_t / max(1, len(fp))
        score = round((3 * recall + spec) / 4, 4)  # recall-weighted (SAIRA)
        cost = sum(r["gate"].get("cost", 0) or 0 for r in rows)
        s = {"arm": arm, "tp_recall": f"{tp_c}/{len(tp)}", "fn": f"{fn_c}/{len(fn)}",
             "fp_triggered": f"{fp_t}/{len(fp)}", "recall": round(recall, 3),
             "specificity": round(spec, 3), "score_recall_x3": score,
             "errors": errs, "cost_usd": round(cost, 5)}
        out["summary"].append(s)
        out["results"][arm] = rows
        print(f"  [{arm:14s}] recall {tp_c+fn_c}/{len(tp)+len(fn)} (TP {tp_c}/{len(tp)}, FN {fn_c}/{len(fn)}) "
              f"| FP trig {fp_t}/{len(fp)} spec={spec:.2f} | score={score} | err={errs} ${cost:.3f}", flush=True)

    (CAMPAIGN_DIR / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== RANKING (score = recall*3 + spec /4) ===", flush=True)
    for s in sorted(out["summary"], key=lambda x: x["score_recall_x3"], reverse=True):
        print(f"  {s['arm']:14s} score={s['score_recall_x3']:.3f} recall={s['recall']:.2f} spec={s['specificity']:.2f} "
              f"(TP {s['tp_recall']}, FN {s['fn']}, FPtrig {s['fp_triggered']}, err {s['errors']})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
