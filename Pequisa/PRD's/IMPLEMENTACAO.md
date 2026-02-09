# Implementacao (Raspberry Pi + IMX219 + LTE + EC2)

Este documento e para passar para um agente/tecnico executar a instalacao e deixar o sistema rodando.

## Objetivo

- Raspberry Pi 3 Model B com camera IMX219 (CSI) em rede LTE/4G.
- Enviar video para uma EC2 para rodar IA (captura de frames).
- Sob demanda, exportar "os ultimos 5 minutos" de video.
- Acesso remoto seguro mesmo com CGNAT (tipico em LTE).

## Recomendacao de SO

- `Raspberry Pi OS Lite (64-bit) - Bookworm`

## Acesso ao Pi (via VS Code)

### Preparacao no Raspberry Pi Imager

Antes de gravar o microSD, no Raspberry Pi Imager:

- Habilitar `SSH`.
- Definir `username/password`.
- Definir `timezone/locale`.
- Se for usar Wi-Fi inicial, configurar SSID/senha. Se for LTE via roteador, pode deixar sem Wi-Fi e usar Ethernet primeiro.

### Conectar via VS Code Remote-SSH

No Windows (sua maquina):

1. Instalar `VS Code`.
2. Instalar extensao: `Remote - SSH`.
3. Descobrir o IP do Pi no roteador (DHCP) ou via `arp -a` depois de ligado.
4. No VS Code:
   - `Ctrl+Shift+P` -> `Remote-SSH: Connect to Host...`
   - Digitar: `alecoleto@saira` (ou o usuario/hostname que voce configurou)
5. Abrir uma pasta no Pi (ex: `/home/pi/app`).

Atalho: se preferir terminal, usar:

```powershell
ssh alecoleto@saira
```

### Credenciais do dispositivo (atual)

- Dispositivo (hostname): `saira`
- Login: `alecoleto`
- Senha: `ale!161207`

Observacao: guardar senha em texto plano nao e recomendado. Assim que estiver tudo ok, prefira trocar para autenticacao por chave SSH e/ou rotacionar a senha.

## Rodar o agente "Codex" no Raspberry Pi (via terminal do VS Code)

Voce pode rodar o Codex CLI direto no Pi abrindo um terminal no VS Code conectado via Remote-SSH.

### Opcao 1 (mais simples): Rodar o Codex no seu PC, editar o Pi via Remote-SSH

- Abra o projeto/pasta no Pi com Remote-SSH.
- No terminal local (PC) rode o Codex CLI.

Vantagens:

- Login com navegador e mais facil no PC.
- Pi 3 tem CPU/RAM limitados; deixa o peso no PC.

### Opcao 2: Instalar e rodar o Codex CLI no proprio Pi

Instalar Node.js + npm:

```bash
sudo apt update
sudo apt -y install nodejs npm
node -v
npm -v
```

Instalar Codex CLI:

```bash
sudo npm install -g @openai/codex
codex --help
```

Autenticacao:

- Em ambiente headless/SSH, o fluxo "Sign in with ChatGPT" pode ser chato (precisa abrir link no seu PC).
- Alternativa mais previsivel: usar `OPENAI_API_KEY` no ambiente:

```bash
export OPENAI_API_KEY="SEU_TOKEN_AQUI"
codex
```

Para persistir:

```bash
echo 'export OPENAI_API_KEY="SEU_TOKEN_AQUI"' >> ~/.bashrc
source ~/.bashrc
```

Uso:

```bash
cd /home/pi/app
codex
```

## Setup basico no Pi (primeiro boot)

No Pi:

```bash
sudo apt update
sudo apt -y full-upgrade
sudo apt -y install git python3-venv python3-pip ffmpeg
sudo reboot
```

## Estrutura do projeto (minima)

Como hoje existe apenas `descobrir_onvif.py` (Windows), recomendo organizar assim no Pi:

- `/home/pi/app/`
  - `requirements.txt`
  - `scripts/`
    - `descobrir_onvif.py` (se ainda for usado para cameras IP; nao e necessario para IMX219)
  - `services/`
  - `README.md` (este arquivo pode ser copiado para la)

### requirements.txt sugerido

Crie `requirements.txt` com:

```txt
requests
```

Criar venv e instalar:

```bash
cd /home/pi/app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Parte 1: Video da IMX219 (libcamera)

No Raspberry Pi OS Bookworm, o stack recomendado e `libcamera`.

Validar camera:

```bash
libcamera-hello -t 3000
```

Se isso falhar:

- Verificar cabo CSI encaixado corretamente.
- Verificar se a camera aparece em `libcamera-hello --list-cameras` (se disponivel).

## Parte 2: Rede remota (LTE) com VPN (WireGuard)

LTE costuma ter CGNAT. Entao:

- EC2 fica com IP publico e porta UDP aberta do WireGuard.
- Pi inicia a conexao para a EC2 (peer).

### EC2 (WireGuard "hub")

No Security Group da EC2:

- Liberar `UDP 51820` (ou outra porta que voce escolher) apenas para o IP de saida do chip 4G se for fixo; se nao for, vai precisar abrir para 0.0.0.0/0 e endurecer com chaves e firewall.

Instalar WireGuard (Ubuntu/Debian):

```bash
sudo apt update
sudo apt -y install wireguard
```

Gerar chaves:

```bash
umask 077
wg genkey | tee server.key | wg pubkey > server.pub
wg genkey | tee pi.key | wg pubkey > pi.pub
```

Config exemplo `/etc/wireguard/wg0.conf` na EC2:

```ini
[Interface]
Address = 10.8.0.1/24
ListenPort = 51820
PrivateKey = <SERVER_PRIVATE_KEY>

# Permitir roteamento se necessario
PostUp = sysctl -w net.ipv4.ip_forward=1

[Peer]
PublicKey = <PI_PUBLIC_KEY>
AllowedIPs = 10.8.0.2/32
PersistentKeepalive = 25
```

Subir:

```bash
sudo systemctl enable --now wg-quick@wg0
sudo wg show
```

### Raspberry Pi (peer)

Instalar:

```bash
sudo apt -y install wireguard
```

Gerar chaves no Pi:

```bash
umask 077
wg genkey | tee /etc/wireguard/pi.key | wg pubkey > /etc/wireguard/pi.pub
sudo cat /etc/wireguard/pi.pub
```

Config `/etc/wireguard/wg0.conf` no Pi:

```ini
[Interface]
Address = 10.8.0.2/24
PrivateKey = <PI_PRIVATE_KEY>
DNS = 1.1.1.1

[Peer]
PublicKey = <SERVER_PUBLIC_KEY>
Endpoint = <EC2_PUBLIC_IP>:51820
AllowedIPs = 10.8.0.0/24
PersistentKeepalive = 25
```

Subir:

```bash
sudo systemctl enable --now wg-quick@wg0
sudo wg show
ping -c 3 10.8.0.1
```

## Parte 3: Stream para a EC2 (para IA)

Nova diretriz: a IA nao precisa de stream continuo. Ela precisa de 1 frame a cada N segundos (ex: 10s, configuravel).

Isso reduz drasticamente consumo de dados LTE e complexidade.

Padrao recomendado para frames:

- `640x360` (ou `960x540` se precisar mais detalhe)
- JPEG `quality 65-75`
- 1 frame a cada `10s` (ajustar conforme necessidade)

### Captura de frame no Pi (IMX219 / libcamera)

Criar diretorio:

```bash
sudo mkdir -p /var/spool/cam/frames
sudo chown -R pi:pi /var/spool/cam
```

Exemplo de captura (1 frame, sem preview):

```bash
libcamera-still -n -t 1 --width 640 --height 360 -q 70 \
  -o /var/spool/cam/frames/$(date +%Y%m%d_%H%M%S).jpg
```

### Envio do frame para a EC2

Voce tem 2 opcoes:

- Endpoint HTTP(S) na EC2 (ex: FastAPI) recebendo `multipart/form-data`.
- Upload direto para S3 usando URL pre-assinada (recomendado para evitar credenciais AWS no Pi).

Exemplo de POST para um endpoint na EC2 (via WireGuard):

```bash
curl -fsS -X POST "http://10.8.0.1:8080/frame" \
  -F "device_id=pi-cam-001" \
  -F "ts=$(date -Iseconds)" \
  -F "image=@/var/spool/cam/frames/$(ls -1t /var/spool/cam/frames/*.jpg | head -n 1)"
```

Na EC2, a IA roda em cima desse frame (armazenar em disco/S3 e/ou processar em memoria).

## Parte 4: Buffer "ultimos 5 minutos" (no Pi)

Como a ingestao da IA e por frames, o buffer mais economico e um "ring buffer" de JPEGs.

Diretorio:

- `/var/spool/cam/frames/`

Regra:

- Se tirar 1 frame a cada 10s, manter os ultimos 30 frames = 5 minutos.
- Para dar folga, manter 40 frames (6-7 minutos).

Script de limpeza `/usr/local/bin/cam-prune-frames.sh` (mantem os 40 mais recentes):

```bash
#!/usr/bin/env bash
set -euo pipefail
dir="/var/spool/cam/frames"
keep=40

mapfile -t files < <(ls -1t "$dir"/*.jpg 2>/dev/null || true)
if (( ${#files[@]} <= keep )); then exit 0; fi

for f in "${files[@]:keep}"; do
  rm -f -- "$f"
done
```

Agendar via `systemd timer` (recomendado) ou cron.

### Opcional: Buffer de video local (se "ultimos 5 min" precisar ser video)

Se a exigencia for exportar video dos ultimos 5 min (nao apenas 30-40 imagens), entao o Pi precisa gravar video localmente.
Para economizar LTE, esse video fica local e so e enviado quando solicitado.

Tradeoff: aumenta escrita no microSD. Para 24/7, considere microSD "High Endurance" ou SSD USB.

## Parte 5: EC2 solicitar export "ultimos 5 minutos"

Implementacao simples e robusta: EC2 faz `ssh` no Pi via WireGuard e roda um script.

Script no Pi: `/usr/local/bin/cam-export-last5min.sh`

- Por padrao (modo economico): empacotar os ultimos frames JPEG em um `.tar`.
- Opcao melhor: mandar para a EC2 via `scp` (pela VPN) ou upload para S3 usando URL pre-assinada.

Exemplo (rascunho) de export para tar:

```bash
#!/usr/bin/env bash
set -euo pipefail
dir="/var/spool/cam/frames"
out="/tmp/last5min_$(date +%Y%m%d_%H%M%S).tar"
ls -1t "$dir"/*.jpg | head -n 40 | tar -cvf "$out" -T -
echo "$out"
```

Na EC2:

```bash
ssh alecoleto@10.8.0.2 sudo /usr/local/bin/cam-export-last5min.sh
scp alecoleto@10.8.0.2:/tmp/last5min_*.tar .
```

## Servicos (systemd) que o agente deve criar

No Pi:

- `wg-quick@wg0` (WireGuard)
- `cam-capture.service` (captura periodica de frame com libcamera)
- `cam-upload.service` (upload/POST do frame para a EC2 ou S3)
- `cam-prune-frames.timer` + `cam-prune-frames.service` (limpeza do buffer de frames)
- Opcional: servico de buffer de video local (se precisar exportar video, nao apenas frames)

Na EC2:

- `wg-quick@wg0`
- Um servico HTTP(S) para receber frames e rodar a IA (ou pipeline que consome do S3).

## Observacoes de robustez (LTE)

- Use `PersistentKeepalive = 25` no WireGuard do Pi.
- Se o upload LTE for limitado, aumente o intervalo (ex: 20s) e reduza resolucao/qualidade do JPEG.
- Mantenha buffer local (frames e opcionalmente video) para resistir a oscilacao de rede.

## Checklist rapido de validacao

No Pi:

- `libcamera-hello` funciona.
- `wg show` mostra handshake com a EC2.
- EC2 pinga `10.8.0.2`.
- Frames aparecem em `/var/spool/cam/frames`.
- EC2 recebe frames (ou ve arquivos novos no S3).
- `cam-export-last5min.sh` gera um arquivo e a EC2 consegue copiar.

## Plano de testes (executar e registrar evidencias)

Este e o passo-a-passo para o agente testar tudo que foi implementado. A ideia e gerar evidencias (outputs) para cada etapa.

### 1) Saude do sistema (Pi)

```bash
hostname
uname -a
uptime
df -h
free -h
```

Esperado:

- Hostname = `saira`
- Sem particao cheia e sem swap zerado se o sistema estiver sob carga.

### 2) Rede e SSH (Pi <-> PC/EC2)

No Pi:

```bash
ip a
ip r
```

Da sua maquina/EC2 (ajustar destino):

```bash
ssh alecoleto@saira
```

### 3) Camera IMX219 (libcamera)

No Pi:

```bash
libcamera-hello -t 2000
libcamera-still -n -t 1 --width 640 --height 360 -q 70 -o /tmp/test.jpg
ls -lh /tmp/test.jpg
```

Esperado:

- `test.jpg` existe e tem tamanho razoavel (ex: dezenas de KB).

### 4) WireGuard (VPN)

No Pi:

```bash
sudo systemctl status wg-quick@wg0 --no-pager
sudo wg show
ping -c 3 10.8.0.1
```

Na EC2:

```bash
sudo systemctl status wg-quick@wg0 --no-pager
sudo wg show
ping -c 3 10.8.0.2
```

Esperado:

- `latest handshake` recente.
- Ping entre `10.8.0.1` e `10.8.0.2` ok.

### 5) Captura periodica de frames (servico)

No Pi (servico e/ou timer criado pelo agente):

```bash
sudo systemctl status cam-capture.service --no-pager || true
sudo systemctl status cam-capture.timer --no-pager || true
ls -1t /var/spool/cam/frames | head
```

Esperado:

- Aparecem arquivos `.jpg` novos a cada N segundos (ex: 10s).

### 6) Upload/entrega para EC2 (servico)

Se estiver usando endpoint HTTP na EC2:

No Pi:

```bash
sudo systemctl status cam-upload.service --no-pager || true
sudo journalctl -u cam-upload.service -n 50 --no-pager || true
```

Na EC2:

- Verificar logs do app receptor (FastAPI/nginx/systemd) e confirmar recebimento.

Se estiver usando S3 presigned:

- Confirmar que o Pi consegue fazer upload (logs ok) e que os objetos chegam no bucket/prefixo esperado.

### 7) Buffer (limpeza) dos frames

No Pi:

```bash
sudo systemctl status cam-prune-frames.service --no-pager || true
sudo systemctl status cam-prune-frames.timer --no-pager || true
ls -1 /var/spool/cam/frames/*.jpg | wc -l
```

Esperado:

- Contagem de frames <= `keep` (ex: 40), sem crescer indefinidamente.

### 8) Export "ultimos 5 min" sob demanda

No Pi:

```bash
sudo /usr/local/bin/cam-export-last5min.sh
ls -lh /tmp/last5min_*.tar | tail -n 1
```

Da EC2:

```bash
scp alecoleto@10.8.0.2:/tmp/last5min_*.tar .
tar -tvf last5min_*.tar | head
```

Esperado:

- Arquivo `.tar` existe, transfere, e contem ~40 JPEGs (ou o numero configurado).

### 9) Teste de resiliencia (reconexao LTE)

No Pi:

- Desconectar/reconectar a internet por 1 minuto (simular queda LTE).
- Confirmar que `wg` volta (handshake recente) e que o pipeline de frames volta sozinho.

Comandos:

```bash
sudo wg show
sudo systemctl --failed
sudo journalctl -u cam-capture.service -n 50 --no-pager || true
sudo journalctl -u cam-upload.service -n 50 --no-pager || true
```
