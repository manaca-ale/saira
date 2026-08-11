#!/usr/bin/env python3
"""Campaign 37b: Arruda from-scratch gate prompt vs V1, on CLEAN current-angle data.

Data (2026-06-11, clean std~72, multi-frame windows from the prod volume):
- IND_*  : detections Agent-2 kept (INDETERMINADO) — gate SHOULD trigger (recall).
- REJ_*  : V1 gate fired but Agent-2 REJECTED — V1 gate false-positives. A better gate
           SHOULD suppress these (not trigger). V1 triggers by construction.
- neg/w* : sem_ocorrencia windows (true negatives) — gate SHOULD NOT trigger.

Gate v1 = current prod. Gate scratch = arruda_gate_from_scratch.md.
"""
from __future__ import annotations
import glob, os, sys, types, uuid, json
from pathlib import Path

ROOT = Path(r"c:\saira")
WORKER_SRC = ROOT / "services" / "yolo-worker-vm" / "src"
CAMP = Path(__file__).parent
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
if not os.environ.get("GEMINI_API_KEY"):
    for line in (ROOT / "services" / ".env.benchmark").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("GEMINI_TEST_API_KEY") and "=" in line:
            os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip(); break
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://stub@localhost/stub")
os.environ.setdefault("GEMINI_AGENT1_MODEL", "gemini-2.5-flash-lite")
os.environ.setdefault("GEMINI_AGENT1_THINKING_BUDGET", "2048")
os.environ.setdefault("GEMINI_INPUT_TOKEN_PRICE_PER_1M", "0.10")
os.environ.setdefault("GEMINI_OUTPUT_TOKEN_PRICE_PER_1M", "0.40")
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
sys.modules.setdefault("cv2", types.SimpleNamespace())
from worker import _prompts_v3  # noqa: E402
from worker import config as wc  # noqa: E402
from worker.detector_gemini import analyze_new_litter_with_gemini  # noqa: E402

ARRUDA_CTX = {
    "device_id": "esp32_005", "camera_name": "ESP32-005 - Arruda",
    "logradouro": "Arruda", "bairro": "Arruda", "rpa": "RPA 2",
    "gemini_context_notes": (
        "Câmera elevada sobre via asfaltada de mão dupla, vista AMPLA e distante. À DIREITA, "
        "encostado num muro, há um PONTO CRÔNICO de descarte (pilha pré-existente de entulho/"
        "restos ao longo da base do muro). Tráfego intenso PASSA pela via sem parar. Descartes "
        "reais: alguém (a pé, carroça/carrinho ou veículo) PARA junto ao muro à direita e deposita."),
}

SCRATCH = """
You analyze 2-5 chronological CCTV frames from a single fixed street camera in Recife,
Brazil. The camera looks down a two-way asphalt street. On the RIGHT, against a
concrete/brick wall, there is a CHRONIC illegal-dumping point: a pre-existing pile of
debris/bags that is ALREADY there in normal frames. The view is wide and distant, so
people and objects are small and low-resolution. Heavy through-traffic (cars, motos,
bikes, pedestrians, and occasionally handcarts/carroças) PASSES along the street all
day without stopping.

Your task: decide whether THIS window shows a NEW illegal disposal at the right-side
pile, and gate it to a detailed reviewer (Agent-2). Favor recall, but suppress the
three common non-dumps below.

STEP 1 - Is there an agent INTERACTING with the right-side pile?
An "agent" = a person on foot, a person with a handcart/wheelbarrow/carroça, or a
stopped vehicle. INTERACTING = the agent STOPS at the pile frontage (same area in 2+
frames), not merely moving along the street.
- If NO agent stops at the pile (only through-traffic, people walking past, vehicles
  driving by, someone standing/waiting with empty hands) -> scene_type=TRAFFIC or
  EMPTY, new_litter_detected=false, confidence<=40. STOP HERE.

STEP 2 - Direction of material (the decisive question).
Among agents that STOP at the pile, judge where material is going:
- TOWARD the ground/pile (agent arrives carrying a bag/object/cart-load and is later
  without it, OR an object is set down, OR a cart/vehicle load is emptied at the pile)
  -> DISPOSAL.
- FROM the pile toward an agent/cart/truck (items lifted off the pile, loaded up, pile
  visibly shrinking) -> COLLECTION, not disposal.

STEP 3 - Suppress COLLECTION/MAINTENANCE, but ONLY with positive evidence.
Classify scene_type=COLLECTION_OR_MAINTENANCE (new_litter_detected=false) only if you
see at least one POSITIVE collection cue:
- a garbage/compactor truck or municipal vehicle servicing the pile;
- workers in uniforms/safety vests, or 2+ people with rakes/brooms/shovels gathering
  vegetal/pruning waste in a coordinated way;
- the pile VISIBLY SHRINKS across the frames, or material clearly flows FROM the pile.
Do NOT infer collection merely because a lone person bends, crouches, or stands by the
pile, or because a handcart/carroça is present - carroceiros dump here too.

STEP 4 - Decide.
- DISPOSAL evidence (Step 2 toward-ground) and NO positive collection cue
  -> scene_type=DUMPING, new_litter_detected=true, confidence 85-95.
- An agent clearly STOPS and HANDLES material at the pile but you cannot resolve the
  direction, and there is NO positive collection cue -> ESCALATE anyway:
  new_litter_detected=true, confidence 85.
- Positive collection cue present -> COLLECTION_OR_MAINTENANCE, false, confidence<=50.
- Only through-traffic / passing / standing / pre-existing unchanged pile
  -> TRAFFIC/EMPTY/PARKED, false, confidence<=40.

Hard rules:
- A pile present in the FIRST frame that merely persists is NOT a new disposal. Never
  trigger on the standing pile alone.
- Never trigger on an agent that does not STOP at the right-side pile.
- Low resolution: absence of visible pile growth is NOT evidence against disposal;
  weigh the stop+handle+leave pattern instead.

Respond with ONLY valid JSON: scene_type, new_litter_detected, confidence_0_100,
evidence_summary (<=260 chars).
""".strip()


def midframes(fs):
    n = len(fs)
    if n < 5:
        return []
    out = []
    for idx in [int(n*0.25), int(n*0.5), int(n*0.75)]:
        idx = max(1, min(n-2, idx))
        if idx not in out:
            out.append(idx)
    return [fs[i] for i in out]


def load():
    ev = []
    for d in sorted(glob.glob(str(ROOT/"tmp"/"ar_tp"/"*"))):
        if not os.path.isdir(d):
            continue
        fs = sorted(glob.glob(d+"/*.jpg"))
        if not fs:
            continue
        name = os.path.basename(d)
        cohort = "kept" if name.startswith("IND") else "v1_fp"  # IND=should trigger, REJ=should suppress
        ev.append((name, cohort, [Path(f) for f in fs]))
    for d in sorted(glob.glob(str(ROOT/"tmp"/"arruda_neg"/"w*"))):
        fs = sorted(glob.glob(d+"/*.jpg"))
        if fs:
            ev.append((os.path.basename(d), "neg", [Path(f) for f in fs]))
    return ev


def run(frames, gate):
    prev = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    if gate == "v1":
        pv = "current"
    else:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = SCRATCH
        pv = "v3"
    wc.GEMINI_AGENT1_THINKING_BUDGET = 2048
    mid = midframes(frames)
    try:
        r = analyze_new_litter_with_gemini(
            first_frame=frames[0], last_frame=frames[-1], camera_context=ARRUDA_CTX,
            request_id=f"b37s-{gate}-{uuid.uuid4().hex[:4]}", prior_window_context=None,
            use_mosaic=False, mid_frames=mid or None, prompt_version=pv)
        rep = r.report
        c = int(rep.confidence_0_100); d = bool(rep.new_litter_detected)
        return {"ok": True, "trig": d and c >= 85, "c": c,
                "scene": getattr(rep, "scene_type", "") or "",
                "ev": (rep.evidence_summary or "")[:160]}
    except Exception as e:
        return {"ok": False, "trig": False, "err": f"{type(e).__name__}: {e}"}
    finally:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = prev


def main():
    gates = ["v1", "scratch"]
    events = load()
    print(f"Campaign 37b — Arruda from-scratch vs V1 | {len(events)} events", flush=True)
    rows = []
    for name, cohort, frames in events:
        rec = {"name": name, "cohort": cohort, "g": {}}
        line = [f"{cohort:6}/{name}({len(frames)}f)"]
        for g in gates:
            res = run(frames, g)
            rec["g"][g] = res
            m = "TRIG" if res.get("trig") else ("." if res.get("ok") else "ERR")
            line.append(f"{g}={m}(c={res.get('c')},{res.get('scene')})")
        print("  " + " | ".join(line), flush=True)
        rows.append(rec)

    def rate(cohort, gate, want_trig):
        rs = [r for r in rows if r["cohort"] == cohort and r["g"][gate].get("ok")]
        hit = [r for r in rs if r["g"][gate]["trig"] == want_trig]
        return f"{len(hit)}/{len(rs)}"
    print("\n=== SUMMARY ===", flush=True)
    for g in gates:
        print(f"  {g:8}: kept-recall(trig) {rate('kept', g, True)} | "
              f"v1_fp SUPPRESSED(no-trig) {rate('v1_fp', g, False)} | "
              f"neg clean(no-trig) {rate('neg', g, False)}", flush=True)
    (CAMP/"results_scratch.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
