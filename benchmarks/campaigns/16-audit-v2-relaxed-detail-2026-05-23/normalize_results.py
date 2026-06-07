#!/usr/bin/env python3
"""Normalize camp 15/16 bench output into the shape compute_metrics.py expects.

The audit bench (bench_detail_audit.py / bench_audit_v2.py) writes
{"arm": str, "windows": [...]} with flat per-window fields. The skill's
compute_metrics.py expects {"results": [...], "summary": {...}} with each
event having nested `gate`/`detail` and uppercase `ground_truth`.

This adapter reads camp 15's `results-current.json` + `results-audit.json`
AND camp 16's `results-audit_v2.json`, normalizes all three into the
expected shape, and writes them as `normalized-<arm>.json` in camp 16.
Then compute_metrics.py picks them up via the standard `results-*.json` glob.

(We rename the normalized outputs as `results-<arm>.json` so compute_metrics
sees them; the original camp 16 file stays as `raw-audit_v2.json` for audit.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CAMP16 = Path(__file__).parent
CAMP15 = CAMP16.parent / "15-detail-audit-2026-05-23"

# category (lowercase) → ground_truth (uppercase for compute_metrics)
CAT_TO_GT = {
    "tp": "TP",
    "fp": "FP",
    "baseline": "FP",  # baselines that pass the gate are functionally FPs
    "indefinido": "INDEF",
}


def normalize_event(window: dict) -> dict:
    """Reshape one camp 15/16 bench window into the compute_metrics event shape."""
    cat = window.get("category", "").lower()
    gt = CAT_TO_GT.get(cat, "?")

    # Bench has Detail-only metrics. There's no real gate cost in this campaign
    # (we reused gate hits from camp 12 V3). For the skill metrics:
    #   - gate_triggered = True (always — they're all gate hits)
    #   - gate.cost_usd = 0 (cost already counted in camp 12)
    #   - detail = the bench window's call
    detail_cost = float(window.get("cost_usd", 0.0) or 0.0)
    return {
        "event": window.get("window_id", ""),
        "ground_truth": gt,
        "fp_cause": window.get("justificativa") or None,
        "triggered": True,
        "gate": {
            "new_litter_detected": True,
            "confidence_0_100": None,
            "cost_usd": 0.0,
            "latency_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        },
        "detail": {
            "infraction_confirmed": bool(window.get("infraction_confirmed", False)),
            "confidence_0_100": int(window.get("confidence", 0) or 0),
            "cost_usd": detail_cost,
            "latency_ms": int(window.get("latency_ms", 0) or 0),
            "input_tokens": int(window.get("input_tokens", 0) or 0),
            "output_tokens": int(window.get("output_tokens", 0) or 0),
            "fp_pattern_match": window.get("fp_pattern_match"),
            "audit_rationale": window.get("audit_rationale"),
        },
        "total_cost_usd": detail_cost,
    }


def normalize_file(src: Path) -> dict:
    raw = json.loads(src.read_text(encoding="utf-8"))
    arm = raw.get("arm", src.stem)
    wins = raw.get("windows", [])
    events = [normalize_event(w) for w in wins if w.get("ok")]
    failed = [w for w in wins if not w.get("ok")]
    return {
        "summary": {
            "arm": arm,
            "n_total": len(wins),
            "n_ok": len(events),
            "n_failed": len(failed),
            "source_file": str(src),
        },
        "results": events,
    }


def main() -> int:
    pairs = [
        (CAMP15 / "results-current.json",  CAMP16 / "results-current.json"),
        (CAMP15 / "results-audit.json",    CAMP16 / "results-audit.json"),
        (CAMP16 / "results-audit_v2.json", CAMP16 / "results-audit_v2.json"),
    ]
    # results-audit_v2.json is BOTH source and destination — we want to keep
    # the original camp 16 raw output but ALSO have the normalized shape.
    # Solution: keep the original at raw-audit_v2.json, then overwrite
    # results-audit_v2.json with the normalized shape.
    raw16 = CAMP16 / "results-audit_v2.json"
    if not raw16.exists():
        print(f"ERR: {raw16} not found — run bench_audit_v2.py first", file=sys.stderr)
        return 1
    raw16.rename(CAMP16 / "raw-audit_v2.json")

    for src, dst in pairs:
        # For the audit_v2 arm, the source after rename is raw-audit_v2.json
        if src == raw16:
            src = CAMP16 / "raw-audit_v2.json"
        if not src.exists():
            print(f"WARN: source missing, skipping: {src}", file=sys.stderr)
            continue
        normalized = normalize_file(src)
        dst.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        s = normalized["summary"]
        print(f"OK: {dst.name} <- {src.name}  ({s['n_ok']}/{s['n_total']} ok)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
