#!/usr/bin/env python3
"""Persiste o split DIÁRIO de 4G da pi-cam-001 num CSV durável.

Roda na EC2 (cron diário). Congela cada dia COMPLETO numa linha de
`4g_daily.csv`, para que o split sobreviva à rotação do journal (~10h) e à
poda dos frames/clipes — hoje esses dados só vivem no log de 10h.

Colunas:
  date, total_mb, upload_mb, download_mb, video_mb, video_count, frames_mb

Fontes de verdade:
  - upload(rx)/download(tx): deltas do wg_transfer_history.csv (WireGuard).
  - video: soma dos mp4 em /app/uploads/videos/<device> por dia (mtime = hora
    do upload = quando o 4G foi gasto). Sob demanda (CMD_VIDEO_CLIP).
  - frames = upload - video  (evento ~99% + snapshot/live <0,5%).

Idempotente: só anexa dias completos (< hoje) que ainda não estão no CSV.
"""
from __future__ import annotations

import csv
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

BRT = timezone(timedelta(hours=-3))
DEVICE = os.environ.get("DEVICE_ID", "pi-cam-001")
WG_HISTORY = Path(os.environ.get("WG_HISTORY_CSV", "/opt/4g-monitor/wg_transfer_history.csv"))
OUT = Path(os.environ.get("DAILY_CSV", "/opt/4g-monitor/4g_daily.csv"))
ESP32 = os.environ.get("ESP32_CONTAINER", "saira-esp32-server-prod")
HEADER = ["date", "total_mb", "upload_mb", "download_mb", "video_mb", "video_count", "frames_mb"]


def wg_per_day() -> dict[str, list[int]]:
    """{date_brt: [rx_bytes, tx_bytes]} — soma dos deltas entre amostras."""
    day: dict[str, list[int]] = {}
    if not WG_HISTORY.exists():
        return day
    prev = None
    for r in csv.DictReader(WG_HISTORY.open(encoding="utf-8")):
        if r["peer"] != DEVICE:
            continue
        t = datetime.fromisoformat(r["ts_utc"]).astimezone(BRT)
        rx, tx = int(r["rx_bytes"]), int(r["tx_bytes"])
        if prev is not None:
            drx, dtx = rx - prev[0], tx - prev[1]
            if drx >= 0 and dtx >= 0:  # ignora reset da interface (contador zera)
                d = t.strftime("%Y-%m-%d")
                day.setdefault(d, [0, 0])
                day[d][0] += drx
                day[d][1] += dtx
        prev = (rx, tx)
    return day


def video_per_day() -> dict[str, list[int]]:
    """{date_brt: [bytes, count]} dos mp4 subidos (mtime)."""
    cmd = (f"find /app/uploads -path '*{DEVICE}*' -name '*.mp4' "
           r"-printf '%TY-%Tm-%Td %s\n' 2>/dev/null")
    proc = subprocess.run(["docker", "exec", ESP32, "sh", "-c", cmd],
                          capture_output=True, text=True, timeout=120)
    day: dict[str, list[int]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            day.setdefault(parts[0], [0, 0])
            day[parts[0]][0] += int(parts[1])
            day[parts[0]][1] += 1
    return day


def main() -> None:
    wg = wg_per_day()
    vid = video_per_day()
    today = datetime.now(BRT).strftime("%Y-%m-%d")

    existing: set[str] = set()
    if OUT.exists():
        existing = {r["date"] for r in csv.DictReader(OUT.open(encoding="utf-8"))}

    added = []
    for d in sorted(wg):
        if d >= today or d in existing:  # só dias COMPLETOS ainda não gravados
            continue
        rx, tx = wg[d]
        vbytes, vcount = vid.get(d, [0, 0])
        video_mb = round(vbytes / 1e6)
        upload_mb = round(rx / 1e6)
        download_mb = round(tx / 1e6)
        frames_mb = max(0, upload_mb - video_mb)
        total_mb = round((rx + tx) / 1e6)
        added.append([d, total_mb, upload_mb, download_mb, video_mb, vcount, frames_mb])

    if added:
        write_header = not OUT.exists()
        with OUT.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(HEADER)
            w.writerows(added)
        print(f"anexados {len(added)} dia(s): {[r[0] for r in added]}")
    else:
        print("nenhum dia novo a gravar")

    # imprime o CSV inteiro (relatório)
    if OUT.exists():
        print("\n=== 4g_daily.csv ===")
        print(f"{'dia':<12}{'total':>8}{'frames':>9}{'video':>8}{'video#':>7}{'download':>10}")
        for r in csv.DictReader(OUT.open(encoding="utf-8")):
            print(f"{r['date']:<12}{r['total_mb']+' MB':>8}{r['frames_mb']+' MB':>9}"
                  f"{r['video_mb']+' MB':>8}{r['video_count']:>7}{r['download_mb']+' MB':>10}")


if __name__ == "__main__":
    main()
