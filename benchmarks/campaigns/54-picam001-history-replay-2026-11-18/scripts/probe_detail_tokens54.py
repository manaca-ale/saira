# -*- coding: utf-8 -*-
"""Sonda sem custo: tokens de entrada do detail em produção (gemini_call_log, pela agent2_request_id da
detecção) contra os do replay (detail54__*.jsonl) no mesmo evento. O Vertex conta o esquema da resposta
como entrada e o AI Studio não: a diferença tem de ser CONSTANTE quando o replay manda o mesmo que a
produção (mesmo aviso da janela anterior, mesmo camera_context, mesmos quadros). Só arquivos locais."""
import collections
import csv
import json
import statistics as st
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"C:\Saira\data\historico-picam")
RES = Path(__file__).resolve().parent.parent / "results"

log = {}
with open(ROOT / "raw" / "gemini_call_log_picam.csv", encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        if r["agent"] == "detail" and r["success"] == "t" and r["input_tokens"]:
            log[r["request_id"]] = int(r["input_tokens"])
det = {}
with open(ROOT / "raw" / "detections_cam15.csv", encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        det[r["id"]] = r
base = {}
with open(ROOT / "base" / "base_eventos.csv", encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        base[r["event_id"]] = r

for name in sys.argv[1:]:
    rows = [json.loads(l) for l in (RES / name).read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if not r.get("error") and r.get("tok_in")]
    difs, por_tipo, sem = [], collections.defaultdict(list), 0
    print(f"== {name}: {len(rows)} linhas")
    for r in rows:
        d = det.get(r.get("detection_id") or "")
        b = base.get(r["event_id"], {})
        # a detecção nasce de UMA janela; só compara o evento cuja janela é a da detecção
        if not d or d.get("agent1_request_id") != b.get("agent1_request_id"):
            sem += 1
            continue
        prod = log.get(d.get("agent2_request_id"))
        if prod is None:
            sem += 1
            continue
        dif = prod - r["tok_in"]
        difs.append(dif)
        por_tipo[str(r.get("prior_type"))].append(dif)
        if len(rows) <= 12:
            print(f"  {r['event_id']} quadros={r['n_sent']} aviso={r.get('prior_type')!r} "
                  f"replay={r['tok_in']} producao={prod} diferenca={dif} "
                  f"por_quadro_prod={(prod - 1317) / r['n_sent']:.1f}")
    if difs:
        print(f"  pares={len(difs)} sem_par={sem} diferenca: min={min(difs)} mediana={st.median(difs)} "
              f"max={max(difs)} valores={dict(sorted(collections.Counter(difs).items()))}")
        for t, v in sorted(por_tipo.items()):
            print(f"    aviso={t!r}: n={len(v)} mediana={st.median(v)} min={min(v)} max={max(v)}")
    else:
        print(f"  sem pares (sem_par={sem})")
