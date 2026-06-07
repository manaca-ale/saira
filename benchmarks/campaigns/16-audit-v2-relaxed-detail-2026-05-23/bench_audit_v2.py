#!/usr/bin/env python3
"""Campanha 16 — Detail (Agent-2) AUDIT_V2 relaxed.

Re-roda o MESMO subset de 44 janelas da camp 15 (gate hits da camp 12 V3),
mas chamando o Detail Agent com prompt_version="audit_v2" — versão relaxada
do AUDIT que só força infraction_confirmed=false para 5 patterns FP claros
{traffic_passing, municipal_collection, pruning_crew, rain_blur,
parking_dropoff}. carroceiro_sorting / other / real_dumping ficam com o
modelo decidir.

Hipótese: recupera os 7 TPs perdidos na camp 15 V1 audit (TP recall 12% →
≥75%) sem reverter o ganho contra FPs (FP rate 15% → ≤30%).

Subset (mesmo da camp 15, seed=42):
- 8 TPs
- 20 FPs (amostrados dos 44 que passaram o gate em camp 12 V3)
- 9 baselines
- 8 indefinidos
- Total: 44 windows × 1 arm (audit_v2) = 44 calls Detail
- Custo estimado: ~$0.10

Comparação cross-campaign:
- baseline "current"     → camp 15 results-current.json (100% TP, 68% FP)
- baseline "audit" (V1)  → camp 15 results-audit.json   (12% TP, 15% FP)
- esta rodada "audit_v2" → camp 16 results-audit_v2.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(r"c:\saira")
WORKER_SRC = PROJECT_ROOT / "services" / "yolo-worker-vm" / "src"
DATASET_ROOT = PROJECT_ROOT / "data" / "datasets" / "official"
CAMPAIGN_DIR = Path(__file__).parent
CAMP12_RESULTS = PROJECT_ROOT / "benchmarks" / "campaigns" / "12-prompt-v3-posture-2026-05-22" / "results-B_v3_posture.json"

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
        k, _, v = line.partition("=")
        v = v.strip()
        if v.startswith("<"):
            continue
        os.environ.setdefault(k.strip(), v)


_load_env_file(CAMPAIGN_DIR / ".env.benchmark")

if not os.environ.get("GEMINI_API_KEY"):
    services_env = PROJECT_ROOT / "services" / ".env.benchmark"
    if services_env.exists():
        for line in services_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == "GEMINI_TEST_API_KEY" and v.strip():
                os.environ["GEMINI_API_KEY"] = v.strip()
                break

if not os.environ.get("GEMINI_API_KEY"):
    print("ERR: GEMINI_API_KEY not set.", file=sys.stderr)
    sys.exit(2)

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://stub@localhost/stub")
os.environ.setdefault("GEMINI_INPUT_TOKEN_PRICE_PER_1M", "0.30")
os.environ.setdefault("GEMINI_OUTPUT_TOKEN_PRICE_PER_1M", "2.50")  # detail = gemini-2.5-flash

if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from worker import config as worker_config  # noqa: E402
from worker.detector_gemini import analyze_with_gemini  # noqa: E402


PRICE_INPUT_PER_1M_USD = float(os.environ["GEMINI_INPUT_TOKEN_PRICE_PER_1M"])
PRICE_OUTPUT_PER_1M_USD = float(os.environ["GEMINI_OUTPUT_TOKEN_PRICE_PER_1M"])

CAMERA_CONTEXT = {
    "cam_mangabeira": {
        "camera_name": "ESP32-002 - Mangabeira",
        "logradouro": "Av. Prof. José dos Anjos, 3254",
        "bairro": "Mangabeira",
        "rpa": "RPA 3",
    },
    "cam_imbiribeira": {
        "camera_name": "ESP32-001 - Imbiribeira",
        "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
        "bairro": "Imbiribeira",
        "rpa": "RPA 2",
    },
}


@dataclass
class Window:
    window_id: str
    camera: str
    category: str
    frames: list[Path]
    justificativa: str
    gate_evidence: str = ""


def build_windows_from_gate_hits(seed: int = 42) -> list[Window]:
    """Carrega gate hits da camp 12 V3 e amostra balanced."""
    with CAMP12_RESULTS.open(encoding="utf-8") as f:
        camp12 = json.load(f)
    gate_hits = [w for w in camp12["windows"] if w.get("final_new_litter_detected")]

    by_cat: dict[str, list] = {}
    for w in gate_hits:
        by_cat.setdefault(w["category"], []).append(w)

    rnd = random.Random(seed)
    picked: list[dict] = []
    picked.extend(by_cat.get("tp", []))                     # all TPs
    picked.extend(by_cat.get("baseline", []))               # all baselines
    fps = by_cat.get("fp", [])
    rnd.shuffle(fps)
    picked.extend(fps[:20])
    indefs = by_cat.get("indefinido", [])
    rnd.shuffle(indefs)
    picked.extend(indefs[:8])

    # Resolve frame paths
    windows = []
    for w in picked:
        wid = w["window_id"]
        cat = w["category"]
        # Find frames dir from manifest.csv
        local_path = None
        if cat == "baseline":
            # baseline window_id = "baseline_cam_X_period_NNN"
            # Use first/last frame from sample (camp 12 didn't persist paths;
            # we re-sample from baseline dir)
            parts = wid.split("_")
            camera = "_".join(parts[1:3])  # cam_imbiribeira / cam_mangabeira
            period = parts[3]
            idx = int(parts[4])
            period_dir = DATASET_ROOT / camera / "baseline" / period
            frames_all = sorted(period_dir.glob("*.jpg"))
            start = idx * 12
            window_frames = frames_all[start:start + 12]
            if len(window_frames) < 2:
                continue
            n = len(window_frames)
            indices = sorted({0, n // 4, n // 2, 3 * n // 4, n - 1})
            frames = [window_frames[i] for i in indices]
        else:
            # Event: find via manifest
            camera = w["camera"]
            cat_dir = DATASET_ROOT / camera / cat / wid / "frames"
            if not cat_dir.exists():
                continue
            all_frames = sorted(cat_dir.glob("*.jpg"))
            if len(all_frames) < 2:
                continue
            n = len(all_frames)
            indices = sorted({0, n // 4, n // 2, 3 * n // 4, n - 1})
            frames = [all_frames[i] for i in indices]
            camera = w["camera"]

        windows.append(Window(
            window_id=wid,
            camera=w["camera"],
            category=cat,
            frames=frames,
            justificativa=(w.get("metadata") or {}).get("justificativa", "")[:120],
            gate_evidence=((w.get("pass1") or {}).get("evidence_summary") or "")[:200],
        ))
    return windows


def run_detail(window: Window, prompt_version: str) -> dict:
    ctx = CAMERA_CONTEXT.get(window.camera, {})
    request_id = f"bench15-{window.window_id[:10]}-{prompt_version[:6]}-{uuid.uuid4().hex[:4]}"
    t0 = time.monotonic()
    try:
        result = analyze_with_gemini(
            image_paths=window.frames,
            camera_context=ctx,
            request_id=request_id,
            mosaic_mode="off",
            prior_window_context=None,
            prompt_version=prompt_version,
        )
        wall_ms = int((time.monotonic() - t0) * 1000)
        report = result.report
        usage = result.usage
        cost = (usage.input_tokens / 1_000_000 * PRICE_INPUT_PER_1M_USD
                + usage.output_tokens / 1_000_000 * PRICE_OUTPUT_PER_1M_USD)
        return {
            "ok": True,
            "prompt_version": prompt_version,
            "infraction_confirmed": bool(report.infraction_confirmed),
            "confidence": int(report.confidence_0_100),
            "waste_type": report.waste_type,
            "fp_pattern_match": getattr(report, "fp_pattern_match", None),
            "audit_rationale": getattr(report, "audit_rationale", None),
            "evidence_summary": (report.evidence_summary or "")[:200],
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "latency_ms": result.latency_ms,
            "wall_ms": wall_ms,
            "cost_usd": round(cost, 6),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "prompt_version": prompt_version, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()

    windows = build_windows_from_gate_hits()
    if args.smoke:
        windows = windows[:3]
    elif args.limit:
        windows = windows[:args.limit]

    print(f"Windows selecionadas: {len(windows)}", flush=True)
    cats = {}
    for w in windows:
        cats[w.category] = cats.get(w.category, 0) + 1
    for k, v in cats.items():
        print(f"  {k}: {v}")
    print()

    arms = ["audit_v2"]
    print(f"Total: {len(windows)} × {len(arms)} (audit_v2 only) = "
          f"{len(windows)*len(arms)} chamadas\n", flush=True)

    results: dict[str, list[dict]] = {a: [] for a in arms}
    for i, w in enumerate(windows, 1):
        print(f"[{i}/{len(windows)}] {w.window_id[:10]} ({w.category})", flush=True)
        for arm in arms:
            r = run_detail(w, arm)
            r.update({
                "window_id": w.window_id,
                "camera": w.camera,
                "category": w.category,
                "justificativa": w.justificativa,
            })
            results[arm].append(r)
            if r.get("ok"):
                print(f"   {arm:7s}: confirmed={r['infraction_confirmed']} conf={r['confidence']} "
                      f"fp_pattern={r.get('fp_pattern_match','-')} cost=${r['cost_usd']:.4f}")
            else:
                print(f"   {arm:7s}: ERROR {r.get('error','')[:80]}")

    out_dir = CAMPAIGN_DIR
    for arm in arms:
        out_path = out_dir / f"results-{arm}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump({"arm": arm, "windows": results[arm]}, f, ensure_ascii=False, indent=2)
        cost = sum(r.get("cost_usd", 0) for r in results[arm] if r.get("ok"))
        print(f"\n  → {out_path.name} (cost ${cost:.4f})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
