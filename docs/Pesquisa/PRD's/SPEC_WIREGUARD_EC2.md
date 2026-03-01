# SPEC: Configurar WireGuard na EC2 (hub VPN)

> Versao: 1.0 | Data: 2026-02-09
> O agente executa diretamente na EC2 (nao via SSH de outra maquina).
> SO esperado: Ubuntu 22.04+ (EC2 AWS)

---

## CONTEXTO

A EC2 e o ponto central da arquitetura SAIRA. Ela recebe imagens dos dispositivos em campo (Raspberry Pi) via VPN e roda o backend, o worker e o frontend.

```
Raspberry Pi (campo, LTE/4G, CGNAT)
    |
    |  WireGuard UDP 51820
    |
    v
EC2 (IP publico, hub VPN)
    - wg0: 10.8.0.1/24
    - esp32-server (Flask) na porta 5002
    - Backend (FastAPI) na porta 8001
    - Frontend (React) na porta 3000
    - PostgreSQL na porta 5432
```

**Por que WireGuard:**
- LTE tem CGNAT — a EC2 nao consegue iniciar conexao para o Pi
- O Pi inicia a conexao para a EC2 (que tem IP publico)
- WireGuard e leve, rapido e estavel em links instáveis

---

## PRE-REQUISITOS (verificar antes de comecar)

```bash
# 1. Verificar SO
cat /etc/os-release
# Esperado: Ubuntu 22.04 ou superior

# 2. Verificar que e EC2 (opcional)
curl -s http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo "nao e EC2 ou IMDSv2"

# 3. Verificar IP publico
curl -s https://checkip.amazonaws.com
# ANOTAR este IP — sera usado na config do Pi

# 4. Verificar espaco em disco
df -h /
# Esperado: espaco livre suficiente

# 5. Verificar que os servicos Docker estao rodando
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "Docker nao esta rodando"
```

---

## TAREFA 1: Abrir porta UDP 51820 no Security Group

**Objetivo:** Permitir que o Pi se conecte ao WireGuard da EC2.

> Esta tarefa requer acesso ao Console AWS ou uso da AWS CLI.

### Opcao A: Via AWS CLI (se configurada)

```bash
# Descobrir o Security Group da instancia
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
SG_ID=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text)

echo "Security Group: $SG_ID"

# Adicionar regra UDP 51820 (de qualquer IP — LTE nao tem IP fixo)
aws ec2 authorize-security-group-ingress \
    --group-id "$SG_ID" \
    --protocol udp \
    --port 51820 \
    --cidr 0.0.0.0/0 \
    --tag-specifications 'ResourceType=security-group-rule,Tags=[{Key=Name,Value=WireGuard}]'
```

### Opcao B: Via Console AWS (manual)

O agente deve instruir o usuario:

1. Abrir AWS Console > EC2 > Security Groups
2. Selecionar o SG da instancia
3. Inbound Rules > Edit > Add Rule:
   - Type: Custom UDP
   - Port: 51820
   - Source: 0.0.0.0/0 (ou IP fixo do LTE se disponivel)
   - Description: WireGuard VPN
4. Salvar

### Verificacao

```bash
# Testar se a porta esta acessivel (rodar de fora da EC2, ex: maquina local)
# NA MAQUINA LOCAL:
# nmap -sU -p 51820 <IP_PUBLICO_EC2>
# Nota: so vai responder apos WireGuard estar rodando

# Na EC2, verificar regra via CLI
aws ec2 describe-security-groups --group-ids "$SG_ID" \
    --query 'SecurityGroups[0].IpPermissions[?FromPort==`51820`]' 2>/dev/null || echo "verificar manualmente no console"
```

---

## TAREFA 2: Instalar WireGuard

```bash
sudo apt update
sudo apt -y install wireguard wireguard-tools
```

### Verificacao

```bash
which wg
# Esperado: /usr/bin/wg

wg --version
# Esperado: wireguard-tools vX.X.X
```

---

## TAREFA 3: Gerar chaves criptograficas

**Objetivo:** Gerar par de chaves do servidor (EC2) e um par para cada Pi.

### 3a. Chaves do servidor

```bash
sudo bash -c '
    umask 077
    mkdir -p /etc/wireguard/keys
    wg genkey | tee /etc/wireguard/keys/server.key | wg pubkey > /etc/wireguard/keys/server.pub
'
```

### 3b. Chaves do primeiro Pi (saira-2)

```bash
sudo bash -c '
    umask 077
    wg genkey | tee /etc/wireguard/keys/pi-saira-2.key | wg pubkey > /etc/wireguard/keys/pi-saira-2.pub
'
```

### 3c. Exibir chaves publicas (necessarias para configuracao dos peers)

```bash
echo "=== CHAVES PUBLICAS ==="
echo ""
echo "EC2 (server.pub) — usar na config do Pi:"
sudo cat /etc/wireguard/keys/server.pub
echo ""
echo "Pi saira-2 (pi-saira-2.pub) — usar na config da EC2:"
sudo cat /etc/wireguard/keys/pi-saira-2.pub
echo ""
echo "=== CHAVES PRIVADAS (nao compartilhar) ==="
echo ""
echo "EC2 (server.key):"
sudo cat /etc/wireguard/keys/server.key
echo ""
echo "Pi saira-2 (pi-saira-2.key):"
sudo cat /etc/wireguard/keys/pi-saira-2.key
```

> ANOTAR: O agente deve guardar esses valores para usar nas proximas tarefas.
> A chave publica da EC2 (`server.pub`) deve ser enviada para quem configura o Pi.
> A chave privada do Pi (`pi-saira-2.key`) deve ser copiada para o Pi.

### Verificacao

```bash
# Verificar que as chaves existem e tem permissoes corretas
ls -la /etc/wireguard/keys/
# Esperado: 4 arquivos, permissao 600 ou similar (so root)

# Verificar que chaves tem formato correto (base64, 44 chars)
sudo cat /etc/wireguard/keys/server.pub | wc -c
# Esperado: 45 (44 chars + newline)
```

---

## TAREFA 4: Criar configuracao WireGuard

**Objetivo:** Configurar a interface `wg0` com IP 10.8.0.1 e o Pi como peer.

### 4a. Ler chaves para montar o arquivo

```bash
SERVER_PRIVATE_KEY=$(sudo cat /etc/wireguard/keys/server.key)
PI_SAIRA2_PUBLIC_KEY=$(sudo cat /etc/wireguard/keys/pi-saira-2.pub)

echo "Server private key: ${SERVER_PRIVATE_KEY:0:8}..."
echo "Pi public key:      ${PI_SAIRA2_PUBLIC_KEY:0:8}..."
```

### 4b. Criar /etc/wireguard/wg0.conf

```bash
SERVER_PRIVATE_KEY=$(sudo cat /etc/wireguard/keys/server.key)
PI_SAIRA2_PUBLIC_KEY=$(sudo cat /etc/wireguard/keys/pi-saira-2.pub)

sudo tee /etc/wireguard/wg0.conf > /dev/null << WGEOF
[Interface]
Address = 10.8.0.1/24
ListenPort = 51820
PrivateKey = ${SERVER_PRIVATE_KEY}

# Habilitar IP forwarding quando a interface sobe
PostUp = sysctl -w net.ipv4.ip_forward=1 > /dev/null
# Opcional: regra de firewall para rotear trafego dos peers
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT 2>/dev/null || true
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT 2>/dev/null || true

# ---- Peer: Raspberry Pi saira-2 ----
[Peer]
# Hostname: saira-2 | Device ID: pi-cam-001
PublicKey = ${PI_SAIRA2_PUBLIC_KEY}
AllowedIPs = 10.8.0.2/32
PersistentKeepalive = 25
WGEOF

sudo chmod 600 /etc/wireguard/wg0.conf
```

### Verificacao

```bash
# Verificar conteudo (mascarar chave privada)
sudo grep -v PrivateKey /etc/wireguard/wg0.conf
# Esperado: Address = 10.8.0.1/24, ListenPort = 51820, peer com AllowedIPs = 10.8.0.2/32

# Verificar permissoes
ls -la /etc/wireguard/wg0.conf
# Esperado: -rw------- root root
```

---

## TAREFA 5: Habilitar IP forwarding persistente

**Objetivo:** Garantir que IP forwarding sobrevive a reboots (alem do PostUp no wg0.conf).

```bash
# Verificar estado atual
sysctl net.ipv4.ip_forward
# Se ja for 1, ok. Se for 0:

# Tornar persistente
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-wireguard.conf
sudo sysctl --system
```

### Verificacao

```bash
sysctl net.ipv4.ip_forward
# Esperado: net.ipv4.ip_forward = 1
```

---

## TAREFA 6: Ativar WireGuard e habilitar no boot

```bash
sudo systemctl enable --now wg-quick@wg0
```

### Verificacao

```bash
# Status do servico
sudo systemctl status wg-quick@wg0 --no-pager
# Esperado: active (exited) — wg-quick e oneshot, "exited" e normal

# Interface wg0 existe
ip a show wg0
# Esperado: inet 10.8.0.1/24

# WireGuard esta escutando
sudo wg show
# Esperado: interface wg0, listening port 51820, 1 peer (ainda sem handshake)

# Porta UDP aberta
sudo ss -ulnp | grep 51820
# Esperado: UNCONN 0 0 0.0.0.0:51820
```

---

## TAREFA 7: Gerar config pronta para o Pi (saira-2)

**Objetivo:** Gerar o arquivo de configuracao que sera copiado para o Pi, com todos os valores preenchidos.

```bash
EC2_PUBLIC_IP=$(curl -s https://checkip.amazonaws.com)
SERVER_PUBLIC_KEY=$(sudo cat /etc/wireguard/keys/server.pub)
PI_PRIVATE_KEY=$(sudo cat /etc/wireguard/keys/pi-saira-2.key)

echo "============================================="
echo " CONFIG PARA COPIAR PARA O Pi (saira-2)"
echo " Arquivo: /etc/wireguard/wg0.conf"
echo "============================================="
cat << PIEOF

[Interface]
Address = 10.8.0.2/24
PrivateKey = ${PI_PRIVATE_KEY}
DNS = 1.1.1.1

[Peer]
PublicKey = ${SERVER_PUBLIC_KEY}
Endpoint = ${EC2_PUBLIC_IP}:51820
AllowedIPs = 10.8.0.0/24
PersistentKeepalive = 25

PIEOF
echo "============================================="
echo ""
echo "Copiar esse conteudo para /etc/wireguard/wg0.conf no Pi saira-2."
echo "Depois: sudo systemctl enable --now wg-quick@wg0"
```

> ANOTAR: O agente deve salvar esse output. Ele sera usado na spec do Pi (SPEC_SETUP_RASPBERRYPI.md, Tarefa 3).

---

## TAREFA 8: Verificar que esp32-server escuta na interface VPN

**Objetivo:** Garantir que o endpoint de upload (`POST /upload`) esta acessivel pelo Pi via VPN.

```bash
# Verificar que esp32-server esta rodando
docker ps --filter name=esp32 --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
# Esperado: container rodando, porta 5002 mapeada

# Testar endpoint localmente
curl -s -o /dev/null -w "%{http_code}" http://localhost:5002/
# Esperado: 200 ou 404 (depende do endpoint, mas nao deve ser connection refused)

# Testar via IP da VPN (como o Pi vai acessar)
curl -s -o /dev/null -w "%{http_code}" http://10.8.0.1:5002/
# Esperado: mesmo resultado — Docker escuta em 0.0.0.0:5002, entao wg0 funciona

# Testar endpoint de upload com imagem fake
echo -n "fake-jpeg" > /tmp/test_upload.jpg
curl -s -X POST http://10.8.0.1:5002/upload \
    -H "X-Device-Id: test-from-ec2" \
    -F "imageFile=@/tmp/test_upload.jpg"
# Esperado: {"status":"ok","device_id":"test-from-ec2",...} ou erro de imagem invalida
rm -f /tmp/test_upload.jpg
```

Se `curl http://10.8.0.1:5002/` falhar com "Connection refused":
- Docker por padrao faz bind em `0.0.0.0` — deve funcionar
- Verificar: `docker port <container_name>`
- Se estiver bind em `127.0.0.1`, mudar no docker-compose para `"5002:5000"` (sem bind IP)

---

## PLANO DE TESTES

Executar em sequencia apos todas as tarefas.

### T1. WireGuard ativo e escutando

```bash
sudo systemctl is-enabled wg-quick@wg0
# Esperado: enabled

sudo wg show
# Esperado: interface wg0, listening port 51820

ip a show wg0
# Esperado: inet 10.8.0.1/24

sudo ss -ulnp | grep 51820
# Esperado: porta aberta
```

### T2. IP forwarding

```bash
sysctl net.ipv4.ip_forward
# Esperado: 1
```

### T3. Endpoint acessivel via VPN

```bash
curl -s -o /dev/null -w "%{http_code}" http://10.8.0.1:5002/
# Esperado: nao "000" (connection refused)
```

### T4. Handshake com Pi (executar DEPOIS de configurar o Pi)

```bash
sudo wg show
# Esperado: latest handshake < 2 minutos

ping -c 3 10.8.0.2
# Esperado: resposta do Pi
```

### T5. Receber upload do Pi via VPN (executar DEPOIS de configurar o Pi)

```bash
# No Pi (via SSH da maquina local):
# curl -X POST http://10.8.0.1:5002/upload -H "X-Device-Id: pi-cam-001" -F "imageFile=@/tmp/test_cam.jpg"

# Na EC2, verificar que a imagem chegou:
ls -la ~/saira/esp32-server/uploads/pi-cam-001/ 2>/dev/null || echo "diretorio ainda nao criado"
docker logs $(docker ps -q --filter name=esp32) --tail 10 2>/dev/null
# Esperado: log "Received image: pi-cam-001/..."
```

### T6. Resiliencia (simular reconexao)

```bash
# Reiniciar WireGuard
sudo systemctl restart wg-quick@wg0
sleep 5
sudo wg show
# Esperado: interface volta, peer reconecta em ~25s (PersistentKeepalive)
```

---

## COMO ADICIONAR MAIS DISPOSITIVOS (Pi) NO FUTURO

Para cada novo Pi, repetir:

### 1. Gerar chaves na EC2

```bash
DEVICE_NAME="pi-novo-device"
sudo bash -c "
    umask 077
    wg genkey | tee /etc/wireguard/keys/${DEVICE_NAME}.key | wg pubkey > /etc/wireguard/keys/${DEVICE_NAME}.pub
"
```

### 2. Adicionar peer no wg0.conf

```bash
# Escolher proximo IP livre (10.8.0.3, 10.8.0.4, ...)
NEW_IP="10.8.0.3"
NEW_PUB_KEY=$(sudo cat /etc/wireguard/keys/${DEVICE_NAME}.pub)

sudo tee -a /etc/wireguard/wg0.conf > /dev/null << PEEREOF

# ---- Peer: ${DEVICE_NAME} ----
[Peer]
PublicKey = ${NEW_PUB_KEY}
AllowedIPs = ${NEW_IP}/32
PersistentKeepalive = 25
PEEREOF
```

### 3. Aplicar sem derrubar conexoes existentes

```bash
sudo wg syncconf wg0 <(sudo wg-quick strip wg0)
sudo wg show
# Esperado: novo peer aparece na lista
```

> IMPORTANTE: Usar `wg syncconf` em vez de `systemctl restart` para nao derrubar peers conectados.

### 4. Gerar config para o novo Pi

```bash
EC2_PUBLIC_IP=$(curl -s https://checkip.amazonaws.com)
SERVER_PUBLIC_KEY=$(sudo cat /etc/wireguard/keys/server.pub)
NEW_PRIVATE_KEY=$(sudo cat /etc/wireguard/keys/${DEVICE_NAME}.key)

echo "Config para ${DEVICE_NAME} (IP VPN: ${NEW_IP}):"
cat << EOF

[Interface]
Address = ${NEW_IP}/24
PrivateKey = ${NEW_PRIVATE_KEY}
DNS = 1.1.1.1

[Peer]
PublicKey = ${SERVER_PUBLIC_KEY}
Endpoint = ${EC2_PUBLIC_IP}:51820
AllowedIPs = 10.8.0.0/24
PersistentKeepalive = 25
EOF
```

---

## MAPA DE IPs DA VPN

| IP VPN | Dispositivo | Hostname | Device ID |
|---|---|---|---|
| 10.8.0.1 | EC2 (hub) | — | — |
| 10.8.0.2 | Raspberry Pi | saira-2 | pi-cam-001 |
| 10.8.0.3 | (reservado para proximo device) | — | — |

---

## ORDEM DE EXECUCAO

```
TAREFA 1  (Security Group — UDP 51820)
    |
TAREFA 2  (apt install wireguard)
    |
TAREFA 3  (gerar chaves)
    |
TAREFA 4  (criar wg0.conf)
    |
TAREFA 5  (IP forwarding persistente)
    |
TAREFA 6  (ativar wg-quick@wg0)
    |
TAREFA 7  (gerar config para o Pi)  ---> GUARDAR OUTPUT
    |
TAREFA 8  (verificar esp32-server via VPN)
    |
PLANO DE TESTES (T1-T3 imediatos, T4-T5 apos config do Pi)
```

---

## NOTAS PARA O AGENTE

1. **Executar tudo como root ou com sudo.** WireGuard requer privilegios.
2. **Nao reiniciar Docker.** A configuracao do WireGuard nao afeta os containers existentes.
3. **Guardar as chaves.** O output da Tarefa 3 e Tarefa 7 sao criticos — salvar em lugar seguro.
4. **Security Group e bloqueante.** Se a porta UDP 51820 nao estiver aberta, o Pi nunca vai conseguir conectar.
5. **O handshake so acontece quando o Pi conectar.** Ate la, `sudo wg show` mostra o peer sem "latest handshake" — isso e normal.
6. **Se mudar o IP publico da EC2** (ex: Elastic IP nao atribuido), a config do Pi precisa ser atualizada. Recomendavel usar Elastic IP.
7. **Usar `wg syncconf` para mudancas em producao** — nao `systemctl restart`, que derruba todos os peers.
