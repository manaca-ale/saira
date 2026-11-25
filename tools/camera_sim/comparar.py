#!/usr/bin/env python3
"""Compara o que o pipeline de TESTE fez com o que o replay da campanha 54 previu.

Entrada (pasta de coleta, preenchida por `coletar.sh`):
  envios.jsonl             log do `camera_sim.py enviar` (event_id original -> sim_event_id)
  manifestos/*.json        manifestos do esp32-server de teste (sim_event_id -> quadros)
  cascade_audit/*.jsonl    auditoria do worker por janela que chegou ao gate
  prefilter_audit/*.jsonl  auditoria do filtro Decisions (inclusive as janelas barradas)
  gemini_call_log.csv      chamadas do dispositivo simulado (custo, latência, modelo, erro)
e o `eventos_dev.csv` do `camera_sim.py montar` (o previsto).

Saída: uma linha por evento (`comparacao.csv`) e um resumo em Markdown.
A ligação é pelos nomes dos quadros: o servidor renomeia cada quadro na chegada, e o
manifesto do evento simulado guarda esses nomes; o filtro e o gate registram os seus.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional


def _jsonl_dir(d: Path) -> list[dict]:
    out = []
    for p in sorted(d.glob("*.jsonl")) if d.is_dir() else []:
        out += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return out


def _b(v) -> Optional[int]:
    if v in (None, ""):
        return None
    if isinstance(v, str):
        return int(v.strip().lower() in ("1", "true", "t"))
    return int(bool(v))


def pct(xs: list[float], q: float) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def join(previsto: list[dict], envios: list[dict], manifests: dict[str, dict],
         cascade: list[dict], prefilter: list[dict], calls: list[dict]) -> list[dict]:
    frame_to_sim: dict[str, str] = {}
    for sid, m in manifests.items():
        for f in m.get("frames") or []:
            frame_to_sim[f.rsplit("/", 1)[-1]] = sid

    def sim_of(names: list[str]) -> Optional[str]:
        for n in reversed(names or []):
            if n in frame_to_sim:
                return frame_to_sim[n]
        return None

    pf_by_sim: dict[str, dict] = {}
    for r in prefilter:
        sid = sim_of(r.get("frames") or [])
        if sid:
            pf_by_sim[sid] = r
    cas_by_sim: dict[str, dict] = {}
    for r in cascade:
        sid = sim_of([r.get("window_first_frame"), r.get("window_last_frame")])
        if sid:
            cas_by_sim[sid] = r
    calls_by_req: dict[str, list[dict]] = defaultdict(list)
    for c in calls:
        calls_by_req[c.get("request_id") or ""].append(c)

    prev = {r["event_id"]: r for r in previsto}
    out = []
    for e in envios:
        if e.get("seco"):
            continue
        p = prev.get(e["event_id"], {})
        sid = e["sim_event_id"]
        pf, ca = pf_by_sim.get(sid), cas_by_sim.get(sid)
        gate_calls = calls_by_req.get((ca or {}).get("agent1_request_id") or "", [])
        det_calls = calls_by_req.get((ca or {}).get("agent2_request_id") or "", [])
        pf_calls = calls_by_req.get((pf or {}).get("request_id") or "", [])
        bedrock_fail = any("nova" in (c.get("model") or "") and _b(c.get("success")) == 0
                           for c in gate_calls)
        gate_ok = [c for c in gate_calls if _b(c.get("success")) == 1]
        cost = sum(float(c.get("estimated_cost_usd") or 0) for c in pf_calls + gate_calls + det_calls)
        nota = (pf or {}).get("wl_v2")
        teste_alerta = int(bool(ca and _b(ca.get("agent2_disposal"))))
        out.append({
            "event_id": e["event_id"], "sim_event_id": sid, "sub": p.get("sub", ""),
            "manifesto": int(sid in manifests),
            "prev_filtro_nota": p.get("filtro_nota", ""), "teste_filtro_nota": "" if nota is None else f"{nota:.4f}",
            "prev_filtro_passa": p.get("filtro_passa", ""),
            "teste_filtro_passa": "" if pf is None or nota is None else int(not pf.get("below_threshold")),
            "teste_filtro_erro": (pf or {}).get("error", "") if pf else "sem_registro",
            "prev_gate": p.get("gate_r1", ""), "prev_gate_r2": p.get("gate_r2", ""),
            "teste_gate": "" if ca is None else _b(ca.get("agent1_triggered")),
            "teste_gate_conf": "" if ca is None else ca.get("agent1_confidence", ""),
            "teste_gate_modelo": gate_ok[-1].get("model", "") if gate_ok else "",
            "teste_gate_reserva": int(bedrock_fail),
            "prev_detail": p.get("detail_cru", ""),
            "teste_detail": "" if not (ca and _b(ca.get("agent2_ran"))) else _b(ca.get("agent2_disposal")),
            "prev_alerta": p.get("previsto_alerta", ""), "teste_alerta": teste_alerta,
            "lat_filtro_ms": (pf or {}).get("latency_ms", ""),
            "lat_gate_ms": gate_ok[-1].get("latency_ms", "") if gate_ok else "",
            "lat_detail_ms": next((c.get("latency_ms") for c in det_calls if _b(c.get("success")) == 1), ""),
            "erros": sum(1 for c in pf_calls + gate_calls + det_calls if _b(c.get("success")) == 0),
            "custo_usd": round(cost, 6),
        })
    return out


def _agree(rows, a, b):
    pares = [(r[a], r[b]) for r in rows if r[a] not in ("", None) and r[b] not in ("", None)]
    iguais = sum(1 for x, y in pares if str(int(float(x))) == str(int(float(y))))
    return iguais, len(pares)


def summary(rows: list[dict]) -> str:
    n = len(rows)
    lines = [f"Eventos enviados e conferidos: {n} (com manifesto no servidor: {sum(r['manifesto'] for r in rows)})", ""]
    for nome, a, b in (("Filtro (passa)", "prev_filtro_passa", "teste_filtro_passa"),
                       ("Gate (dispara)", "prev_gate", "teste_gate"),
                       ("Detail (sim)", "prev_detail", "teste_detail"),
                       ("Alerta", "prev_alerta", "teste_alerta")):
        i, t = _agree(rows, a, b)
        lines.append(f"- {nome}: concorda em {i} de {t}")
    g12 = _agree([r for r in rows if r["prev_gate_r2"] != ""], "prev_gate", "prev_gate_r2")
    lines.append(f"- Referência de ruído: o gate do replay concorda consigo mesmo (r1 × r2) em {g12[0]} de {g12[1]}")
    difs = [abs(float(r["prev_filtro_nota"]) - float(r["teste_filtro_nota"])) for r in rows
            if r["prev_filtro_nota"] and r["teste_filtro_nota"]]
    if difs:
        lines.append(f"- Nota do filtro: diferença absoluta mediana {statistics.median(difs):.3f}, p90 {pct(difs, 0.9):.3f}")
    lines.append(f"- Alertas: replay {sum(int(r['prev_alerta'] or 0) for r in rows)}, teste {sum(r['teste_alerta'] for r in rows)}")
    by_sub = Counter((r["sub"], r["teste_alerta"]) for r in rows)
    lines.append("- Alertas do teste por estrato: " + ", ".join(
        f"{s} {by_sub[(s, 1)]}/{by_sub[(s, 0)] + by_sub[(s, 1)]}" for s in ("S2C", "S2R", "S2X", "S1", "S0")))
    for k, nome in (("lat_filtro_ms", "filtro"), ("lat_gate_ms", "gate"), ("lat_detail_ms", "detail")):
        xs = [float(r[k]) / 1000 for r in rows if r[k] not in ("", None)]
        if xs:
            lines.append(f"- Latência {nome}: p50 {pct(xs, 0.5):.1f} s, p90 {pct(xs, 0.9):.1f} s (n={len(xs)})")
    lines.append(f"- Quedas para a reserva Gemini no gate: {sum(r['teste_gate_reserva'] for r in rows)}")
    lines.append(f"- Chamadas com erro: {sum(r['erros'] for r in rows)}; filtro sem registro: "
                 f"{sum(1 for r in rows if r['teste_filtro_erro'] == 'sem_registro')}")
    custo = sum(r["custo_usd"] for r in rows)
    lines.append(f"- Custo registrado no gemini_call_log: US$ {custo:.4f} (US$ {custo / max(n, 1):.6f} por evento)")
    return "\n".join(lines)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--coleta", type=Path, required=True)
    ap.add_argument("--eventos", type=Path, required=True)
    ap.add_argument("--saida", type=Path, required=True)
    a = ap.parse_args()
    c = a.coleta
    previsto = list(csv.DictReader(a.eventos.open(encoding="utf-8", newline="")))
    envios = [json.loads(x) for x in (c / "envios.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    manifests = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (c / "manifestos").glob("*.json")}
    calls = list(csv.DictReader((c / "gemini_call_log.csv").open(encoding="utf-8", newline="")))
    rows = join(previsto, envios, manifests, _jsonl_dir(c / "cascade_audit"),
                _jsonl_dir(c / "prefilter_audit"), calls)
    a.saida.mkdir(parents=True, exist_ok=True)
    if rows:
        with (a.saida / "comparacao.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    text = summary(rows)
    (a.saida / "resumo.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
