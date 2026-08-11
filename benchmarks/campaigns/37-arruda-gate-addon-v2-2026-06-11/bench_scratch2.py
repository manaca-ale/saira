#!/usr/bin/env python3
"""Campaign 37d: SCRATCH2 = SCRATCH + narrow on-foot-carrier clause (id32 class).

Single change vs SCRATCH: a person ON FOOT inside the litter strip carrying
bags/objects counts as interacting even without a 2-frame static stop, and
arrive-with / later-without = disposal evidence. Everything else identical.
1 rep (flash-lite@2048 was fully deterministic across 228 calls in 37c).
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

sys.path.insert(0, str(CAMP))
import importlib.util
_spec = importlib.util.spec_from_file_location("_bs", CAMP / "bench_scratch.py")
_bs = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_bs)
except SystemExit:
    pass
ARRUDA_CTX = _bs.ARRUDA_CTX

SCRATCH2 = _bs.SCRATCH.replace(
    """STEP 1 - Is there an agent INTERACTING with the right-side pile?
An "agent" = a person on foot, a person with a handcart/wheelbarrow/carroça, or a
stopped vehicle. INTERACTING = the agent STOPS at the pile frontage (same area in 2+
frames), not merely moving along the street.""",
    """STEP 1 - Is there an agent INTERACTING with the right-side pile?
An "agent" = a person on foot, a person with a handcart/wheelbarrow/carroça, or a
stopped vehicle. INTERACTING = the agent STOPS at the pile frontage (same area in 2+
frames), not merely moving along the street. EXCEPTION: a person ON FOOT who is
INSIDE the litter strip itself (off the roadway) while CARRYING bags or objects
counts as interacting even if seen there in only one frame — on-foot dumps are fast
and frames are ~60s apart.""").replace(
    """- TOWARD the ground/pile (agent arrives carrying a bag/object/cart-load and is later
  without it, OR an object is set down, OR a cart/vehicle load is emptied at the pile)
  -> DISPOSAL.""",
    """- TOWARD the ground/pile (agent arrives carrying a bag/object/cart-load and is later
  without it, OR an object is set down, OR a cart/vehicle load is emptied at the pile)
  -> DISPOSAL. A person seen carrying bags/objects INTO the strip in one frame and
  empty-handed (or absent) in a later frame is DISPOSAL evidence even without a
  visible set-down moment.""")
assert SCRATCH2 != _bs.SCRATCH and "EXCEPTION" in SCRATCH2

# same loader as 37c
import importlib.util as _ilu
_spec2 = _ilu.spec_from_file_location("_b37c", CAMP / "bench_v1_vs_scratch_full.py")
_b37c = _ilu.module_from_spec(_spec2)
_b37c.__name__ = "_b37c"
import builtins
_orig_main = None
# load() needs module import without running main
src = (CAMP / "bench_v1_vs_scratch_full.py").read_text(encoding="utf-8")
ns = {"__name__": "_b37c", "__file__": str(CAMP / "bench_v1_vs_scratch_full.py")}
exec(compile(src, str(CAMP / "bench_v1_vs_scratch_full.py"), "exec"), ns)
load = ns["load"]


def run(frames):
    prev = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = SCRATCH2
    wc.GEMINI_AGENT1_THINKING_BUDGET = 2048
    mid = frames[1:-1] if len(frames) > 2 else None
    try:
        r = analyze_new_litter_with_gemini(
            first_frame=frames[0], last_frame=frames[-1], camera_context=ARRUDA_CTX,
            request_id=f"b37d-{uuid.uuid4().hex[:4]}", prior_window_context=None,
            use_mosaic=False, mid_frames=mid, prompt_version="v3")
        rep_ = r.report
        c = int(rep_.confidence_0_100); d = bool(rep_.new_litter_detected)
        return {"ok": True, "trig": d and c >= 85, "c": c,
                "scene": getattr(rep_, "scene_type", "") or "",
                "ev": (rep_.evidence_summary or "")[:200]}
    except Exception as e:
        return {"ok": False, "trig": False, "err": f"{type(e).__name__}: {e}"[:200]}
    finally:
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = prev


def main():
    events = load()
    print(f"Campaign 37d — SCRATCH2 | {len(events)} windows x 1 rep", flush=True)
    rows = []
    for name, cohort, frames in events:
        res = run(frames)
        rows.append({"name": name, "cohort": cohort, "scratch2": res})
        m = "TRIG" if res.get("trig") else ("." if res.get("ok") else "ERR")
        print(f"  {cohort:9}/{name:24} {m} c={res.get('c')} {res.get('scene','')}", flush=True)
        time.sleep(0.3)
    (CAMP / "results_37d.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved results_37d.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
