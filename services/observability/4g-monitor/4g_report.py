#!/usr/bin/env python3
"""Relatório diário de 4G da pi-cam-001 — junta as 3 fontes de verdade.

Roda NA EC2. Combina:
  1. DISCO (verdade dos bytes de imagem): soma `/app/uploads/*pi-cam-001*` por
     dia via `docker exec` no esp32-server. É o total real de frames subidos
     (evento+live+snapshot) enquanto não podado pelo sync do Drive.
  2. WIREGUARD (verdade do total): delta de rx/tx do `wg_transfer_history.csv`
     (gerado pelo wg_sampler.py). rx = uploads Pi->EC2; tx = downloads EC2->Pi
     (comandos, config, deploy/SSH).
  3. SPLIT por fonte: opcionalmente chama o usage_aggregator (journal da Pi)
     para separar evento vs live vs snapshot — o disco não distingue.

Atribuição final:
    residual (SSH/keepalive/overhead) = WG_rx_delta - bytes_de_imagem_no_disco

Uso:
    python3 4g_report.py                 # últimos dias (disco) + delta WG total
    python3 4g_report.py --days 7
    python3 4g_report.py --split --since today   # + split por fonte do journal
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEVICE = os.environ.get("DEVICE_ID", "pi-cam-001")
ESP32_CONTAINER = os.environ.get("ESP32_CONTAINER", "saira-esp32-server-prod")
UPLOAD_ROOT = os.environ.get("UPLOAD_ROOT", "/app/uploads")
WG_HISTORY = Path(os.environ.get("WG_HISTORY_CSV", Path(__file__).resolve().parent / "wg_transfer_history.csv"))


def disk_bytes_per_day() -> dict[str, tuple[int, int]]:
    """{YYYY-MM-DD: (frames, bytes)} somando a árvore inteira (frames movidos
    para processed/ocorrencias/sem_ocorrencia continuam contando)."""
    find = (
        f"find {UPLOAD_ROOT} -path '*{DEVICE}*' -name '*.jpg' "
        r"-printf '%TY-%Tm-%Td %s\n' 2>/dev/null"
    )
    proc = subprocess.run(
        ["docker", "exec", ESP32_CONTAINER, "sh", "-c", find],
        capture_output=True, text=True, timeout=180,
    )
    days: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            days[parts[0]][0] += 1
            days[parts[0]][1] += int(parts[1])
    return {k: (v[0], v[1]) for k, v in days.items()}


def wg_deltas() -> list[tuple[str, str, int, int]]:
    """Deltas (rx, tx) por peer entre amostras consecutivas do CSV do sampler.
    Trata reset da interface (delta negativo -> ignora esse intervalo)."""
    if not WG_HISTORY.exists():
        return []
    rows: list[dict] = []
    with WG_HISTORY.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    last: dict[str, tuple[str, int, int]] = {}
    out: list[tuple[str, str, int, int]] = []
    for r in rows:
        peer = r["peer"]
        rx, tx = int(r["rx_bytes"]), int(r["tx_bytes"])
        if peer in last:
            pts, prx, ptx = last[peer]
            drx, dtx = rx - prx, tx - ptx
            if drx >= 0 and dtx >= 0:
                out.append((pts, r["ts_utc"], drx, dtx))
        last[peer] = (r["ts_utc"], rx, tx)
    return out


def fmt_mb(b: int) -> str:
    return f"{b/1e6:,.1f} MB" if b < 1e9 else f"{b/1e9:,.2f} GB"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--split", action="store_true", help="split por fonte via journal da Pi")
    ap.add_argument("--since", default="today")
    args = ap.parse_args()

    print(f"=== 4G {DEVICE} — bytes de imagem no disco (por dia) ===")
    print(f"{'dia':<12}{'frames':>9}{'imagem':>14}   {'proj/dia*'}")
    days = disk_bytes_per_day()
    today = datetime.now().strftime("%Y-%m-%d")
    for day in sorted(days)[-args.days:]:
        frames, byts = days[day]
        proj = ""
        if day == today:
            hour = datetime.now().hour + datetime.now().minute / 60
            if hour > 0:
                proj = fmt_mb(int(byts * 24 / hour)) + " (parcial)"
        print(f"{day:<12}{frames:>9}{fmt_mb(byts):>14}   {proj}")
    print("* projeção linear do dia corrente (só o dia de hoje, ainda não podado)")

    deltas = wg_deltas()
    if deltas:
        pi = [d for d in deltas if True]  # todos os peers já vêm nomeados
        print(f"\n=== WireGuard — consumo por intervalo amostrado ({WG_HISTORY.name}) ===")
        tot_rx = sum(d[2] for d in deltas)
        tot_tx = sum(d[3] for d in deltas)
        print(f"  amostras: {len(deltas)+1}  |  rx(uploads Pi->EC2)={fmt_mb(tot_rx)}  "
              f"tx(downloads EC2->Pi)={fmt_mb(tot_tx)}")
        # Reconciliação grosseira com o disco de hoje.
        if today in days:
            disk_today = days[today][1]
            print(f"  disco hoje={fmt_mb(disk_today)}  ->  residual(SSH/keepalive/overhead) "
                  f"~= rx_delta - disco (calcule sobre a MESMA janela)")
    else:
        print(f"\n[WG] sem histórico ainda ({WG_HISTORY}). Rode wg_sampler.py 2x para ter delta.")

    if args.split:
        print("\n=== SPLIT por fonte (journal da Pi) ===")
        subprocess.run(
            ["python3", str(Path(__file__).resolve().parent / "usage_aggregator.py"),
             "--since", args.since],
            check=False,
        )


if __name__ == "__main__":
    main()
