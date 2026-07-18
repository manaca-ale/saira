#!/usr/bin/env python3
"""Agrega os logs do agente da Pi em uso de 4G POR FONTE (event/live/snapshot).

Roda NA EC2. Puxa o journal do `saira-agent` da Pi por SSH (read-only) e
soma bytes/frames por fonte a partir das linhas de log que o agente já emite:

    * evento (per-frame) : "Upload OK <name> (<N> bytes, ...)"   -> bytes exatos
    * evento (batch)     : "Batch OK <evt>: <K> frames (...)"    -> só CONTAGEM
    * ao vivo            : "Live OK (<N> bytes, ...)"            -> bytes exatos
    * snapshot           : "CMD_SNAPSHOT: frame enviado (<N> bytes)" -> bytes exatos

⚠️ Limitação real: o caminho BATCH (o dominante em campo) loga a contagem de
frames mas NÃO os bytes. Para batch estimamos bytes = frames × avg_kb, onde
avg_kb vem da média das linhas per-frame da mesma janela (fallback 250 KB).
Os bytes "verdade" das imagens vêm do disco (ver 4g_report.py); aqui o valor
é a MELHOR estimativa por fonte + o SPLIT (proporção) que o disco não separa
(frames de live e evento ficam indistinguíveis no /app/uploads).

Uso:
    python3 usage_aggregator.py --since "2026-07-18 00:00:00"
    python3 usage_aggregator.py --since today --csv usage_by_hour.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from collections import defaultdict

PI_SSH = os.environ.get("PI_SSH", "saira@10.8.0.3")
AGENT_UNIT = os.environ.get("AGENT_UNIT", "saira-agent")
DEFAULT_AVG_KB = float(os.environ.get("FRAME_AVG_KB", "250"))

# A linha do app (journalctl -o cat) começa com 'YYYY-MM-DD HH:MM:SS,mmm'.
RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):")
RE_EVENT_FRAME = re.compile(r"Upload OK \S+ \((\d+) bytes")
RE_LIVE = re.compile(r"Live OK \((\d+) bytes")
RE_SNAPSHOT = re.compile(r"CMD_SNAPSHOT: frame enviado \((\d+) bytes")
RE_BATCH = re.compile(r"Batch OK \S+: (\d+) frames")
RE_REASON = re.compile(r"reason=([a-z:_]+)")
RE_TRIM = re.compile(r"window_trimmed .*?frames=(\d+)->(\d+)")


def fetch_journal(since: str | None, until: str | None) -> list[str]:
    cmd = f"journalctl -u {AGENT_UNIT} --no-pager -o cat"
    if since:
        cmd += f' --since "{since}"'
    if until:
        cmd += f' --until "{until}"'
    proc = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=15", PI_SSH, cmd],
        capture_output=True, text=True, timeout=240,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ssh/journalctl falhou: {proc.stderr.strip()}")
    return proc.stdout.splitlines()


def aggregate(lines: list[str]) -> dict:
    # (day, hour, source) -> [frames, exact_bytes]
    buckets: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    batch_frames: dict[tuple[str, str], int] = defaultdict(int)  # (day,hour) -> frames
    reasons: dict[str, int] = defaultdict(int)
    trims: list[tuple[int, int]] = []
    per_frame_bytes: list[int] = []

    for line in lines:
        mts = RE_TS.match(line)
        if not mts:
            continue
        day, hour = mts.group(1), mts.group(2)

        m = RE_EVENT_FRAME.search(line)
        if m:
            n = int(m.group(1))
            buckets[(day, hour, "event")][0] += 1
            buckets[(day, hour, "event")][1] += n
            per_frame_bytes.append(n)
            continue
        m = RE_LIVE.search(line)
        if m:
            n = int(m.group(1))
            buckets[(day, hour, "live")][0] += 1
            buckets[(day, hour, "live")][1] += n
            per_frame_bytes.append(n)
            continue
        m = RE_SNAPSHOT.search(line)
        if m:
            n = int(m.group(1))
            buckets[(day, hour, "snapshot")][0] += 1
            buckets[(day, hour, "snapshot")][1] += n
            per_frame_bytes.append(n)
            continue
        m = RE_BATCH.search(line)
        if m:
            batch_frames[(day, hour)] += int(m.group(1))
            continue
        m = RE_REASON.search(line)
        if m:
            reasons[m.group(1)] += 1
            continue
        m = RE_TRIM.search(line)
        if m:
            trims.append((int(m.group(1)), int(m.group(2))))

    avg_kb = (sum(per_frame_bytes) / len(per_frame_bytes) / 1024) if per_frame_bytes else DEFAULT_AVG_KB
    # Estima bytes dos frames de batch (que não logam bytes) pela média medida.
    for (day, hour), frames in batch_frames.items():
        buckets[(day, hour, "event")][0] += frames
        buckets[(day, hour, "event")][1] += int(frames * avg_kb * 1024)

    return {"buckets": buckets, "reasons": reasons, "trims": trims, "avg_kb": avg_kb}


def summarize(agg: dict) -> None:
    buckets = agg["buckets"]
    by_source: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (day, hour, source), (frames, byts) in buckets.items():
        by_source[source][0] += frames
        by_source[source][1] += byts
    total_bytes = sum(v[1] for v in by_source.values()) or 1

    print("\n=== 4G por fonte (janela do journal) ===")
    print(f"{'fonte':<12}{'frames':>10}{'MB':>10}{'%':>7}")
    for source in ("event", "live", "snapshot"):
        frames, byts = by_source.get(source, [0, 0])
        print(f"{source:<12}{frames:>10}{byts/1e6:>10.1f}{100*byts/total_bytes:>7.1f}")
    print(f"{'TOTAL':<12}{'':>10}{total_bytes/1e6:>10.1f}")
    print(f"(avg frame = {agg['avg_kb']:.0f} KB; bytes de batch são ESTIMADOS por essa média)")

    if agg["reasons"]:
        print("\n=== reason= (por que eventos abriram/fecharam) ===")
        for reason, count in sorted(agg["reasons"].items(), key=lambda x: -x[1]):
            print(f"  {count:>6}  {reason}")

    if agg["trims"]:
        got = [a for a, _ in agg["trims"]]
        used = [b for _, b in agg["trims"]]
        print(f"\n=== window_trimmed (worker) : {len(agg['trims'])} eventos ===")
        print(f"  frames subidos p/ janela: media {sum(got)/len(got):.0f}  |  "
              f"usados pelo modelo: media {sum(used)/len(used):.0f}  "
              f"-> {100*(1-sum(used)/sum(got)):.0f}% descartados (desperdício de 4G)")


def write_csv(agg: dict, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["day", "hour", "source", "frames", "bytes"])
        for (day, hour, source), (frames, byts) in sorted(agg["buckets"].items()):
            writer.writerow([day, hour, source, frames, byts])
    print(f"\nCSV por hora/fonte -> {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="today")
    ap.add_argument("--until", default=None)
    ap.add_argument("--csv", default=None, help="grava CSV por (dia,hora,fonte)")
    args = ap.parse_args()

    lines = fetch_journal(args.since, args.until)
    if not lines:
        print("journal vazio para a janela pedida.", file=sys.stderr)
    agg = aggregate(lines)
    summarize(agg)
    if args.csv:
        write_csv(agg, args.csv)


if __name__ == "__main__":
    main()
