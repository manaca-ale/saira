# SPEC: Setup Raspberry Pi — Agente via SSH

> Versao: 1.0 | Data: 2026-02-09
> Este documento e para um agente (Claude Code / Codex / etc.) executar remotamente via SSH.
> O agente roda na maquina local (Windows) e acessa o Raspberry Pi via SSH.

---

## CONTEXTO

**Projeto:** SAIRA — Sistema de monitoramento com camera em campo + IA na nuvem.

**Arquitetura resumida:**

```
Camera IMX219 (CSI) -> Raspberry Pi 3B -> (LTE/4G + WireGuard VPN) -> EC2 (IA + Backend)
```

**O que o Pi faz:**
1. Captura 1 frame JPEG a cada N segundos via `libcamera-still`
2. Envia o frame para a EC2 via HTTP POST (endpoint na VPN)
3. Mantem buffer local dos ultimos 5 minutos (~40 frames)
4. Limpa frames antigos automaticamente
5. Sob demanda, exporta os ultimos 5 min como `.tar`

**O que o Pi NAO faz:**
- NAO roda IA/YOLO (CPU limitada)
- NAO precisa de stream de video continuo (frames discretos bastam)
- NAO precisa de interface grafica

---

## ACESSO SSH

```
Host:     saira-2
User:     alecoleto
Senha:    ale!161207
IP local: descobrir via arp -a ou router DHCP (ex: 192.168.x.x)
```

**Comando de conexao:**

```bash
ssh alecoleto@saira-2
```

> IMPORTANTE: Todo comando nesta spec deve ser executado via SSH no Pi, a menos que explicitamente indicado como "NA MAQUINA LOCAL" ou "NA EC2".

---

## PRE-REQUISITOS (verificar antes de comecar)

Antes de executar qualquer tarefa, o agente deve validar o estado do Pi:

```bash
# 1. Conectar
ssh alecoleto@saira

# 2. Verificar SO
cat /etc/os-release
# Esperado: Raspberry Pi OS (Bookworm) 64-bit

# 3. Verificar hardware
uname -m
# Esperado: aarch64

# 4. Verificar espaco em disco
df -h /
# Esperado: espaco livre suficiente (>2GB)

# 5. Verificar internet
ping -c 3 8.8.8.8
# Esperado: resposta ok

# 6. Verificar camera
vcgencmd get_camera 2>/dev/null || echo "vcgencmd nao disponivel, testar com libcamera"
libcamera-hello --list-cameras 2>/dev/null || echo "libcamera nao instalado ainda"
```

Se algum pre-requisito falhar, resolver antes de continuar.

---

## TAREFA 1: Setup basico do sistema

**Objetivo:** Atualizar SO e instalar dependencias essenciais.

### Comandos

```bash
sudo apt update && sudo apt -y full-upgrade
sudo apt -y install git python3-venv python3-pip ffmpeg curl jq
sudo reboot
```

Apos reboot, reconectar:

```bash
ssh alecoleto@saira
```

### Verificacao

```bash
python3 --version    # >= 3.11
ffmpeg -version      # instalado
git --version        # instalado
curl --version       # instalado
```

---

## TAREFA 2: Validar camera IMX219 (libcamera)

**Objetivo:** Confirmar que a camera CSI esta funcionando.

### Comandos

```bash
# Listar cameras detectadas
libcamera-hello --list-cameras

# Teste rapido (3 segundos de preview, sem tela — so valida que nao da erro)
libcamera-hello -t 3000 --nopreview

# Capturar um frame de teste
libcamera-still -n -t 1 --width 640 --height 360 -q 70 -o /tmp/test_cam.jpg

# Verificar resultado
ls -lh /tmp/test_cam.jpg
file /tmp/test_cam.jpg
```

### Verificacao

- `/tmp/test_cam.jpg` existe e tem tamanho razoavel (10-100 KB)
- `file /tmp/test_cam.jpg` retorna "JPEG image data"

### Troubleshooting

Se `libcamera-hello` falhar:
1. Verificar cabo flat CSI (encaixe firme, lado correto)
2. Verificar se camera aparece em `dmesg | grep -i cam`
3. Verificar `/boot/firmware/config.txt` — deve ter `camera_auto_detect=1` ou `dtoverlay=imx219`
4. Tentar `sudo raspi-config` > Interface Options > Camera > Enable

---

## TAREFA 3: Configurar WireGuard (VPN para EC2)

**Objetivo:** Criar tunel VPN entre o Pi e a EC2 para comunicacao segura mesmo com CGNAT do LTE.

### Topologia

```
Pi (10.8.0.2) <--- WireGuard UDP 51820 ---> EC2 (10.8.0.1, IP publico)
```

### 3a. Instalar WireGuard no Pi

```bash
sudo apt -y install wireguard wireguard-tools
```

### 3b. Gerar chaves no Pi

```bash
sudo bash -c 'umask 077 && wg genkey | tee /etc/wireguard/pi.key | wg pubkey > /etc/wireguard/pi.pub'
sudo cat /etc/wireguard/pi.pub
```

> ANOTAR: copiar a chave publica do Pi. Ela sera usada na configuracao da EC2.

### 3c. Dados da EC2 (ja conhecidos)

```
Chave publica EC2 (server.pub): kXlgc+KyMntVjNW2gH4xLAZZRoe3FatyA9sB3zQbjko=
IP publico EC2:                  (preencher — rodar na EC2: curl -s https://checkip.amazonaws.com)
```

> Se o IP publico nao estiver preenchido acima, o agente DEVE perguntar ao usuario.

### 3d. Criar configuracao no Pi

```bash
# Ler chave privada do Pi
PI_PRIVATE_KEY=$(sudo cat /etc/wireguard/pi.key)

sudo tee /etc/wireguard/wg0.conf > /dev/null << WGEOF
[Interface]
Address = 10.8.0.2/24
PrivateKey = ${PI_PRIVATE_KEY}
DNS = 1.1.1.1

[Peer]
PublicKey = kXlgc+KyMntVjNW2gH4xLAZZRoe3FatyA9sB3zQbjko=
Endpoint = IP_PUBLICO_DA_EC2:51820
AllowedIPs = 10.8.0.0/24
PersistentKeepalive = 25
WGEOF
```

> IMPORTANTE: Substituir `IP_PUBLICO_DA_EC2` pelo IP publico real da EC2.
> A chave privada do Pi e lida automaticamente do arquivo gerado na etapa 3b.

```bash
# Proteger permissoes
sudo chmod 600 /etc/wireguard/wg0.conf
sudo chmod 600 /etc/wireguard/pi.key
```

### 3e. Ativar e habilitar no boot

```bash
sudo systemctl enable --now wg-quick@wg0
```

### Verificacao

```bash
sudo wg show
# Esperado: interface wg0, peer com endpoint da EC2

ping -c 3 10.8.0.1
# Esperado: resposta do servidor EC2 via VPN

ip a show wg0
# Esperado: inet 10.8.0.2/24
```

### Troubleshooting

Se ping falhar:
1. Verificar `sudo wg show` — se "latest handshake" esta ausente, o peer nao respondeu
2. Na EC2: verificar Security Group (UDP 51820 aberto)
3. Na EC2: verificar que o peer do Pi esta configurado com a chave publica correta
4. No Pi: verificar se a internet esta ok (`ping 8.8.8.8`)

---

## TAREFA 4: Criar estrutura de diretorios

**Objetivo:** Criar os diretorios de trabalho para captura e scripts.

```bash
# Diretorio de frames
sudo mkdir -p /var/spool/cam/frames
sudo chown -R alecoleto:alecoleto /var/spool/cam

# Diretorio do app
mkdir -p /home/alecoleto/app/scripts
mkdir -p /home/alecoleto/app/services

# Verificacao
ls -la /var/spool/cam/frames
ls -la /home/alecoleto/app/
```

---

## TAREFA 5: Script de captura de frames

**Objetivo:** Criar script que captura 1 frame JPEG da camera IMX219 a cada N segundos.

### Criar o script

```bash
sudo tee /usr/local/bin/cam-capture.sh > /dev/null << 'CAPTEOF'
#!/usr/bin/env bash
set -euo pipefail

FRAMES_DIR="/var/spool/cam/frames"
WIDTH="${CAM_WIDTH:-640}"
HEIGHT="${CAM_HEIGHT:-360}"
QUALITY="${CAM_QUALITY:-70}"

mkdir -p "$FRAMES_DIR"

FILENAME="$(date +%Y%m%d_%H%M%S).jpg"
FILEPATH="${FRAMES_DIR}/${FILENAME}"

libcamera-still -n -t 1 --width "$WIDTH" --height "$HEIGHT" -q "$QUALITY" -o "$FILEPATH" 2>/dev/null

if [ -f "$FILEPATH" ]; then
    SIZE=$(stat -c%s "$FILEPATH")
    if [ "$SIZE" -lt 500 ]; then
        echo "WARN: imagem muito pequena (${SIZE} bytes), descartando"
        rm -f "$FILEPATH"
        exit 1
    fi
    echo "OK: ${FILENAME} (${SIZE} bytes)"
else
    echo "ERRO: falha na captura"
    exit 1
fi
CAPTEOF

sudo chmod +x /usr/local/bin/cam-capture.sh
```

### Teste manual

```bash
/usr/local/bin/cam-capture.sh
ls -lht /var/spool/cam/frames/ | head -5
# Esperado: arquivo .jpg com tamanho razoavel (10-100 KB)
```

---

## TAREFA 6: Script de upload de frames para EC2

**Objetivo:** Enviar o frame mais recente para o endpoint HTTP na EC2 via VPN.

### Criar o script

```bash
sudo tee /usr/local/bin/cam-upload.sh > /dev/null << 'UPLEOF'
#!/usr/bin/env bash
set -euo pipefail

FRAMES_DIR="/var/spool/cam/frames"
DEVICE_ID="${DEVICE_ID:-pi-cam-001}"
EC2_UPLOAD_URL="${EC2_UPLOAD_URL:-http://10.8.0.1:5002/upload}"
TIMEOUT="${UPLOAD_TIMEOUT:-30}"

# Encontrar o frame mais recente ainda nao enviado
# Convenção: apos envio, cria marker .uploaded
LATEST=""
for f in $(ls -1t "$FRAMES_DIR"/*.jpg 2>/dev/null); do
    if [ ! -f "${f}.uploaded" ]; then
        LATEST="$f"
        break
    fi
done

if [ -z "$LATEST" ]; then
    echo "INFO: nenhum frame novo para enviar"
    exit 0
fi

FILENAME=$(basename "$LATEST")
echo "Enviando: $FILENAME -> $EC2_UPLOAD_URL"

HTTP_CODE=$(curl -fsS --max-time "$TIMEOUT" -o /tmp/upload_response.json -w "%{http_code}" \
    -X POST "$EC2_UPLOAD_URL" \
    -H "X-Device-Id: ${DEVICE_ID}" \
    -F "imageFile=@${LATEST}" \
    2>/dev/null) || HTTP_CODE="000"

if [ "$HTTP_CODE" = "200" ]; then
    touch "${LATEST}.uploaded"
    echo "OK: ${FILENAME} enviado (HTTP ${HTTP_CODE})"
    cat /tmp/upload_response.json 2>/dev/null || true
else
    echo "ERRO: HTTP ${HTTP_CODE} ao enviar ${FILENAME}"
    cat /tmp/upload_response.json 2>/dev/null || true
    exit 1
fi
UPLEOF

sudo chmod +x /usr/local/bin/cam-upload.sh
```

### Teste manual

> PRE-REQUISITO: EC2 com esp32-server rodando e acessivel via VPN (10.8.0.1:5002)

```bash
# Primeiro, capturar um frame
/usr/local/bin/cam-capture.sh

# Enviar
DEVICE_ID="pi-cam-001" EC2_UPLOAD_URL="http://10.8.0.1:5002/upload" /usr/local/bin/cam-upload.sh

# Verificar marker
ls -la /var/spool/cam/frames/*.uploaded | head -3
```

---

## TAREFA 7: Script de limpeza de frames (buffer 5 min)

**Objetivo:** Manter apenas os 40 frames mais recentes (~5-7 minutos a cada 10s).

### Criar o script

```bash
sudo tee /usr/local/bin/cam-prune-frames.sh > /dev/null << 'PRUNEEOF'
#!/usr/bin/env bash
set -euo pipefail

FRAMES_DIR="/var/spool/cam/frames"
KEEP="${CAM_KEEP_FRAMES:-40}"

mapfile -t files < <(ls -1t "$FRAMES_DIR"/*.jpg 2>/dev/null || true)

TOTAL=${#files[@]}
if (( TOTAL <= KEEP )); then
    echo "OK: ${TOTAL} frames (<= ${KEEP}), nada a limpar"
    exit 0
fi

DELETED=0
for f in "${files[@]:KEEP}"; do
    rm -f -- "$f"
    rm -f -- "${f}.uploaded"
    DELETED=$((DELETED + 1))
done

echo "OK: removidos ${DELETED} frames antigos (mantidos ${KEEP})"
PRUNEEOF

sudo chmod +x /usr/local/bin/cam-prune-frames.sh
```

### Teste manual

```bash
/usr/local/bin/cam-prune-frames.sh
ls /var/spool/cam/frames/*.jpg 2>/dev/null | wc -l
# Esperado: <= 40
```

---

## TAREFA 8: Script de export "ultimos 5 min"

**Objetivo:** Empacotar os frames recentes em um `.tar` para envio sob demanda.

### Criar o script

```bash
sudo tee /usr/local/bin/cam-export-last5min.sh > /dev/null << 'EXPEOF'
#!/usr/bin/env bash
set -euo pipefail

FRAMES_DIR="/var/spool/cam/frames"
KEEP="${CAM_KEEP_FRAMES:-40}"
OUTDIR="/tmp"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTFILE="${OUTDIR}/last5min_${TIMESTAMP}.tar"

# Listar os N frames mais recentes
FILES=$(ls -1t "$FRAMES_DIR"/*.jpg 2>/dev/null | head -n "$KEEP")

if [ -z "$FILES" ]; then
    echo "ERRO: nenhum frame disponivel em ${FRAMES_DIR}"
    exit 1
fi

COUNT=$(echo "$FILES" | wc -l)
echo "$FILES" | tar -cf "$OUTFILE" -T -

echo "OK: ${OUTFILE} criado (${COUNT} frames)"
ls -lh "$OUTFILE"
EXPEOF

sudo chmod +x /usr/local/bin/cam-export-last5min.sh
```

### Teste manual

```bash
sudo /usr/local/bin/cam-export-last5min.sh
ls -lh /tmp/last5min_*.tar | tail -1
# Esperado: arquivo .tar com N frames
```

---

## TAREFA 9: Servicos systemd — captura periodica

**Objetivo:** Criar servico + timer para capturar frames automaticamente a cada 10 segundos.

### 9a. Service de captura (oneshot, executado pelo timer)

```bash
sudo tee /etc/systemd/system/cam-capture.service > /dev/null << 'SVCEOF'
[Unit]
Description=SAIRA - Captura frame da camera IMX219
After=network.target

[Service]
Type=oneshot
User=alecoleto
ExecStart=/usr/local/bin/cam-capture.sh
StandardOutput=journal
StandardError=journal
SVCEOF
```

### 9b. Timer de captura (a cada 10 segundos)

```bash
sudo tee /etc/systemd/system/cam-capture.timer > /dev/null << 'TMREOF'
[Unit]
Description=SAIRA - Timer de captura (a cada 10s)

[Timer]
OnBootSec=30
OnUnitActiveSec=10
AccuracySec=1s

[Install]
WantedBy=timers.target
TMREOF
```

### 9c. Ativar

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cam-capture.timer
```

### Verificacao

```bash
sudo systemctl status cam-capture.timer --no-pager
# Esperado: active (waiting)

# Aguardar ~30 segundos e verificar frames aparecendo
sleep 35
ls -lht /var/spool/cam/frames/ | head -5
# Esperado: novos arquivos .jpg aparecendo a cada ~10s
```

---

## TAREFA 10: Servicos systemd — upload periodico

**Objetivo:** Enviar frames para a EC2 periodicamente.

### 10a. Service de upload

```bash
sudo tee /etc/systemd/system/cam-upload.service > /dev/null << 'SVCEOF'
[Unit]
Description=SAIRA - Upload frame para EC2
After=network-online.target wg-quick@wg0.service
Wants=network-online.target

[Service]
Type=oneshot
User=alecoleto
Environment=DEVICE_ID=pi-cam-001
Environment=EC2_UPLOAD_URL=http://10.8.0.1:5002/upload
Environment=UPLOAD_TIMEOUT=30
ExecStart=/usr/local/bin/cam-upload.sh
StandardOutput=journal
StandardError=journal
SVCEOF
```

### 10b. Timer de upload (a cada 10 segundos, defasado da captura)

```bash
sudo tee /etc/systemd/system/cam-upload.timer > /dev/null << 'TMREOF'
[Unit]
Description=SAIRA - Timer de upload (a cada 10s)

[Timer]
OnBootSec=35
OnUnitActiveSec=10
AccuracySec=1s

[Install]
WantedBy=timers.target
TMREOF
```

### 10c. Ativar

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cam-upload.timer
```

### Verificacao

```bash
sudo systemctl status cam-upload.timer --no-pager
sudo journalctl -u cam-upload.service -n 10 --no-pager
# Esperado: logs de "OK: ... enviado" ou "ERRO: ..." se EC2 inacessivel
```

---

## TAREFA 11: Servico systemd — limpeza de frames

**Objetivo:** Limpar frames antigos a cada 2 minutos para nao lotar o microSD.

### 11a. Service de limpeza

```bash
sudo tee /etc/systemd/system/cam-prune-frames.service > /dev/null << 'SVCEOF'
[Unit]
Description=SAIRA - Limpeza de frames antigos

[Service]
Type=oneshot
User=alecoleto
ExecStart=/usr/local/bin/cam-prune-frames.sh
StandardOutput=journal
StandardError=journal
SVCEOF
```

### 11b. Timer de limpeza (a cada 2 minutos)

```bash
sudo tee /etc/systemd/system/cam-prune-frames.timer > /dev/null << 'TMREOF'
[Unit]
Description=SAIRA - Timer limpeza de frames (a cada 2min)

[Timer]
OnBootSec=60
OnUnitActiveSec=120
AccuracySec=5s

[Install]
WantedBy=timers.target
TMREOF
```

### 11c. Ativar

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cam-prune-frames.timer
```

### Verificacao

```bash
sudo systemctl status cam-prune-frames.timer --no-pager
sudo journalctl -u cam-prune-frames.service -n 5 --no-pager
```

---

## TAREFA 12: Configuracao do environment

**Objetivo:** Centralizar variaveis de configuracao em um arquivo `.env`.

```bash
sudo tee /home/alecoleto/app/.env > /dev/null << 'ENVEOF'
# ---- SAIRA Pi Config ----
DEVICE_ID=pi-cam-001
EC2_UPLOAD_URL=http://10.8.0.1:5002/upload
UPLOAD_TIMEOUT=30

# Camera
CAM_WIDTH=640
CAM_HEIGHT=360
CAM_QUALITY=70

# Buffer
CAM_KEEP_FRAMES=40

# Intervalo (usado pelos timers systemd — alterar nos .timer se necessario)
# CAPTURE_INTERVAL=10
# UPLOAD_INTERVAL=10
ENVEOF

chmod 600 /home/alecoleto/app/.env
```

> NOTA: Os servicos systemd usam `Environment=` direto no unit file.
> Se quiser centralizar, mudar para `EnvironmentFile=/home/alecoleto/app/.env` nos services.

---

## PLANO DE TESTES (executar apos todas as tarefas)

O agente deve executar cada teste em sequencia e registrar o output.

### T1. Saude do sistema

```bash
hostname && uname -a && uptime && df -h / && free -h
```

**Esperado:** hostname=saira, aarch64, disco e memoria ok.

### T2. Camera

```bash
libcamera-still -n -t 1 --width 640 --height 360 -q 70 -o /tmp/test_final.jpg
ls -lh /tmp/test_final.jpg && file /tmp/test_final.jpg
```

**Esperado:** JPEG valido, 10-100 KB.

### T3. WireGuard

```bash
sudo wg show
ping -c 3 10.8.0.1
```

**Esperado:** handshake recente, ping ok.

### T4. Captura periodica

```bash
sudo systemctl status cam-capture.timer --no-pager
sleep 25
ls -1t /var/spool/cam/frames/*.jpg 2>/dev/null | head -5
```

**Esperado:** novos frames aparecendo.

### T5. Upload para EC2

```bash
sudo systemctl status cam-upload.timer --no-pager
sudo journalctl -u cam-upload.service -n 10 --no-pager
```

**Esperado:** logs de envio com HTTP 200.

### T6. Limpeza

```bash
sudo systemctl status cam-prune-frames.timer --no-pager
ls /var/spool/cam/frames/*.jpg 2>/dev/null | wc -l
```

**Esperado:** contagem <= 40.

### T7. Export sob demanda

```bash
sudo /usr/local/bin/cam-export-last5min.sh
ls -lh /tmp/last5min_*.tar | tail -1
```

**Esperado:** arquivo .tar com frames.

### T8. Servicos no boot

```bash
sudo systemctl is-enabled wg-quick@wg0
sudo systemctl is-enabled cam-capture.timer
sudo systemctl is-enabled cam-upload.timer
sudo systemctl is-enabled cam-prune-frames.timer
```

**Esperado:** todos "enabled".

### T9. Resiliencia (simulacao de queda de rede)

```bash
# Desativar WireGuard por 30s
sudo systemctl stop wg-quick@wg0
sleep 30
sudo systemctl start wg-quick@wg0
sleep 10
sudo wg show
ping -c 3 10.8.0.1
sudo systemctl --failed
```

**Esperado:** WireGuard reconecta, nenhum servico falhou, frames locais continuaram sendo capturados durante a queda.

---

## RESUMO DE SERVICOS CRIADOS

| Servico | Tipo | Funcao | Intervalo |
|---|---|---|---|
| `wg-quick@wg0` | auto (wireguard) | VPN para EC2 | boot |
| `cam-capture.timer` | timer + oneshot | Captura frame | 10s |
| `cam-upload.timer` | timer + oneshot | Upload frame | 10s |
| `cam-prune-frames.timer` | timer + oneshot | Limpeza buffer | 2min |

---

## RESUMO DE SCRIPTS CRIADOS

| Script | Path | Funcao |
|---|---|---|
| `cam-capture.sh` | `/usr/local/bin/cam-capture.sh` | Captura 1 frame via libcamera |
| `cam-upload.sh` | `/usr/local/bin/cam-upload.sh` | Envia frame mais recente para EC2 |
| `cam-prune-frames.sh` | `/usr/local/bin/cam-prune-frames.sh` | Mantem apenas os 40 mais recentes |
| `cam-export-last5min.sh` | `/usr/local/bin/cam-export-last5min.sh` | Empacota frames recentes em .tar |

---

## ORDEM DE EXECUCAO

```
TAREFA 1  (apt update, instalar deps)
    |
TAREFA 2  (validar camera)
    |
TAREFA 4  (criar diretorios)
    |
TAREFA 5  (script captura)  ---> Teste manual
    |
TAREFA 3  (WireGuard VPN)   ---> Teste manual (ping EC2)
    |                             REQUER: chaves + IP da EC2 do usuario
    |
TAREFA 6  (script upload)   ---> Teste manual (requer EC2 acessivel)
    |
TAREFA 7  (script limpeza)
    |
TAREFA 8  (script export)
    |
TAREFA 9  (systemd captura)
    |
TAREFA 10 (systemd upload)
    |
TAREFA 11 (systemd limpeza)
    |
TAREFA 12 (arquivo .env)
    |
PLANO DE TESTES (T1-T9)
```

**Dependencias criticas:**
- Tarefa 3 (VPN) requer dados da EC2 fornecidos pelo usuario
- Tarefa 6 (upload) requer VPN funcionando + EC2 com esp32-server rodando
- Tudo mais pode ser feito offline

---

## INFORMACOES QUE O AGENTE DEVE PEDIR AO USUARIO

Antes de executar a Tarefa 3 (WireGuard), o agente precisa receber:

1. **IP publico da EC2** (ex: `54.x.x.x`)
2. **Chave publica WireGuard da EC2** (conteudo de `server.pub`)
3. **DEVICE_ID desejado** para este Pi (ex: `pi-cam-001` ou `cam_01_coque`)
4. **URL do endpoint de upload** na EC2 (default: `http://10.8.0.1:5002/upload`)

---

## NOTAS PARA O AGENTE

1. **Executar tudo via SSH.** Nao tentar instalar nada na maquina local.
2. **Registrar outputs.** Copiar o output de cada verificacao para comprovar sucesso.
3. **Parar se algo falhar.** Nao pular tarefas — cada uma depende da anterior.
4. **Cuidado com o microSD.** Nao fazer escritas desnecessarias. O Pi 3B usa microSD que tem vida util limitada.
5. **Senha do sudo.** O user `alecoleto` tem sudo. A senha e `ale!161207`.
6. **Sem interface grafica.** Todos os comandos sao via terminal. Nao usar `raspi-config` com TUI.
7. **Reconexao apos reboot.** Apos `sudo reboot`, aguardar ~60s e reconectar via SSH.
