"""Quick test: verify JSON truncation fix + ghost detection on ch23."""
from __future__ import annotations
import json, os, sys
from pathlib import Path

_worker_root = Path(__file__).resolve().parent / "yolo-worker-vm" / "src"
sys.path.insert(0, str(_worker_root))

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

os.environ["AI_MODE"] = "gemini"
os.environ["MOCK_MODE"] = "false"
os.environ.setdefault("P1_MODEL_PATH", "/dev/null")
os.environ.setdefault("P2_MODEL_PATH", "/dev/null")
os.environ["GEMINI_MODEL"] = "gemini-2.5-flash-lite"
os.environ["GEMINI_AGENT1_MODEL"] = "gemini-2.5-flash-lite"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from worker import config
from worker.detector_gemini import analyze_new_litter_with_gemini

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "datasets" / "field_cctv"


def test_ghost_ch23():
    """ch23: ghost infraction — car arrives, dumps, leaves. First/last identical."""
    ds = DATA_ROOT / "BOA_VISTA_ch23_20260202101133"
    frames = sorted(ds.glob("*.jpg"))
    first = frames[0]   # 10:11:33 - empty scene
    mid = frames[len(frames)//2]  # ~10:12:08 - car + person dumping
    last = frames[-1]    # 10:12:53 - empty scene again

    print(f"=== GHOST TEST (ch23) ===")
    print(f"First: {first.name}")
    print(f"Mid:   {mid.name}")
    print(f"Last:  {last.name}")

    # Test WITHOUT mid_frame (should miss, like before)
    print(f"\n--- Without mid_frame (2 frames) ---")
    try:
        r = analyze_new_litter_with_gemini(
            first_frame=first, last_frame=last,
            camera_context={"camera_name": "ch23_test"},
            request_id="ghost-no-mid",
        )
        print(f"  detected={r.report.new_litter_detected}  conf={r.report.confidence_0_100}")
        print(f"  evidence: {r.report.evidence_summary[:150]}")
        print(f"  tokens: {r.usage.input_tokens}in/{r.usage.output_tokens}out  lat={r.latency_ms}ms")
    except Exception as e:
        print(f"  ERROR: {e}")

    # Test WITH mid_frames (should detect Pattern C)
    print(f"\n--- With mid_frames (3 frames) ---")
    try:
        r = analyze_new_litter_with_gemini(
            first_frame=first, last_frame=last,
            camera_context={"camera_name": "ch23_test"},
            request_id="ghost-with-mid",
            mid_frames=[mid],
        )
        print(f"  detected={r.report.new_litter_detected}  conf={r.report.confidence_0_100}")
        print(f"  evidence: {r.report.evidence_summary[:200]}")
        print(f"  scene_delta ({len(r.report.scene_delta_analysis)} chars): {r.report.scene_delta_analysis[:200]}")
        print(f"  tokens: {r.usage.input_tokens}in/{r.usage.output_tokens}out  lat={r.latency_ms}ms")
    except Exception as e:
        print(f"  ERROR: {e}")


def test_json_truncation():
    """ID_23 and foto_46_a_52 had frequent JSON truncation errors. Run a few windows."""
    for ds_name in ["ID_23", "foto_46_a_52"]:
        ds = DATA_ROOT / ds_name
        if not ds.exists():
            print(f"\n=== SKIP {ds_name} (not found) ===")
            continue
        frames = sorted(ds.glob("*.jpg"))
        if len(frames) < 6:
            continue

        first = frames[0]
        mid = frames[len(frames)//4]  # quarter point
        last = frames[min(11, len(frames)-1)]

        print(f"\n=== JSON TRUNCATION TEST ({ds_name}) ===")
        print(f"First: {first.name}  Mid: {mid.name}  Last: {last.name}")

        errors = 0
        for attempt in range(3):
            try:
                r = analyze_new_litter_with_gemini(
                    first_frame=first, last_frame=last,
                    camera_context={"camera_name": ds_name},
                    request_id=f"trunc-{ds_name}-{attempt}",
                    mid_frames=[mid],
                )
                delta_len = len(r.report.scene_delta_analysis)
                print(f"  Run {attempt+1}: OK  detected={r.report.new_litter_detected}  "
                      f"delta_len={delta_len}  tokens={r.usage.output_tokens}out  lat={r.latency_ms}ms")
            except Exception as e:
                errors += 1
                err_msg = str(e)[:100]
                print(f"  Run {attempt+1}: ERROR  {err_msg}")

        print(f"  Result: {3-errors}/3 success")


if __name__ == "__main__":
    test_ghost_ch23()
    test_json_truncation()
