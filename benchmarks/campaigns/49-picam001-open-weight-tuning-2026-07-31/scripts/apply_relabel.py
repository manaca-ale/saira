#!/usr/bin/env python3
"""Camp 49 — aplica a reclassificação humana da Fase 0 no dataset oficial.

O operador revisou 9 eventos ambíguos do Camp 48 e julgou 3 como descarte real
(estavam rotulados `fp`). O dataset rotula **por detecção** e propaga para os eventos
(foi assim que os rótulos originais vieram do operador), então as detecções inteiras
migram — inclusive 2 eventos-irmão que não foram revistos individualmente. Decisão do
usuário em 31/07/2026.

Move `fp/<evento>/` → `tp/<evento>/` e reescreve `label.json` preservando os valores
antigos em campos `relabel_*` para que a operação seja auditável e reversível.

Uso:
    python scripts/apply_relabel.py              # dry-run (default)
    python scripts/apply_relabel.py --apply
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import date
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
CAM = ROOT / "data" / "datasets" / "official" / "cam_picam001"
REVIEW = CAM / "_review_camp49" / "INDEX.csv"
C48 = ROOT / "benchmarks" / "campaigns" / "48-bedrock-oss-vlm-picam001-2026-07-30" / \
    "results" / "bench_bedrock.csv"

VERDICT_TO_CAT = {"descarte": "tp", "catador": None, "sem_ocorrencia": None,
                  "indefinido": "indefinido"}
CLASSIF = {"tp": "Descarte", "fp": "Falso Positivo", "indefinido": "Indefinido",
           "baseline": "Sem Ocorrência"}


def read_review() -> dict[str, str]:
    """O INDEX.csv volta do Excel com `;` (locale pt-BR). Aceita os dois."""
    raw = REVIEW.read_text(encoding="utf-8-sig")
    delim = ";" if raw.splitlines()[0].count(";") > raw.splitlines()[0].count(",") else ","
    out = {}
    for r in csv.DictReader(raw.splitlines(), delimiter=delim):
        v = (r.get("VEREDITO") or "").strip().lower()
        if v:
            out[r["event_id"]] = v
    return out


def siblings_by_det(event_ids: set[str]) -> dict[str, set[str]]:
    """Todos os eventos que dividem detecção com os reclassificados."""
    rows = list(csv.DictReader(C48.open(encoding="utf-8")))
    det_of = {r["event_id"]: r["det_id"] for r in rows}
    dets = {det_of[e] for e in event_ids if e in det_of}
    grupos: dict[str, set[str]] = {d: set() for d in dets}
    for r in rows:
        if r["det_id"] in dets:
            grupos[r["det_id"]].add(r["event_id"])
    return grupos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    verd = read_review()
    if not verd:
        sys.exit(f"nenhum VEREDITO preenchido em {REVIEW}")
    alvo = {e for e, v in verd.items() if VERDICT_TO_CAT.get(v) == "tp"}
    if not alvo:
        print("nenhum evento vira TP — nada a fazer")
        return 0

    grupos = siblings_by_det(alvo)
    mover: list[tuple[str, str, bool]] = []   # (event_id, det, revisado_pelo_operador)
    for det, evs in sorted(grupos.items()):
        for e in sorted(evs):
            mover.append((e, det, e in alvo))

    print(f"veredictos lidos: {len(verd)}  "
          f"({sum(1 for v in verd.values() if v == 'catador')} catador, "
          f"{len(alvo)} descarte)")
    print(f"detecções que viram TP: {len(grupos)}   eventos afetados: {len(mover)}\n")
    print(f"{'evento':24}{'det':10}{'de':>6} -> {'para':<6}{'revisado?':>11}")
    print("-" * 62)
    faltando = []
    for e, det, rev in mover:
        origem = next((c for c in ("fp", "tp", "indefinido", "baseline")
                       if (CAM / c / e).is_dir()), None)
        if origem is None:
            faltando.append(e)
            continue
        print(f"{e:24}{det[:8]:10}{origem:>6} -> {'tp':<6}"
              f"{('sim' if rev else 'ARRASTADO'):>11}")
    if faltando:
        print(f"\nNAO ENCONTRADOS no disco: {faltando}")
        return 1

    if not a.apply:
        print("\n[DRY-RUN] nada foi movido. Rode com --apply para efetivar.")
        print("Depois: python benchmarks/scripts/rebuild_official_manifest.py --dry-run")
        return 0

    hoje = date.today().isoformat()
    for e, det, rev in mover:
        origem = next(c for c in ("fp", "tp", "indefinido", "baseline")
                      if (CAM / c / e).is_dir())
        if origem == "tp":
            continue
        src, dst = CAM / origem / e, CAM / "tp" / e
        lab = src / "label.json"
        L = json.loads(lab.read_text(encoding="utf-8"))
        L["relabel_from"] = origem
        L["relabel_prev_classificacao"] = L.get("classificacao", "")
        L["relabel_prev_justificativa"] = L.get("justificativa", "")
        L["relabel_source"] = "camp49_fase0_revisao_operador"
        L["relabel_date"] = hoje
        L["relabel_reviewed_directly"] = rev
        L["category"] = "tp"
        L["classificacao"] = CLASSIF["tp"]
        L["justificativa"] = (
            "Descarte confirmado na revisão da Fase 0 do Camp 49 (31/07/2026)."
            if rev else
            f"Detecção {det[:8]} reclassificada como descarte pela revisão do Camp 49; "
            "este evento herda o rótulo da detecção-pai (não revisado isoladamente).")
        # frames[] guarda caminhos relativos com a categoria antiga
        L["frames"] = [f.replace(f"/{origem}/", "/tp/") for f in L.get("frames", [])]
        lab.write_text(json.dumps(L, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.move(str(src), str(dst))
        print(f"  movido {origem}/{e} -> tp/{e}")

    print(f"\n{len(mover)} eventos reclassificados.")
    print("AGORA: python benchmarks/scripts/rebuild_official_manifest.py --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
