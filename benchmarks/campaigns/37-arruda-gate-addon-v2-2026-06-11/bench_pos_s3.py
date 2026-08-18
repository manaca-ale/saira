#!/usr/bin/env python3
"""Camp 37e — V1 vs SCRATCH on ALL historical cam_14 positive exact windows (S3).

Windows from build_pos_corpus.py: bit-exact prod replay (detection_frames index ==
window frame list; same 0/25/50/75/100 picks). Cohorts by dir prefix:
DESCARTE (spreadsheet-confirmed), CONF, INDET, COLETA (spreadsheet says collection).
1 rep (deterministic per 37c).
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
SCRATCH = _bs.SCRATCH
ARRUDA_CTX = _bs.ARRUDA_CTX


def run(frames, gate):
    prev = _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3
    pv = "current"
    if gate == "scratch":
        _prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = SCRATCH
        pv = "v3"
    wc.GEMINI_AGENT1_THINKING_BUDGET = 2048
    mid = frames[1:-1] if len(frames) > 2 else None
    try:
        r = analyze_new_litter_with_gemini(
            first_frame=frames[0], last_frame=frames[-1], camera_context=ARRUDA_CTX,
            request_id=f"b37e-{gate}-{uuid.uuid4().hex[:4]}", prior_window_context=None,
            use_mosaic=False, mid_frames=mid, prompt_version=pv)
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
    manifest = json.loads((ROOT / "tmp" / "ar_pos_s3" / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    print(f"Campaign 37e — V1 vs SCRATCH | {len(manifest)} janelas exatas S3 (positivos históricos)", flush=True)
    for m in manifest:
        d = ROOT / "tmp" / "ar_pos_s3" / m["dir"]
        frames = [Path(f) for f in sorted(glob.glob(str(d / "*.jpg")))]
        if len(frames) < 4:
            print(f"  SKIP {m['dir']} ({len(frames)}f)", flush=True)
            continue
        rec = {"name": m["dir"], "status": m["status"], "a1c_prod": m["a1c_prod"], "g": {}}
        line = [f"{m['status']:9}/{m['dir']:34} prod_a1c={m['a1c_prod']}"]
        for g in ("v1", "scratch"):
            res = run(frames, g)
            rec["g"][g] = res
            mark = "TRIG" if res.get("trig") else ("." if res.get("ok") else "ERR")
            line.append(f"{g}={mark}({res.get('c')})")
            time.sleep(0.3)
        print("  " + " | ".join(line), flush=True)
        rows.append(rec)

    print("\n=== RECALL (quer TRIG) ===", flush=True)
    for coh in ("DESCARTE", "CONF", "INDET", "COLETA"):
        rs = [r for r in rows if r["status"] == coh]
        if not rs:
            continue
        for g in ("v1", "scratch"):
            hit = sum(1 for r in rs if r["g"][g].get("trig"))
            print(f"  {coh:9} {g:8}: {hit}/{len(rs)}", flush=True)
    (CAMP / "results_37e.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved results_37e.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
