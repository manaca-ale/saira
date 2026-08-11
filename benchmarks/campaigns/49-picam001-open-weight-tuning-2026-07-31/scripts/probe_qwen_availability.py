#!/usr/bin/env python3
"""Camp 49 / Tema 1 — o `qwen3-vl-235b` está indisponível ou estava?

O Camp 49 eliminou o qwen com 93 erros de endpoint (13%/13%/66% de perda nos três
braços) enquanto kimi e magistral não erraram uma vez. Só que os 9 braços rodaram
SEQUENCIALMENTE num único processo (`bench_bedrock.py:652`) e os três do qwen ficaram
no terço final: kimi e magistral nunca foram exercitados na mesma janela de tempo.
"Zero erros no mesmo período" não foi medido — foi inferido de rodadas disjuntas.

E os erros são AGRUPADOS no tempo: o `v4_casc_5f` falhou nos 13 primeiros eventos e
depois rodou 96 consecutivos com zero erro. O mesmo endpoint, o mesmo payload. Isso é
episódio de capacidade, não teto estrutural por requisição.

Este script conserta as duas lacunas do desenho:

  1. CONTROLE INTERCALADO — qwen e um modelo de controle na MESMA fila, submetidos ao
     mesmo pool. Se o serviço/conta degradar, os dois sentem no mesmo minuto. Sem isso
     não dá para atribuir a falha ao modelo.
  2. TELEMETRIA POR TENTATIVA (`bc.LOG_ATTEMPTS`) — separa a taxa BRUTA de 1a tentativa
     (propriedade do endpoint) da taxa EFETIVA por evento (endpoint + política de
     retentativa). Só a bruta é comparável entre rodadas com políticas diferentes.

O que ele NÃO faz: nova janela, novo prompt, nova métrica. Tudo isso vem de
`bench_bedrock.run_one`, verbatim — é a única forma de os números saírem comparáveis
com a tabela do `report.md`. `bench_bedrock.py` não é modificado.

Uso:
    # paridade de payload antes de gastar
    python scripts/probe_qwen_availability.py --dry-run

    # Fase A — sonda: 3 células (região × concorrência), 24 eventos, controle 1:2
    python scripts/probe_qwen_availability.py --probe

    # Fase B — rodada limpa dos 3 braços qwen na região escolhida
    python scripts/probe_qwen_availability.py --full --region us-east-1 --workers 3

    # só reagregar o que já está no disco
    python scripts/probe_qwen_availability.py --summarize
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_bedrock as bb      # noqa: E402  — fixa o env de janela de prod no import
import _bedrock_client as bc    # noqa: E402

RESULTS = bb.RESULTS
PROBE_JSONL = RESULTS / "qwen_probe_attempts.jsonl"
PROBE_SUMMARY = RESULTS / "qwen_probe_summary.json"
FULL_JSONL = RESULTS / "qwen_retry_attempts.jsonl"
FULL_CSV = RESULTS / "bench_v4_qwen_retry.csv"

QWEN = "qwen3-vl-235b"
CONTROL = "magistral-small"

# Modo de structured output MEDIDO em results/bench_v4.csv (qwen: 255 chamadas em
# `tool`; magistral: 364 em `text`). Pré-semear evita que a chamada de descoberta
# apareça como se fosse uma falha de disponibilidade.
KNOWN_JSON_MODE = {QWEN: "tool", CONTROL: "text"}


def set_region(region: str) -> None:
    """Troca de pool regional. Só entre células — nunca com chamadas em voo."""
    bc.REGION = region
    bc._client = None
    bc.client()          # aquece fora do pool: `client()` não tem lock


def run_cell(arms: list[str], events: list[dict], region: str, workers: int,
             csv_path: Path, control_every: int = 0, label: str = "") -> list[dict]:
    """Uma célula = (região, concorrência). Os braços vão INTERCALADOS numa fila só."""
    set_region(region)
    bb.CSV_PATH = csv_path
    done = bb.done_keys()
    specs = {a: bb.resolve_arm(a) for a in arms}

    jobs: list[tuple[dict, str]] = []
    main_arms = [a for a in arms if a.split(":")[0] != CONTROL]
    ctrl_arms = [a for a in arms if a.split(":")[0] == CONTROL]
    for i, ev in enumerate(events):
        for a in main_arms:
            jobs.append((ev, a))
        if ctrl_arms and control_every and i % control_every == 0:
            for a in ctrl_arms:
                jobs.append((ev, a))
    jobs = [(ev, a) for ev, a in jobs if (a, ev["event_id"]) not in done]

    print(f"\n=== célula {label or region} | region={region} workers={workers} "
          f"| {len(jobs)} chamadas ({len(events)} eventos, arms={arms}) ===")
    if not jobs:
        return []

    def work(ev, arm):
        # a célula ENTRA na tag: sem ela, A1 (w=3) e A2 (w=1) rodam os mesmos eventos
        # com a mesma tag e colapsam num grupo só no `summarize`.
        bc.set_tag(f"{label or region}|{arm}|{ev['event_id']}")
        r = bb.run_one(ev, arm, specs[arm], False)
        r["_region"], r["_workers"], r["_cell"] = region, workers, label or region
        return r

    out, buf = [], []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(work, ev, a) for ev, a in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            out.append(r)
            buf.append({k: v for k, v in r.items() if k in bb.COLS})
            tag = "ERR" if r["error"] else f"gate={r['gate_fire']} disp={r['disposal']}"
            print(f"  [{i}/{len(jobs)}] {r['arm']:28} {r['category']:10} "
                  f"{r['event_id']} {tag} {r['error'][:60]}")
            if len(buf) >= 5:
                bb.append_csv(buf)
                buf = []
    if buf:
        bb.append_csv(buf)
    print(f"  célula terminou em {(time.time()-t0)/60:.1f} min")
    return out


def dump_attempts(path: Path) -> None:
    with path.open("a", encoding="utf-8") as f:
        for a in bc.ATTEMPTS:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    print(f"  {len(bc.ATTEMPTS)} tentativas gravadas em {path.name}")
    bc.ATTEMPTS.clear()


# ── análise ──────────────────────────────────────────────────────────────────
def replay_camp49(attempts: list[dict]) -> bool:
    """O evento teria falhado sob o predicado de retentativa ANTIGO?

    Sem isto a comparação com o Camp 49 é injusta a favor do re-teste: o predicado
    novo retenta 4 classes de exceção botocore que o antigo devolvia de cara.
    Replay fiel: sucesso encerra; exceção fora do predicado antigo mata o evento;
    exceção dentro dele consome uma das 5 tentativas.
    """
    tries = 0
    for a in attempts:
        if a.get("ok"):
            return False
        if not a.get("retryable_camp49"):
            return True
        tries += 1
        if tries >= 5:
            return True
    return True


def summarize(jsonl: Path, out: Path) -> dict:
    if not jsonl.exists():
        sys.exit(f"não achei {jsonl}")
    rows = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_ev: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_ev[(r["region"], r["alias"], r["tag"])].append(r)

    cells: dict[str, dict] = {}
    for (region, alias, _tag), att in by_ev.items():
        key = f"{region} · {alias}"
        c = cells.setdefault(key, {"eventos": 0, "erro_efetivo": 0, "erro_camp49": 0,
                                   "tentativas": 0, "falhas_1a": 0, "exc": {},
                                   "lat_ok_ms": [], "relogio_ms": 0})
        c["eventos"] += 1
        c["tentativas"] += len(att)
        first = att[0]
        if not first.get("ok"):
            c["falhas_1a"] += 1
        if not any(a.get("ok") for a in att):
            c["erro_efetivo"] += 1
        if replay_camp49(att):
            c["erro_camp49"] += 1
        for a in att:
            if a.get("ok"):
                c["lat_ok_ms"].append(a["latency_ms"])
            else:
                c["exc"][a["exc"]] = c["exc"].get(a["exc"], 0) + 1
            c["relogio_ms"] += a.get("latency_ms", 0)

    for c in cells.values():
        n, lat = c["eventos"], sorted(c["lat_ok_ms"])
        c["taxa_erro_efetivo_pct"] = round(100 * c["erro_efetivo"] / n, 1)
        c["taxa_erro_camp49_pct"] = round(100 * c["erro_camp49"] / n, 1)
        c["taxa_falha_1a_tentativa_pct"] = round(100 * c["falhas_1a"] / c["tentativas"], 1)
        c["lat_ok_p50_s"] = round(lat[len(lat) // 2] / 1000, 1) if lat else None
        c["lat_ok_p90_s"] = round(lat[int(0.9 * (len(lat) - 1))] / 1000, 1) if lat else None
        c.pop("lat_ok_ms")

    out.write_text(json.dumps(cells, ensure_ascii=False, indent=2), encoding="utf-8")
    hdr = (f"{'célula':40}{'ev':>5}{'err efet':>10}{'err c49':>9}"
           f"{'falha 1a tent':>15}{'p50 s':>8}{'p90 s':>8}")
    print("\n" + hdr)
    print("-" * len(hdr))
    for k in sorted(cells):
        c = cells[k]
        print(f"{k:40}{c['eventos']:>5}{c['taxa_erro_efetivo_pct']:>9.1f}%"
              f"{c['taxa_erro_camp49_pct']:>8.1f}%{c['taxa_falha_1a_tentativa_pct']:>14.1f}%"
              f"{(c['lat_ok_p50_s'] or 0):>8.1f}{(c['lat_ok_p90_s'] or 0):>8.1f}")
        if c["exc"]:
            print(f"{'':40}exceções: {c['exc']}")
    print(f"\nresumo em {out.name}")
    return cells


def verdict(cells: dict) -> None:
    """Critério PRÉ-REGISTRADO no plano — aplicado ao qwen, com o controle ao lado."""
    q = {k: v for k, v in cells.items() if QWEN in k}
    c = {k: v for k, v in cells.items() if CONTROL in k}
    if not q:
        return
    best = min(q.values(), key=lambda v: v["taxa_erro_efetivo_pct"])
    worst_ctrl = max([v["taxa_erro_efetivo_pct"] for v in c.values()], default=0.0)
    b = best["taxa_erro_efetivo_pct"]
    print("\n── veredito (critério pré-registrado) ──")
    print(f"  melhor célula do qwen: {b:.1f}% de erro efetivo | "
          f"pior célula do controle ({CONTROL}): {worst_ctrl:.1f}%")
    if worst_ctrl >= 20:
        print("  CONTROLE DEGRADOU JUNTO → a causa é conta/Bedrock, não o modelo. "
              "Célula inválida; repetir depois.")
    elif b < 5:
        print("  < 5% → episódio TRANSITÓRIO. O qwen volta à mesa; segue a Fase B.")
    elif b >= 20:
        print("  ≥ 20% em todas as células → limitação ESTRUTURAL de capacidade. "
              "Confirma o Camp 49; NÃO gastar a Fase B.")
    else:
        print("  5–20% → zona cinza: usável só com retentativa. "
              "Reportar custo de latência e decidir com o usuário.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="Fase A: células região × concorrência")
    ap.add_argument("--full", action="store_true", help="Fase B: 3 braços qwen, 122 eventos")
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=6, help="eventos por categoria na sonda")
    ap.add_argument("--control-every", type=int, default=2,
                    help="1 chamada de controle a cada N eventos (0 = sem controle)")
    ap.add_argument("--arms", default=None)
    a = ap.parse_args()

    if a.summarize:
        c = summarize(PROBE_JSONL, PROBE_SUMMARY)
        verdict(c)
        return 0

    bb.load_review(strict=not a.dry_run)
    bc._json_mode.update(KNOWN_JSON_MODE)

    if a.dry_run:
        # Paridade de payload: se o input não for idêntico ao do Camp 49, os números
        # não são comparáveis (feedback_bench_match_prod_exactly).
        evs = bb.load_events(None, None, frozenset())
        for arm in (f"{QWEN}:v4_single", f"{QWEN}:v4_casc", f"{QWEN}:v4_casc_5f"):
            spec = bb.resolve_arm(arm)
            recs = [bb.run_one(ev, arm, spec, True) for ev in evs]
            print(f"[{arm}] n={len(recs)} "
                  f"janela med={int(st.median(r['n_window'] for r in recs))} "
                  f"detail: {int(st.median(r['n_images_sent'] for r in recs))} img med, "
                  f"{st.median(r['payload_mb'] for r in recs):.2f} MB med, "
                  f"gate={recs[0]['gate_n_images'] or '-'} img, "
                  f"cortes de payload={sum(1 for r in recs if r['n_dropped_payload'])}")
        return 0

    bc.LOG_ATTEMPTS = True

    if a.full:
        arms = (a.arms or f"{QWEN}:v4_single,{QWEN}:v4_casc,{QWEN}:v4_casc_5f").split(",")
        events = bb.load_events(None, None, frozenset())
        run_cell(arms, events, a.region, a.workers, FULL_CSV, 0, label=f"full-{a.region}")
        dump_attempts(FULL_JSONL)
        print("\nagora: python scripts/agg_all.py --csv results/bench_v4_qwen_retry.csv")
        return 0

    if not a.probe:
        ap.error("escolha --probe, --full, --dry-run ou --summarize")

    events = bb.load_events(a.limit, None, frozenset())
    arms = (a.arms or f"{QWEN}:v4_single,{CONTROL}:v4_single").split(",")
    # A1 reproduz a condição original (workers=3, o default do runner); A2 isola
    # concorrência; A3 isola o pool regional.
    cells = [("A1", "us-east-1", 3), ("A2", "us-east-1", 1), ("A3", "us-west-2", 3)]
    for label, region, workers in cells:
        run_cell(arms, events, region, workers,
                 RESULTS / f"probe_{label}_{region}_w{workers}.csv",
                 a.control_every, label=f"{label} {region} w{workers}")
        dump_attempts(PROBE_JSONL)
    c = summarize(PROBE_JSONL, PROBE_SUMMARY)
    verdict(c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
