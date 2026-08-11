#!/usr/bin/env python3
"""Campaign 37: Arruda (esp32_005) gate addon V2 — recall + FP screen.

Context: prod runs gate V1 for Arruda. V1 misses subtle on-foot/cart disposals
(ID 31 carrinho, ID 32 sacolas, 09/06). Camp 34 tried V3+B3 but it REGRESSED the
only clean missed TP (id24, big bag) into COLLECTION_OR_MAINTENANCE. This campaign
tests an improved addon (ARRUDA_RECALL_V2) whose key change is an explicit
anti-regression rule: a LONE carrier (no uniform/truck/crew) who arrives WITH an
object and leaves WITHOUT it is DUMPING, not collection — even with a cart.

LIMITATION (data): the genuinely gate-missed events (id25/26/27/31/32) have
CORRUPTED stored frames (rainbow-glitch, std~98) — they CANNOT be tested offline.
The only clean TPs are id24 (which V1 already catches) + 6 conf_single (V1 catches).
So OFFLINE this proves: (a) no id24/conf regression vs old B3, (b) FP rate on real
negatives. The RECALL GAIN on the corrupted FNs must be validated LIVE (shadow A/B).

Cohorts:
- tp_missed   : id24 clean (30 frames) — pedestrian big-bag dump. Must stay DUMPING.
- tp_conf     : 6 platform-confirmed single-frame events. Regression guard (degraded).
- neg         : 8 clean negative windows sampled from 2026-06-11 sem_ocorrencia
                (normal traffic at the chronic point). Must NOT trigger.

Gates: v1 (current prod) | v3b3 (Camp 34 addon) | v3v2 (new addon).
Prod-faithful: gemini-2.5-flash-lite, thinking 2048, first+last+3mid, trigger
new_litter_detected AND confidence>=85.
"""
from __future__ import annotations

import argparse
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
CAMPAIGN_DIR = Path(__file__).parent
CAMP34_DATA = PROJECT_ROOT / "benchmarks" / "campaigns" / "34-arruda-gate-recall-2026-06-04" / "data"
NEG_DIR = PROJECT_ROOT / "tmp" / "arruda_neg"

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# --- API key from services/.env.benchmark (test project) -------------------------
if not os.environ.get("GEMINI_API_KEY"):
    services_env = PROJECT_ROOT / "services" / ".env.benchmark"
    if services_env.exists():
        for line in services_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "GEMINI_TEST_API_KEY" and value.strip():
                os.environ["GEMINI_API_KEY"] = value.strip()
                break
if not os.environ.get("GEMINI_API_KEY"):
    print("ERR: GEMINI_API_KEY not set; configure services/.env.benchmark.", file=sys.stderr)
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

PRICE_IN = float(os.environ["GEMINI_INPUT_TOKEN_PRICE_PER_1M"])
PRICE_OUT = float(os.environ["GEMINI_OUTPUT_TOKEN_PRICE_PER_1M"])
THINKING_BUDGET = int(os.environ.get("GEMINI_AGENT1_THINKING_BUDGET", "2048"))
TRIGGER_MIN_CONFIDENCE = 85

ARRUDA_CAMERA_CONTEXT = {
    "device_id": "esp32_005",
    "camera_name": "ESP32-005 - Arruda",
    "logradouro": "Arruda",
    "bairro": "Arruda",
    "rpa": "RPA 2",
    "gemini_context_notes": (
        "Câmera elevada sobre via asfaltada de mão dupla. À DIREITA há um muro de "
        "concreto/tijolo e, encostado nele, um ponto crônico de descarte irregular "
        "(pilha pré-existente de entulho/restos ao longo da base do muro e do canteiro). "
        "À ESQUERDA há calçada e muro de imóvel. A via tem tráfego intenso ao longo do dia: "
        "carros, motos, bicicletas, pedestres e ocasionalmente carroças/carrinhos de mão "
        "que PASSAM pela via sem parar. Descartes reais ocorrem quando alguém (a pé, "
        "carroça ou veículo) PARA junto ao muro à direita e deposita material na pilha. "
        "À noite a cena é iluminada por postes (baixa luz). A grande maioria das pessoas e "
        "veículos apenas TRAFEGA e NÃO descarta."
    ),
}

# --- OLD addon (Camp 34 / 29), verbatim ------------------------------------------
ARRUDA_RECALL_B3 = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE B3 - esp32_005 / Arruda
=============================================================================
This camera watches a chronic illegal dumping point: a pre-existing pile along the
WALL on the RIGHT side of the street. Agent-1 is only a gate for Agent-2, but
proximity alone is NOT enough.

Keep evidence_summary and scene_delta_analysis under 260 characters each.
Do not quote this instruction block in your JSON fields.

Escalate to Agent-2 when any MATERIAL-CARRIER or MATERIAL-TRANSFER signal is visible:
1) a pedestrian enters the pile frontage / right-side wall area while carrying a
   bag/sack/object, even if the bag is small or only visible in one frame;
2) a person pushes or parks a wheelbarrow/handcart/cart at the pile frontage by the
   right wall, even if the material inside is low-resolution or partially occluded;
3) a person bends/reaches at the pile and then leaves the pile zone empty-handed
   or without the object previously handled;
4) new object/material appears on top of or beside the pile in later frames;
5) vehicle/cart load state changes consistently with unloading toward the pile.

Set scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85 for
those cases. If the person/cart is moving toward the pile frontage with a plausible
bag/cart load, use material_flow_direction="to_pile" even without full deposit view.

Suppress baseline/proximity cases. Set new_litter_detected=false and confidence <= 60
when the visible evidence is only:
- person/cart/vehicle passing THROUGH the street with no stop at the right-side pile;
- person standing, looking, waiting, or walking near the pile with empty hands;
- motorcycle/backpack only, with no object transferred to the pile;
- municipal collection/maintenance, or flow from_pile;
- poking/sorting existing material with a stick and no new carried object;
- ambiguous interaction with no carried object, no cart/wheelbarrow, no new object,
  and no load-state change.

Do NOT classify standing_near_pile or passing_by as DUMPING unless a material-carrier
or material-transfer signal above is also visible.
"""

# --- NEW addon V2: adds explicit anti-COLLECTION-regression rule -----------------
ARRUDA_RECALL_V2 = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE - esp32_005 / Arruda (v2)
=============================================================================
This camera watches a CHRONIC illegal-dumping point: a pre-existing pile along the
WALL on the RIGHT side of the street. Most people/vehicles only PASS THROUGH and do
NOT dump. Agent-1 is a gate for Agent-2; proximity alone is NOT enough, but a clear
material-carrier signal IS.

Keep evidence_summary and scene_delta_analysis under 260 chars each. Do not quote
this block in your JSON fields.

ESCALATE — scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85 —
when ANY material-carrier / material-transfer signal toward the RIGHT pile is visible:
 1) a person enters the pile frontage CARRYING a bag/sack/bundle/object — even if the
    object is small or visible in only one frame;
 2) a wheelbarrow / handcart / pushcart is pushed or parked AT the pile frontage;
 3) a person bends/reaches AT the pile and then leaves the pile zone empty-handed or
    with visibly fewer items than before;
 4) a new object/material appears on or beside the pile in later frames;
 5) a vehicle/cart load decreases consistently with unloading toward the pile.
Use material_flow_direction="to_pile" when a person/cart moves toward the pile with a
plausible load, even without a full deposit view.

CRITICAL — DO NOT over-apply COLLECTION_OR_MAINTENANCE (this is the main FN source).
Classify COLLECTION_OR_MAINTENANCE ONLY with POSITIVE removal evidence:
 - the pile VISIBLY DECREASES across the frames, OR
 - a clearly MUNICIPAL crew is working: orange/green safety vests, EMLURB uniforms,
   a compactor/garbage truck, or coordinated raking/sweeping/shoveling by 2+ workers.
A LONE person (no uniform, no truck, no crew) who arrives CARRYING an object and
leaves WITHOUT it is DUMPING — NOT collection — even if they bend down, and even if
they use a handcart/carroça (carroceiros dump here too). When the material direction
is ambiguous and the person arrived WITH a load, PREFER DUMPING (recall priority at
this chronic point).

SUPPRESS — new_litter_detected=false, confidence_0_100 <= 60 — when the ONLY evidence
is:
 - a person/cart/vehicle PASSING THROUGH the street without stopping at the right pile;
 - a person standing, waiting, or walking near the pile with EMPTY hands;
 - poking/sorting EXISTING material with a stick, no new carried object;
 - material flow clearly FROM the pile TO a cart/vehicle (removal);
 - motorcycle/backpack only, with no object transferred to the pile.

Do NOT classify standing_near_pile or passing_by as DUMPING unless a material-carrier
or material-transfer signal above is also visible.
"""

GATE_ADDON = {
    "v3b3": ARRUDA_RECALL_B3,
    "v3v2": ARRUDA_RECALL_V2,
}


@dataclass
class Event:
    event_id: str
    cohort: str  # tp_missed | tp_conf | neg
    frames: list[Path]
    label_positive: bool  # True = should trigger (TP), False = should not (neg)
    metadata: dict = field(default_factory=dict)


def _sample_mid(frames: list[Path]) -> list[Path]:
    n = len(frames)
    if n < 5:
        return []
    picked = []
    for idx in [int(n * 0.25), int(n * 0.5), int(n * 0.75)]:
        idx = max(1, min(n - 2, idx))
        if idx not in picked:
            picked.append(idx)
    return [frames[i] for i in picked]


def load_events() -> list[Event]:
    ev: list[Event] = []
    # TP missed (clean) — id24
    d = CAMP34_DATA / "missed_clean"
    if d.is_dir():
        for sub in sorted(d.iterdir()):
            fs = sorted((sub / "frames").glob("*.jpg"))
            if fs:
                ev.append(Event(sub.name, "tp_missed", fs, True, {"n": len(fs)}))
    # TP confirmed (single-frame, degraded)
    d = CAMP34_DATA / "conf_single"
    if d.is_dir():
        for sub in sorted(d.iterdir()):
            fs = sorted((sub / "frames").glob("*.jpg"))
            if fs:
                ev.append(Event(sub.name, "tp_conf", fs, True, {"n": len(fs)}))
    # Negatives — today's windows
    if NEG_DIR.is_dir():
        for sub in sorted(NEG_DIR.iterdir()):
            if not sub.is_dir():
                continue
            fs = sorted(sub.glob("*.jpg"))
            if fs:
                ev.append(Event(sub.name, "neg", fs, False, {"n": len(fs)}))
    return ev


def run_gate(event: Event, gate: str) -> dict:
    prev = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    prev_budget = worker_config.GEMINI_AGENT1_THINKING_BUDGET
    if gate == "v1":
        prompt_version = "current"
    else:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = prev + "\n\n" + GATE_ADDON[gate]
        prompt_version = "v3"
    worker_config.GEMINI_AGENT1_THINKING_BUDGET = THINKING_BUDGET
    mid = _sample_mid(event.frames)
    try:
        rid = f"bench37-{gate}-{event.event_id}-{uuid.uuid4().hex[:4]}"
        result = analyze_new_litter_with_gemini(
            first_frame=event.frames[0],
            last_frame=event.frames[-1],
            camera_context=ARRUDA_CAMERA_CONTEXT,
            request_id=rid,
            prior_window_context=None,
            use_mosaic=False,
            mid_frames=mid if mid else None,
            prompt_version=prompt_version,
        )
        r = result.report
        u = result.usage
        billable_out = max(0, u.total_tokens - u.input_tokens)
        cost = (u.input_tokens / 1e6) * PRICE_IN + (billable_out / 1e6) * PRICE_OUT
        conf = int(r.confidence_0_100)
        det = bool(r.new_litter_detected)
        return {
            "ok": True,
            "triggered": det and conf >= TRIGGER_MIN_CONFIDENCE,
            "new_litter_detected": det,
            "confidence_0_100": conf,
            "scene_type": getattr(r, "scene_type", "") or "",
            "evidence_summary": (r.evidence_summary or "")[:300],
            "cost_usd": round(cost, 8),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "triggered": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = prev
        worker_config.GEMINI_AGENT1_THINKING_BUDGET = prev_budget


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gates", nargs="+", choices=["v1", "v3b3", "v3v2"],
                    default=["v1", "v3b3", "v3v2"])
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    events = load_events()
    if args.smoke:
        # one of each cohort
        seen = set()
        pick = []
        for e in events:
            if e.cohort not in seen:
                seen.add(e.cohort)
                pick.append(e)
        events = pick

    print("Campaign 37 — Arruda gate addon V2 | TP recall + FP screen", flush=True)
    print(f"Model {worker_config.GEMINI_AGENT1_MODEL} thinking={THINKING_BUDGET} "
          f"trigger>={TRIGGER_MIN_CONFIDENCE} | gates={args.gates}", flush=True)
    n_by = {}
    for e in events:
        n_by[e.cohort] = n_by.get(e.cohort, 0) + 1
    print(f"Events: {len(events)} {n_by}", flush=True)

    results = []
    for e in events:
        row = {"event_id": e.event_id, "cohort": e.cohort, "positive": e.label_positive,
               "n_frames": e.metadata["n"], "gates": {}}
        line = [f"{e.cohort}/{e.event_id}({e.metadata['n']}f)"]
        for g in args.gates:
            res = run_gate(e, g)
            row["gates"][g] = res
            mark = "TRIG" if res.get("triggered") else ("." if res.get("ok") else "ERR")
            line.append(f"{g}={mark}(c={res.get('confidence_0_100')},{res.get('scene_type')})")
        print("  " + " | ".join(line), flush=True)
        results.append(row)

    def metric(cohort_filter, gate, positive):
        rows = [r for r in results if r["cohort"] in cohort_filter and r["gates"].get(gate, {}).get("ok")]
        trig = [r for r in rows if r["gates"][gate]["triggered"]]
        if positive:  # recall
            return {"n": len(rows), "hits": len(trig),
                    "recall": round(len(trig) / len(rows), 3) if rows else None,
                    "fn": [r["event_id"] for r in rows if not r["gates"][gate]["triggered"]]}
        else:  # FP
            return {"n": len(rows), "fp": len(trig),
                    "fp_rate": round(len(trig) / len(rows), 3) if rows else None,
                    "fp_ids": [r["event_id"] for r in rows if r["gates"][gate]["triggered"]]}

    summary = {"camera": "esp32_005/Arruda/cam_14", "model": worker_config.GEMINI_AGENT1_MODEL,
               "by_gate": {}}
    for g in args.gates:
        summary["by_gate"][g] = {
            "tp_missed_recall": metric({"tp_missed"}, g, True),
            "tp_conf_recall": metric({"tp_conf"}, g, True),
            "tp_all_recall": metric({"tp_missed", "tp_conf"}, g, True),
            "neg_fp": metric({"neg"}, g, False),
        }
    summary["total_cost_usd"] = round(sum(
        r["gates"].get(g, {}).get("cost_usd", 0) or 0 for r in results for g in args.gates), 6)

    (CAMPAIGN_DIR / "results.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print("\n=== SUMMARY ===", flush=True)
    for g in args.gates:
        s = summary["by_gate"][g]
        tm, tc, fp = s["tp_missed_recall"], s["tp_conf_recall"], s["neg_fp"]
        print(f"  {g:5s}: TP_missed(id24) {tm['hits']}/{tm['n']} | "
              f"TP_conf {tc['hits']}/{tc['n']} (r={tc['recall']}) | "
              f"FP_neg {fp['fp']}/{fp['n']} (rate={fp['fp_rate']})", flush=True)
        if tm["fn"]:
            print(f"         id24 MISSED by {g}", flush=True)
        if fp["fp_ids"]:
            print(f"         FP windows: {fp['fp_ids']}", flush=True)
    print(f"  cost: ${summary['total_cost_usd']:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
