#!/usr/bin/env python3
"""Campaign 32: recover the 2026-06-02 13:13 Mangabeira FN (bulky construction-debris
dump) without increasing FP.

The deployed esp32_002 gate (V3 + B3 recall addon) MISSED a real dump on 2026-06-02 at
13:13-13:16: people on foot placed/stacked green doors/panels, wood boards and metal rails
at the pile. The gate said "person near pile, no clear dumping" (conf 50, not escalated).
B3 keys on a bag/sack "material-carrier" signal; it lacks the bulky-item clause that
campaign-19 B4/B5 had.

This tests whether adding a BULKY-ITEM clause to the deployed B3 recovers that FN (and the
6 dataset 'missed' FNs) without hurting specificity.

Arms (gate-only, gemini-2.5-flash-lite, thinking 2048, first+last+3 mid, trigger conf>=85):
- b3        : deployed prod gate (V3 + ESP32_002_RECALL_B3_ADDON) — baseline
- b3_bulky  : B3 + bulky-item clause — candidate
- b4        : V3 + campaign-19 B4 block (already has bulky) — reference

Eval (cam_mangabeira, local): recall = 13 TP + 6 'missed' + the 13:13 FN; spec = 48 FP.
Score = (3*recall + spec)/4 (SAIRA recall weighting).
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
FN1313_DIR = Path(r"C:\Users\aleco\Downloads\mangabeira_2026-06-02_12-00_a_13-49")

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            if not v.strip().startswith("<"):
                os.environ.setdefault(k.strip(), v.strip())


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

THINKING_BUDGET = int(os.environ.get("GEMINI_AGENT1_THINKING_BUDGET", "2048"))
PRICE_IN = float(os.environ["GEMINI_INPUT_TOKEN_PRICE_PER_1M"])
PRICE_OUT = float(os.environ["GEMINI_OUTPUT_TOKEN_PRICE_PER_1M"])
TRIGGER_MIN_CONF = 85

# camera_context WITHOUT device_id (so gate_system_prompt_for_camera does not auto-append
# B3; we patch NEW_LITTER_SYSTEM_PROMPT_V3 = base + arm-block instead).
CAMERA_CONTEXT = {
    "camera_name": "ESP32-002 - Mangabeira",
    "logradouro": "Av. Prof. José dos Anjos, 3254",
    "bairro": "Mangabeira",
    "rpa": "RPA 3",
    "gemini_context_notes": (
        "Câmera sobre lixeira pública informal na esquina, calçada à direita e via à "
        "esquerda, com pilha de resíduos pré-existente. Descartes por moradores a pé "
        "(sacos), carrinho de mão, e também ENTULHO/material de construção volumoso "
        "(portas, painéis, madeira, perfis metálicos) colocado a mão. Coleta da prefeitura "
        "passa em caminhão. Tráfego intenso de pedestres que NÃO param para descartar."
    ),
}

# Deployed B3 (prod baseline).
B3 = _prompts_v3.ESP32_002_RECALL_B3_ADDON

# Bulky-item clause appended to B3 (the candidate's only delta).
BULKY_CLAUSE = """

BULKY-ITEM RULE (in addition to the above):
ALSO escalate (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) when
ONE OR MORE people HANDLE, CARRY, DRAG, DISMANTLE, STACK, or PLACE a BULKY item at or beside
the pile — furniture, mattress, appliance, TV/monitor/mirror, door/panel, wood/boards,
scrap metal/rails/tubes, or construction/demolition debris — even WITHOUT a bag/sack, and even
if it looks like they might be sorting or salvaging. Leaving or stacking a bulky item at the
pile IS dumping; set material_flow_direction="to_pile". (Loading items FROM the ground ONTO a
truck = municipal collection = NOT dumping, keep suppressing that.)
"""

B3_BULKY = B3 + BULKY_CLAUSE

# Campaign-19 B4 block (reference; already contains a bulky clause).
B4 = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE B4 - esp32_002 / Av. Prof. Jose dos Anjos
=============================================================================
This camera watches a chronic illegal dumping point with a large pre-existing pile.
Agent-1 is only a gate for Agent-2; proximity alone is NOT enough, but err toward
ESCALATION whenever material is being HANDLED, CARRIED, or ADDED at the pile.

Keep evidence_summary and scene_delta_analysis under 260 characters each.
Do not quote this instruction block in your JSON fields.

Escalate (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) when
ANY material-transfer / material-carrier / bulky-handling signal is visible:
1) a pedestrian enters the pile frontage/sidewalk carrying a bag/sack/object, even if
   small or visible in only one frame;
2) a person bends/reaches at the pile and then leaves the pile zone empty-handed or
   without the object previously handled;
3) a new object/material appears on top of or beside the pile in later frames;
4) a wheelbarrow/handcart/cart/truck is positioned AT the pile frontage in 2+ frames,
   OR its load state changes toward unloading — escalate even if the load is low-res
   or partially occluded;
5) ONE OR MORE people are actively HANDLING, DISMANTLING, BREAKING, or PLACING a bulky
   item at the pile — furniture, mattress, appliance, electronics (TV, monitor, mirror,
   panel), wood, scrap metal, or construction debris — regardless of a clean
   carry-then-empty-hands transition. Dismantling or leaving a bulky object at the pile
   IS dumping.
If a person/cart is moving toward the pile frontage with a plausible load, set
material_flow_direction="to_pile" even without a full deposit view.

Suppress baseline/proximity cases. Set new_litter_detected=false and confidence <= 60
when the only visible evidence is:
- a person standing, looking, waiting, or walking near the pile with empty hands;
- a person passing by with no carried object/cart and no stop at the pile frontage;
- motorcycle/backpack only, with no object transferred to the pile;
- municipal collection/maintenance (brooms, rakes, shovels, EMLURB compactor), or flow
  is from_pile, or people REMOVING items from the pile;
- poking/sorting existing material with a stick or hands, no new object added and no
  bulky item being placed;
- ambiguous interaction with no carried object, no cart, no bulky handling, no new
  object, and no load-state change.

Do NOT classify standing_near_pile / passing_by as DUMPING unless one of signals 1-5
is also visible. When collection-vs-dumping is genuinely ambiguous AND a bulky item or
a new object is involved, prefer to ESCALATE (Agent-2 makes the final call).
""".strip()

ARMS = {"b3": B3, "b3_bulky": B3_BULKY, "b4": B4}


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


def load_events():
    rows = [r for r in csv.DictReader((DATASET_ROOT / "manifest.csv").open(encoding="utf-8"))
            if r.get("camera") == "cam_mangabeira"]
    events = []
    for r in rows:
        cat = r.get("category")
        if cat == "tp":
            label = "TP"
        elif cat == "missed":
            label = "FN"   # known prod miss = recall target
        elif cat == "fp":
            label = "FP"
        else:
            continue
        fr = sorted((DATASET_ROOT / r["local_path"] / "frames").glob("*.jpg"))
        if len(fr) >= 2:
            events.append(Event(r["event_id"][:8], label, fr,
                                {"just": (r.get("justificativa") or "")[:55]}))
    # the new 2026-06-02 13:13 FN (bulky construction-debris dump)
    fn = sorted(FN1313_DIR.glob("2026-06-02_13-1[3-6]-*.jpg"))
    fn = [f for f in fn if f.name >= "2026-06-02_13-13-52.jpg" and f.name <= "2026-06-02_13-16-58.jpg"]
    if len(fn) >= 2:
        events.append(Event("fn_1313", "FN", fn,
                            {"just": "2026-06-02 13:13 painéis/madeira/metal a pé (prod MISSED)"}))
    return events


def run_gate(ev: Event, arm: str) -> dict:
    block = ARMS[arm]
    prev = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    prev_b = worker_config.GEMINI_AGENT1_THINKING_BUDGET
    _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = prev + "\n\n" + block
    worker_config.GEMINI_AGENT1_THINKING_BUDGET = THINKING_BUDGET
    try:
        mids = _mid(ev.frames)
        res = analyze_new_litter_with_gemini(
            first_frame=ev.frames[0], last_frame=ev.frames[-1],
            camera_context=CAMERA_CONTEXT,
            request_id=f"b32-{arm}-{ev.event_id}-{uuid.uuid4().hex[:4]}",
            prior_window_context=None, use_mosaic=False,
            mid_frames=mids if mids else None, prompt_version="v3")
        rep, us = res.report, res.usage
        billable = max(0, us.total_tokens - us.input_tokens)
        cost = (us.input_tokens / 1e6) * PRICE_IN + (billable / 1e6) * PRICE_OUT
        conf = int(rep.confidence_0_100)
        det = bool(rep.new_litter_detected)
        return {"ok": True, "triggered": det and conf >= TRIGGER_MIN_CONF, "conf": conf,
                "scene": getattr(rep, "scene_type", "") or "",
                "flow": getattr(rep, "material_flow_direction", None),
                "ev": (rep.evidence_summary or "")[:220], "cost": round(cost, 8)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "triggered": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    finally:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = prev
        worker_config.GEMINI_AGENT1_THINKING_BUDGET = prev_b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="b3,b3_bulky,b4")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    events = load_events()
    if args.smoke:
        events = ([e for e in events if e.label == "TP"][:1]
                  + [e for e in events if e.label == "FN"]
                  + [e for e in events if e.label == "FP"][:1])
    n = {l: sum(1 for e in events if e.label == l) for l in ("TP", "FN", "FP")}
    print(f"Campaign 32 - Mangabeira bulky-item FN recovery", flush=True)
    print(f"Model {worker_config.GEMINI_AGENT1_MODEL} thinking={THINKING_BUDGET} trigger>={TRIGGER_MIN_CONF}", flush=True)
    print(f"Events: TP={n['TP']} FN={n['FN']} FP={n['FP']} | arms={arms}", flush=True)

    out = {"summary": [], "results": {}}
    for arm in arms:
        rows = []
        for ev in events:
            g = run_gate(ev, arm)
            rows.append({"id": ev.event_id, "label": ev.label, "meta": ev.meta, "gate": g})
            if ev.label == "FN":
                mk = "CATCH" if g.get("triggered") else "MISS "
                print(f"  [{arm}] FN {ev.event_id}: [{mk}] conf={g.get('conf')} scene={g.get('scene')}", flush=True)
        tp = [r for r in rows if r["label"] == "TP"]; fn = [r for r in rows if r["label"] == "FN"]
        fp = [r for r in rows if r["label"] == "FP"]
        tp_c = sum(1 for r in tp if r["gate"].get("triggered"))
        fn_c = sum(1 for r in fn if r["gate"].get("triggered"))
        fp_t = sum(1 for r in fp if r["gate"].get("triggered"))
        errs = sum(1 for r in rows if not r["gate"].get("ok"))
        recall = (tp_c + fn_c) / max(1, len(tp) + len(fn))
        spec = 1 - fp_t / max(1, len(fp))
        score = round((3 * recall + spec) / 4, 4)
        cost = sum(r["gate"].get("cost", 0) or 0 for r in rows)
        s = {"arm": arm, "tp": f"{tp_c}/{len(tp)}", "fn": f"{fn_c}/{len(fn)}",
             "fp_trig": f"{fp_t}/{len(fp)}", "recall": round(recall, 3),
             "spec": round(spec, 3), "score": score, "errors": errs, "cost": round(cost, 5)}
        out["summary"].append(s); out["results"][arm] = rows
        print(f"  [{arm:9s}] recall {tp_c+fn_c}/{len(tp)+len(fn)} (TP {tp_c}/{len(tp)}, FN {fn_c}/{len(fn)}) "
              f"| FP {fp_t}/{len(fp)} spec={spec:.2f} | score={score} err={errs} ${cost:.3f}", flush=True)

    (CAMPAIGN_DIR / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== RANKING ===", flush=True)
    for s in sorted(out["summary"], key=lambda x: x["score"], reverse=True):
        print(f"  {s['arm']:9s} score={s['score']:.3f} recall={s['recall']:.2f} spec={s['spec']:.2f} "
              f"(TP {s['tp']}, FN {s['fn']}, FPtrig {s['fp_trig']})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
