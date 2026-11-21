#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — base com TODOS os eventos da pi-cam-001 em producao (sem custo de API).

Junta, por evento:
  - o manifesto do receptor (`events/<evento>.json`: frames, inicio, motivo de fechamento);
  - a decisao do gate e do detail gravada pelo worker (`gemini_cascade_audit/<dia>/pi-cam-001.jsonl`),
    ligada pelo nome do primeiro frame da janela;
  - a deteccao e a avaliacao do operador (`detections_cam15.csv`).

Entrada: copia so de leitura de producao feita em 18/11/2026 (C:\\Saira\\data\\historico-picam).
Saida:   base/base_eventos.csv (uma linha por evento com manifesto) e base/resumo.json.

Uso: python build_base.py
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\Saira\data\historico-picam")
EXT = ROOT / "extraido"
RAW = ROOT / "raw"
OUT = ROOT / "base"
START = "2026-07-14"      # o worker passou a ler os manifestos da Pi em 14/07


def base(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def week_of(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    OUT.mkdir(parents=True, exist_ok=True)

    # 1) manifestos
    man = {}
    for p in sorted((EXT / "events").glob("evt-*.json")):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        fr = m.get("frames") or []
        man[m.get("event_id") or p.stem] = {
            "event_id": m.get("event_id") or p.stem,
            "started_at": m.get("started_at") or "",
            "closed_at": m.get("closed_at") or "",
            "state": m.get("state") or "",
            "closed_reason": m.get("closed_reason") or "",
            "n_frames": len(fr),
            "first_frame": base(fr[0]) if fr else "",
            "last_frame": base(fr[-1]) if fr else "",
            "gate_fg_px": m.get("gate_fg_px", ""),
            "gate_delta_px": m.get("gate_delta_px", ""),
            "gate_config_version": m.get("gate_config_version", ""),
        }
    by_first = defaultdict(list)
    for e in man.values():
        if e["first_frame"]:
            by_first[e["first_frame"]].append(e["event_id"])

    # 2) auditoria da cascata (uma linha por janela avaliada pelo gate)
    audit = []
    for p in sorted((EXT / "gemini_cascade_audit").glob("*/pi-cam-001.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    audit.append(json.loads(line))
                except ValueError:
                    pass
    # 3) deteccoes
    det = {}
    with (RAW / "detections_cam15.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            det[r["id"]] = r

    # 4) liga auditoria -> evento
    by_event = defaultdict(list)
    unmatched = 0
    frame_to_event = {}
    for e in man.values():
        pass
    for a in audit:
        evs = by_first.get(a.get("window_first_frame") or "")
        if not evs:
            unmatched += 1
            continue
        by_event[evs[0]].append(a)

    rows = []
    for eid, e in sorted(man.items()):
        day = e["started_at"][:10] or f"{eid[4:8]}-{eid[8:10]}-{eid[10:12]}"
        aa = by_event.get(eid, [])
        a = aa[-1] if aa else None
        did = (a or {}).get("detection_id") or ""
        d = det.get(did, {})
        rows.append({
            "event_id": eid, "dia": day, "semana": week_of(day), "hora": e["started_at"][11:13],
            "closed_reason": e["closed_reason"], "n_frames": e["n_frames"],
            "first_frame": e["first_frame"], "last_frame": e["last_frame"],
            "gate_config_version": e["gate_config_version"],
            "n_linhas_auditoria": len(aa),
            "gate_avaliou": int(a is not None),
            "window_size": (a or {}).get("window_size", ""),
            "window_last_frame": (a or {}).get("window_last_frame", ""),
            "gate_disparou": int(bool((a or {}).get("agent1_triggered"))) if a else "",
            "gate_conf": (a or {}).get("agent1_confidence", "") if a else "",
            "gate_new_litter": int(bool((a or {}).get("agent1_new_litter_detected"))) if a else "",
            "agent1_request_id": (a or {}).get("agent1_request_id", "") if a else "",
            "detail_rodou": int(bool((a or {}).get("agent2_ran"))) if a else "",
            "detail_ok": int(bool((a or {}).get("agent2_success"))) if a else "",
            "detail_sim": int(bool((a or {}).get("agent2_disposal"))) if a else "",
            "detection_id": did, "status": d.get("status", ""),
            "validity_comment": (d.get("validity_comment") or "").replace("\n", " ")[:300],
        })
    cols = list(rows[0].keys())
    with (OUT / "base_eventos.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    # 5) resumo
    per = [r for r in rows if r["dia"] >= START]
    ev = [r for r in per if r["gate_avaliou"]]
    print(f"manifestos: {len(man)} | linhas de auditoria: {len(audit)} (sem evento correspondente: {unmatched}) | "
          f"deteccoes da camera: {len(det)}")
    print(f"de {START} em diante: {len(per)} eventos com manifesto; {len(ev)} avaliados pelo gate; "
          f"sem chamada ao Gemini: {len(per) - len(ev)} "
          f"({dict(Counter(r['closed_reason'] for r in per if not r['gate_avaliou']))})")
    multi = sum(1 for r in ev if r["n_linhas_auditoria"] > 1)
    print(f"eventos com mais de uma linha de auditoria: {multi}")
    fired = [r for r in ev if r["gate_disparou"] == 1]
    ran = [r for r in ev if r["detail_rodou"] == 1]
    yes = [r for r in ev if r["detail_sim"] == 1]
    st = Counter(r["status"] for r in ev if r["detection_id"])
    print(f"gate disparou: {len(fired)} = {100 * len(fired) / len(ev):.2f}% | detail rodou: {len(ran)} | detail disse sim: "
          f"{len(yes)} | eventos ligados a deteccao: {sum(st.values())} {dict(st)}")
    dets_seen = {r["detection_id"]: r["status"] for r in ev if r["detection_id"]}
    print(f"deteccoes distintas alcancadas pela auditoria: {len(dets_seen)} {dict(Counter(dets_seen.values()))}")
    print("\nsemana | eventos | avaliados | gate disparou (%) | detail sim | janela mediana | frames/evento mediana | "
          "eventos de deteccao C/R/I")
    weeks = sorted({r["semana"] for r in per})
    resumo = {"inicio": START, "semanas": {}}
    for wk in weeks:
        sub = [r for r in per if r["semana"] == wk]
        e2 = [r for r in sub if r["gate_avaliou"]]
        f2 = [r for r in e2 if r["gate_disparou"] == 1]
        y2 = [r for r in e2 if r["detail_sim"] == 1]
        ws = [int(r["window_size"]) for r in e2 if str(r["window_size"]).isdigit()]
        nf = [r["n_frames"] for r in sub]
        c = Counter(r["status"] for r in e2 if r["detection_id"])
        resumo["semanas"][wk] = {"eventos": len(sub), "avaliados": len(e2), "gate_disparou": len(f2),
                                 "detail_sim": len(y2), "janela_mediana": statistics.median(ws) if ws else None}
        print(f"{wk} | {len(sub)} | {len(e2)} | {len(f2)} ({100 * len(f2) / max(1, len(e2)):.2f}%) | {len(y2)} | "
              f"{statistics.median(ws) if ws else '-'} | {statistics.median(nf) if nf else '-'} | "
              f"{c.get('CONFIRMADO', 0)}/{c.get('REJEITADO', 0)}/{c.get('INDETERMINADO', 0)}")
    print("\njanela mediana por dia (para achar mudancas de configuracao):")
    byday = defaultdict(list)
    for r in ev:
        if str(r["window_size"]).isdigit():
            byday[r["dia"]].append(int(r["window_size"]))
    print(" ".join(f"{d[5:]}:{int(statistics.median(v))}" for d, v in sorted(byday.items())))
    cfg = Counter(r["gate_config_version"] for r in per)
    print("\nversoes de configuracao do gate de movimento da Pi (eventos):",
          {k or "(vazio)": v for k, v in sorted(cfg.items())})
    resumo.update({"eventos": len(per), "avaliados": len(ev), "gate_disparou": len(fired), "detail_rodou": len(ran),
                   "detail_sim": len(yes), "deteccoes": dict(Counter(dets_seen.values()))})
    (OUT / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
