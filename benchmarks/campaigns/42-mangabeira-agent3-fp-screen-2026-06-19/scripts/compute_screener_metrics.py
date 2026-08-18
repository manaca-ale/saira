#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compute screener metrics per arm and emit a comparison table.

Reads results-*.json (from run_screener.py) and the eval manifest. For each arm:
  - TP-preservation %  = of gold=keep events, fraction the arm KEEPs   (recall guard; baseline=100)
  - FP-suppression % per subtype and overall = of gold=kill events, fraction the arm KILLs
  - TP lost (count), FP killed (count)
  - cost/event, latency p50, error count

SAIRA weighting: recall x3 -> the decision rule prefers max FP-suppression
subject to TP-preservation >= TP_FLOOR (default 95%).
"""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

CAMP = Path(__file__).resolve().parents[1]
TP_FLOOR = 95.0


def load_arm(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    return d["summary"], {r["event"]: r for r in d["results"]}


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", nargs="+", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=CAMP / "metrics.json")
    args = ap.parse_args()

    arms = []
    for p in args.results:
        summary, by_event = load_arm(p)
        # gold + subtype come from each result row (written by run_screener via manifest)
        keep_gold = [r for r in by_event.values() if r["gold"] == "keep"]
        kill_gold = [r for r in by_event.values() if r["gold"] == "kill"]
        tp_preserved = sum(1 for r in keep_gold if r.get("keep"))
        tp_lost = [r["event"] for r in keep_gold if not r.get("keep")]
        fp_killed = sum(1 for r in kill_gold if not r.get("keep"))

        by_sub = defaultdict(lambda: [0, 0])  # subtype -> [killed, total] among gold=kill
        for r in kill_gold:
            s = r.get("subtype", "?")
            by_sub[s][1] += 1
            if not r.get("keep"):
                by_sub[s][0] += 1

        lat = [r.get("latency_ms", 0) for r in by_event.values() if r.get("ok")]
        errs = sum(1 for r in by_event.values() if not r.get("ok"))
        cost = sum(r.get("cost_usd", 0) or 0 for r in by_event.values())

        arms.append({
            "arm": summary.get("arm"),
            "provider": summary.get("provider"),
            "model": summary.get("model"),
            "n_events": len(by_event),
            "n_keep_gold": len(keep_gold),
            "n_kill_gold": len(kill_gold),
            "tp_preservation_pct": pct(tp_preserved, len(keep_gold)),
            "tp_lost_count": len(tp_lost),
            "tp_lost_events": tp_lost,
            "fp_suppression_overall_pct": pct(fp_killed, len(kill_gold)),
            "fp_killed_count": fp_killed,
            "fp_suppression_by_subtype": {s: {"killed": v[0], "total": v[1], "pct": pct(v[0], v[1])}
                                          for s, v in sorted(by_sub.items())},
            "cost_total_usd": round(cost, 6),
            "cost_per_event_usd": round(cost / max(1, len(by_event)), 6),
            "latency_p50_ms": int(statistics.median(lat)) if lat else 0,
            "errors": errs,
            "passes_tp_floor": pct(tp_preserved, len(keep_gold)) >= TP_FLOOR,
        })

    args.out.write_text(json.dumps({"tp_floor": TP_FLOOR, "arms": arms},
                                   ensure_ascii=False, indent=2), encoding="utf-8")

    # console table
    print(f"\n{'arm':22s} {'TP-pres%':>8s} {'TPlost':>6s} {'FP-supp%':>8s} {'FPkill':>6s} "
          f"{'$/ev':>9s} {'p50ms':>7s} {'err':>4s} floor")
    print("-" * 92)
    for a in arms:
        print(f"{a['arm']:22s} {a['tp_preservation_pct']:>8.1f} {a['tp_lost_count']:>6d} "
              f"{a['fp_suppression_overall_pct']:>8.1f} {a['fp_killed_count']:>6d} "
              f"{a['cost_per_event_usd']:>9.5f} {a['latency_p50_ms']:>7d} {a['errors']:>4d} "
              f"{'PASS' if a['passes_tp_floor'] else 'FAIL'}")
    print("\nFP-suppression by subtype:")
    for a in arms:
        subs = " | ".join(f"{s}:{v['pct']}%({v['killed']}/{v['total']})"
                          for s, v in a["fp_suppression_by_subtype"].items())
        print(f"  {a['arm']:22s} {subs}")
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
