# Raspberry Pi — Agente de Captura SAIRA

Captura frames JPEG da camera IMX219 (CSI) a cada 10s e envia para a EC2 via WireGuard VPN.

## Arquitetura

```
Camera IMX219 (CSI) -> Raspberry Pi 3B -> (LTE/4G + WireGuard VPN) -> EC2 (IA + Backend)
```

## Estrutura

```
scripts/
  cam-capture.sh          # Captura 1 frame JPEG com timestamp overlay
  cam-upload.sh           # Envia frame mais recente para EC2 via HTTP POST
  cam-prune-frames.sh     # Mantem apenas os 40 frames mais recentes
  cam-export-last5min.sh  # Empacota frames recentes em .tar

systemd/
  cam-capture.service     # Oneshot — executado pelo timer
  cam-capture.timer       # A cada 10s
  cam-upload.service      # Oneshot — executado pelo timer
  cam-upload.timer        # A cada 10s (defasado 5s da captura)
  cam-prune-frames.service
  cam-prune-frames.timer  # A cada 2min

wireguard/
  wg0.conf.example        # Template de config WireGuard (sem chaves)
```

## Deploy no Pi

```bash
# 1. Copiar scripts
sudo cp scripts/cam-*.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/cam-*.sh

# 2. Copiar systemd units
sudo cp systemd/cam-* /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Ativar timers
sudo systemctl enable --now cam-capture.timer
sudo systemctl enable --now cam-upload.timer
sudo systemctl enable --now cam-prune-frames.timer

# 4. Copiar .env
cp .env.example ~/app/.env
chmod 600 ~/app/.env
# Editar ~/app/.env com valores reais
```

## WireGuard VPN

```bash
# Gerar chaves
sudo bash -c 'umask 077 && wg genkey | tee /etc/wireguard/pi.key | wg pubkey > /etc/wireguard/pi.pub'

# Copiar e editar config
sudo cp wireguard/wg0.conf.example /etc/wireguard/wg0.conf
# Preencher: PrivateKey, PublicKey da EC2, Endpoint
sudo chmod 600 /etc/wireguard/wg0.conf

# Ativar
sudo systemctl enable --now wg-quick@wg0
```

## Verificacao

```bash
sudo systemctl status cam-capture.timer   # captura ativa
sudo systemctl status cam-upload.timer    # upload ativo
sudo wg show                              # VPN conectada
ls -lht /var/spool/cam/frames/ | head -5  # frames recentes
```
