#!/usr/bin/env python3
"""Amostrador do contador cumulativo do WireGuard (ground truth de 4G).

Roda NA EC2 (host do túnel `wg0`). O `wg show wg0 transfer` reporta bytes
rx/tx ACUMULADOS por peer desde que a interface subiu; o consumo de um
período é o DELTA entre duas amostras. Este script apenas anexa uma linha de
snapshot ao CSV — o cálculo de delta fica no `wg_report`/`4g_report`.

Detecta reset da interface (rx/tx decrescem) implicitamente: quem lê o CSV
trata delta negativo como "contador reiniciou" (ver 4g_report.py).

Uso:
    sudo python3 wg_sampler.py              # anexa um snapshot
    # cron (root), a cada 5 min:
    #   */5 * * * * /usr/bin/python3 /opt/4g-monitor/wg_sampler.py >> /var/log/wg_sampler.log 2>&1

Requer root (o `wg show` só lê os contadores como root). Em cron use o crontab
do root ou sudo NOPASSWD para `/usr/bin/wg`.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Prefixo da chave pública -> nome amigável do peer. pi-cam-001 = W35S6c8...
# (a chave real vive só na EC2 em /etc/wireguard/keys; filtramos por prefixo).
PEER_NAMES = {
    "W35S6c8": "pi-cam-001",
}

IFACE = os.environ.get("WG_IFACE", "wg0")
OUT = Path(os.environ.get("WG_HISTORY_CSV", Path(__file__).resolve().parent / "wg_transfer_history.csv"))


def read_transfer(iface: str) -> dict[str, tuple[int, int]]:
    """Retorna {pubkey: (rx_bytes, tx_bytes)} do `wg show <iface> transfer`."""
    proc = subprocess.run(
        ["wg", "show", iface, "transfer"],
        capture_output=True, text=True, timeout=20,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"wg show falhou (rc={proc.returncode}): {proc.stderr.strip()}\n")
        # Fallback: alguns hosts exigem sudo mesmo sob root em cron restrito.
        proc = subprocess.run(
            ["sudo", "-n", "wg", "show", iface, "transfer"],
            capture_output=True, text=True, timeout=20,
        )
        if proc.returncode != 0:
            raise SystemExit(f"não consegui ler wg show {iface} transfer: {proc.stderr.strip()}")
    rows: dict[str, tuple[int, int]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            pub, rx, tx = parts
            try:
                rows[pub] = (int(rx), int(tx))
            except ValueError:
                continue
    return rows


def peer_name(pub: str) -> str:
    for prefix, name in PEER_NAMES.items():
        if pub.startswith(prefix):
            return name
    return pub[:8]


def main() -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = read_transfer(IFACE)
    is_new = not OUT.exists()
    with OUT.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["ts_utc", "peer", "pubkey_prefix", "rx_bytes", "tx_bytes"])
        for pub, (rx, tx) in sorted(rows.items()):
            writer.writerow([ts, peer_name(pub), pub[:8], rx, tx])
    print(f"[{ts}] amostrei {len(rows)} peers -> {OUT}")


if __name__ == "__main__":
    main()
