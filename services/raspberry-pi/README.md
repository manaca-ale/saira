# Raspberry Pi — Agente de Captura SAIRA (relay de câmera IP)

Substitui a ESP32 no kit de campo. A Pi busca o snapshot da **câmera IP** e
repassa, **byte a byte, sem reencode** (pass-through), para o `esp32-server`
na EC2 — preservando a qualidade nativa da câmera. Mesmo contrato de rede da
ESP32, então worker/backend **não mudam**.

## Arquitetura

```
Câmera IP (snapshot HTTP + RTSP, na LAN)
   └─ LAN via roteador 4G ── Raspberry Pi 3 Model B ── 4G ── Internet
                                   │  WireGuard (wg0, 10.8.0.x)
                                   ▼
                            EC2 (10.8.0.1)
                            ├─ esp32-server :5002  /upload, /device/<id>/poll, /config.txt, /video
                            └─ worker + backend
```

## O que o agente faz

| Requisito | Como |
|---|---|
| #1 Qualidade | Pass-through puro: o JPEG da câmera vai sem reencode. Zero `cv2`/`ffmpeg` no caminho da imagem. |
| #2 Upload | HTTP **dentro do túnel WireGuard** (sem TLS, o WG já cifra) + `requests.Session` keep-alive. |
| #3 Vídeo sob demanda | `saira-rtsp-buffer.service` mantém ~2 min de RTSP em segmentos `.ts` num tmpfs. `CMD_VIDEO_CLIP` concatena e envia um mp4. |
| #4 BGSUB | **Fase 2** — hook `motion_gate()` em [agent/saira_agent.py](agent/saira_agent.py); porta o `bgsub_filter.py` do worker. |
| #5 Intervalo ≥5s | `capture_loop` com agendamento monotônico; piso de 5s aplicado no código. |
| #6 SSH/OTA | SSH pelo IP do túnel WireGuard. "OTA" = `git pull` + `systemctl restart saira-agent`. Config em runtime via `config.txt`. |

## Estrutura

```
agent/
  saira_agent.py            # daemon: captura + upload + config remota + comandos
  config.py                 # carrega .env / variaveis de ambiente
  cam-rtsp-buffer.sh        # ffmpeg: ring de segmentos RTSP (item #3)
  .env.example              # copie para .env e ajuste
  requirements.txt          # fase 1: requests (fase 2: opencv-headless+numpy)
  systemd/
    saira-agent.service
    saira-rtsp-buffer.service
wireguard/
  wg0.conf.example          # lado Pi do tunel
```

## 0) Gravar a imagem (no PC)

Raspberry Pi Imager → **Raspberry Pi OS Lite (64-bit, Bookworm)**. Em
"Editar configurações": hostname `pi-cam-001`, habilitar **SSH por chave
pública**, usuário/senha, Wi-Fi de bancada, timezone `America/Recife`.

## 1) WireGuard + SSH (itens #2 e #6)

Lado EC2 (servidor WireGuard em 10.8.0.1:51820/udp) adiciona a Pi como peer.
Lado Pi:

```bash
sudo apt update && sudo apt install -y wireguard-tools ffmpeg python3 python3-venv curl
sudo bash -c 'umask 077 && wg genkey | tee /etc/wireguard/pi.key | wg pubkey > /etc/wireguard/pi.pub'
sudo cp wireguard/wg0.conf.example /etc/wireguard/wg0.conf   # preencha as chaves/endpoint
sudo chmod 600 /etc/wireguard/wg0.conf
sudo systemctl enable --now wg-quick@wg0
sudo wg show                       # deve mostrar handshake
```

Depois disso, da EC2: `ssh <user>@10.8.0.2`.

## 2) Instalar o agente

```bash
sudo mkdir -p /opt/saira
sudo cp -r agent /opt/saira/
cd /opt/saira/agent
python3 -m venv /opt/saira/venv
/opt/saira/venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env     # DEVICE_ID, EC2_BASE, IP_CAM_*, RTSP_URL
chmod +x cam-rtsp-buffer.sh

sudo cp systemd/saira-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now saira-rtsp-buffer.service
sudo systemctl enable --now saira-agent.service
```

> Os units rodam como root (appliance dedicado, acesso só por SSH-key sobre
> WireGuard). Para rodar como usuário próprio, adicione `User=` e garanta
> permissão em `/var/spool/saira` e `/dev/shm/saira`.

## 3) Verificação

```bash
journalctl -u saira-agent -f                 # 1 upload a cada ~5s
journalctl -u saira-rtsp-buffer -f           # segmentos sendo gravados
ls -lht /dev/shm/saira/segments | head        # ring de .ts
ls -lht /var/spool/saira/frames | head        # frames recentes

# Clip de video sob demanda (da EC2):
curl -X POST http://10.8.0.1:5002/device/pi-cam-001/trigger \
     -H 'Content-Type: application/json' -d '{"cmd":"CMD_VIDEO_CLIP"}'

# Ajustar intervalo em runtime (sem restart):
curl -X POST http://10.8.0.1:5002/device/pi-cam-001/config \
     -H 'Content-Type: application/json' -d '{"timer_delay_ms":"5000"}'
```

## Config remota (runtime, via `/device/<id>/config.txt`)

`timer_delay_ms` (≥5000 aplicado), `ip_cam_url`, `ip_cam_user`, `ip_cam_pass`.

## Fase 2 — BGSUB no dispositivo (item #4)

1. Capture cena real por alguns dias (já feito pelo agente).
2. Defina o polígono de zona e calibre o baseline `.npz` por câmera.
3. Porte `services/yolo-worker-vm/src/worker/bgsub_filter.py` (MOG2:
   `history=80`, `varThreshold=40`, `shadow_threshold=100`, modo `area_min`
   `area=400`, `persistence_threshold=1000`) para dentro de `motion_gate()`.
4. `pip install opencv-python-headless numpy` (piwheels). Custo ~100-150ms/frame
   @720p no Pi 3 Model B (1.2 GHz) — folgado a 5s. Só single-rate.
