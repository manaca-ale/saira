#!/usr/bin/env python3
"""Relatório MENSAL de volume de imagens por câmera, por e-mail (Resend).

Roda na EC2 (cron no dia 1 do mês). Agrega o mês fechado do
`camera_volume_daily.csv` (gerado pelo camera_volume_daily.py) e envia a tabela
por câmera — a mesma métrica usada na seção 4.5 (Conectividade 4G) dos
relatórios mensais EMLURB.

Envio reaproveita a infra do Alertmanager: API HTTP do Resend, com a key lida
do mesmo arquivo de secret (`observability/alertmanager/secrets/resend_api_key`).

Uso:
  camera_volume_monthly_report.py                  # mês anterior, envia
  camera_volume_monthly_report.py --month 2026-07  # mês específico
  camera_volume_monthly_report.py --dry-run        # imprime sem enviar
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRT = timezone(timedelta(hours=-3))
CSV_PATH = Path(os.environ.get("CAMERA_VOLUME_CSV", "/opt/4g-monitor/camera_volume_daily.csv"))
KEY_FILE = Path(os.environ.get(
    "RESEND_API_KEY_FILE",
    "/home/ubuntu/saira/services/observability/alertmanager/secrets/resend_api_key"))
MAIL_FROM = os.environ.get("MAIL_FROM", "SAIRA Alertas <saira@pagamentos.manaca.tech>")
MAIL_TO = os.environ.get("MAIL_TO", "alecoleto@gmail.com,contato@manaca.tech").split(",")

# Mapeamento device → nome da câmera nos relatórios (Controle Simcard)
CAMERA_NAMES = {
    "esp32_001": "Via Mangue III-1 (Imbiribeira)",
    "esp32_002": "Mangabeira",
    "esp32_003": "Sá e Souza",
    "esp32_004": "Irmã Dorothy",
    "esp32_005": "Arruda",
    "pi-cam-001": "Via Mangue III-2 (alta definição)",
}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def gb(n: int) -> str:
    """Bytes → 'X,XX GB' (decimal, vírgula pt-BR)."""
    return f"{n / 1e9:.2f}".replace(".", ",") + " GB"


def aggregate(month: str) -> tuple[dict[str, dict], int]:
    """{device: {bytes, ocorr_count, days}} para o mês YYYY-MM + total de bytes."""
    per_dev: dict[str, dict] = {}
    total = 0
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV não existe: {CSV_PATH}")
    for r in csv.DictReader(CSV_PATH.open(encoding="utf-8")):
        if not r["date"].startswith(month):
            continue
        d = per_dev.setdefault(r["device"], {"bytes": 0, "ocorr_count": 0, "days": 0})
        row_bytes = int(r["total_bytes"])
        d["bytes"] += row_bytes
        d["ocorr_count"] += int(r["ocorr_count"])
        if row_bytes > 0:
            d["days"] += 1
        total += row_bytes
    return per_dev, total


def build_html(month: str, per_dev: dict[str, dict], total: int) -> str:
    y, m = month.split("-")
    mes_nome = f"{MESES[int(m) - 1]}/{y}"
    rows = []
    for dev in CAMERA_NAMES:
        d = per_dev.get(dev)
        if not d or d["bytes"] == 0:
            rows.append(f"<tr><td>{CAMERA_NAMES[dev]}</td><td>{dev}</td>"
                        f"<td style='text-align:right'>—</td>"
                        f"<td style='text-align:right'>0</td></tr>")
        else:
            rows.append(f"<tr><td>{CAMERA_NAMES[dev]}</td><td>{dev}</td>"
                        f"<td style='text-align:right'><strong>{gb(d['bytes'])}</strong></td>"
                        f"<td style='text-align:right'>{d['days']}</td></tr>")
    return f"""
<p>Volume de imagens por câmera em <strong>{mes_nome}</strong> — base para a
tabela de consumo 4G (seção 4.5) do relatório mensal.</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
  <tr><th>Câmera</th><th>Device</th><th>Consumo</th><th>Dias com dados</th></tr>
  {''.join(rows)}
  <tr><td colspan="2"><strong>Total</strong></td>
      <td style="text-align:right"><strong>{gb(total)}</strong></td><td></td></tr>
</table>
<p style="color:#666;font-size:0.9em">Metodologia: soma diária dos objetos no S3
<code>saira-images</code> (frames de ocorrência + ZIPs diários de frames
descartados) mais os bursts locais que não migram para o S3. É o volume de
imagens efetivamente transmitido pelas câmeras — proxy do consumo 4G; não inclui
overhead/retransmissões da operadora. Fonte:
<code>/opt/4g-monitor/camera_volume_daily.csv</code> na EC2.</p>
"""


def send(subject: str, html: str) -> None:
    key = KEY_FILE.read_text(encoding="utf-8").strip()
    payload = json.dumps({"from": MAIL_FROM, "to": MAIL_TO,
                          "subject": subject, "html": html}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"Resend: HTTP {resp.status} {resp.read().decode('utf-8')[:200]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (default: mês anterior)")
    ap.add_argument("--dry-run", action="store_true", help="imprime sem enviar")
    args = ap.parse_args()

    month = args.month or (datetime.now(BRT).replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    per_dev, total = aggregate(month)
    html = build_html(month, per_dev, total)
    y, m = month.split("-")
    subject = f"SAÍRA — Volume de imagens por câmera — {MESES[int(m) - 1]}/{y}"

    if args.dry_run:
        print(subject)
        print(html)
        return
    if not per_dev:
        print(f"sem dados para {month}; e-mail não enviado")
        return
    send(subject, html)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)
