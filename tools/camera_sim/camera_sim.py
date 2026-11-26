#!/usr/bin/env python3
"""Simulador da pi-cam: manda eventos históricos ao esp32-server de TESTE como a Pi manda.

Frente saira-rollout-develop (teste de ponta a ponta do funil A, campanha 54).

O que a Pi faz (services/raspberry-pi/agent/saira_agent.py, `_flush_event_batch`) e este
simulador repete:
  - POST `{base}/upload-batch`, cabeçalho `X-Device-Id`, N partes `imageFile`
    (`f000.jpg`, `f001.jpg`, ... `image/jpeg`) e os campos `event_id` e `event_state`
    (`active` nos lotes do meio, `end` no último, que fecha o manifesto);
  - lotes de 5 quadros (o `EVENT_BATCH_SIZE` da pi-cam-001: os nomes históricos terminam
    em -000 a -004), no mesmo intervalo entre lotes que o evento original teve;
  - os campos `gate_fg_px`, `gate_delta_px` e `gate_config_version`, quando o manifesto
    original os tem.

Quais quadros vão: a janela que o worker de produção montou para o evento (reconstruída e
conferida pela campanha 54 em `sample.csv`), quando ela está toda no disco; senão os 5
quadros do gate (eventos S0 sem disparo em produção). Com 5 quadros e
`GEMINI_GATE_MID_FRAMES=3`, o worker escolhe exatamente esses 5 para o gate.

Subcomandos:
  montar  lê a amostra e os resultados do replay e grava `eventos.csv` (um evento `dev`
          por linha, com o que o replay previu em cada etapa) e as rodadas;
  enviar  manda os eventos de uma rodada (`--seco` monta as requisições sem enviar).

Travas: só eventos `split=dev` (o conjunto `aval` da campanha 54 é intocável) e nunca o
id da câmera real (`pi-cam-001`).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

REAL_DEVICES = {"pi-cam-001"}
BATCH_SIZE = 5
FILTER_THR = 0.30
GATE_CONF = 85
_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})-(\d{6})(?:-(\d{3}))?\.jpg$")

FIELDS = [
    "event_id", "split", "estrato", "sub", "status", "dia", "inicio", "fonte", "n_quadros", "quadros",
    "filtro_nota", "filtro_passa", "gate_r1", "gate_r2", "gate_conf_r1",
    "detail_cru", "detail_final", "previsto_alerta", "rodada",
]


class SimError(RuntimeError):
    pass


# ── nomes e lotes ─────────────────────────────────────────────────────────────
def edge_headers(device_id: str) -> dict:
    """Cabeçalhos da borda. CAMERA_SIM_DEVICE_TOKEN só é preciso quando o
    esp32-server está com EDGE_AUTH_REQUIRED ligado."""
    headers = {"X-Device-Id": device_id}
    token = os.environ.get("CAMERA_SIM_DEVICE_TOKEN", "").strip()
    if token:
        headers["X-Device-Token"] = token
    return headers


def frame_time(name: str) -> datetime:
    m = _NAME.match(name)
    if not m:
        raise SimError(f"nome de quadro fora do padrão: {name}")
    day, hh, mm, ss, us, _ = m.groups()
    return datetime.strptime(f"{day} {hh}:{mm}:{ss}.{us}", "%Y-%m-%d %H:%M:%S.%f")


def split_batches(names: list[str], size: int = BATCH_SIZE) -> list[tuple[float, list[str]]]:
    """Agrupa os quadros nos lotes em que a Pi os mandou: um lote novo começa no índice
    -000, quando o índice não é o seguinte, ou ao chegar a `size` quadros. Devolve
    (segundos desde o primeiro quadro, nomes) de cada lote."""
    if not names:
        return []
    t0 = frame_time(names[0])
    out: list[tuple[float, list[str]]] = []
    prev_idx: Optional[int] = None
    for n in names:
        idx_s = _NAME.match(n).group(6) if _NAME.match(n) else None
        idx = int(idx_s) if idx_s is not None else None
        new = (not out or idx is None or prev_idx is None or idx != prev_idx + 1
               or len(out[-1][1]) >= size)
        if new:
            out.append(((frame_time(n) - t0).total_seconds(), [n]))
        else:
            out[-1][1].append(n)
        prev_idx = idx
    return out


# ── montar: lista de eventos com o previsto pelo replay ──────────────────────
def _jsonl(path: Path) -> dict[str, dict]:
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error"):
                out[r["event_id"]] = r
    return out


def _sub(row: dict) -> str:
    if row["estrato"] != "S2":
        return row["estrato"]
    return {"CONFIRMADO": "S2C", "REJEITADO": "S2R"}.get(row["status"], "S2X")


def build_events(sample_csv: Path, results: Path, frame_dirs: list[Path]) -> list[dict]:
    have: set[str] = set()
    for d in frame_dirs:
        if d.is_dir():
            have.update(p.name for p in d.iterdir())
    filt = _jsonl(results / "dgate54__q5_gate5_low__r1.jsonl")
    g1 = _jsonl(results / "gate54__nvl_v1p_low_ctx__r1.jsonl")
    g2 = _jsonl(results / "gate54__nvl_v1p_low_ctx__r2.jsonl")
    det = _jsonl(results / "detail54__d38f_g3_low_low__r1.jsonl")
    rows = []
    with sample_csv.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["split"] != "dev":
                continue                      # aval: intocável
            win, g5 = r["window"].split("|"), r["gate5"].split("|")
            if all(n in have for n in win):
                fonte, frames = "janela", win
            elif all(n in have for n in g5):
                fonte, frames = "gate5", g5
            else:
                fonte, frames = "faltam", []
            f = filt.get(r["event_id"])
            nota = None
            if f:
                nota = ((f.get("answers") or {}).get("wl_v2") or {}).get("noul")
            passa = nota is not None and nota >= FILTER_THR
            a, b = g1.get(r["event_id"]), g2.get(r["event_id"])
            d = det.get(r["event_id"])
            fire = bool(a and a.get("fire")) if a else None
            cru = (bool(d.get("raw_disposal")) if d else None) if fire else None
            fin = (bool(d.get("disposal")) if d else None) if fire else None
            rows.append({
                "event_id": r["event_id"], "split": r["split"], "estrato": r["estrato"], "sub": _sub(r),
                "status": r["status"], "dia": r["dia"],
                "inicio": frame_time(frames[0]).strftime("%H:%M:%S") if frames else "",
                "fonte": fonte, "n_quadros": len(frames), "quadros": "|".join(frames),
                "filtro_nota": "" if nota is None else f"{nota:.4f}",
                "filtro_passa": int(passa) if nota is not None else "",
                "gate_r1": "" if a is None else int(bool(a.get("fire"))),
                "gate_r2": "" if b is None else int(bool(b.get("fire"))),
                "gate_conf_r1": "" if a is None else a.get("conf", ""),
                "detail_cru": "" if cru is None else int(cru),
                "detail_final": "" if fin is None else int(fin),
                # GEMINI_REQUIRE_BBOX=false no rollout: vale a resposta crua do detail.
                "previsto_alerta": int(bool(passa and fire and cru)),
                "rodada": "",
            })
    return rows


def assign_rounds(rows: list[dict], n_r0: int = 20, seed: int = 54) -> None:
    """R0 (encanamento): eventos que passam por todos os caminhos do funil (barrado no
    filtro, gate sem disparo, gate com disparo e detail sim/não). R1: todos os outros
    eventos `dev` com quadros no disco."""
    rng = random.Random(seed)
    ok = [r for r in rows if r["fonte"] != "faltam"]
    paths = {
        "barrado_no_filtro": [r for r in ok if r["filtro_passa"] == 0 and r["sub"] == "S0"],
        "gate_nao": [r for r in ok if r["filtro_passa"] == 1 and r["gate_r1"] == 0],
        "alerta_confirmado": [r for r in ok if r["previsto_alerta"] == 1 and r["sub"] == "S2C"],
        "detail_nao": [r for r in ok if r["filtro_passa"] == 1 and r["gate_r1"] == 1
                       and r["detail_cru"] == 0],
        "alerta_rejeitado": [r for r in ok if r["previsto_alerta"] == 1 and r["sub"] == "S2R"],
    }
    quota = {"barrado_no_filtro": 6, "gate_nao": 4, "alerta_confirmado": 4, "detail_nao": 3,
             "alerta_rejeitado": 3}
    chosen: list[dict] = []
    for k, pool in paths.items():
        pool = [r for r in pool if r not in chosen]
        chosen += rng.sample(pool, min(quota[k], len(pool)))
    for r in chosen[:n_r0]:
        r["rodada"] = "R0"
    for r in ok:
        if not r["rodada"]:
            r["rodada"] = "R1"


def write_events(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def read_events(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# ── enviar ────────────────────────────────────────────────────────────────────
@dataclass
class Request:
    url: str
    headers: dict
    data: dict
    files: list = field(default_factory=list)   # [(campo, (nome, bytes, mime))]
    offset_s: float = 0.0


def check_device(device_id: str) -> None:
    if device_id.strip().lower() in REAL_DEVICES:
        raise SimError(f"{device_id} é a câmera real; use um id simulado (pi-cam-sim-001)")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", device_id):
        raise SimError(f"id de dispositivo inválido: {device_id!r}")


def sim_event_id(tag: str, event_id: str) -> str:
    eid = f"sim{tag}-{event_id}"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", eid):
        raise SimError(f"event_id simulado inválido: {eid!r}")
    return eid


def build_requests(event: dict, base_url: str, device_id: str, tag: str,
                   read_frame: Callable[[str], bytes], manifest: Optional[dict] = None,
                   velocidade: float = 1.0) -> list[Request]:
    """As requisições de um evento, na ordem e no intervalo em que a Pi as mandaria."""
    check_device(device_id)
    names = [n for n in event["quadros"].split("|") if n]
    if not names:
        raise SimError(f"{event['event_id']}: sem quadros no disco")
    eid = sim_event_id(tag, event["event_id"])
    extra = {k: str(manifest[k]) for k in ("gate_fg_px", "gate_delta_px", "gate_config_version")
             if manifest and manifest.get(k) not in (None, "")}
    batches = split_batches(names)
    out = []
    for i, (off, batch) in enumerate(batches):
        last = i == len(batches) - 1
        data = {"event_id": eid, "event_state": "end" if last else "active", **extra}
        files = [("imageFile", (f"f{j:03d}.jpg", read_frame(n), "image/jpeg"))
                 for j, n in enumerate(batch)]
        out.append(Request(url=base_url.rstrip("/") + "/upload-batch",
                           headers=edge_headers(device_id), data=data, files=files,
                           offset_s=off / max(velocidade, 1e-6)))
    return out


def next_time_of_day(hhmmss: str, now: datetime) -> datetime:
    t = datetime.strptime(hhmmss, "%H:%M:%S").time()
    at = datetime.combine(now.date(), t)
    return at if at >= now else at + timedelta(days=1)


def schedule(events: list[dict], now: datetime, hora_original: bool, intervalo_s: float,
             min_gap_s: float = 10.0) -> list[tuple[datetime, dict]]:
    """Quando mandar cada evento. Sem `hora_original`: um atrás do outro, a cada
    `intervalo_s`. Com ela: na próxima vez em que o relógio marcar a hora de início do
    evento original (o gate leva `horario_local` no texto), em ordem de hora do dia, com
    pelo menos `min_gap_s` entre dois eventos."""
    if not hora_original:
        return [(now + timedelta(seconds=i * intervalo_s), e) for i, e in enumerate(events)]
    plan = sorted(((next_time_of_day(e["inicio"], now), e) for e in events), key=lambda x: x[0])
    out, last = [], None
    for at, e in plan:
        if last is not None and at < last + timedelta(seconds=min_gap_s):
            at = last + timedelta(seconds=min_gap_s)
        out.append((at, e))
        last = at
    return out


def find_frame(name: str, frame_dirs: list[Path]) -> Path:
    for d in frame_dirs:
        p = d / name
        if p.is_file():
            return p
    raise SimError(f"quadro não encontrado: {name}")


def sent_ok(log_path: Path) -> set[str]:
    """event_id dos eventos que o log já tem como enviados sem erro (para `--retomar`)."""
    done: set[str] = set()
    if not log_path.is_file():
        return done
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if not r.get("seco") and not r.get("erro") and r.get("http") and all(c == 200 for c in r["http"]):
            done.add(r["event_id"])
    return done


def run_send(events: list[dict], *, base_url: str, device_id: str, tag: str,
             frame_dirs: list[Path], manifest_dir: Optional[Path], log_path: Path,
             seco: bool, limite: int, hora_original: bool, intervalo_s: float,
             velocidade: float, post: Optional[Callable] = None,
             sleep: Callable[[float], None] = time.sleep,
             clock: Callable[[], datetime] = datetime.now,
             paralelo: int = 1, tentativas: int = 1, pausa_tentativa_s: float = 5.0,
             retomar: bool = False) -> list[dict]:
    """Manda os eventos. `paralelo` > 1 deixa um evento começar na hora marcada mesmo com
    o anterior ainda no ar: a Pi nunca sobrepõe eventos, mas a amostra junta 4 meses num
    dia só (33 h de eventos em 24 h) e, um atrás do outro, a hora do dia se perderia. O
    worker trata cada evento pelo seu manifesto, então a sobreposição não mistura quadros.
    `tentativas` repete o lote só quando não houve resposta (túnel caído); `retomar` pula
    os eventos que o log já tem como enviados sem erro."""
    check_device(device_id)
    for e in events:
        if e.get("split") != "dev":
            raise SimError(f"{e['event_id']} não é do conjunto dev")
    events = [e for e in events if e["fonte"] != "faltam"][:max(0, limite)]
    if retomar:
        done = sent_ok(log_path)
        events = [e for e in events if e["event_id"] not in done]
    plan = schedule(events, clock(), hora_original, intervalo_s)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_lock = threading.Lock()

    def send_event(at: datetime, e: dict) -> dict:
        manifest = None
        if manifest_dir is not None:
            mp = manifest_dir / f"{e['event_id']}.json"
            if mp.is_file():
                manifest = json.loads(mp.read_text(encoding="utf-8"))
        reqs = build_requests(e, base_url, device_id, tag,
                              lambda n: find_frame(n, frame_dirs).read_bytes(),
                              manifest=manifest, velocidade=velocidade)
        rec = {"event_id": e["event_id"], "sim_event_id": reqs[0].data["event_id"],
               "device_id": device_id, "rodada": e.get("rodada", ""), "agendado": at.isoformat(),
               "n_quadros": sum(len(r.files) for r in reqs), "lotes": len(reqs),
               "bytes": sum(len(f[1][1]) for r in reqs for f in r.files), "seco": seco,
               "http": [], "enviado_em": [], "erro": ""}
        if not seco:
            rec["atraso_s"] = round(max(0.0, (clock() - at).total_seconds()), 1)
            t0 = time.monotonic()
            for r in reqs:
                lag = r.offset_s - (time.monotonic() - t0)
                if lag > 0:
                    sleep(lag)
                for k in range(max(1, tentativas)):
                    try:
                        resp = post(r.url, headers=r.headers, data=r.data, files=r.files, timeout=60)
                        rec["http"].append(resp.status_code)
                        rec["erro"] = ""
                        break
                    except Exception as exc:  # noqa: BLE001 — registra e segue para o próximo
                        rec["erro"] = f"{type(exc).__name__}: {exc}"[:300]
                        if k + 1 < max(1, tentativas):
                            rec["novas_tentativas"] = rec.get("novas_tentativas", 0) + 1
                            sleep(pausa_tentativa_s)
                if rec["erro"]:
                    rec["http"].append(0)
                rec["enviado_em"].append(datetime.now().isoformat(timespec="milliseconds"))
                if rec["erro"]:
                    break
        with log_lock:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def wait_until(at: datetime) -> None:
        if not seco:
            wait = (at - clock()).total_seconds()
            if wait > 0:
                sleep(wait)

    if paralelo <= 1 or seco:
        out = []
        for at, e in plan:
            wait_until(at)
            out.append(send_event(at, e))
        return out
    with ThreadPoolExecutor(max_workers=paralelo) as pool:
        futures = []
        for at, e in plan:
            wait_until(at)
            futures.append(pool.submit(send_event, at, e))
        return [f.result() for f in futures]


# ── linha de comando ──────────────────────────────────────────────────────────
HIST = Path(r"C:\Saira\data\historico-picam")
C54 = Path(r"C:\Saira-migracao\benchmarks\campaigns\54-picam001-history-replay-2026-11-18\results")


def main(argv: Optional[Iterable[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("montar")
    m.add_argument("--amostra", type=Path, default=HIST / "amostra" / "sample.csv")
    m.add_argument("--resultados", type=Path, default=C54)
    m.add_argument("--quadros", type=Path, nargs="+",
                   default=[HIST / "frames" / "janela", HIST / "frames" / "gate5"])
    m.add_argument("--saida", type=Path, required=True)
    e = sub.add_parser("enviar")
    e.add_argument("--eventos", type=Path, required=True)
    e.add_argument("--rodada", required=True)
    # 15002 e não 5002: nesta máquina a 5002 local pode ser de outro contêiner (testspace)
    e.add_argument("--url", default="http://127.0.0.1:15002")
    e.add_argument("--device", default="pi-cam-sim-001")
    e.add_argument("--tag", required=True, help="marca da rodada no event_id (ex.: 0, 1)")
    e.add_argument("--quadros", type=Path, nargs="+",
                   default=[HIST / "frames" / "janela", HIST / "frames" / "gate5"])
    e.add_argument("--manifestos", type=Path, default=HIST / "extraido" / "events")
    e.add_argument("--log", type=Path, required=True)
    e.add_argument("--limite", type=int, required=True)
    e.add_argument("--seco", action="store_true")
    e.add_argument("--hora-original", action="store_true")
    e.add_argument("--intervalo", type=float, default=30.0)
    e.add_argument("--velocidade", type=float, default=1.0)
    e.add_argument("--paralelo", type=int, default=1,
                   help="eventos no ar ao mesmo tempo (com --hora-original, para a hora não atrasar)")
    e.add_argument("--tentativas", type=int, default=1,
                   help="vezes que um lote é tentado quando não há resposta (túnel caído)")
    e.add_argument("--retomar", action="store_true",
                   help="pula os eventos que o log já tem como enviados sem erro")
    a = ap.parse_args(list(argv) if argv is not None else None)

    if a.cmd == "montar":
        rows = build_events(a.amostra, a.resultados, a.quadros)
        assign_rounds(rows)
        write_events(rows, a.saida)
        from collections import Counter
        print("eventos dev:", len(rows), dict(Counter(r["rodada"] or "-" for r in rows)),
              "| fonte:", dict(Counter(r["fonte"] for r in rows)),
              "| alertas previstos:", sum(int(r["previsto_alerta"]) for r in rows))
        return 0

    events = [r for r in read_events(a.eventos) if r["rodada"] == a.rodada]
    post = None
    if not a.seco:
        import requests
        local = threading.local()

        def post(url, **kw):  # uma sessão por thread: requests.Session não é segura entre threads
            if not hasattr(local, "session"):
                local.session = requests.Session()
            return local.session.post(url, **kw)
    recs = run_send(events, base_url=a.url, device_id=a.device, tag=a.tag,
                    frame_dirs=a.quadros, manifest_dir=a.manifestos, log_path=a.log,
                    seco=a.seco, limite=a.limite, hora_original=a.hora_original,
                    intervalo_s=a.intervalo, velocidade=a.velocidade, post=post,
                    paralelo=a.paralelo, tentativas=a.tentativas, retomar=a.retomar)
    n_err = sum(1 for r in recs if r["erro"] or any(c != 200 for c in r["http"]))
    print(f"{len(recs)} eventos {'montados (seco)' if a.seco else 'enviados'}, "
          f"{sum(r['n_quadros'] for r in recs)} quadros, "
          f"{sum(r['bytes'] for r in recs) / 1e6:.1f} MB, com erro: {n_err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
