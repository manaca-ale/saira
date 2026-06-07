#!/usr/bin/env python3
"""Campaign 28: FP screen for the V3+B3 gate on esp32_005 (Arruda).

Before porting the esp32_002 V3+B3 recall gate to Arruda (to fix the 2026-06-01
cart-dumping false negative), we must check it does NOT explode false positives on
Arruda's busy street (traffic, pedestrians, passing handcarts).

This runs ONLY Agent-1 (the gate) against Arruda baseline windows (no real
occurrence) for day and night, and counts how many windows the gate would escalate.
Every escalation on a baseline window is a candidate false positive.

Prod-faithful replication (see memory feedback_bench_match_prod_exactly):
- model gemini-2.5-flash-lite (GEMINI_AGENT1_MODEL)
- cascade window ~37 frames / ~3 min, SEQUENCE_SIZE=5 frames sent (first+last+3 mid)
- trigger = new_litter_detected AND confidence_0_100 >= 85 (GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE)
- thinking budget 2048 (matches ~2000 thinking tokens observed in prod gate logs)

Day frames: local export 2026-06-01 08:00-14:11 (dump window 11:24-11:35 excluded).
Night frames: prod sem_ocorrencia 2026-06-01 02:00-04:59 (dark / streetlight).
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

DAY_DIR = Path(r"C:\Users\aleco\Downloads\6bed1ff4-994a-469a-a554-940a7fa75bcc\2026-06-01\sem_ocorrencia")
NIGHT_DIR = CAMPAIGN_DIR / "night_frames"

# Real cart-dumping occurrence on 2026-06-01 — exclude from the day BASELINE so it
# is not counted as an FP (it is a genuine TP, not baseline).
DUMP_START = "11-24-00"
DUMP_END = "11-35-00"

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

# gate sends individual frames (use_mosaic=False); stub cv2 so importing
# detector_gemini does not require OpenCV.
if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.SimpleNamespace()

from worker import _prompts_v3  # noqa: E402
from worker import config as worker_config  # noqa: E402
from worker.detector_gemini import analyze_new_litter_with_gemini  # noqa: E402

PRICE_INPUT_PER_1M_USD = float(os.environ["GEMINI_INPUT_TOKEN_PRICE_PER_1M"])
PRICE_OUTPUT_PER_1M_USD = float(os.environ["GEMINI_OUTPUT_TOKEN_PRICE_PER_1M"])
THINKING_BUDGET = int(os.environ.get("GEMINI_AGENT1_THINKING_BUDGET", "2048"))
TRIGGER_MIN_CONFIDENCE = 85

# Arruda (esp32_005) camera context — feeds the V3 base scene description.
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

# B3 material-carrier recall logic (campaign 19 winner for esp32_002), adapted to the
# Arruda scene (pile against the right-side wall). Same escalation/suppression logic.
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
class Window:
    window_id: str
    period: str
    first_frame: Path
    last_frame: Path
    mid_frames: list[Path]
    metadata: dict = field(default_factory=dict)


def _frame_time(p: Path) -> str:
    # 2026-06-01_HH-MM-SS.jpg -> "HH-MM-SS"
    return p.stem.split("_", 1)[1]


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


def build_windows(frame_dir: Path, period: str, window_size: int,
                  per_period: int | None, exclude_dump: bool) -> list[Window]:
    frames = sorted(frame_dir.glob("2026-06-01_*.jpg"))
    windows: list[Window] = []
    starts = list(range(0, len(frames) - window_size + 1, window_size))
    for start in starts:
        chunk = frames[start:start + window_size]
        if exclude_dump:
            # drop any window that overlaps the real dump occurrence
            if any(DUMP_START <= _frame_time(f) <= DUMP_END for f in chunk):
                continue
        windows.append(Window(
            window_id=f"{period}_{_frame_time(chunk[0])}",
            period=period,
            first_frame=chunk[0],
            last_frame=chunk[-1],
            mid_frames=_sample_mid_frames(chunk),
            metadata={
                "first": chunk[0].name,
                "last": chunk[-1].name,
                "window_size": len(chunk),
            },
        ))
    if per_period is not None and per_period < len(windows):
        step = len(windows) / per_period
        windows = [windows[int(i * step)] for i in range(per_period)]
    return windows


def run_gate(window: Window, gate_mode: str = "v3b3") -> dict:
    # gate_mode: "v3b3" = deploy candidate (V3 + Arruda B3 recall);
    #            "v1"   = current prod gate (vehicle-centric NEW_LITTER_SYSTEM_PROMPT).
    previous = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    previous_budget = worker_config.GEMINI_AGENT1_THINKING_BUDGET
    if gate_mode == "v3b3":
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = GATE_PROMPT_TEXT
        prompt_version = "v3"
    else:
        prompt_version = "current"  # V1 prod gate
    worker_config.GEMINI_AGENT1_THINKING_BUDGET = THINKING_BUDGET
    try:
        rid = f"bench29-{gate_mode}-{window.window_id}-{uuid.uuid4().hex[:4]}"
        t0 = time.monotonic()
        result = analyze_new_litter_with_gemini(
            first_frame=window.first_frame,
            last_frame=window.last_frame,
            camera_context=ARRUDA_CAMERA_CONTEXT,
            request_id=rid,
            prior_window_context=None,
            use_mosaic=False,
            mid_frames=window.mid_frames if window.mid_frames else None,
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
            "input_tokens": usage.input_tokens,
            "total_tokens": usage.total_tokens,
            "latency_ms": result.latency_ms,
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
    parser.add_argument("--window-size", type=int, default=37)
    parser.add_argument("--per-period", type=int, default=40,
                        help="subsample N windows per period (day/night)")
    parser.add_argument("--smoke", action="store_true", help="2 windows per period")
    parser.add_argument("--gate", choices=["v3b3", "v1"], default="v3b3",
                        help="v3b3 = deploy candidate; v1 = current prod control")
    args = parser.parse_args()

    per_period = 2 if args.smoke else args.per_period

    day = build_windows(DAY_DIR, "day", args.window_size, per_period, exclude_dump=True)
    night = build_windows(NIGHT_DIR, "night", args.window_size, per_period, exclude_dump=False)
    windows = day + night

    print(f"Campaign 29 - Arruda (esp32_005) gate FP screen | gate={args.gate}", flush=True)
    print(f"Model: {worker_config.GEMINI_AGENT1_MODEL} | thinking={THINKING_BUDGET} "
          f"| window={args.window_size} frames | trigger conf>={TRIGGER_MIN_CONFIDENCE}", flush=True)
    print(f"Windows: day={len(day)} night={len(night)} total={len(windows)}", flush=True)

    results = []
    for i, w in enumerate(windows, 1):
        gate = run_gate(w, args.gate)
        flag = "  *** TRIGGER (FP) ***" if gate.get("triggered") else ""
        if i == 1 or i % 10 == 0 or i == len(windows) or gate.get("triggered") or not gate.get("ok"):
            err = "" if gate.get("ok") else f" ERR={gate.get('error')}"
            print(f"  [{i}/{len(windows)}] {w.window_id} -> "
                  f"det={gate.get('new_litter_detected')} conf={gate.get('confidence_0_100')} "
                  f"scene={gate.get('scene_type')}{flag}{err}", flush=True)
        results.append({"window_id": w.window_id, "period": w.period,
                        "metadata": w.metadata, "gate": gate})

    def summarize(period: str) -> dict:
        rows = [r for r in results if r["period"] == period]
        ok = [r for r in rows if r["gate"].get("ok")]
        trig = [r for r in rows if r["gate"].get("triggered")]
        return {"period": period, "windows": len(rows), "ok": len(ok),
                "triggered_fp": len(trig),
                "fp_rate": round(len(trig) / len(ok), 4) if ok else None,
                "triggered_ids": [r["window_id"] for r in trig]}

    gate_label = ("V3 + B3 (material-carrier recall, Arruda-adapted)"
                  if args.gate == "v3b3" else "V1 (current prod, vehicle-centric)")
    summary = {
        "camera": "esp32_005 / Arruda / cam_14",
        "gate_mode": args.gate,
        "gate": gate_label,
        "model": worker_config.GEMINI_AGENT1_MODEL,
        "thinking_budget": THINKING_BUDGET,
        "window_size": args.window_size,
        "trigger_min_confidence": TRIGGER_MIN_CONFIDENCE,
        "day": summarize("day"),
        "night": summarize("night"),
        "total_cost_usd": round(sum(r["gate"].get("cost_usd", 0) or 0 for r in results), 6),
    }

    out = CAMPAIGN_DIR / f"results-{args.gate}.json"
    out.write_text(json.dumps({"summary": summary, "results": results},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===", flush=True)
    for p in ("day", "night"):
        s = summary[p]
        print(f"  {p:5s}: {s['triggered_fp']}/{s['ok']} windows triggered "
              f"(FP rate {s['fp_rate']})", flush=True)
        for tid in s["triggered_ids"]:
            ev = next(r["gate"]["evidence_summary"] for r in results if r["window_id"] == tid)
            print(f"         FP {tid}: {ev}", flush=True)
    print(f"  cost: ${summary['total_cost_usd']:.4f}", flush=True)
    print(f"  -> {out.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
