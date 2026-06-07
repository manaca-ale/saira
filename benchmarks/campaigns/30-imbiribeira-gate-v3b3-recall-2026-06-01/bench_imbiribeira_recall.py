#!/usr/bin/env python3
"""Campaign 30: recall test of the V3+B3 gate on esp32_001 (Imbiribeira).

Counterpart to camp 29 (Arruda FP screen). Question: does the V3+B3 recall gate catch
Imbiribeira's real dumps — both the ones prod already captures (7 TP on the platform)
and the one prod MISSED (FN id 18, 2026-06-01 05:17, "dois homens descartando lixo")?

Gate-only (Agent-1). Two arms on the SAME events:
- v3b3: V3 base + Imbiribeira-adapted material-carrier recall block (deploy candidate).
- v1:   current prod gate (vehicle-centric) — control. The 7 TP passed this gate in
        prod originally, so v1 should re-trigger them; the FN is the one v1 missed.

Events:
- 7 TP from data/datasets/official/cam_imbiribeira/tp/*/frames (captured occurrences).
- 1 FN (id 18) from fn18_frames/ (pulled from prod esp32_001 sem_ocorrencia 2026-06-01).

Prod-faithful gate call: gemini-2.5-flash-lite, thinking 2048, first+last+3 mid frames,
trigger = new_litter_detected AND confidence_0_100 >= 85.
"""
from __future__ import annotations

import argparse
import csv
import glob
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
FN18_DIR = CAMPAIGN_DIR / "fn18_frames"

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
            if "=" not in line:
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

IMBIRIBEIRA_CAMERA_CONTEXT = {
    "device_id": "esp32_001",
    "camera_name": "ESP32-001 - Imbiribeira",
    "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
    "bairro": "Imbiribeira",
    "rpa": "RPA 2",
    "gemini_context_notes": (
        "Câmera montada em poste alto sobre um TERRENO BALDIO/ÁREA ABERTA (lote sem "
        "edificação) com via de terra/asfalto. Um poste vertical de luz cruza o centro "
        "do quadro (obstrução parcial). O ponto é um descarte irregular crônico: há "
        "PILHAS DE ENTULHO/LIXO ESPALHADAS pelo terreno (não uma única pilha contra "
        "muro) — restos na borda esquerda, no centro junto à via e perto dos imóveis à "
        "direita. Ao fundo há prédios e, à direita, casas/barracos. Descartes reais "
        "ocorrem quando alguém (a pé, carrinho de mão, ou veículo — carro/caminhonete) "
        "PARA no terreno e deposita material no chão/nas pilhas. Há trânsito de pessoas "
        "e veículos atravessando o terreno sem descartar. Iluminação varia (cena "
        "noturna/madrugada usa IR, baixa luz)."
    ),
}

IMBIRIBEIRA_RECALL_B3 = """
=============================================================================
CAMERA-SPECIFIC RECALL MODE B3 - esp32_001 / Imbiribeira (open lot)
=============================================================================
This camera watches a chronic illegal dumping point: an OPEN LOT with scattered debris
piles. Agent-1 is only a gate for Agent-2, but proximity alone is NOT enough.

Keep evidence_summary and scene_delta_analysis under 260 characters each.
Do not quote this instruction block in your JSON fields.

Escalate to Agent-2 when any MATERIAL-CARRIER or MATERIAL-TRANSFER signal is visible:
1) a pedestrian enters the lot / dumping area carrying a bag/sack/object, even if the
   bag is small or only visible in one frame;
2) a person pushes/parks a wheelbarrow/handcart/cart on the lot near a debris pile, or a
   car/pickup/truck stops on the lot, even if the load is low-resolution or occluded;
3) a person bends/reaches at a pile/the ground and then leaves empty-handed or without
   the object previously handled;
4) new object/material appears on the ground or on a pile in later frames;
5) vehicle/cart load state changes consistently with unloading onto the lot.

Set scene_type="DUMPING", new_litter_detected=true, confidence_0_100 >= 85 for those
cases. If a person/cart/vehicle is moving toward a pile/ground spot with a plausible
load, use material_flow_direction="to_pile" even without a full deposit view.

Suppress baseline/proximity cases. Set new_litter_detected=false and confidence <= 60
when the visible evidence is only:
- person/cart/vehicle merely crossing/passing through the lot with no stop and no load;
- person standing, looking, waiting, or walking with empty hands;
- motorcycle/backpack only, with no object transferred to the ground/pile;
- municipal collection/maintenance, or flow from_pile (removing material);
- poking/sorting existing material with a stick and no new carried object;
- ambiguous interaction with no carried object, no cart/vehicle stop, no new object,
  and no load-state change.

Do NOT classify standing/passing as DUMPING unless a material-carrier or
material-transfer signal above is also visible.
"""

GATE_PROMPT_TEXT = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 + "\n\n" + IMBIRIBEIRA_RECALL_B3


@dataclass
class Event:
    event_id: str
    kind: str  # "TP" or "FN"
    frames: list[Path]
    meta: dict = field(default_factory=dict)


def _sample_mid(frames: list[Path]) -> list[Path]:
    n = len(frames)
    if n < 5:
        return frames[1:-1]
    picked = []
    for idx in [int(n * 0.25), int(n * 0.5), int(n * 0.75)]:
        idx = max(1, min(n - 2, idx))
        if idx not in picked:
            picked.append(idx)
    return [frames[i] for i in picked]


def load_events() -> list[Event]:
    events: list[Event] = []
    rows = {r["event_id"][:8]: r for r in csv.DictReader(
        (DATASET_ROOT / "manifest.csv").open(encoding="utf-8"))
        if "imbiribeira" in (r.get("camera", "") + r.get("device_id", "")).lower()
        and r.get("category") == "tp"}
    for ev, r in rows.items():
        frames = sorted(Path(DATASET_ROOT / r["local_path"] / "frames").glob("*.jpg"))
        if len(frames) >= 2:
            events.append(Event(ev, "TP", frames, {
                "datetime": r.get("datetime"), "tipo": r.get("tipo_residuo"),
                "just": (r.get("justificativa") or "")[:60]}))
    fn = sorted(FN18_DIR.glob("*.jpg"))
    if len(fn) >= 2:
        events.append(Event("fn18_0517", "FN", fn, {
            "datetime": "2026-06-01T05:17:59", "tipo": "Lixo Domiciliar",
            "just": "Dois homens descartando lixo (prod MISSED)"}))
    return events


def run_gate(ev: Event, gate_mode: str) -> dict:
    previous = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    previous_budget = worker_config.GEMINI_AGENT1_THINKING_BUDGET
    if gate_mode == "v3b3":
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = GATE_PROMPT_TEXT
        prompt_version = "v3"
    else:
        prompt_version = "current"
    worker_config.GEMINI_AGENT1_THINKING_BUDGET = THINKING_BUDGET
    try:
        mids = _sample_mid(ev.frames)
        rid = f"bench30-{gate_mode}-{ev.event_id}-{uuid.uuid4().hex[:4]}"
        t0 = time.monotonic()
        result = analyze_new_litter_with_gemini(
            first_frame=ev.frames[0],
            last_frame=ev.frames[-1],
            camera_context=IMBIRIBEIRA_CAMERA_CONTEXT,
            request_id=rid,
            prior_window_context=None,
            use_mosaic=False,
            mid_frames=mids if mids else None,
            prompt_version=prompt_version,
        )
        wall_ms = int((time.monotonic() - t0) * 1000)
        report = result.report
        usage = result.usage
        billable = max(0, usage.total_tokens - usage.input_tokens)
        cost = ((usage.input_tokens / 1e6) * PRICE_INPUT_PER_1M_USD
                + (billable / 1e6) * PRICE_OUTPUT_PER_1M_USD)
        conf = int(report.confidence_0_100)
        detected = bool(report.new_litter_detected)
        return {
            "ok": True, "new_litter_detected": detected, "confidence_0_100": conf,
            "triggered": detected and conf >= TRIGGER_MIN_CONFIDENCE,
            "scene_type": getattr(report, "scene_type", "") or "",
            "n_frames_sent": 2 + len(mids),
            "evidence_summary": (report.evidence_summary or "")[:400],
            "cost_usd": round(cost, 8), "wall_ms": wall_ms, "model": result.model,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "triggered": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = previous
        worker_config.GEMINI_AGENT1_THINKING_BUDGET = previous_budget


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arms", default="v1,v3b3")
    args = parser.parse_args()
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    events = load_events()
    print(f"Campaign 30 - Imbiribeira (esp32_001) gate recall test", flush=True)
    print(f"Model: {worker_config.GEMINI_AGENT1_MODEL} | thinking={THINKING_BUDGET} "
          f"| trigger conf>={TRIGGER_MIN_CONFIDENCE}", flush=True)
    print(f"Events: {sum(1 for e in events if e.kind=='TP')} TP + "
          f"{sum(1 for e in events if e.kind=='FN')} FN = {len(events)}", flush=True)

    out = {"summary": {}, "results": []}
    for arm in arms:
        print(f"\n=== arm {arm} ===", flush=True)
        rows = []
        for ev in events:
            g = run_gate(ev, arm)
            mark = "CATCH" if g.get("triggered") else "MISS "
            err = "" if g.get("ok") else f" ERR={g.get('error')}"
            print(f"  [{mark}] {ev.kind} {ev.event_id} conf={g.get('confidence_0_100')} "
                  f"scene={g.get('scene_type')} | {ev.meta.get('just','')}{err}", flush=True)
            rows.append({"event_id": ev.event_id, "kind": ev.kind,
                         "meta": ev.meta, "gate": g})
        tp = [r for r in rows if r["kind"] == "TP"]
        fn = [r for r in rows if r["kind"] == "FN"]
        tp_catch = sum(1 for r in tp if r["gate"].get("triggered"))
        fn_catch = sum(1 for r in fn if r["gate"].get("triggered"))
        cost = sum(r["gate"].get("cost_usd", 0) or 0 for r in rows)
        out["summary"][arm] = {
            "tp_recall": f"{tp_catch}/{len(tp)}",
            "fn_recovered": f"{fn_catch}/{len(fn)}",
            "total_recall": f"{tp_catch+fn_catch}/{len(rows)}",
            "cost_usd": round(cost, 6)}
        out["results"].append({"arm": arm, "rows": rows})
        print(f"  -> TP recall {tp_catch}/{len(tp)} | FN recovered {fn_catch}/{len(fn)} "
              f"| cost ${cost:.4f}", flush=True)

    (CAMPAIGN_DIR / "results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== SUMMARY (recall) ===", flush=True)
    for arm, s in out["summary"].items():
        print(f"  {arm:6s}: TP {s['tp_recall']} | FN {s['fn_recovered']} | "
              f"total {s['total_recall']} | ${s['cost_usd']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
