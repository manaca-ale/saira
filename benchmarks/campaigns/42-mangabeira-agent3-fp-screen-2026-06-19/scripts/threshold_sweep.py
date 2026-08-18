#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Operating-point sweep for a screener arm.

The raw decision (KILL iff is_real_new_disposal==false) is maximally aggressive.
A safer rule kills only when the model is CONFIDENT it is not a real disposal:

    KILL iff (is_real_new_disposal == false) AND (confidence_0_100 >= T)

Higher T -> fewer kills -> higher TP-preservation, lower FP-suppression. This
sweeps T and reports, per threshold, TP-preservation and FP-suppression (overall
and for the revira target), so we can pick the operating point that keeps
TP-preservation >= the SAIRA floor (95%).
"""
import argparse
import json
from pathlib import Path

REVIRA = {"revira_explicit", "revira_mexe"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, type=Path)
    ap.add_argument("--floor", type=float, default=95.0)
    args = ap.parse_args()

    d = json.loads(args.results.read_text(encoding="utf-8"))
    arm = d["summary"]["arm"]
    rows = [r for r in d["results"] if r.get("ok")]
    keep_gold = [r for r in rows if r["gold"] == "keep"]
    kill_gold = [r for r in rows if r["gold"] == "kill"]
    revira_gold = [r for r in kill_gold if r.get("subtype") in REVIRA]

    def conf(r):
        return int((r.get("verdict") or {}).get("confidence_0_100", 0) or 0)

    def is_false(r):
        return not bool((r.get("verdict") or {}).get("is_real_new_disposal", True))

    print(f"\n=== {arm} — operating-point sweep (KILL iff not-real AND conf>=T) ===")
    print(f"{'T':>4s} {'TP-pres%':>8s} {'TPlost':>6s} {'FP-supp%':>8s} {'revira-supp%':>12s}")
    best = None
    for T in [0, 50, 60, 70, 75, 80, 85, 90, 95, 100]:
        def killed(r):
            return is_false(r) and conf(r) >= T
        tp_pres = 100.0 * sum(1 for r in keep_gold if not killed(r)) / max(1, len(keep_gold))
        tp_lost = sum(1 for r in keep_gold if killed(r))
        fp_supp = 100.0 * sum(1 for r in kill_gold if killed(r)) / max(1, len(kill_gold))
        rev_supp = 100.0 * sum(1 for r in revira_gold if killed(r)) / max(1, len(revira_gold))
        mark = "  <- floor" if tp_pres >= args.floor and (best is None) else ""
        if tp_pres >= args.floor and best is None:
            best = {"T": T, "tp_pres": round(tp_pres, 1), "tp_lost": tp_lost,
                    "fp_supp": round(fp_supp, 1), "revira_supp": round(rev_supp, 1)}
        print(f"{T:>4d} {tp_pres:>8.1f} {tp_lost:>6d} {fp_supp:>8.1f} {rev_supp:>12.1f}{mark}")
    print(f"\nbest operating point (TP-pres >= {args.floor}): {best}")
    return best


if __name__ == "__main__":
    main()
