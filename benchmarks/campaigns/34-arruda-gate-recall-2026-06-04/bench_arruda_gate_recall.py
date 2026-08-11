#!/usr/bin/env python3
"""Campaign 34: GATE RECALL for esp32_005 (Arruda) — V1 vs V3+B3.

Phase-5 question (after the BGSUB frozen-baseline fix unblocks the gate): does the
current prod gate V1 still MISS the real on-foot/cart/poda disposals, and does the
candidate V3+B3 (material-carrier recall) CATCH them — without regressing the
platform-confirmed occurrences?

Test set (all real TP events; trigger = recall hit, no-trigger = FN):
- missed/   : the 4 suppressed disposals of 2026-06-02 (IDs 24-27) — mini-windows
              (5-10 labeled frames each, from data/datasets/official/cam_arruda/tp).
- conf_single/: the 6 platform-CONFIRMADO detections (cam_14). Only the single
              representative frame survives (esp32_005 frame history is ephemeral),
              so these are a DEGRADED single-frame check: the gate's cross-frame
              delta/flow logic is blind, which DEPRESSES recall for BOTH gates
              equally — read as indicative, not prod-faithful. Weight conclusions on
              the 4 missed (proper mini-windows).

Prod-faithful gate settings (see memory feedback_bench_match_prod_exactly + Camp 29):
- model gemini-2.5-flash-lite, thinking 2048, SEQUENCE first+last+3mid frames,
  trigger = new_litter_detected AND confidence_0_100 >= 85.
Reuses the exact ARRUDA context + B3 recall block from Campaign 29.
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
DATA_DIR = CAMPAIGN_DIR / "data"

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value.startswith("<"):
            continue
        os.environ.setdefault(key.strip(), value)


_load_env_file(CAMPAIGN_DIR / ".env.benchmark")

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

PRICE_INPUT_PER_1M_USD = float(os.environ["GEMINI_INPUT_TOKEN_PRICE_PER_1M"])
PRICE_OUTPUT_PER_1M_USD = float(os.environ["GEMINI_OUTPUT_TOKEN_PRICE_PER_1M"])
THINKING_BUDGET = int(os.environ.get("GEMINI_AGENT1_THINKING_BUDGET", "2048"))
TRIGGER_MIN_CONFIDENCE = 85

# --- Arruda context + B3 recall block: copied verbatim from Campaign 29 ----------
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

GATE_PROMPT_TEXT = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 + "\n\n" + ARRUDA_RECALL_B3


@dataclass
class Event:
    event_id: str
    cohort: str  # "missed" | "conf_single"
    frames: list[Path]
    metadata: dict = field(default_factory=dict)


def _sample_mid_frames(frames: list[Path]) -> list[Path]:
    n = len(frames)
    if n < 5:
        return []
    picked: list[int] = []
    for idx in [int(n * 0.25), int(n * 0.5), int(n * 0.75)]:
        idx = max(1, min(n - 2, idx))
        if idx not in picked:
            picked.append(idx)
    return [frames[i] for i in picked]


def load_events() -> list[Event]:
    events: list[Event] = []
    for cohort in ("missed_clean", "conf_single"):
        cohort_dir = DATA_DIR / cohort
        if not cohort_dir.is_dir():
            continue
        for ev_dir in sorted(cohort_dir.iterdir()):
            frames = sorted((ev_dir / "frames").glob("*.jpg"))
            if not frames:
                continue
            events.append(Event(
                event_id=ev_dir.name,
                cohort=cohort,
                frames=frames,
                metadata={"n_frames": len(frames),
                          "first": frames[0].name, "last": frames[-1].name},
            ))
    return events


def run_gate(event: Event, gate_mode: str) -> dict:
    # gate_mode: "v3b3" = deploy candidate (V3 + Arruda B3); "v1" = current prod gate.
    previous = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    previous_budget = worker_config.GEMINI_AGENT1_THINKING_BUDGET
    if gate_mode == "v3b3":
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = GATE_PROMPT_TEXT
        prompt_version = "v3"
    else:
        prompt_version = "current"  # V1 prod gate
    worker_config.GEMINI_AGENT1_THINKING_BUDGET = THINKING_BUDGET
    mid = _sample_mid_frames(event.frames)
    try:
        rid = f"bench34-{gate_mode}-{event.event_id}-{uuid.uuid4().hex[:4]}"
        t0 = time.monotonic()
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
        wall_ms = int((time.monotonic() - t0) * 1000)
        report = result.report
        usage = result.usage
        billable_output = max(0, usage.total_tokens - usage.input_tokens)
        cost = ((usage.input_tokens / 1e6) * PRICE_INPUT_PER_1M_USD
                + (billable_output / 1e6) * PRICE_OUTPUT_PER_1M_USD)
        conf = int(report.confidence_0_100)
        detected = bool(report.new_litter_detected)
        return {
            "ok": True,
            "new_litter_detected": detected,
            "confidence_0_100": conf,
            "triggered": detected and conf >= TRIGGER_MIN_CONFIDENCE,
            "scene_type": getattr(report, "scene_type", "") or "",
            "person_position_signature": getattr(report, "person_position_signature", None),
            "material_flow_direction": getattr(report, "material_flow_direction", None),
            "evidence_summary": (report.evidence_summary or "")[:400],
            "scene_delta_analysis": (getattr(report, "scene_delta_analysis", "") or "")[:400],
            "n_sent_frames": 2 + len(mid),
            "input_tokens": usage.input_tokens,
            "total_tokens": usage.total_tokens,
            "wall_ms": wall_ms,
            "cost_usd": round(cost, 8),
            "model": result.model,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "triggered": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = previous
        worker_config.GEMINI_AGENT1_THINKING_BUDGET = previous_budget


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gates", nargs="+", choices=["v1", "v3b3"], default=["v1", "v3b3"])
    parser.add_argument("--smoke", action="store_true", help="run only the first event")
    args = parser.parse_args()

    events = load_events()
    if args.smoke:
        events = events[:1]

    print("Campaign 34 — Arruda (esp32_005) GATE RECALL | V1 vs V3+B3", flush=True)
    print(f"Model: {worker_config.GEMINI_AGENT1_MODEL} | thinking={THINKING_BUDGET} "
          f"| trigger conf>={TRIGGER_MIN_CONFIDENCE}", flush=True)
    print(f"Events: {len(events)} "
          f"(missed={sum(e.cohort=='missed' for e in events)}, "
          f"conf_single={sum(e.cohort=='conf_single' for e in events)})", flush=True)

    results = []
    for e in events:
        row = {"event_id": e.event_id, "cohort": e.cohort, "metadata": e.metadata, "gates": {}}
        line = [f"{e.cohort}/{e.event_id} ({e.metadata['n_frames']}f)"]
        for g in args.gates:
            gate = run_gate(e, g)
            row["gates"][g] = gate
            mark = "HIT" if gate.get("triggered") else ("FN " if gate.get("ok") else "ERR")
            line.append(f"{g}={mark}(d={gate.get('new_litter_detected')},c={gate.get('confidence_0_100')},{gate.get('scene_type')})")
        print("  " + " | ".join(line), flush=True)
        results.append(row)

    def recall(cohort: str | None, gate: str) -> dict:
        rows = [r for r in results if cohort is None or r["cohort"] == cohort]
        ok = [r for r in rows if r["gates"].get(gate, {}).get("ok")]
        hit = [r for r in ok if r["gates"][gate].get("triggered")]
        return {"n": len(ok), "hits": len(hit),
                "recall": round(len(hit) / len(ok), 3) if ok else None,
                "fn_ids": [r["event_id"] for r in ok if not r["gates"][gate].get("triggered")]}

    summary = {
        "camera": "esp32_005 / Arruda / cam_14",
        "model": worker_config.GEMINI_AGENT1_MODEL,
        "thinking_budget": THINKING_BUDGET,
        "trigger_min_confidence": TRIGGER_MIN_CONFIDENCE,
        "recall": {g: {"missed": recall("missed", g),
                       "conf_single": recall("conf_single", g),
                       "all": recall(None, g)} for g in args.gates},
        "total_cost_usd": round(sum(
            r["gates"].get(g, {}).get("cost_usd", 0) or 0
            for r in results for g in args.gates), 6),
    }

    out = CAMPAIGN_DIR / "results.json"
    out.write_text(json.dumps({"summary": summary, "results": results},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== RECALL SUMMARY ===", flush=True)
    for g in args.gates:
        s = summary["recall"][g]
        print(f"  {g:5s}: missed {s['missed']['hits']}/{s['missed']['n']} "
              f"(recall {s['missed']['recall']})  |  "
              f"conf_single {s['conf_single']['hits']}/{s['conf_single']['n']} "
              f"(recall {s['conf_single']['recall']})  |  "
              f"ALL {s['all']['hits']}/{s['all']['n']}", flush=True)
        if s["missed"]["fn_ids"]:
            print(f"         missed FN: {s['missed']['fn_ids']}", flush=True)
    print(f"  cost: ${summary['total_cost_usd']:.4f}", flush=True)
    print(f"  -> {out.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
