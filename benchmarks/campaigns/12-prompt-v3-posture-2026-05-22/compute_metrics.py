#!/usr/bin/env python3
"""compute_metrics.py — Compute metrics for campaign 12 (V3 posture vs V2 baseline).

Reads results-{A_v2_baseline,B_v3_posture}.json from bench_prompt_v3_posture.py.

PASS criteria from run-config.yaml:
- V3 TP recall >= 35.0%        (V1 baseline level — must recover what V2 lost)
- V3 FP rate <= 21.42%         (V2 baseline 16.42% + 5pp tolerance)
- V3 recall delta vs V2 >= 0pp (no regression)
- V3 must pass 3 golden cases:
  - 48350bb4 (TP pano branco) → detected
  - 12506543 (TP pedestre)    → detected
  - d00a79bd (TP uniforme)    → detected

All four must pass → recommend V3 for next-step canary.
Any failure → write follow-up doc.

Also computes per-camera split, per-event flip table V2→V3, and posture
distribution to verify V3 is using person_position_signature correctly.

Output:
- metrics.json
- Rewrites <!-- metrics-start --> ... <!-- metrics-end --> in report.md
"""
from __future__ import annotations

import json
import re as _re
import sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CAMPAIGN_DIR = Path(__file__).parent
DETAIL_COST_PER_CALL_USD = 0.005

ARMS = ["A_v2_baseline", "B_v3_posture"]

PASS_CRITERIA = {
    "tp_recall_min_pct": 35.0,
    "fp_rate_max_pct": 21.42,
    "recall_delta_min_pp": 0.0,
}

GOLDEN_CASES = [
    {
        "id": "48350bb4-b72c-4bc1-aeaa-89bc00d1595c",
        "category": "tp",
        "reason": "TP pano branco (descarte pedestre noturno)",
        "expected_detected": True,
    },
    {
        "id": "12506543-1c64-4604-8c76-a85300a43669",
        "category": "tp",
        "reason": "TP pedestre puro (3 homens)",
        "expected_detected": True,
    },
    {
        "id": "d00a79bd-4052-4406-986f-01707b7fc713",
        "category": "tp",
        "reason": "TP uniforme laranja",
        "expected_detected": True,
    },
]


def load_arm(arm: str) -> dict:
    path = CAMPAIGN_DIR / f"results-{arm}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(p / 100.0 * (len(s) - 1))))
    return float(s[idx])


def compute_arm_metrics(data: dict) -> dict:
    windows = data.get("windows", [])
    if not windows:
        return {"error": "no windows"}

    positives = [w for w in windows if w["category"] in ("tp", "missed")]
    negatives_fp = [w for w in windows if w["category"] == "fp"]
    negatives_baseline = [w for w in windows if w["category"] == "baseline"]
    indefinidos = [w for w in windows if w["category"] == "indefinido"]
    tp_only = [w for w in windows if w["category"] == "tp"]
    missed_only = [w for w in windows if w["category"] == "missed"]

    n_pos = len(positives)
    n_neg_fp = len(negatives_fp)
    n_neg_baseline = len(negatives_baseline)
    n_neg_total = n_neg_fp + n_neg_baseline

    def _det(w: dict) -> bool:
        return bool(w.get("final_new_litter_detected", False))

    tp_hits = sum(1 for w in positives if _det(w))
    tp_recall = (tp_hits / n_pos * 100.0) if n_pos > 0 else 0.0

    tp_only_hits = sum(1 for w in tp_only if _det(w))
    tp_only_recall = (tp_only_hits / len(tp_only) * 100.0) if tp_only else 0.0

    missed_hits = sum(1 for w in missed_only if _det(w))
    missed_recall = (missed_hits / len(missed_only) * 100.0) if missed_only else 0.0

    fp_fp_hits = sum(1 for w in negatives_fp if _det(w))
    fp_fp_rate = (fp_fp_hits / n_neg_fp * 100.0) if n_neg_fp > 0 else 0.0

    fp_baseline_hits = sum(1 for w in negatives_baseline if _det(w))
    fp_baseline_rate = (fp_baseline_hits / n_neg_baseline * 100.0) if n_neg_baseline > 0 else 0.0

    fp_total_hits = fp_fp_hits + fp_baseline_hits
    fp_rate_total = (fp_total_hits / n_neg_total * 100.0) if n_neg_total > 0 else 0.0

    indef_hits = sum(1 for w in indefinidos if _det(w))
    indef_trigger_rate = (indef_hits / len(indefinidos) * 100.0) if indefinidos else 0.0

    total_cost = sum(w.get("total_cost_usd", 0.0) for w in windows)
    n_ok = sum(1 for w in windows if w.get("final_ok", False))
    cost_per_call = (total_cost / n_ok) if n_ok > 0 else 0.0

    latencies = [w.get("total_latency_ms", 0) for w in windows if w.get("final_ok")]
    lat_p50 = percentile(latencies, 50)
    lat_p95 = percentile(latencies, 95)

    n_detail_calls = sum(1 for w in windows if _det(w))
    detail_spillover_cost = n_detail_calls * DETAIL_COST_PER_CALL_USD
    blended_cost = total_cost + detail_spillover_cost
    blended_per_window = blended_cost / len(windows) if windows else 0.0

    # Per-camera split.
    by_camera: dict[str, dict] = {}
    for cam in ("cam_mangabeira", "cam_imbiribeira"):
        cam_pos = [w for w in positives if w["camera"] == cam]
        cam_neg = [w for w in negatives_fp if w["camera"] == cam]
        n_cp = len(cam_pos)
        n_cn = len(cam_neg)
        by_camera[cam] = {
            "tp_hits": sum(1 for w in cam_pos if _det(w)),
            "tp_total": n_cp,
            "tp_recall_pct": round((sum(1 for w in cam_pos if _det(w)) / n_cp * 100.0) if n_cp else 0, 2),
            "fp_hits": sum(1 for w in cam_neg if _det(w)),
            "fp_total": n_cn,
            "fp_rate_pct": round((sum(1 for w in cam_neg if _det(w)) / n_cn * 100.0) if n_cn else 0, 2),
        }

    # Posture distribution (V3 only — V2 returns None here).
    posture_counter: Counter = Counter()
    for w in windows:
        p1 = w.get("pass1") or {}
        posture = p1.get("person_position_signature")
        if posture:
            posture_counter[posture] += 1

    return {
        "arm": data.get("arm"),
        "spec": data.get("spec"),
        "n_windows": len(windows),
        "n_ok": n_ok,
        "n_err": len(windows) - n_ok,
        "categories": {
            "positives_total": n_pos,
            "tp_catalogued": len(tp_only),
            "missed": len(missed_only),
            "negatives_fp": n_neg_fp,
            "negatives_baseline": n_neg_baseline,
            "negatives_total": n_neg_total,
            "indefinidos": len(indefinidos),
        },
        "recall": {
            "tp_hits_total": tp_hits,
            "tp_recall_pct": round(tp_recall, 2),
            "tp_only_hits": tp_only_hits,
            "tp_only_recall_pct": round(tp_only_recall, 2),
            "missed_hits": missed_hits,
            "missed_recall_pct": round(missed_recall, 2),
        },
        "fp": {
            "fp_in_fp_category_hits": fp_fp_hits,
            "fp_in_fp_category_rate_pct": round(fp_fp_rate, 2),
            "fp_in_baseline_hits": fp_baseline_hits,
            "fp_in_baseline_rate_pct": round(fp_baseline_rate, 2),
            "fp_total_hits": fp_total_hits,
            "fp_total_rate_pct": round(fp_rate_total, 2),
        },
        "indefinido": {
            "trigger_count": indef_hits,
            "trigger_rate_pct": round(indef_trigger_rate, 2),
        },
        "cost": {
            "total_usd": round(total_cost, 5),
            "per_call_usd": round(cost_per_call, 6),
            "detail_spillover_usd": round(detail_spillover_cost, 4),
            "blended_total_usd": round(blended_cost, 4),
            "blended_per_window_usd": round(blended_per_window, 5),
            "n_detail_calls_triggered": n_detail_calls,
        },
        "latency_ms": {
            "p50": int(lat_p50),
            "p95": int(lat_p95),
            "mean": int(sum(latencies) / len(latencies)) if latencies else 0,
        },
        "by_camera": by_camera,
        "posture_distribution": dict(posture_counter),
    }


def check_golden_cases(data: dict) -> list[dict]:
    windows = {w["window_id"]: w for w in data.get("windows", [])}
    results = []
    for golden in GOLDEN_CASES:
        w = windows.get(golden["id"])
        if w is None:
            results.append({**golden, "found": False, "passed": False, "actual": None})
            continue
        actual = bool(w.get("final_new_litter_detected", False))
        results.append({
            **golden,
            "found": True,
            "actual_detected": actual,
            "passed": actual == golden["expected_detected"],
            "confidence": w.get("final_confidence"),
            "scene_type": (w.get("pass1") or {}).get("scene_type"),
            "posture": (w.get("pass1") or {}).get("person_position_signature"),
            "evidence": ((w.get("pass1") or {}).get("evidence_summary") or "")[:140],
        })
    return results


def evaluate_pass(metrics_a: dict, metrics_b: dict, golden_b: list[dict]) -> dict:
    tp_a = metrics_a["recall"]["tp_recall_pct"]
    tp_b = metrics_b["recall"]["tp_recall_pct"]
    fp_b = metrics_b["fp"]["fp_total_rate_pct"]
    delta = tp_b - tp_a

    recall_abs_pass = tp_b >= PASS_CRITERIA["tp_recall_min_pct"]
    recall_delta_pass = delta >= PASS_CRITERIA["recall_delta_min_pp"]
    fp_pass = fp_b <= PASS_CRITERIA["fp_rate_max_pct"]
    golden_pass = all(g["passed"] for g in golden_b if g.get("found"))
    all_golden_found = all(g.get("found") for g in golden_b)

    overall = recall_abs_pass and recall_delta_pass and fp_pass and golden_pass and all_golden_found

    return {
        "tp_recall_abs": {
            "value_pct": tp_b,
            "threshold_pct": PASS_CRITERIA["tp_recall_min_pct"],
            "rule": f"B_v3 TP recall >= {PASS_CRITERIA['tp_recall_min_pct']}%",
            "pass": recall_abs_pass,
        },
        "tp_recall_delta": {
            "value_pp": round(delta, 2),
            "threshold_pp": PASS_CRITERIA["recall_delta_min_pp"],
            "rule": "B-A >= 0pp (no regression vs V2)",
            "pass": recall_delta_pass,
        },
        "fp_rate": {
            "value_pct": fp_b,
            "threshold_pct": PASS_CRITERIA["fp_rate_max_pct"],
            "rule": f"B_v3 FP rate <= {PASS_CRITERIA['fp_rate_max_pct']}%",
            "pass": fp_pass,
        },
        "golden_cases": {
            "n_total": len(golden_b),
            "n_passed": sum(1 for g in golden_b if g.get("passed")),
            "n_found": sum(1 for g in golden_b if g.get("found")),
            "rule": "All 3 golden cases match expected",
            "pass": golden_pass and all_golden_found,
            "details": golden_b,
        },
        "overall_pass": overall,
    }


def format_comparison_table(a: dict, b: dict, decision: dict) -> str:
    lines = ["| Métrica | A_v2_baseline | B_v3_posture | Δ (B-A) | Regra | Veredito |"]
    lines.append("|---------|----------------|----------------|----------|-------|----------|")

    def fmt(v):
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    rows = [
        ("**TP recall total (%)**",
         a["recall"]["tp_recall_pct"], b["recall"]["tp_recall_pct"],
         f"{decision['tp_recall_delta']['value_pp']:+.1f}pp",
         f"B >= {PASS_CRITERIA['tp_recall_min_pct']}%",
         "✅" if decision["tp_recall_abs"]["pass"] else "❌"),
        ("  delta vs A",
         "—", f"{decision['tp_recall_delta']['value_pp']:+.1f}pp", "—",
         f"B-A >= {PASS_CRITERIA['recall_delta_min_pp']}pp",
         "✅" if decision["tp_recall_delta"]["pass"] else "❌"),
        ("  TP só catalogados",
         a["recall"]["tp_only_recall_pct"], b["recall"]["tp_only_recall_pct"], "—",
         "(informativo)", "—"),
        ("  Missed recall",
         a["recall"]["missed_recall_pct"], b["recall"]["missed_recall_pct"], "—", "—", "—"),
        ("**FP rate total (%)**",
         a["fp"]["fp_total_rate_pct"], b["fp"]["fp_total_rate_pct"],
         f"{b['fp']['fp_total_rate_pct'] - a['fp']['fp_total_rate_pct']:+.1f}pp",
         f"B <= {PASS_CRITERIA['fp_rate_max_pct']}%",
         "✅" if decision["fp_rate"]["pass"] else "❌"),
        ("  FP só catalogados",
         a["fp"]["fp_in_fp_category_rate_pct"], b["fp"]["fp_in_fp_category_rate_pct"], "—", "—", "—"),
        ("  FP em baseline",
         a["fp"]["fp_in_baseline_rate_pct"], b["fp"]["fp_in_baseline_rate_pct"], "—", "—", "—"),
        ("Indef trigger rate",
         a["indefinido"]["trigger_rate_pct"], b["indefinido"]["trigger_rate_pct"], "—",
         "informativo", "—"),
        ("Gate cost total (USD)",
         a["cost"]["total_usd"], b["cost"]["total_usd"], "—", "—", "—"),
        ("**Blended cost (USD)**",
         a["cost"]["blended_total_usd"], b["cost"]["blended_total_usd"], "—", "(informativo)", "—"),
        ("Latency p50 (ms)",
         a["latency_ms"]["p50"], b["latency_ms"]["p50"], "—", "—", "—"),
        ("Latency p95 (ms)",
         a["latency_ms"]["p95"], b["latency_ms"]["p95"], "—", "—", "—"),
    ]
    for r in rows:
        lines.append(f"| {r[0]} | {fmt(r[1])} | {fmt(r[2])} | {r[3]} | {r[4]} | {r[5]} |")
    return "\n".join(lines)


def format_golden_table(golden_results: list[dict]) -> str:
    lines = ["| Golden case | Esperado | B_v3 retornou | Veredito | Posture | Razão |"]
    lines.append("|-------------|----------|----------------|----------|---------|-------|")
    for g in golden_results:
        eid = g["id"][:8]
        expected = "✅ detected" if g["expected_detected"] else "❌ rejected"
        if not g.get("found"):
            actual = "(não encontrado)"
            verdict = "❌"
            posture = "—"
        else:
            actual = ("✅ detected" if g["actual_detected"] else "❌ rejected") + f" (conf={g.get('confidence')})"
            verdict = "✅" if g["passed"] else "❌"
            posture = g.get("posture") or "—"
        lines.append(f"| {eid} | {expected} | {actual} | {verdict} | {posture} | {g['reason']} |")
    return "\n".join(lines)


def format_per_camera_table(a: dict, b: dict) -> str:
    lines = ["| Câmera | A TP recall | B TP recall | Δ | A FP rate | B FP rate | Δ |"]
    lines.append("|--------|--------------|--------------|----|------------|------------|----|")
    for cam in ("cam_mangabeira", "cam_imbiribeira"):
        ca = a["by_camera"].get(cam, {})
        cb = b["by_camera"].get(cam, {})
        if not ca or not cb:
            continue
        d_tp = cb["tp_recall_pct"] - ca["tp_recall_pct"]
        d_fp = cb["fp_rate_pct"] - ca["fp_rate_pct"]
        lines.append(
            f"| {cam} | {ca['tp_recall_pct']:.1f}% ({ca['tp_hits']}/{ca['tp_total']}) "
            f"| {cb['tp_recall_pct']:.1f}% ({cb['tp_hits']}/{cb['tp_total']}) "
            f"| {d_tp:+.1f}pp "
            f"| {ca['fp_rate_pct']:.1f}% ({ca['fp_hits']}/{ca['fp_total']}) "
            f"| {cb['fp_rate_pct']:.1f}% ({cb['fp_hits']}/{cb['fp_total']}) "
            f"| {d_fp:+.1f}pp |"
        )
    return "\n".join(lines)


def format_posture_distribution(b: dict) -> str:
    posture = b.get("posture_distribution") or {}
    if not posture:
        return "_(V3 não retornou posture — verificar smoke)_"
    lines = ["| Posture (V3) | N windows |"]
    lines.append("|--------------|-----------|")
    for k, v in sorted(posture.items(), key=lambda x: -x[1]):
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def diff_per_window(arm_a: dict, arm_b: dict) -> list[dict]:
    a_by_id = {w["window_id"]: w for w in arm_a.get("windows", [])}
    b_by_id = {w["window_id"]: w for w in arm_b.get("windows", [])}

    flips = []
    for wid in sorted(set(a_by_id) | set(b_by_id)):
        wa = a_by_id.get(wid)
        wb = b_by_id.get(wid)
        if not wa or not wb:
            continue
        da = bool(wa.get("final_new_litter_detected"))
        db = bool(wb.get("final_new_litter_detected"))
        if da == db:
            continue
        cat = wa.get("category")
        if da is False and db is True:
            kind = ("gain_pos" if cat in ("tp", "missed")
                    else "gain_fp" if cat in ("fp", "baseline")
                    else "gain_indef")
        else:
            kind = ("loss_pos" if cat in ("tp", "missed")
                    else "loss_fp" if cat in ("fp", "baseline")
                    else "loss_indef")
        flips.append({
            "window_id": wid,
            "camera": wa.get("camera"),
            "category": cat,
            "kind": kind,
            "a_detected": da,
            "b_detected": db,
            "justificativa": (wa.get("metadata") or {}).get("justificativa", "")[:80],
            "b_posture": (wb.get("pass1") or {}).get("person_position_signature"),
            "b_evidence": ((wb.get("pass1") or {}).get("evidence_summary") or "")[:140],
        })
    return flips


def format_flip_summary(flips: list[dict]) -> str:
    buckets: dict[str, list[dict]] = {}
    for f in flips:
        buckets.setdefault(f["kind"], []).append(f)
    titles = {
        "gain_pos": "✅ TPs/Missed que V3 recuperou (V2 perdeu, V3 pegou) — DESEJADO",
        "loss_pos": "🔴 TPs/Missed que V3 perdeu (V2 pegava, V3 não) — REGRESSÃO",
        "gain_fp": "🟡 FPs/baseline novos do V3 (V2 rejeitava, V3 confirma) — REGRESSÃO",
        "loss_fp": "✅ FPs/baseline que V3 rejeitou (V2 confirmava, V3 rejeita) — DESEJADO",
        "gain_indef": "🟡 Indef que V3 marcou (V2 não marcava)",
        "loss_indef": "✅ Indef que V3 parou de marcar (V2 marcava)",
    }
    out = []
    for k in ("gain_pos", "loss_pos", "gain_fp", "loss_fp", "gain_indef", "loss_indef"):
        items = buckets.get(k, [])
        if not items:
            continue
        out.append(f"\n#### {titles[k]} ({len(items)} eventos)\n")
        out.append("| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |")
        out.append("|----------|---------|-----------|---------------|------------|-------------|")
        for it in items:
            out.append(
                f"| {it['window_id'][:8]} | {it['camera']} | {it['category']} | "
                f"{it['justificativa']} | {it['b_posture'] or '—'} | {it['b_evidence']} |"
            )
    return "\n".join(out) if out else "_Nenhum flip entre V2 e V3._"


def rewrite_report_md(report_path: Path, metrics: dict, decision: dict, flips_text: str) -> None:
    text = report_path.read_text(encoding="utf-8")
    a = metrics["A_v2_baseline"]
    b = metrics["B_v3_posture"]

    if decision["overall_pass"]:
        status = (f"> ✅ **PASS** — V3 bate todos os critérios: "
                  f"TP recall {b['recall']['tp_recall_pct']:.1f}% "
                  f"(Δ {decision['tp_recall_delta']['value_pp']:+.1f}pp vs V2), "
                  f"FP rate {b['fp']['fp_total_rate_pct']:.1f}%, "
                  "3/3 golden cases. Recomendação: prosseguir para canary em prod.")
    else:
        fails = []
        if not decision["tp_recall_abs"]["pass"]:
            fails.append(f"TP recall {b['recall']['tp_recall_pct']:.1f}% < {PASS_CRITERIA['tp_recall_min_pct']}%")
        if not decision["tp_recall_delta"]["pass"]:
            fails.append(f"Δ recall {decision['tp_recall_delta']['value_pp']:+.1f}pp regrediu")
        if not decision["fp_rate"]["pass"]:
            fails.append(f"FP rate {b['fp']['fp_total_rate_pct']:.1f}% > {PASS_CRITERIA['fp_rate_max_pct']}%")
        if not decision["golden_cases"]["pass"]:
            np_ = decision["golden_cases"]["n_passed"]
            nt = decision["golden_cases"]["n_total"]
            fails.append(f"golden cases {np_}/{nt}")
        status = ("> ❌ **FAIL** — V3 não atingiu os critérios: " + ", ".join(fails) +
                  ". Não promover. Escrever follow-up doc com próximos passos.")

    lines = text.splitlines()
    for i in range(min(15, len(lines))):
        if lines[i].startswith("> "):
            lines[i] = status
            break
    else:
        lines.insert(2, status)
        lines.insert(3, "")
    text = "\n".join(lines)

    new_section = (
        "## Resultados\n\n"
        "<!-- metrics-start -->\n\n"
        "### Comparação A_v2_baseline vs B_v3_posture\n\n"
        f"{format_comparison_table(a, b, decision)}\n\n"
        "### Golden cases (PASS criterion)\n\n"
        f"{format_golden_table(decision['golden_cases']['details'])}\n\n"
        "### Por câmera\n\n"
        f"{format_per_camera_table(a, b)}\n\n"
        "### Distribuição de posture (V3)\n\n"
        f"{format_posture_distribution(b)}\n\n"
        "### Categorias do dataset\n\n"
        "| Categoria | N |\n"
        "|-----------|---|\n"
        f"| TP catalogados | {a['categories']['tp_catalogued']} |\n"
        f"| Missed | {a['categories']['missed']} |\n"
        f"| FP catalogados | {a['categories']['negatives_fp']} |\n"
        f"| Baseline | {a['categories']['negatives_baseline']} |\n"
        f"| Indefinido | {a['categories']['indefinidos']} |\n\n"
        "### Diffs por evento (V2 → V3)\n"
        f"{flips_text}\n\n"
        "<!-- metrics-end -->"
    )

    pattern = _re.compile(r"## Resultados.*?<!-- metrics-end -->", _re.DOTALL)
    if pattern.search(text):
        text = pattern.sub(new_section, text)
    else:
        text = text.replace("## Decisão", new_section + "\n\n---\n\n## Decisão")

    report_path.write_text(text, encoding="utf-8")


def main() -> int:
    print(f"Lendo resultados de {CAMPAIGN_DIR}...", flush=True)
    raw_data = {}
    metrics = {}
    for arm in ARMS:
        data = load_arm(arm)
        if not data:
            print(f"  ERR: results-{arm}.json não encontrado", file=sys.stderr)
            return 1
        raw_data[arm] = data
        metrics[arm] = compute_arm_metrics(data)

    golden_b = check_golden_cases(raw_data["B_v3_posture"])
    decision = evaluate_pass(metrics["A_v2_baseline"], metrics["B_v3_posture"], golden_b)
    flips = diff_per_window(raw_data["A_v2_baseline"], raw_data["B_v3_posture"])

    out_path = CAMPAIGN_DIR / "metrics.json"
    out_path.write_text(json.dumps({
        "arms": metrics,
        "pass_criteria": PASS_CRITERIA,
        "decision": decision,
        "flips": flips,
        "constants": {"detail_cost_per_call_usd": DETAIL_COST_PER_CALL_USD},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → metrics.json ({out_path.stat().st_size} bytes)")

    report_path = CAMPAIGN_DIR / "report.md"
    rewrite_report_md(report_path, metrics, decision, format_flip_summary(flips))
    print(f"  → report.md atualizado")

    print("\n=== Resumo ===")
    print(format_comparison_table(metrics["A_v2_baseline"], metrics["B_v3_posture"], decision))
    print()
    print(f"PASS overall: {'SIM' if decision['overall_pass'] else 'NAO'}")
    print(f"  TP recall abs: {decision['tp_recall_abs']['value_pct']:.2f}% — "
          f"{'PASS' if decision['tp_recall_abs']['pass'] else 'FAIL'}")
    print(f"  TP recall delta: {decision['tp_recall_delta']['value_pp']:+.2f}pp — "
          f"{'PASS' if decision['tp_recall_delta']['pass'] else 'FAIL'}")
    print(f"  FP rate: {decision['fp_rate']['value_pct']:.2f}% — "
          f"{'PASS' if decision['fp_rate']['pass'] else 'FAIL'}")
    print(f"  Golden cases: {decision['golden_cases']['n_passed']}/"
          f"{decision['golden_cases']['n_total']} — "
          f"{'PASS' if decision['golden_cases']['pass'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
