#!/usr/bin/env python3
"""compute_metrics.py — Compute metrics for campaign 11.

Reads results-{A_current,B_v2_patched}.json from bench_prompt_v2_promotion.py
and computes per-arm TP recall, FP rate (geral + por sub-categoria), cost, latency.

Evaluates the PASS criteria from run-config.yaml:
- B_v2_patched TP recall >= 25.0%        (V1 baseline ~15% on camp 08)
- B_v2_patched FP rate   <= 43.8%        (V1 baseline ~38.8% on camp 09)
- B_v2_patched recall delta vs A >= 10pp
- B_v2_patched must pass all 3 golden cases:
  - d00a79bd (TP uniforme)     → new_litter_detected=True
  - 12506543 (TP pedestre)     → new_litter_detected=True
  - fb4a2c50 (FP coleta truck) → new_litter_detected=False

All four conditions must pass → PASS, recommend PR to develop.
Any failure → FAIL, write follow-up doc.

Output:
- metrics.json (machine-readable)
- Rewrites <!-- metrics-start --> ... <!-- metrics-end --> in report.md
"""
from __future__ import annotations

import json
import re as _re
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CAMPAIGN_DIR = Path(__file__).parent

DETAIL_COST_PER_CALL_USD = 0.005

ARMS = ["A_current", "B_v2_patched"]

PASS_CRITERIA = {
    "tp_recall_min_pct": 25.0,
    "fp_rate_max_pct": 43.8,
    "recall_delta_min_pp": 10.0,
}

GOLDEN_CASES = [
    {
        "id": "d00a79bd-4052-4406-986f-01707b7fc713",
        "category": "tp",
        "reason": "TP uniforme — V2 deve detectar",
        "expected_detected": True,
    },
    {
        "id": "12506543-1c64-4604-8c76-a85300a43669",
        "category": "tp",
        "reason": "TP pedestre puro — V2 deve detectar",
        "expected_detected": True,
    },
    {
        "id": "fb4a2c50-8124-4055-9968-f1237817367b",
        "category": "fp",
        "reason": "FP coleta caminhão — V2 deve rejeitar",
        "expected_detected": False,
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

    pass1_input = [w["pass1"].get("input_tokens", 0) for w in windows if w["pass1"].get("ok")]
    pass1_billable = [w["pass1"].get("billable_output_tokens", 0) for w in windows if w["pass1"].get("ok")]
    pass1_thinking = [w["pass1"].get("thinking_tokens", 0) for w in windows if w["pass1"].get("ok")]
    pass1_n_frames = [w["pass1"].get("n_frames_sent", 0) for w in windows if w["pass1"].get("ok")]

    # Per-camera split (useful to detect Imbiribeira regression).
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
        "tokens_pass1": {
            "n_frames_mean": round(sum(pass1_n_frames) / len(pass1_n_frames), 2) if pass1_n_frames else 0,
            "input_mean": int(sum(pass1_input) / len(pass1_input)) if pass1_input else 0,
            "billable_output_mean": int(sum(pass1_billable) / len(pass1_billable)) if pass1_billable else 0,
            "thinking_mean": int(sum(pass1_thinking) / len(pass1_thinking)) if pass1_thinking else 0,
        },
        "by_camera": by_camera,
    }


def check_golden_cases(data: dict) -> list[dict]:
    """For each golden case, check whether the arm's prediction matches expected."""
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
            "scene_type": w["pass1"].get("scene_type"),
        })
    return results


def evaluate_pass(metrics_a: dict, metrics_b: dict, golden_b: list[dict]) -> dict:
    """Evaluate the 4-part PASS criterion for promoting V2."""
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
            "rule": "B_v2_patched TP recall >= 25.0%",
            "pass": recall_abs_pass,
        },
        "tp_recall_delta": {
            "value_pp": round(delta, 2),
            "threshold_pp": PASS_CRITERIA["recall_delta_min_pp"],
            "rule": "B - A >= 10pp",
            "pass": recall_delta_pass,
        },
        "fp_rate": {
            "value_pct": fp_b,
            "threshold_pct": PASS_CRITERIA["fp_rate_max_pct"],
            "rule": "B_v2_patched FP rate <= 43.8%",
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
    lines = ["| Métrica | A_current (V1) | B_v2_patched | Δ (B-A) | Regra | Veredito |"]
    lines.append("|---------|-----------------|---------------|----------|-------|----------|")

    def fmt(v):
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    rows = [
        ("Frames/janela (avg)", a["tokens_pass1"]["n_frames_mean"], b["tokens_pass1"]["n_frames_mean"], "—", "—", "—"),
        ("**TP recall total (%) [n=positivos]**",
         a["recall"]["tp_recall_pct"], b["recall"]["tp_recall_pct"],
         f"{decision['tp_recall_delta']['value_pp']:+.1f}pp",
         "B >= 25.0%",
         "✅" if decision["tp_recall_abs"]["pass"] else "❌"),
        ("  delta vs A",
         "—", f"{decision['tp_recall_delta']['value_pp']:+.1f}pp", "—",
         "B-A >= 10pp",
         "✅" if decision["tp_recall_delta"]["pass"] else "❌"),
        ("  TP recall só TP catalogados (%)",
         a["recall"]["tp_only_recall_pct"], b["recall"]["tp_only_recall_pct"], "—",
         "(informativo)", "—"),
        ("  Missed recall (%)",
         a["recall"]["missed_recall_pct"], b["recall"]["missed_recall_pct"], "—", "—", "—"),
        ("**FP rate total (%) [FP+baseline]**",
         a["fp"]["fp_total_rate_pct"], b["fp"]["fp_total_rate_pct"],
         f"{b['fp']['fp_total_rate_pct'] - a['fp']['fp_total_rate_pct']:+.1f}pp",
         "B <= 43.8%",
         "✅" if decision["fp_rate"]["pass"] else "❌"),
        ("  FP rate só FP catalogados (%)",
         a["fp"]["fp_in_fp_category_rate_pct"], b["fp"]["fp_in_fp_category_rate_pct"], "—", "—", "—"),
        ("  FP rate só baseline (%)",
         a["fp"]["fp_in_baseline_rate_pct"], b["fp"]["fp_in_baseline_rate_pct"], "—", "—", "—"),
        ("Indef trigger rate (%)",
         a["indefinido"]["trigger_rate_pct"], b["indefinido"]["trigger_rate_pct"], "—",
         "informativo (V2 ≠ suprimir todos)", "—"),
        ("Cost/call (USD)",
         a["cost"]["per_call_usd"], b["cost"]["per_call_usd"], "—", "(informativo)", "—"),
        ("Gate cost total (USD)",
         a["cost"]["total_usd"], b["cost"]["total_usd"], "—", "—", "—"),
        ("Detail spillover (USD)",
         a["cost"]["detail_spillover_usd"], b["cost"]["detail_spillover_usd"], "—", "—", "—"),
        ("**Blended cost (USD)**",
         a["cost"]["blended_total_usd"], b["cost"]["blended_total_usd"],
         "—", "(informativo)", "—"),
        ("Latency p50 (ms)",
         a["latency_ms"]["p50"], b["latency_ms"]["p50"], "—", "—", "—"),
        ("Latency p95 (ms)",
         a["latency_ms"]["p95"], b["latency_ms"]["p95"], "—", "—", "—"),
    ]
    for r in rows:
        lines.append(f"| {r[0]} | {fmt(r[1])} | {fmt(r[2])} | {r[3]} | {r[4]} | {r[5]} |")
    return "\n".join(lines)


def format_golden_table(golden_results: list[dict]) -> str:
    lines = ["| Golden case | Esperado | B_v2 retornou | Veredito | Razão |"]
    lines.append("|-------------|----------|----------------|----------|-------|")
    for g in golden_results:
        eid = g["id"][:8]
        expected = "✅ detected" if g["expected_detected"] else "❌ rejected"
        if not g.get("found"):
            actual = "(não encontrado)"
            verdict = "❌"
        else:
            actual = ("✅ detected" if g["actual_detected"] else "❌ rejected") + f" (conf={g.get('confidence')})"
            verdict = "✅" if g["passed"] else "❌"
        lines.append(f"| {eid} | {expected} | {actual} | {verdict} | {g['reason']} |")
    return "\n".join(lines)


def format_per_camera_table(metrics_a: dict, metrics_b: dict) -> str:
    lines = ["| Câmera | A TP recall | B TP recall | Δ | A FP rate | B FP rate | Δ |"]
    lines.append("|--------|--------------|--------------|----|------------|------------|----|")
    for cam in ("cam_mangabeira", "cam_imbiribeira"):
        a = metrics_a["by_camera"].get(cam, {})
        b = metrics_b["by_camera"].get(cam, {})
        if not a or not b:
            continue
        d_tp = b["tp_recall_pct"] - a["tp_recall_pct"]
        d_fp = b["fp_rate_pct"] - a["fp_rate_pct"]
        lines.append(
            f"| {cam} | {a['tp_recall_pct']:.1f}% ({a['tp_hits']}/{a['tp_total']}) "
            f"| {b['tp_recall_pct']:.1f}% ({b['tp_hits']}/{b['tp_total']}) "
            f"| {d_tp:+.1f}pp "
            f"| {a['fp_rate_pct']:.1f}% ({a['fp_hits']}/{a['fp_total']}) "
            f"| {b['fp_rate_pct']:.1f}% ({b['fp_hits']}/{b['fp_total']}) "
            f"| {d_fp:+.1f}pp |"
        )
    return "\n".join(lines)


def diff_per_window(arm_a: dict, arm_b: dict) -> list[dict]:
    """Compute per-window flip table: which TPs gained, which TPs lost, etc."""
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
            "b_evidence": (wb["pass1"].get("evidence_summary") or "")[:140],
        })
    return flips


def format_flip_summary(flips: list[dict]) -> str:
    buckets: dict[str, list[dict]] = {}
    for f in flips:
        buckets.setdefault(f["kind"], []).append(f)
    titles = {
        "gain_pos": "✅ TPs/Missed que B ganhou (V1 perdeu, V2 pegou) — ESPERADO",
        "loss_pos": "🔴 TPs/Missed que B perdeu (V1 pegou, V2 não) — REGRESSÃO",
        "gain_fp": "🟡 FPs/baseline que B passou a confirmar (V1 rejeitava, V2 confirma) — REGRESSÃO",
        "loss_fp": "✅ FPs/baseline que B rejeitou (V1 confirmava, V2 rejeita) — ESPERADO",
        "gain_indef": "🟡 Indef que B passou a marcar detected (V1 não marcava)",
        "loss_indef": "✅ Indef que B parou de marcar detected (V1 marcava)",
    }
    out = []
    for k in ("gain_pos", "loss_pos", "gain_fp", "loss_fp", "gain_indef", "loss_indef"):
        items = buckets.get(k, [])
        if not items:
            continue
        out.append(f"\n#### {titles[k]} ({len(items)} eventos)\n")
        out.append("| event_id | câmera | categoria | justificativa | B evidence |")
        out.append("|----------|---------|-----------|---------------|------------|")
        for it in items:
            out.append(
                f"| {it['window_id'][:8]} | {it['camera']} | {it['category']} | "
                f"{it['justificativa']} | {it['b_evidence']} |"
            )
    return "\n".join(out) if out else "_Nenhum flip entre A e B (todos os eventos têm a mesma classificação)._"


def rewrite_report_md(report_path: Path, metrics: dict, decision: dict, flips_text: str) -> None:
    text = report_path.read_text(encoding="utf-8")
    a = metrics["A_current"]
    b = metrics["B_v2_patched"]

    if decision["overall_pass"]:
        status = ("> ✅ **PASS** — V2 (com fix carroça) bate todos os 4 critérios: "
                  f"TP recall {b['recall']['tp_recall_pct']:.1f}% "
                  f"(Δ {decision['tp_recall_delta']['value_pp']:+.1f}pp), "
                  f"FP rate {b['fp']['fp_total_rate_pct']:.1f}%, "
                  "3/3 golden cases. Recomendação: abrir PR para `develop` e seguir fase 4 (canary).")
    else:
        fails = []
        if not decision["tp_recall_abs"]["pass"]:
            fails.append(f"TP recall {b['recall']['tp_recall_pct']:.1f}% < 25%")
        if not decision["tp_recall_delta"]["pass"]:
            fails.append(f"Δ recall {decision['tp_recall_delta']['value_pp']:+.1f}pp < 10pp")
        if not decision["fp_rate"]["pass"]:
            fails.append(f"FP rate {b['fp']['fp_total_rate_pct']:.1f}% > 43.8%")
        if not decision["golden_cases"]["pass"]:
            n_pass = decision["golden_cases"]["n_passed"]
            n_tot = decision["golden_cases"]["n_total"]
            fails.append(f"golden cases {n_pass}/{n_tot}")
        status = ("> ❌ **FAIL** — V2 não atingiu os critérios: " + ", ".join(fails) +
                  ". Não promover sem investigação. Escrever follow-up doc com hipóteses de fix.")

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
        "### Comparação A_current (V1) vs B_v2_patched (V2 com fix carroça)\n\n"
        f"{format_comparison_table(a, b, decision)}\n\n"
        "### Golden cases (PASS criterion)\n\n"
        f"{format_golden_table(decision['golden_cases']['details'])}\n\n"
        "### Por câmera (detectar regressão por geometria)\n\n"
        f"{format_per_camera_table(a, b)}\n\n"
        "### Categorias do dataset\n\n"
        "| Categoria | N |\n"
        "|-----------|---|\n"
        f"| TP catalogados | {a['categories']['tp_catalogued']} |\n"
        f"| Missed (sistema não capturou em prod) | {a['categories']['missed']} |\n"
        f"| FP catalogados | {a['categories']['negatives_fp']} |\n"
        f"| Baseline | {a['categories']['negatives_baseline']} |\n"
        f"| Indefinido | {a['categories']['indefinidos']} |\n\n"
        "### Diffs por evento (A → B)\n"
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

    golden_b = check_golden_cases(raw_data["B_v2_patched"])
    decision = evaluate_pass(metrics["A_current"], metrics["B_v2_patched"], golden_b)
    flips = diff_per_window(raw_data["A_current"], raw_data["B_v2_patched"])

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
    print(format_comparison_table(metrics["A_current"], metrics["B_v2_patched"], decision))
    print()
    print(f"PASS overall: {'SIM' if decision['overall_pass'] else 'NÃO'}")
    print(f"  TP recall abs: {decision['tp_recall_abs']['value_pct']:.2f}% >= "
          f"{decision['tp_recall_abs']['threshold_pct']:.1f}% — "
          f"{'PASS' if decision['tp_recall_abs']['pass'] else 'FAIL'}")
    print(f"  TP recall delta: {decision['tp_recall_delta']['value_pp']:+.2f}pp >= "
          f"{decision['tp_recall_delta']['threshold_pp']:.1f}pp — "
          f"{'PASS' if decision['tp_recall_delta']['pass'] else 'FAIL'}")
    print(f"  FP rate: {decision['fp_rate']['value_pct']:.2f}% <= "
          f"{decision['fp_rate']['threshold_pct']:.1f}% — "
          f"{'PASS' if decision['fp_rate']['pass'] else 'FAIL'}")
    print(f"  Golden cases: {decision['golden_cases']['n_passed']}/"
          f"{decision['golden_cases']['n_total']} — "
          f"{'PASS' if decision['golden_cases']['pass'] else 'FAIL'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
