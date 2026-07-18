# 4g-monitor — atribuição de consumo de 4G por câmera (pi-cam-001)

Ferramentas de medição do gasto de 4G da `pi-cam-001` (Raspberry Pi + câmera
Intelbras, camera_id=15). Todo o tráfego da Pi passa pelo túnel WireGuard `wg0`
na EC2, então **a conta de 4G da Pi = uploads Pi→EC2 (rx) + downloads EC2→Pi (tx)**.

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
```

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

## Notas de campo (diagnóstico de 18/07/2026)

- **>98% do 4G é upload de frames de EVENTO** (rx domina; tx = SSH/deploy é ~0,76 GB/4 dias).
- Live estava em 0, snapshot ~1 MB — **não** eram a causa.
- ~147 eventos/10h, cada um subindo ~92 frames a 1 fps (`BURST_UPLOAD_INTERVAL=1.0`),
  batendo o teto de 120s (`EVENT_MAX_SECONDS`, `reason=close:max_duration`).
- O worker corta a janela no cap de 8 MB (`window_trimmed frames=48->23`), então
  **~60-75% dos frames subidos nunca chegam ao modelo** — desperdício puro de 4G.
- Alavanca principal (hot-reload, sem deploy): subir `burst_interval_ms` (1000→~4000)
  para casar o upload com o que o modelo usa (~23-30 frames/evento).
