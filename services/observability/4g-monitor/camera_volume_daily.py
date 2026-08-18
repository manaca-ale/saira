#!/usr/bin/env python3
"""Registro DIÁRIO do volume de imagens por câmera (todas as 6) num CSV durável.

Roda na EC2 (cron diário, após o sync S3 das 03h BRT). Congela cada dia COMPLETO
numa linha por câmera em `camera_volume_daily.csv` — é a fonte da tabela de
consumo por câmera da seção 4.5 dos relatórios mensais (proxy do consumo 4G).

Colunas:
  date, device, ocorr_bytes, ocorr_count, desc_bytes, desc_zips, bulk_bytes, total_bytes

Fontes de verdade:
  - S3 `saira-images` (medido DENTRO do worker via `docker exec` — a role da EC2
    não tem s3:ListBucket; o worker tem credenciais AWS no env):
      * `ocorrencias/{device}/{YYYY}/{MM}/{DD}/`  (JPGs soltos de detecção)
      * `descartadas/{device}/{YYYY-MM-DD}/`      (ZIP diário dos frames sem
        ocorrência — ~95% do volume; atenção: formato de data DIFERENTE)
  - `bulk/{device}/` local no esp32-server (bursts da pi-cam-001 que NÃO migram
    para o S3), por mtime — mesmo padrão do video_per_day() do 4g_daily.py.
    Vídeos ficam FORA (já cobertos pelo 4g_daily.csv e não são imagem).

Idempotente: só anexa pares (dia, câmera) completos (< hoje BRT) ainda ausentes.
Backfill: na primeira execução preenche desde START_DATE (2026-05-18, início dos
ZIPs de descartadas).
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BRT = timezone(timedelta(hours=-3))
DEVICES = os.environ.get(
    "DEVICES", "esp32_001,esp32_002,esp32_003,esp32_004,esp32_005,pi-cam-001"
).split(",")
OUT = Path(os.environ.get("CAMERA_VOLUME_CSV", "/opt/4g-monitor/camera_volume_daily.csv"))
START = os.environ.get("START_DATE", "2026-05-18")
WORKER = os.environ.get("WORKER_CONTAINER", "saira-yolo-worker-prod")
ESP32 = os.environ.get("ESP32_CONTAINER", "saira-esp32-server-prod")
HEADER = ["date", "device", "ocorr_bytes", "ocorr_count",
          "desc_bytes", "desc_zips", "bulk_bytes", "total_bytes"]

# Sub-script executado DENTRO do worker (boto3 + credenciais AWS do container).
# Recebe em argv[1] um JSON [[device, "YYYY-MM-DD"], ...] e devolve uma linha
# S3JSON:{"device|date": [ocorr_bytes, ocorr_count, desc_bytes, desc_zips]}.
S3_SUBSCRIPT = r"""
import json, os, sys
import boto3
s3 = boto3.client("s3", region_name=os.environ.get("S3_REGION", "sa-east-1"))
bucket = os.environ["S3_BUCKET_NAME"]
out = {}
for dev, day in json.loads(sys.argv[1]):
    y, m, d = day.split("-")
    row = []
    for prefix in (f"ocorrencias/{dev}/{y}/{m}/{d}/", f"descartadas/{dev}/{day}/"):
        b = n = 0
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                b += obj["Size"]
                n += 1
        row += [b, n]
    out[f"{dev}|{day}"] = row
print("S3JSON:" + json.dumps(out))
"""


def s3_per_pair(pairs: list[tuple[str, str]]) -> dict[str, list[int]]:
    """{'device|date': [ocorr_bytes, ocorr_count, desc_bytes, desc_zips]} via worker."""
    proc = subprocess.run(
        ["docker", "exec", "-i", WORKER, "python", "-", json.dumps(pairs)],
        input=S3_SUBSCRIPT, capture_output=True, text=True, timeout=3600,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("S3JSON:"):
            return json.loads(line[len("S3JSON:"):])
    raise RuntimeError(f"worker S3 probe failed: {proc.stderr.strip()[:500]}")


def bulk_per_day() -> dict[str, dict[str, int]]:
    """{device: {date: bytes}} das imagens em bulk/ (mtime, só existe local)."""
    cmd = (r"find /app/uploads/bulk -type f \( -iname '*.jpg' -o -iname '*.jpeg' "
           r"-o -iname '*.png' \) -printf '%P %TY-%Tm-%Td %s\n' 2>/dev/null")
    proc = subprocess.run(["docker", "exec", ESP32, "sh", "-c", cmd],
                          capture_output=True, text=True, timeout=300)
    out: dict[str, dict[str, int]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2].isdigit():
            dev = parts[0].split("/")[0]
            out.setdefault(dev, {})
            out[dev][parts[1]] = out[dev].get(parts[1], 0) + int(parts[2])
    return out


def main() -> None:
    today = datetime.now(BRT).strftime("%Y-%m-%d")

    existing: set[str] = set()
    if OUT.exists():
        existing = {f"{r['device']}|{r['date']}" for r in csv.DictReader(OUT.open(encoding="utf-8"))}

    pairs: list[tuple[str, str]] = []
    day = date.fromisoformat(START)
    while day.isoformat() < today:
        for dev in DEVICES:
            if f"{dev}|{day.isoformat()}" not in existing:
                pairs.append((dev, day.isoformat()))
        day += timedelta(days=1)

    if not pairs:
        print("nenhum (dia, câmera) novo a gravar")
        return

    print(f"medindo {len(pairs)} pares (dia, câmera) no S3...")
    s3 = s3_per_pair(pairs)
    bulk = bulk_per_day()

    added = 0
    write_header = not OUT.exists()
    with OUT.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(HEADER)
        for dev, day_s in pairs:
            ob, oc, db, dz = s3.get(f"{dev}|{day_s}", [0, 0, 0, 0])
            bb = bulk.get(dev, {}).get(day_s, 0)
            w.writerow([day_s, dev, ob, oc, db, dz, bb, ob + db + bb])
            added += 1
    print(f"anexadas {added} linha(s) em {OUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # cron: falha visível no log, exit != 0
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)
