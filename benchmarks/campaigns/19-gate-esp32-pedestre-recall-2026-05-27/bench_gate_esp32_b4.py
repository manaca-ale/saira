#!/usr/bin/env python3
"""Campaign 18: gate-only A/B for cam_mangabeira.

Compares:
- A_v3: production V3 prompt/schema/gates.
- B_v3_esp32_recall: V3 plus a camera-specific recall block for esp32_002.

This benchmark intentionally runs only Agent-1. The question is whether the new
prompt escalates more real TP windows without increasing FP/baseline triggers too
much. Agent-2 quality is out of scope for this campaign.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import uuid
import types
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(r"c:\saira")
WORKER_SRC = PROJECT_ROOT / "services" / "yolo-worker-vm" / "src"
DATASET_ROOT = PROJECT_ROOT / "data" / "datasets" / "official"
CAMPAIGN_DIR = Path(__file__).parent

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

# The gate benchmark sends individual frames (`use_mosaic=False`), but importing
# detector_gemini imports worker.mosaic, which imports cv2. Keep this runner
# self-contained on machines without OpenCV.
if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.SimpleNamespace()

from worker import _prompts_v3  # noqa: E402
from worker import config as worker_config  # noqa: E402
from worker.detector_gemini import analyze_new_litter_with_gemini  # noqa: E402

PRICE_INPUT_PER_1M_USD = float(os.environ["GEMINI_INPUT_TOKEN_PRICE_PER_1M"])
PRICE_OUTPUT_PER_1M_USD = float(os.environ["GEMINI_OUTPUT_TOKEN_PRICE_PER_1M"])
THINKING_BUDGET = int(os.environ.get("GEMINI_AGENT1_THINKING_BUDGET", "2048"))

CAMERA_CONTEXT = {
    "cam_mangabeira": {
        "camera_name": "ESP32-002 - Mangabeira",
        "logradouro": "Av. Prof. José dos Anjos, 3254",
        "bairro": "Mangabeira",
        "rpa": "RPA 3",
        "gemini_context_notes": (
            "Câmera em vista frontal/lateral sobre lixeira pública informal na esquina, "
            "com calçada à direita e via à esquerda. Descartes acontecem ao longo do dia "
            "por moradores a pé (1-2 sacos), pessoas com carrinho de mão, e ocasionalmente "
            "funcionários uniformizados de obras/construtoras. Coleta da prefeitura passa "
            "13h-15h em caminhão compactador EMLURB com rear-loading hopper. Cena tem "
            "tráfego intenso de pedestres na calçada que NÃO param para descartar."
        ),
    },
}

ESP32_RECALL_BLOCK = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE - esp32_002 / Av. Prof. José dos Anjos
=============================================================================
This camera watches a chronic illegal dumping point with a large pre-existing pile.
For this camera, Agent-1 is NOT the final accusation step; it is only a cheap gate
that decides whether Agent-2 should inspect the full sequence.

Escalate ambiguous pile interactions to Agent-2. If the scene contains BOTH:
1) a person staying near or entering the pile area across frames, bending/reaching,
   handling/carrying a bag/debris/object, or otherwise interacting with the pile;
AND at least one of:
2a) a new bright/white/large object appears on top of the existing pile in any later frame,
2b) the person is seen near the pile before/after such object appears,
2c) material movement direction is ambiguous but close to the pile,
THEN set scene_type="DUMPING", new_litter_detected=true, confidence_0_100 at least 85,
and explain this as "suspect escalation to Agent-2".

Do NOT escalate if the person is clearly only passing by, clearly collecting/removing
material from the pile, or municipal collection/maintenance is visible.
For esp32_002, absence of visible total pile growth is not enough to block escalation
when a new object on the pile or ambiguous person-pile interaction is visible.
"""

ESP32_RECALL_BLOCK_B2 = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE B2 - esp32_002 / Av. Prof. José dos Anjos
=============================================================================
This camera watches a chronic illegal dumping point with a large pre-existing pile.
Agent-1 is only a gate for Agent-2, but proximity alone is NOT enough.

Keep evidence_summary and scene_delta_analysis under 280 characters each.
Do not quote this instruction block in your JSON fields.

Escalate to Agent-2 only when at least one MATERIAL-TRANSFER signal is visible:
1) a person/cart/wheelbarrow arrives at or enters the pile zone carrying/holding
   a bag, debris, branches, panel, sack, bucket, or other disposable material;
2) the person bends/reaches at the pile and then leaves the pile zone empty-handed
   or without the object previously being handled;
3) a new object/material appears on top of or beside the pile in later frames;
4) a wheelbarrow/cart/truck/handcart is positioned at the pile with material flow
   toward the pile, or with load state changing consistently with unloading.

Set scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85 only
for those material-transfer cases.

Suppress baseline/proximity cases. Set new_litter_detected=false and confidence <= 60
when the visible evidence is only:
- a person standing, looking, walking, or waiting near the pile;
- a person passing by with no stop and no material transfer;
- a person poking/sorting/collecting from the pile, or flow is from_pile;
- motorcycle/backpack presence with no object transferred to the pile;
- ambiguous pile interaction with no carried object, no new object, and no load change.

Do NOT classify standing_near_pile as DUMPING unless one material-transfer signal
above is also visible. If the case is suspicious but lacks material transfer, keep
new_litter_detected=false and mention "insufficient transfer evidence".
"""

ESP32_RECALL_BLOCK_B3 = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE B3 - esp32_002 / Av. Prof. José dos Anjos
=============================================================================
This camera watches a chronic illegal dumping point with a large pre-existing pile.
Agent-1 is only a gate for Agent-2, but proximity alone is NOT enough.

Keep evidence_summary and scene_delta_analysis under 260 characters each.
Do not quote this instruction block in your JSON fields.

Escalate to Agent-2 when any MATERIAL-CARRIER or MATERIAL-TRANSFER signal is visible:
1) a pedestrian enters the pile frontage or sidewalk beside the pile while carrying
   a bag/sack/object, even if the bag is small or only visible in one frame;
2) a person pushes or parks a wheelbarrow/handcart/cart at the pile frontage, even
   if the material inside is low-resolution or partially occluded;
3) a person bends/reaches at the pile and then leaves the pile zone empty-handed
   or without the object previously handled;
4) new object/material appears on top of or beside the pile in later frames;
5) vehicle/cart load state changes consistently with unloading toward the pile.

Set scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85 for
those cases. If the person/cart is moving toward the pile frontage with a plausible
bag/cart load, use material_flow_direction="to_pile" even without full deposit view.

Suppress baseline/proximity cases. Set new_litter_detected=false and confidence <= 60
when the visible evidence is only:
- person standing, looking, waiting, or walking near the pile with empty hands;
- person passing by with no carried object/cart and no stop at the pile frontage;
- motorcycle/backpack only, with no object transferred to the pile;
- municipal collection/maintenance, or flow from_pile;
- poking/sorting existing material with a stick and no new carried object;
- ambiguous interaction with no carried object, no cart/wheelbarrow, no new object,
  and no load-state change.

Do NOT classify standing_near_pile as DUMPING unless a material-carrier or
material-transfer signal above is also visible.
"""

ESP32_RECALL_BLOCK_B4 = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE B4 - esp32_002 / Av. Prof. José dos Anjos
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
"""

ESP32_RECALL_BLOCK_B5 = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE B5 - esp32_002 / Av. Prof. José dos Anjos (HIGH-RECALL)
=============================================================================
This camera watches a chronic illegal dumping point. Agent-1 is ONLY a cheap gate;
Agent-2 makes the final decision and filters false alarms. For THIS camera the priority
is RECALL: WHEN IN DOUBT, ESCALATE. A missed real dump is worse than an extra Agent-2 call.

Keep evidence_summary and scene_delta_analysis under 260 characters each.
Do not quote this instruction block in your JSON fields.

ESCALATE (scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85) when
ANY of the following is visible. Do NOT require a clean carry-then-empty-hands transition,
and do NOT require visible pile growth:
1) a person bends, squats, crouches, kneels, or reaches DOWN toward the pile or the ground
   in the pile zone;
2) a person carries, holds, drags, or handles ANY object, bag, sack, box, or item near the
   pile frontage — even briefly or in a single frame;
3) ONE OR MORE people HANDLE, DISMANTLE, LIFT, DRAG, or PLACE a bulky item (furniture,
   mattress, appliance, TV, monitor, mirror, panel, wood, scrap metal, construction debris)
   near the pile — ESCALATE EVEN IF IT LOOKS LIKE THEY MIGHT BE REMOVING/SALVAGING IT.
   Deposit-vs-removal is Agent-2's job to decide, NOT yours;
4) a wheelbarrow, handcart, cart, or truck is at or near the pile frontage in ANY frame;
5) a new object appears on/beside the pile, OR material_flow_direction is to_pile OR
   ambiguous, OR you are unsure of the direction.

If a person is interacting with the pile, or carrying/handling anything near it, and you
are unsure → set new_litter_detected=true. Reserve new_litter_detected=false for clearly
NON-interacting scenes.

Suppress (new_litter_detected=false, confidence <= 50) ONLY when:
- the scene is empty (no person/vehicle/cart visible) OR shows only animals, rain, or
  shadow/lighting changes;
- people/vehicles merely pass THROUGH far from the pile, with no stop and nothing handled;
- an EMLURB compactor truck (large garbage truck with rear-loading hopper) is clearly
  performing municipal collection (workers loading FROM ground TO the hopper).

Everything else that involves a person AT or NEAR the pile → ESCALATE.
"""


@dataclass
class Window:
    window_id: str
    source: str
    camera: str
    category: str
    first_frame: Path
    last_frame: Path
    mid_frames: list[Path]
    is_positive: bool
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


def build_windows_from_manifest() -> list[Window]:
    windows: list[Window] = []
    with (DATASET_ROOT / "manifest.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("camera") != "cam_mangabeira":
                continue
            if row.get("category") not in {"tp", "fp"}:
                continue
            try:
                frame_count = int(row.get("frame_count") or 0)
            except ValueError:
                continue
            if frame_count < 2:
                continue
            frames_dir = DATASET_ROOT / row["local_path"] / "frames"
            frames = sorted(frames_dir.glob("*.jpg"))
            if len(frames) < 2:
                continue
            category = row["category"]
            windows.append(Window(
                window_id=row["event_id"],
                source="event",
                camera=row["camera"],
                category=category,
                first_frame=frames[0],
                last_frame=frames[-1],
                mid_frames=_sample_mid_frames(frames),
                is_positive=category == "tp",
                metadata={
                    "datetime": row.get("datetime"),
                    "device_id": row.get("device_id"),
                    "tipo_residuo": row.get("tipo_residuo"),
                    "volumetria": row.get("volumetria"),
                    "justificativa": row.get("justificativa"),
                    "frame_count": frame_count,
                    "classificacao": row.get("classificacao"),
                    "local_path": row.get("local_path"),
                },
            ))
    return windows


def build_baseline_windows(window_size: int = 12, per_period: int | None = None) -> list[Window]:
    windows: list[Window] = []
    for period in ("day", "night"):
        period_dir = DATASET_ROOT / "cam_mangabeira" / "baseline" / period
        frames = sorted(period_dir.glob("*.jpg"))
        starts = list(range(0, len(frames) - window_size + 1, window_size))
        if per_period is not None and per_period < len(starts):
            step = len(starts) / per_period
            starts = [starts[int(i * step)] for i in range(per_period)]
        for start in starts:
            chunk = frames[start:start + window_size]
            windows.append(Window(
                window_id=f"baseline_cam_mangabeira_{period}_{start // window_size:03d}",
                source="baseline",
                camera="cam_mangabeira",
                category=f"baseline_{period}",
                first_frame=chunk[0],
                last_frame=chunk[-1],
                mid_frames=_sample_mid_frames(chunk),
                is_positive=False,
                metadata={
                    "period": period,
                    "first_frame_name": chunk[0].name,
                    "last_frame_name": chunk[-1].name,
                    "window_size": window_size,
                },
            ))
    return windows


def _serialize_gate_result(result, window: Window, wall_ms: int, prompt_label: str) -> dict:
    report = result.report
    usage = result.usage
    billable_output = max(0, usage.total_tokens - usage.input_tokens)
    thinking_tokens = max(0, billable_output - usage.output_tokens)
    cost = (
        (usage.input_tokens / 1_000_000.0) * PRICE_INPUT_PER_1M_USD
        + (billable_output / 1_000_000.0) * PRICE_OUTPUT_PER_1M_USD
    )
    return {
        "ok": True,
        "prompt_version": "v3",
        "prompt_label": prompt_label,
        "thinking_budget": THINKING_BUDGET,
        "n_frames_sent": 2 + len(window.mid_frames),
        "confidence_0_100": int(report.confidence_0_100),
        "new_litter_detected": bool(report.new_litter_detected),
        "scene_type": getattr(report, "scene_type", "") or "",
        "waste_type": report.waste_type,
        "vehicle_stopped": bool(getattr(report, "vehicle_stopped", False)),
        "person_handling_material": bool(getattr(report, "person_handling_material", False)),
        "new_ground_material": bool(getattr(report, "new_ground_material", False)),
        "material_flow_direction": getattr(report, "material_flow_direction", None),
        "pile_volume_change": getattr(report, "pile_volume_change", None),
        "municipal_equipment_present": getattr(report, "municipal_equipment_present", None),
        "person_position_signature": getattr(report, "person_position_signature", None),
        "is_maintenance": bool(getattr(result, "is_maintenance", False)),
        "evidence_summary": (report.evidence_summary or "")[:500],
        "scene_delta_analysis": (getattr(report, "scene_delta_analysis", "") or "")[:500],
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "thinking_tokens": thinking_tokens,
        "billable_output_tokens": billable_output,
        "total_tokens": usage.total_tokens,
        "latency_ms": result.latency_ms,
        "wall_ms": wall_ms,
        "cost_usd": round(cost, 8),
        "model": result.model,
    }


def run_gate_call(window: Window, prompt_label: str, prompt_text: str | None,
                  prompt_version: str = "v3") -> dict:
    previous_prompt = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    previous_budget = worker_config.GEMINI_AGENT1_THINKING_BUDGET
    # Only the v3 arms patch the V3 system prompt; the V1 arm (A_v1) uses the
    # unmodified production NEW_LITTER_SYSTEM_PROMPT via prompt_version="current".
    if prompt_version == "v3" and prompt_text:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = prompt_text
    worker_config.GEMINI_AGENT1_THINKING_BUDGET = THINKING_BUDGET
    try:
        request_id = f"bench19-{window.window_id[:8]}-{prompt_label}-{uuid.uuid4().hex[:4]}"
        t0 = time.monotonic()
        result = analyze_new_litter_with_gemini(
            first_frame=window.first_frame,
            last_frame=window.last_frame,
            camera_context=CAMERA_CONTEXT[window.camera],
            request_id=request_id,
            prior_window_context=None,
            use_mosaic=False,
            mid_frames=window.mid_frames if window.mid_frames else None,
            prompt_version=prompt_version,
        )
        wall_ms = int((time.monotonic() - t0) * 1000)
        gate = _serialize_gate_result(result, window, wall_ms, prompt_label)
        gate["prompt_version"] = prompt_version
        return gate
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "prompt_version": prompt_version,
            "prompt_label": prompt_label,
            "thinking_budget": THINKING_BUDGET,
            "n_frames_sent": 2 + len(window.mid_frames),
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = previous_prompt
        worker_config.GEMINI_AGENT1_THINKING_BUDGET = previous_budget


def result_entry(window: Window, gate: dict) -> dict:
    triggered = bool(gate.get("new_litter_detected"))
    return {
        "event": window.window_id,
        "ground_truth": "TP" if window.category == "tp" else ("FP" if window.category == "fp" else "BASELINE"),
        "source": window.source,
        "camera": window.camera,
        "category": window.category,
        "metadata": window.metadata,
        "gate": gate,
        "triggered": triggered,
        "detail": None,
        "total_cost_usd": gate.get("cost_usd", 0.0) or 0.0,
    }


ARM_SPECS = {
    "A_v1": {
        "description": "V1 production gate (NEW_LITTER_SYSTEM_PROMPT) — current prod baseline",
        "prompt_label": "v1_current",
        "prompt_version": "current",
        "prompt_text": None,
    },
    "C_v3_esp32_recall_b2": {
        "description": "V3 + recall mode esp32_002 B2 (material-transfer required) — develop atual",
        "prompt_label": "v3_esp32_recall_b2",
        "prompt_version": "v3",
        "prompt_text": _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 + "\n\n" + ESP32_RECALL_BLOCK_B2,
    },
    "D_v3_esp32_recall_b3": {
        "description": "V3 + recall mode esp32_002 B3 (material-carrier recall)",
        "prompt_label": "v3_esp32_recall_b3",
        "prompt_version": "v3",
        "prompt_text": _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 + "\n\n" + ESP32_RECALL_BLOCK_B3,
    },
    "F_v3_esp32_recall_b4": {
        "description": "V3 + recall mode esp32_002 B4 (bulky/dismantling + stationary cart, baseline-safe)",
        "prompt_label": "v3_esp32_recall_b4",
        "prompt_version": "v3",
        "prompt_text": _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 + "\n\n" + ESP32_RECALL_BLOCK_B4,
    },
    "G_v3_esp32_recall_b5": {
        "description": "V3 + recall mode esp32_002 B5 (HIGH-RECALL: escala em qualquer interação pessoa-pilha, incl. ambíguo depositar-vs-remover)",
        "prompt_label": "v3_esp32_recall_b5",
        "prompt_version": "v3",
        "prompt_text": _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 + "\n\n" + ESP32_RECALL_BLOCK_B5,
    },
}


def run_arm(arm: str, windows: list[Window]) -> list[dict]:
    spec = ARM_SPECS[arm]
    results: list[dict] = []
    for idx, window in enumerate(windows, 1):
        if idx == 1 or idx % 25 == 0 or idx == len(windows):
            print(
                f"  [{arm}] {idx}/{len(windows)} - {window.window_id[:8]} "
                f"({window.category}, {2 + len(window.mid_frames)} frames)",
                flush=True,
            )
        gate = run_gate_call(window, spec["prompt_label"], spec["prompt_text"],
                             spec.get("prompt_version", "v3"))
        results.append(result_entry(window, gate))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_DIR)
    parser.add_argument("--arms", default="A_v1,C_v3_esp32_recall_b2,D_v3_esp32_recall_b3,F_v3_esp32_recall_b4")
    parser.add_argument("--baseline-per-period", type=int, default=None)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()

    out_dir = args.campaign.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    event_windows = build_windows_from_manifest()
    baseline_windows = build_baseline_windows(per_period=args.baseline_per_period)
    if args.smoke_test:
        event_windows = [w for w in event_windows if w.category == "tp"][:1] + [
            w for w in event_windows if w.category == "fp"
        ][:1]
        baseline_windows = baseline_windows[:2]
    windows = event_windows + baseline_windows

    arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    unknown = [arm for arm in arms if arm not in ARM_SPECS]
    if unknown:
        print(f"ERR: unknown arms: {unknown}", file=sys.stderr)
        return 2

    print(f"Campaign: {out_dir}", flush=True)
    print(f"Model gate: {worker_config.GEMINI_AGENT1_MODEL}", flush=True)
    print(f"Thinking budget: {THINKING_BUDGET}", flush=True)
    print(
        f"Windows: events={len(event_windows)} baseline={len(baseline_windows)} "
        f"total={len(windows)} x arms={len(arms)}",
        flush=True,
    )

    for arm in arms:
        spec = ARM_SPECS[arm]
        print(f"\n=== Arm {arm} - {spec['description']} ===", flush=True)
        started = time.monotonic()
        results = run_arm(arm, windows)
        elapsed = time.monotonic() - started
        cost_total = sum(item.get("total_cost_usd", 0.0) or 0.0 for item in results)
        ok_total = sum(1 for item in results if item["gate"].get("ok"))
        triggered_total = sum(1 for item in results if item.get("triggered"))
        payload = {
            "summary": {
                "arm": arm,
                "description": spec["description"],
                "prompt_label": spec["prompt_label"],
                "prompt_version": "v3",
                "model_gate": worker_config.GEMINI_AGENT1_MODEL,
                "thinking_budget": THINKING_BUDGET,
                "events_total": len(results),
                "events_ok": ok_total,
                "events_triggered": triggered_total,
                "total_cost_usd": round(cost_total, 6),
                "elapsed_seconds": round(elapsed, 1),
            },
            "results": results,
        }
        out_path = out_dir / f"results-{arm}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"  Done: ok={ok_total}/{len(results)} triggered={triggered_total} "
            f"cost=${cost_total:.4f} elapsed={elapsed:.1f}s -> {out_path.name}",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
