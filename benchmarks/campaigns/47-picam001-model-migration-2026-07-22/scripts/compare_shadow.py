#!/usr/bin/env python3
"""Camp 47 — fecha a comparação Gemini-2.5 (prod) vs Gemini-3.1 (shadow) na pi-cam-001.

Era o follow-up pendente do HANDOFF_SHADOW_B (linha 103). O shadow roda desde 22/07 e
o ledger nunca foi lido.

⚠️ O ledger tem DUAS FASES e misturá-las confunde prompt com modelo:
      prompt=g3       22–28/07  — 3.1 com prompt próprio (modelo E prompt diferentes)
      prompt=current  28/07 →    — 3.1 com o prompt V1 de prod (A/B SÓ-MODELO)
    Só a fase `current` responde "2.5 vs 3.1". A fase `g3` responde "pipeline de prod vs
    pipeline g3". O relatório separa as duas e nunca agrega.

Verdade de campo = status do operador na tabela `detections`. Ela só existe para eventos
em que a PROD criou detecção; onde a prod não criou, o shadow positivo não tem rótulo —
esses viram a lista de revisão manual (quadrante SHADOW-ONLY), não um número.

Pull dos insumos:
  ssh saira-prod 'docker cp saira-yolo-worker-prod:/app/state/shadow_model_audit /tmp/shadow_pull'
  scp -r saira-prod:/tmp/shadow_pull ./shadow_pull
  ssh saira-prod "docker exec saira-db-prod psql -U postgres -d saira_db -A -F',' -c \\
    \\"copy (select id, status, event_ref, created_at, timestamp, confidence_score, \\
    waste_type, validity_comment from detections where camera_id=15 \\
    and created_at >= '2026-07-21') to stdout with csv header\\"" > detections.csv

Uso:
  python -X utf8 compare_shadow.py ./shadow_pull --detections detections.csv \\
      --calllog calllog.csv --out ../results
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

# Preço por 1M tokens (USD), igual a detector_gemini._MODEL_PRICES. Thinking é faturado
# na taxa de OUTPUT — omiti-lo subestimou o custo em ~2x no Camp 47, então recomputamos
# a partir dos tokens crus do ledger em vez de confiar no campo `*_cost_usd`.
PRICES = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.125, 0.75),
}

CONFIRMED = "CONFIRMADO"
REJECTED = "REJEITADO"


def read_jsonl(root: Path):
    """Ledger no layout {data}/{device}.jsonl — mesmo de summarize_shadow.py (Camp 36)."""
    for p in sorted(root.rglob("*.jsonl")):
        device, day = p.stem, p.parent.name
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield day, device, json.loads(line)
            except json.JSONDecodeError:
                continue


def read_detections(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["id"]: row for row in csv.DictReader(fh)}


def cost_of(model: str, tok_in: int, tok_out: int, tok_think: int) -> float:
    pin, pout = PRICES.get((model or "").strip().lower(), (0.0, 0.0))
    return tok_in / 1e6 * pin + (tok_out + tok_think) / 1e6 * pout


def record_cost(r: dict) -> float:
    """Custo do registro recomputado dos tokens crus (gate + detail)."""
    total = cost_of(r.get("gate_model", ""), int(r.get("gate_input_tokens") or 0),
                    int(r.get("gate_output_tokens") or 0),
                    int(r.get("gate_thinking_tokens") or 0))
    if r.get("detail_ran"):
        total += cost_of(r.get("detail_model", ""), int(r.get("detail_input_tokens") or 0),
                         int(r.get("detail_output_tokens") or 0),
                         int(r.get("detail_thinking_tokens") or 0))
    return total


def pct(num: int, den: int) -> str:
    return f"{num}/{den} · {100.0 * num / den:.1f}%" if den else f"{num}/0 · —"


def analyse(rows: list[dict], dets: dict[str, dict]) -> dict:
    """Confusão do shadow contra prod e contra o operador, para UMA fase."""
    st = {
        "n": len(rows),
        "cost": sum(record_cost(r) for r in rows),
        "gate_fired": sum(1 for r in rows if r.get("gate_triggered")),
        "detail_ran": sum(1 for r in rows if r.get("detail_ran")),
        "shadow_yes": sum(1 for r in rows if r.get("would_confirm_model")),
        "prod_yes": sum(1 for r in rows if r.get("prod_created_detection")),
        # concordância bruta prod x shadow (sem rótulo humano)
        "both_yes": 0, "both_no": 0, "prod_only": 0, "shadow_only": 0,
        # contra o operador (só onde a prod criou detecção e o operador julgou)
        "op_confirmed": 0, "op_confirmed_shadow_yes": 0,
        "op_rejected": 0, "op_rejected_shadow_yes": 0,
        "labelled": 0,
        "disagreements": [],
    }
    for r in rows:
        p, s = bool(r.get("prod_created_detection")), bool(r.get("would_confirm_model"))
        st["both_yes" if (p and s) else "both_no" if not (p or s)
           else "prod_only" if p else "shadow_only"] += 1

        det = dets.get(r.get("prod_detection_id") or "")
        status = (det or {}).get("status", "")
        if status in (CONFIRMED, REJECTED):
            st["labelled"] += 1
            if status == CONFIRMED:
                st["op_confirmed"] += 1
                st["op_confirmed_shadow_yes"] += int(s)
            else:
                st["op_rejected"] += 1
                st["op_rejected_shadow_yes"] += int(s)
        if p != s:
            st["disagreements"].append({
                "event_ref": r.get("event_ref"), "ts": r.get("ts"),
                "quadrant": "PROD-ONLY" if p else "SHADOW-ONLY",
                "operator_status": status or ("(sem detecção de prod)" if not p else "(sem rótulo)"),
                "operator_comment": (det or {}).get("validity_comment", ""),
                "prod_detection_id": r.get("prod_detection_id") or "",
                "gate_conf": r.get("gate_confidence"),
                "gate_scene": r.get("gate_scene"),
                "detail_conf": r.get("detail_confidence"),
                "shadow_evidence": (r.get("detail_evidence") or r.get("gate_evidence") or "")[:300],
            })
    return st


def phase_block(name: str, st: dict) -> str:
    n = st["n"]
    lines = [
        f"### Fase `{name}`", "",
        f"- eventos: **{n}** · gate disparou {pct(st['gate_fired'], n)} · "
        f"detail rodou {st['detail_ran']}",
        f"- prod criou detecção: {pct(st['prod_yes'], n)} · "
        f"shadow confirmaria: {pct(st['shadow_yes'], n)}",
        f"- custo do shadow (recomputado dos tokens): **US$ {st['cost']:.4f}** "
        f"(US$ {st['cost'] / n:.5f}/evento)" if n else "- custo: —",
        "",
        "| | shadow SIM | shadow NÃO |",
        "|---|---|---|",
        f"| **prod SIM** | {st['both_yes']} | {st['prod_only']} |",
        f"| **prod NÃO** | {st['shadow_only']} | {st['both_no']} |",
        "",
    ]
    if st["labelled"]:
        lines += [
            f"Contra o operador (n={st['labelled']} detecções julgadas):", "",
            f"- **recall** — de {st['op_confirmed']} CONFIRMADO, o 3.1 confirmaria "
            f"{pct(st['op_confirmed_shadow_yes'], st['op_confirmed'])}",
            f"- **alarme falso** — de {st['op_rejected']} REJEITADO, o 3.1 confirmaria "
            f"{pct(st['op_rejected_shadow_yes'], st['op_rejected'])}",
            "",
        ]
    else:
        lines += ["_Sem detecção de prod julgada pelo operador nesta fase._", ""]
    n_shadow_only = sum(1 for d in st["disagreements"] if d["quadrant"] == "SHADOW-ONLY")
    lines += [
        f"Discordâncias: **{len(st['disagreements'])}** "
        f"({n_shadow_only} SHADOW-ONLY sem rótulo, {len(st['disagreements']) - n_shadow_only} PROD-ONLY) "
        f"— ver `shadow_3v1_quadrants.csv`.", "",
    ]
    return "\n".join(lines)


def calllog_block(path: Path) -> str:
    """Custo REAL lado a lado a partir de gemini_call_log (prod 2.5 vs shadow 3.1)."""
    agg = defaultdict(lambda: {"n": 0, "usd": 0.0, "lat": 0.0, "err": 0})
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            side = "shadow (3.1)" if row["agent"].startswith("shadow_") else "prod (2.5)"
            stage = row["agent"].replace("shadow_", "")
            a = agg[(side, stage)]
            n = int(row["n"])
            a["n"] += n
            a["usd"] += float(row["usd"] or 0)
            a["lat"] += float(row["lat_ms"] or 0) * n
            a["err"] += int(row["errors"] or 0)
    out = ["| lado | estágio | chamadas | custo US$ | latência média | erros |",
           "|---|---|---|---|---|---|"]
    for (side, stage), a in sorted(agg.items()):
        out.append(f"| {side} | {stage} | {a['n']} | {a['usd']:.4f} | "
                   f"{a['lat'] / a['n']:.0f} ms | {a['err']} |")
    tot = defaultdict(float)
    for (side, _), a in agg.items():
        tot[side] += a["usd"]
    out += ["", "Total por lado: " + " · ".join(
        f"**{s}** US$ {v:.4f}" for s, v in sorted(tot.items())) + "."]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ledger", type=Path, help="dir do pull de shadow_model_audit")
    ap.add_argument("--detections", type=Path, required=True, help="CSV de detections")
    ap.add_argument("--calllog", type=Path, help="CSV agregado de gemini_call_log (opcional)")
    ap.add_argument("--device", default="pi-cam-001")
    ap.add_argument("--out", type=Path, required=True, help="dir de saída")
    a = ap.parse_args()

    dets = read_detections(a.detections)
    rows = [r for _, dev, r in read_jsonl(a.ledger) if dev == a.device]
    if not rows:
        print(f"nenhum registro para {a.device} em {a.ledger}", file=sys.stderr)
        return 1

    by_phase: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_phase[r.get("prompt") or "(sem prompt)"].append(r)

    a.out.mkdir(parents=True, exist_ok=True)

    # linha-a-linha, para reanálise sem repetir o pull
    flat = a.out / "shadow_3v1.csv"
    cols = ["event_ref", "ts", "prompt", "window_size", "gate_triggered", "gate_confidence",
            "gate_scene", "detail_ran", "detail_confirmed", "detail_confidence",
            "would_confirm_model", "prod_created_detection", "prod_detection_id",
            "operator_status", "operator_comment", "cost_usd_recomputed"]
    with flat.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            det = dets.get(r.get("prod_detection_id") or "") or {}
            w.writerow({**r, "operator_status": det.get("status", ""),
                        "operator_comment": det.get("validity_comment", ""),
                        "cost_usd_recomputed": round(record_cost(r), 8)})

    stats = {ph: analyse(rs, dets) for ph, rs in by_phase.items()}

    quad = a.out / "shadow_3v1_quadrants.csv"
    qcols = ["phase", "quadrant", "event_ref", "ts", "operator_status", "operator_comment",
             "prod_detection_id", "gate_conf", "gate_scene", "detail_conf", "shadow_evidence"]
    with quad.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=qcols, extrasaction="ignore")
        w.writeheader()
        for ph, st in sorted(stats.items()):
            for d in st["disagreements"]:
                w.writerow({"phase": ph, **d})

    days = sorted({d for d, dev, _ in read_jsonl(a.ledger) if dev == a.device})
    md = [
        "# Shadow Gemini-3.1 vs prod 2.5 — pi-cam-001", "",
        f"Ledger: {len(rows)} eventos, {days[0]} a {days[-1]}. "
        f"Rótulos do operador: {len(dets)} detecções exportadas.", "",
        "> As duas fases NÃO são agregadas. `g3` troca modelo **e** prompt; só `current` "
        "isola o modelo, que é a pergunta da migração de 16/out.", "",
    ]
    for ph in sorted(stats, key=lambda p: (p != "current", p)):
        md.append(phase_block(ph, stats[ph]))
    if a.calllog and a.calllog.exists():
        md += ["## Custo real (gemini_call_log)", "", calllog_block(a.calllog), ""]
    md += ["## Arquivos", "",
           f"- `{flat.name}` — uma linha por evento do shadow, com o rótulo do operador",
           f"- `{quad.name}` — só as discordâncias, para revisão manual", ""]

    rep = a.out / "shadow_3v1_report.md"
    rep.write_text("\n".join(md), encoding="utf-8")
    print(f"escrito: {flat}\n         {quad}\n         {rep}")
    for ph, st in sorted(stats.items()):
        print(f"  fase {ph}: n={st['n']} shadow_yes={st['shadow_yes']} "
              f"prod_yes={st['prod_yes']} rotulados={st['labelled']} "
              f"custo=US$ {st['cost']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
