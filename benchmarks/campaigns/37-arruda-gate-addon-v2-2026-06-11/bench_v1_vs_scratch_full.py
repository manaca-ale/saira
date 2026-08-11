#!/usr/bin/env python3
"""Campaign 37c: Arruda gate V1 vs SCRATCH on the FULL labeled set, 3 repeats.

Cohorts:
- FN        : 5 real missed disposals (id25/26/27 02-06, id31/32 09-06) recovered CLEAN
              from the Drive "Não Capturadas" exports. Gate SHOULD trigger (recall).
              All current wide-angle. id25/26/31/32 reached the gate in prod (conf=0);
              id27 was BGSUB-suppressed.
- KEPT      : exact prod windows whose detection survived review (INDETERMINADO).
- REVIEWREJ : exact prod windows where V1+Agent-2 confirmed but human review REJECTED
              -> operator-facing FP. Suppressing these is the real FP win.
- A2REJ     : exact prod windows where V1 triggered but Agent-2 rejected -> cost-only FP.
- NEG       : exact prod windows where V1 did not trigger (true negatives).

Each window: prod-style 5-frame pick (first + 25/50/75% + last), flash-lite,
thinking 2048, trigger = new_litter_detected AND conf >= 85. 3 repeats per gate.
"""
from __future__ import annotations
import glob, os, sys, types, uuid, json, time
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

# reuse SCRATCH constant + context from bench_scratch.py
sys.path.insert(0, str(CAMP))
import importlib.util
_spec = importlib.util.spec_from_file_location("_bs", CAMP / "bench_scratch.py")
_bs = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_bs)
except SystemExit:
    pass
SCRATCH = _bs.SCRATCH
ARRUDA_CTX = _bs.ARRUDA_CTX

REPS = 3
GATES = ["v1", "scratch"]


def pick5(fs):
    n = len(fs)
    if n <= 5:
        return fs
    idxs = [0, int(n * 0.25), int(n * 0.5), int(n * 0.75), n - 1]
    seen, out = set(), []
    for i in idxs:
        i = max(0, min(n - 1, i))
        if i not in seen:
            seen.add(i); out.append(fs[i])
    return out


def load():
    ev = []
    for name in ["id25", "id26", "id27", "id31", "id32"]:
        fs = sorted(glob.glob(str(ROOT / "tmp" / "arruda_fn_drive" / name / "*.jpg")))
        ev.append((name, "FN", [Path(f) for f in pick5(fs)]))
    for d in sorted(glob.glob(str(ROOT / "tmp" / "ar_exact" / "*"))):
        if not os.path.isdir(d):
            continue
        name = os.path.basename(d)
        fs = sorted(glob.glob(d + "/*.jpg"))
        if len(fs) < 2:
            continue
        if "KEPT" in name or name.startswith(("32_DET", "34_DET")):
            cohort = "KEPT"  # 32/34 PENDENTE — tracked, excluded from FP math until reviewed
        elif "REVIEWREJ" in name or name.startswith(("01_", "02_")):
            cohort = "REVIEWREJ"
        elif "A2REJ" in name:
            cohort = "A2REJ"
        elif "NEG" in name:
            cohort = "NEG"
        else:
            cohort = "REVIEWREJ"
        ev.append((name, cohort, [Path(f) for f in pick5(fs)]))
    return ev


def run(frames, gate, rep):
    prev = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    if gate == "v1":
        pv = "current"
    else:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = SCRATCH
        pv = "v3"
    wc.GEMINI_AGENT1_THINKING_BUDGET = 2048
    mid = frames[1:-1] if len(frames) > 2 else None
    try:
        r = analyze_new_litter_with_gemini(
            first_frame=frames[0], last_frame=frames[-1], camera_context=ARRUDA_CTX,
            request_id=f"b37c-{gate}-r{rep}-{uuid.uuid4().hex[:4]}", prior_window_context=None,
            use_mosaic=False, mid_frames=mid, prompt_version=pv)
        rep_ = r.report
        c = int(rep_.confidence_0_100); d = bool(rep_.new_litter_detected)
        return {"ok": True, "trig": d and c >= 85, "det": d, "c": c,
                "scene": getattr(rep_, "scene_type", "") or "",
                "ev": (rep_.evidence_summary or "")[:200]}
    except Exception as e:
        return {"ok": False, "trig": False, "err": f"{type(e).__name__}: {e}"[:200]}
    finally:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = prev


def main():
    events = load()
    n_calls = len(events) * len(GATES) * REPS
    print(f"Campaign 37c — V1 vs SCRATCH | {len(events)} windows x {len(GATES)} gates x {REPS} reps = {n_calls} calls", flush=True)
    rows = []
    for name, cohort, frames in events:
        rec = {"name": name, "cohort": cohort, "n_frames": len(frames), "g": {}}
        for g in GATES:
            runs = []
            for rp in range(REPS):
                res = run(frames, g, rp)
                runs.append(res)
                time.sleep(0.3)
            rec["g"][g] = runs
            marks = "".join("T" if r.get("trig") else ("." if r.get("ok") else "E") for r in runs)
            confs = ",".join(str(r.get("c", "-")) for r in runs)
            print(f"  {cohort:9}/{name:24} {g:7}: {marks} (c={confs})", flush=True)
        rows.append(rec)

    print("\n=== SUMMARY (per-rep trigger rate; want FN/KEPT=TRIG, others=no-trig) ===", flush=True)
    for g in GATES:
        parts = []
        for coh, want in [("FN", True), ("KEPT", True), ("REVIEWREJ", False), ("A2REJ", False), ("NEG", False)]:
            rs = [r for r in rows if r["cohort"] == coh]
            tot = hit = 0
            for r in rs:
                for rr in r["g"][g]:
                    if rr.get("ok"):
                        tot += 1
                        if rr["trig"] == want:
                            hit += 1
            parts.append(f"{coh} {'ok' if want else 'supp'} {hit}/{tot}")
        print(f"  {g:8}: " + " | ".join(parts), flush=True)
    (CAMP / "results_37c.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved results_37c.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
