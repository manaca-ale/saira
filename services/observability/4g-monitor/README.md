# 4g-monitor — atribuição de consumo de 4G por câmera

Duas famílias de ferramentas, todas rodando **na EC2**:

1. **Split fino da pi-cam-001** (WireGuard): a Pi tuneliza tudo pela `wg0`,
   então **a conta de 4G da Pi = uploads Pi→EC2 (rx) + downloads EC2→Pi (tx)**.
   Ferramentas: `wg_sampler.py`, `4g_report.py`, `usage_aggregator.py`, `4g_daily.py`.
2. **Volume de imagens por câmera (TODAS as 6)**: `camera_volume_daily.py`
   congela por dia/câmera os bytes de imagem no S3 `saira-images`
   (`ocorrencias/` + ZIPs de `descartadas/`) + bursts locais (`bulk/`), e
   `camera_volume_monthly_report.py` envia o rollup mensal por e-mail — é a
   fonte da tabela de consumo 4G (seção 4.5) dos relatórios mensais EMLURB.

Nenhuma dessas ferramentas altera o agente da Pi — rodam **na EC2** (a de logs
faz `ssh` read-only na Pi).

## Três fontes de verdade

| Fonte | O que mede | Ferramenta |
|---|---|---|
| **WireGuard** | total real rx/tx (ground truth) — inclui SSH, overhead, tudo | `wg_sampler.py` |
| **Disco** (`/app/uploads`) | bytes reais das imagens subidas (evento+live+snapshot) | `4g_report.py` |
| **Journal da Pi** | SPLIT por fonte (event vs live vs snapshot) + `reason=` + `window_trimmed` | `usage_aggregator.py` |

O disco tem os bytes exatos das imagens mas **não separa** evento de live (frames
de live não têm `event_id`); o journal separa mas **não loga bytes do caminho
batch** (o dominante). Cruzando os três: `residual (SSH/keepalive/overhead) =
WG_rx_delta − bytes_de_imagem_no_disco`.

## Instalação na EC2

```bash
# copiar para a EC2 (a partir do repo)
scp -r services/observability/4g-monitor saira-prod:/opt/4g-monitor

# amostrador do WireGuard a cada 5 min (crontab do ROOT — wg show exige root)
sudo crontab -e
#   */5 * * * * /usr/bin/python3 /opt/4g-monitor/wg_sampler.py >> /var/log/wg_sampler.log 2>&1

# registro diário por câmera + relatório mensal (crontab do UBUNTU — usa docker exec)
crontab -e
#   40 7 * * * /usr/bin/python3 /opt/4g-monitor/camera_volume_daily.py >> /home/ubuntu/logs/camera_volume_daily.log 2>&1
#   0 11 1 * * /usr/bin/python3 /opt/4g-monitor/camera_volume_monthly_report.py >> /home/ubuntu/logs/camera_volume_monthly.log 2>&1
# (07:40 UTC = 04:40 BRT, depois do sync D-1 p/ S3 das 03h BRT; dia 1 11:00 UTC = 08:00 BRT)
```

## Registro por câmera (`camera_volume_daily.csv`)

Colunas: `date, device, ocorr_bytes, ocorr_count, desc_bytes, desc_zips, bulk_bytes, total_bytes`.

- `ocorr_*`: JPGs em `s3://saira-images/ocorrencias/{device}/{YYYY}/{MM}/{DD}/`.
- `desc_*`: ZIP diário em `s3://saira-images/descartadas/{device}/{YYYY-MM-DD}/`
  (~95% do volume; formato de data DIFERENTE do prefixo de ocorrências).
- `bulk_bytes`: imagens em `/app/uploads/bulk/{device}` no esp32-server (só
  pi-cam-001; NÃO migram para o S3), por mtime.
- A listagem do S3 roda **dentro do worker** (`docker exec saira-yolo-worker-prod`)
  porque a role da instância EC2 não tem `s3:ListBucket`; o worker tem as
  credenciais no env. Vídeos ficam fora (já cobertos pelo `4g_daily.csv`).
- Idempotente + backfill: primeira execução preenche desde `START_DATE`
  (2026-05-18, início dos ZIPs de descartadas); depois só anexa D-1.
- O e-mail mensal usa a API do Resend com a MESMA secret do Alertmanager
  (`observability/alertmanager/secrets/resend_api_key`).

## Uso

```bash
# 1) snapshot do contador WireGuard (precisa root)
sudo python3 wg_sampler.py

# 2) relatório de bytes de imagem por dia (+ delta WG se já houver histórico)
python3 4g_report.py --days 7

# 3) relatório COM split por fonte (puxa o journal da Pi)
python3 4g_report.py --split --since today

# 4) só o agregador de logs por fonte, com CSV por hora
python3 usage_aggregator.py --since "2026-07-18 00:00:00" --csv usage.csv
```

## Variáveis de ambiente

| Var | Default | Uso |
|---|---|---|
| `WG_IFACE` | `wg0` | interface WireGuard |
| `WG_HISTORY_CSV` | `./wg_transfer_history.csv` | histórico de snapshots |
| `PI_SSH` | `saira@10.8.0.3` | alvo SSH da Pi (a partir da EC2) |
| `AGENT_UNIT` | `saira-agent` | unit systemd do agente |
| `ESP32_CONTAINER` | `saira-esp32-server-prod` | container que guarda `/app/uploads` |
| `DEVICE_ID` | `pi-cam-001` | device alvo |
| `FRAME_AVG_KB` | `250` | média p/ estimar bytes de frames batch |
| `DEVICES` | as 6 câmeras | lista (vírgula) p/ `camera_volume_daily.py` |
| `CAMERA_VOLUME_CSV` | `/opt/4g-monitor/camera_volume_daily.csv` | CSV do registro por câmera |
| `START_DATE` | `2026-05-18` | início do backfill (primeiros ZIPs de descartadas) |
| `WORKER_CONTAINER` | `saira-yolo-worker-prod` | container com credenciais S3 |
| `RESEND_API_KEY_FILE` | secret do alertmanager | key p/ o e-mail mensal |
| `MAIL_TO` | `alecoleto@gmail.com,contato@manaca.tech` | destinatários do mensal |

## Notas de campo (diagnóstico de 18/07/2026)

- **>98% do 4G é upload de frames de EVENTO** (rx domina; tx = SSH/deploy é ~0,76 GB/4 dias).
- Live estava em 0, snapshot ~1 MB — **não** eram a causa.
- ~147 eventos/10h, cada um subindo ~92 frames a 1 fps (`BURST_UPLOAD_INTERVAL=1.0`),
  batendo o teto de 120s (`EVENT_MAX_SECONDS`, `reason=close:max_duration`).
- O worker corta a janela no cap de 8 MB (`window_trimmed frames=48->23`), então
  **~60-75% dos frames subidos nunca chegam ao modelo** — desperdício puro de 4G.
- Alavanca principal (hot-reload, sem deploy): subir `burst_interval_ms` (1000→~4000)
  para casar o upload com o que o modelo usa (~23-30 frames/evento).
