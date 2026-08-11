#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Combine the LLM screener veto with the Camp-41 structural-delta veto.

Hypothesis: KILL only when BOTH the LLM says "not a real disposal" AND the pixels
say "the pile did not structurally change" (census_ntiles_t32 < thr). A real
deposit usually trips the structural signal (pile grew), so the intersection
should preserve recall better than either veto alone.

Compares, at the SAITA recall floor (TP-preservation >= 95%):
  - structural alone   (KILL iff census < thr_s)
  - LLM alone          (KILL iff is_real=false AND conf >= T)
  - intersection       (KILL iff LLM-kill AND structural-kill)
  - union              (KILL iff LLM-kill OR  structural-kill)
"""
import argparse
import json
from pathlib import Path

CAMP = Path(__file__).resolve().parents[1]
REVIRA = {"revira_explicit", "revira_mexe"}
FLOOR = 95.0


def load_llm(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for r in d["results"]:
        if not r.get("ok"):
            continue
        v = r.get("verdict") or {}
        out[r["event"]] = {"is_false": not bool(v.get("is_real_new_disposal", True)),
                           "conf": int(v.get("confidence_0_100", 0) or 0)}
    return out


def load_struct(path):
    import csv
    out = {}
    for r in csv.DictReader(Path(path).open(encoding="utf-8")):
        out[r["event_id"]] = {"census": int(r["census_ntiles_t32"]),
                              "gold": r["gold"], "subtype": r["subtype"]}
    return out


def metrics(events, kill_fn):
    keep = [e for e in events if e["gold"] == "keep"]
    kill = [e for e in events if e["gold"] == "kill"]
    rev = [e for e in kill if e["subtype"] in REVIRA]
    tp_pres = 100.0 * sum(1 for e in keep if not kill_fn(e)) / max(1, len(keep))
    tp_lost = sum(1 for e in keep if kill_fn(e))
    fp_supp = 100.0 * sum(1 for e in kill if kill_fn(e)) / max(1, len(kill))
    rev_supp = 100.0 * sum(1 for e in rev if kill_fn(e)) / max(1, len(rev))
    return tp_pres, tp_lost, fp_supp, rev_supp


def best_at_floor(events, make_fn, grid):
    """grid: list of param tuples. Returns the param maximizing fp_supp s.t. tp_pres>=FLOOR."""
    best = None
    for params in grid:
        tp_pres, tp_lost, fp_supp, rev_supp = metrics(events, make_fn(*params))
        if tp_pres >= FLOOR:
            cand = (fp_supp, params, tp_pres, tp_lost, rev_supp)
            if best is None or cand[0] > best[0]:
                best = cand
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default=str(CAMP / "results" / "haiku.json"))
    ap.add_argument("--struct", default=str(CAMP / "struct_scores.csv"))
    ap.add_argument("--label", default="haiku")
    args = ap.parse_args()

    llm = load_llm(args.llm)
    struct = load_struct(args.struct)
    events = []
    for eid, s in struct.items():
        l = llm.get(eid)
        if not l:
            continue
        events.append({"event": eid, "gold": s["gold"], "subtype": s["subtype"],
                       "census": s["census"], "is_false": l["is_false"], "conf": l["conf"]})
    print(f"joined events: {len(events)} (llm={len(llm)} struct={len(struct)})")

    thr_grid = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20]
    T_grid = [0, 50, 60, 70, 75, 80, 85, 90]

    # strategy fns
    def struct_only(thr): return lambda e: e["census"] < thr
    def llm_only(T): return lambda e: e["is_false"] and e["conf"] >= T
    def inter(T, thr): return lambda e: (e["is_false"] and e["conf"] >= T) and (e["census"] < thr)
    def union(T, thr): return lambda e: (e["is_false"] and e["conf"] >= T) or (e["census"] < thr)

    print(f"\n=== best operating point @ TP-preservation >= {FLOOR}% ({args.label}) ===")
    print(f"{'strategy':16s} {'FP-supp%':>8s} {'revira%':>8s} {'TP-pres%':>8s} {'TPlost':>6s} params")

    b = best_at_floor(events, struct_only, [(t,) for t in thr_grid])
    if b: print(f"{'structural':16s} {b[0]:>8.1f} {b[4]:>8.1f} {b[2]:>8.1f} {b[3]:>6d} thr_s={b[1][0]}")
    b = best_at_floor(events, llm_only, [(t,) for t in T_grid])
    if b: print(f"{args.label+' only':16s} {b[0]:>8.1f} {b[4]:>8.1f} {b[2]:>8.1f} {b[3]:>6d} T={b[1][0]}")
    b = best_at_floor(events, inter, [(T, thr) for T in T_grid for thr in thr_grid])
    if b: print(f"{'intersection':16s} {b[0]:>8.1f} {b[4]:>8.1f} {b[2]:>8.1f} {b[3]:>6d} T={b[1][0]} thr_s={b[1][1]}")
    b = best_at_floor(events, union, [(T, thr) for T in T_grid for thr in thr_grid])
    if b: print(f"{'union':16s} {b[0]:>8.1f} {b[4]:>8.1f} {b[2]:>8.1f} {b[3]:>6d} T={b[1][0]} thr_s={b[1][1]}")

    # full intersection grid table (T=0 = any LLM-false) for transparency
    print(f"\n=== intersection detail (T=0, KILL iff LLM-false AND census<thr_s) ===")
    print(f"{'thr_s':>5s} {'TP-pres%':>8s} {'TPlost':>6s} {'FP-supp%':>8s} {'revira%':>8s}")
    for thr in thr_grid:
        tp_pres, tp_lost, fp_supp, rev_supp = metrics(events, inter(0, thr))
        flag = "  <-floor" if tp_pres >= FLOOR else ""
        print(f"{thr:>5d} {tp_pres:>8.1f} {tp_lost:>6d} {fp_supp:>8.1f} {rev_supp:>8.1f}{flag}")


if __name__ == "__main__":
    main()
