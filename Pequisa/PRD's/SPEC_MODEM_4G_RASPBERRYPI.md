# SPEC: Modem 4G LTE Altomex — Raspberry Pi 3B

> Versao: 1.0 | Data: 2026-02-09
> Baseado na analise tecnica: `Pequisa/Compatibilidade Raspberry Pi 3 Modem 4G.pdf`
> Este documento e para um agente executar remotamente via SSH no Raspberry Pi.

---

## CONTEXTO

**Problema:** O Pi precisa de conectividade internet em campo (postes, farois, areas externas) onde nao existe WiFi disponivel.

**Solucao:** Modem 4G LTE WiFi Altomex conectado ao Raspberry Pi 3B, fornecendo link de dados para o tunel WireGuard que ja existe.

**Arquitetura atual:**
```
Camera IMX219 (CSI) -> Pi 3B -> [???] -> WireGuard VPN -> EC2
```

**Arquitetura alvo:**
```
Camera IMX219 (CSI) -> Pi 3B -> [Modem 4G USB / RNDIS] -> WireGuard VPN -> EC2
```

**O que muda:** Apenas a camada de transporte. WireGuard, scripts de captura e upload continuam inalterados.

---

## DECISAO DE ARQUITETURA: USB vs WiFi

O modem Altomex oferece dois modos de conexao com o Pi. A decisao impacta energia, latencia e complexidade.

| Criterio | USB Direto (RNDIS) | WiFi Hotspot |
|---|---|---|
| Latencia | Menor (sem overhead wireless) | Maior (+10-30ms) |
| Energia | Modem consome da porta USB do Pi (risco) | Modem alimentado externamente (seguro) |
| Complexidade | Precisa de usb_modeswitch + driver | Apenas wpa_supplicant / nmcli |
| Confiabilidade | Mais estavel (conexao fisica) | Suscetivel a interferencia 2.4GHz |
| Custo extra | Nenhum (ou hub USB alimentado ~R$30) | Fonte USB extra para o modem |

### Recomendacao: **Modo Hibrido**

1. **Primario:** WiFi do modem Altomex (isola eletricamente, evita brownout no Pi)
2. **Fallback:** USB RNDIS (se WiFi do modem falhar ou latencia for critica)

**Justificativa:** O Pi 3B tem limite de 1200mA total nas portas USB. O modem consome 300-500mA em picos de transmissao. Somado ao consumo do Pi (730mA sob carga), estamos no limite do polifusivel (2.5A). Alimentar o modem externamente e mais seguro para operacao 24/7.

---

## PRE-REQUISITOS

### Hardware
- [ ] Raspberry Pi 3B com Raspberry Pi OS Bookworm (64-bit) Lite
- [ ] Modem 4G LTE WiFi Altomex
- [ ] Chip SIM ativo (Vivo/Claro/TIM) com plano de dados
- [ ] Fonte de alimentacao Pi: **5.1V / 2.5A minimo** (cabo curto, AWG baixo)
- [ ] Fonte USB separada para o modem (5V / 1A) — power bank ou carregador
- [ ] WireGuard ja configurado e funcional (conforme SPEC_WIREGUARD_EC2.md)

### Software (ja presente no Bookworm)
- NetworkManager (substituiu dhcpcd no Bookworm)
- wpa_supplicant
- Kernel modules: `rndis_host`, `cdc_ether` (built-in)

### Informacoes necessarias antes de comecar
- [ ] Operadora do chip SIM
- [ ] APN da operadora (ver tabela abaixo)
- [ ] SSID e senha do hotspot do modem (padrao: ver etiqueta do modem)
- [ ] Senha admin do modem (padrao: `admin`)

**APNs das operadoras brasileiras:**

| Operadora | APN | Usuario | Senha |
|---|---|---|---|
| Vivo | zap.vivo.com.br | vivo | vivo |
| Claro | claro.com.br | claro | claro |
| TIM | timbrasil.br | tim | tim |
| Oi | gprs.oi.com.br | oi | oi |

---

## FASE 1: Preparar o Modem Altomex (manual, sem SSH)

> Estas etapas sao feitas com um notebook/celular, NAO no Pi.

### 1.1 Primeiro boot do modem

```
1. Inserir chip SIM (tamanho Standard) no slot do modem
2. Conectar modem a uma fonte USB (nao no Pi ainda)
3. Aguardar LED:
   - Vermelho fixo  = sem SIM ou sem rede
   - Verde piscando = conectando
   - Verde fixo     = conectado ao 4G
   - Azul fixo      = conectado ao 4G com WiFi ativo
4. Conectar um celular/notebook ao WiFi do modem
   - SSID padrao: verificar etiqueta no corpo do modem
   - Senha padrao: verificar etiqueta no corpo do modem
```

### 1.2 Acessar Web UI e configurar

```
1. Abrir navegador: http://192.168.100.1 (ou http://192.168.199.1)
2. Login: admin / admin
3. Configuracoes criticas:
   a) SEGURANCA:
      - Trocar senha admin (obrigatorio)
      - WiFi: WPA2-PSK com senha forte (minimo 12 caracteres)
      - Anotar o novo SSID e senha
   b) APN (se auto-deteccao falhar):
      - Network Settings > APN
      - Inserir APN da operadora (tabela acima)
      - Salvar e reiniciar modem
   c) REDE:
      - Verificar se esta registrado em 4G/LTE (nao 3G)
      - Anotar o IP do gateway (ex: 192.168.100.1)
   d) FILTRO MAC (opcional mas recomendado):
      - Anotar MAC do WiFi do Pi: executar no Pi `cat /sys/class/net/wlan0/address`
      - Adicionar na whitelist do modem
4. Testar: abrir qualquer site no celular conectado ao modem
```

### 1.3 Validar conectividade do modem

```
- Ping: abrir um site qualquer
- Velocidade: speedtest.net (esperar 10-50 Mbps down, 5-20 Mbps up em 4G real)
- Se LED vermelho fixo: SIM nao detectado ou PIN ativo — desbloquear via Web UI
```

---

## FASE 2: Conectar Pi ao Modem via WiFi (modo primario)

> A partir daqui, tudo via SSH no Pi.
> O Pi precisa estar temporariamente conectado a outra rede (Ethernet ou WiFi local) para acesso SSH inicial.

### 2.1 Verificar estado atual da rede

```bash
# Ver interfaces disponiveis
nmcli device status

# Ver conexoes WiFi visiveis
nmcli device wifi list

# O SSID do modem Altomex deve aparecer na lista
```

### 2.2 Conectar ao WiFi do modem

```bash
# Conectar (substitua SSID e SENHA pelos valores reais)
sudo nmcli device wifi connect "SSID_DO_MODEM" password "SENHA_DO_MODEM" ifname wlan0

# Verificar conexao
nmcli connection show --active

# Testar conectividade
ping -c 4 8.8.8.8
ping -c 4 1.1.1.1
```

### 2.3 Configurar prioridade e auto-connect

```bash
# Garantir que o WiFi do modem reconecta automaticamente
sudo nmcli connection modify "SSID_DO_MODEM" connection.autoconnect yes
sudo nmcli connection modify "SSID_DO_MODEM" connection.autoconnect-priority 100

# Se houver outra rede WiFi configurada, diminuir prioridade dela
# sudo nmcli connection modify "OUTRA_REDE" connection.autoconnect-priority 50
```

### 2.4 Verificar rota padrao

```bash
# O gateway deve ser o IP do modem (192.168.100.1 ou 192.168.199.1)
ip route show default

# Esperado:
# default via 192.168.100.1 dev wlan0 proto dhcp metric 600
```

---

## FASE 3: Validar WireGuard sobre 4G

> O tunel WireGuard ja deve estar configurado (SPEC_WIREGUARD_EC2.md).
> Esta fase apenas valida que funciona sobre o link 4G.

### 3.1 Subir tunel e testar

```bash
# Subir WireGuard
sudo wg-quick up wg0

# Verificar handshake
sudo wg show

# Esperado: "latest handshake: X seconds ago"
# Se nao houver handshake, o endpoint EC2 nao esta acessivel via 4G

# Testar ping pela VPN
ping -c 4 10.8.0.1
```

### 3.2 Validar upload de frame

```bash
# Testar upload manual (simula o que cam-upload.sh faz)
curl -X POST \
  -H "X-Device-Id: saira-pi-01" \
  -F "imageFile=@/var/spool/cam/frames/$(ls -t /var/spool/cam/frames/*.jpg | head -1)" \
  http://10.8.0.1:5002/upload

# Esperado: HTTP 200
```

### 3.3 Troubleshooting WireGuard sobre 4G

```
Problema: Sem handshake
  -> Verificar se a operadora bloqueia UDP 51820
  -> Tentar trocar porta do WireGuard na EC2 para 443 ou 53
  -> Verificar se CGNAT esta ativo (sempre esta em 4G): PersistentKeepalive=25 resolve

Problema: Handshake OK mas sem ping
  -> Verificar ip forwarding na EC2: sysctl net.ipv4.ip_forward
  -> Verificar iptables/nftables na EC2

Problema: Conexao intermitente
  -> Verificar LED do modem (verde fixo = OK)
  -> Verificar sinal: acessar http://192.168.100.1 > status
  -> Se sinal fraco, reposicionar modem (janela, local elevado)
```

---

## FASE 4: Modo USB RNDIS (alternativa/fallback)

> Usar APENAS se o modo WiFi for insuficiente (latencia critica, interferencia, etc.)
> ATENCAO: Risco de brownout — usar hub USB alimentado ou fonte 5.1V/3A no Pi.

### 4.1 Instalar dependencias

```bash
sudo apt update
sudo apt install -y usb-modeswitch usb-modeswitch-data
```

### 4.2 Conectar modem via USB e identificar

```bash
# Conectar modem na porta USB do Pi
# Aguardar 10 segundos

# Verificar se aparece no barramento USB
lsusb

# Procurar por algo como:
# Bus 001 Device 00X: ID XXXX:XXXX (Qualcomm ou nome do chipset)
# Anotar o Vendor ID (VID) e Product ID (PID)

# Verificar se usb_modeswitch ja trocou o modo automaticamente
dmesg | tail -30

# Procurar por mensagens como:
# "rndis_host" ou "cdc_ether" = modem ja esta em modo rede
# "usb-storage" = ainda em modo CD-ROM, precisa de modeswitch manual
```

### 4.3 Modeswitch manual (se necessario)

```bash
# Se o modem apareceu como storage (CD-ROM), forcar troca:
# Substituir VID:PID pelo valor real do lsusb

# Exemplo generico para chipsets Qualcomm:
sudo usb_modeswitch -v 0x05c6 -p 0x1000 -M "5553424312345678000000000000061b000000020000000000000000000000"

# Verificar se trocou
dmesg | tail -10
# Deve aparecer nova interface: usb0 ou eth1

# Se nao funcionar, verificar se existe regra em:
ls /usr/share/usb_modeswitch/
# Procurar por arquivo com o VID do modem
```

### 4.4 Configurar interface RNDIS

```bash
# Verificar se a interface apareceu
ip link show

# Procurar por usb0 ou eth1
# Obter IP via DHCP do modem
sudo dhclient usb0

# Verificar IP atribuido
ip addr show usb0

# Testar conectividade
ping -c 4 8.8.8.8
```

### 4.5 Persistir configuracao USB com NetworkManager

```bash
# Criar conexao gerenciada
sudo nmcli connection add type ethernet ifname usb0 con-name "modem-4g-usb"
sudo nmcli connection modify "modem-4g-usb" connection.autoconnect yes
sudo nmcli connection modify "modem-4g-usb" ipv4.method auto

# Ativar
sudo nmcli connection up "modem-4g-usb"
```

---

## FASE 5: Script de Monitoramento e Reconexao

> Script que verifica a saude da conexao 4G e faz auto-recovery.

### 5.1 Criar script de monitoramento

Criar arquivo: `/home/alecoleto/scripts/monitor-4g.sh`

```bash
#!/usr/bin/env bash
# monitor-4g.sh — Monitora conexao 4G e reconecta se necessario
# Executado via systemd timer a cada 60 segundos

set -euo pipefail

LOG_TAG="monitor-4g"
VPN_PEER="10.8.0.1"
WAN_CHECK="1.1.1.1"
MODEM_SSID="SSID_DO_MODEM"  # <-- EDITAR

log() { logger -t "$LOG_TAG" "$*"; }

# 1. Verificar link WAN (internet via 4G)
if ! ping -c 2 -W 5 "$WAN_CHECK" &>/dev/null; then
    log "WARN: sem internet. Tentando reconectar WiFi do modem..."

    nmcli device wifi connect "$MODEM_SSID" ifname wlan0 2>/dev/null || true
    sleep 10

    if ! ping -c 2 -W 5 "$WAN_CHECK" &>/dev/null; then
        log "ERROR: reconexao WiFi falhou. Internet indisponivel."
        exit 1
    fi
    log "OK: WiFi reconectado."
fi

# 2. Verificar tunel WireGuard
if ! ping -c 2 -W 5 "$VPN_PEER" &>/dev/null; then
    log "WARN: VPN down. Reiniciando WireGuard..."
    sudo wg-quick down wg0 2>/dev/null || true
    sleep 2
    sudo wg-quick up wg0
    sleep 5

    if ! ping -c 2 -W 5 "$VPN_PEER" &>/dev/null; then
        log "ERROR: VPN nao subiu apos restart."
        exit 1
    fi
    log "OK: VPN reconectada."
fi

log "OK: 4G + VPN operacionais."
```

### 5.2 Criar servico e timer systemd

Criar `/etc/systemd/system/monitor-4g.service`:
```ini
[Unit]
Description=SAIRA 4G connection monitor
After=network-online.target wg-quick@wg0.service
Wants=network-online.target

[Service]
Type=oneshot
User=root
ExecStart=/home/alecoleto/scripts/monitor-4g.sh
```

Criar `/etc/systemd/system/monitor-4g.timer`:
```ini
[Unit]
Description=Run 4G monitor every 60s

[Timer]
OnBootSec=90
OnUnitActiveSec=60
AccuracySec=10

[Install]
WantedBy=timers.target
```

### 5.3 Ativar

```bash
chmod +x /home/alecoleto/scripts/monitor-4g.sh
sudo systemctl daemon-reload
sudo systemctl enable --now monitor-4g.timer
sudo systemctl status monitor-4g.timer
```

---

## FASE 6: Hardening para Operacao em Campo

### 6.1 Gerenciamento termico

```bash
# Monitorar temperatura do Pi
vcgencmd measure_temp

# Se > 70C, considerar:
# - Dissipador no SoC do Pi
# - Extensao USB para afastar modem do Pi
# - Gabinete ventilado (nunca selado sem furos)
```

### 6.2 Watchdog de hardware

```bash
# Ativar watchdog do BCM2837 (reinicia Pi se travar)
sudo bash -c 'echo "dtparam=watchdog=on" >> /boot/firmware/config.txt'
sudo apt install -y watchdog
sudo systemctl enable --now watchdog

# Editar /etc/watchdog.conf:
# max-load-1 = 24
# watchdog-device = /dev/watchdog
# watchdog-timeout = 15
```

### 6.3 Otimizacao de consumo de dados

O pipeline atual consome aproximadamente:
- 1 frame JPEG (640x360, q70) ~ **15-40 KB**
- Intervalo: 10 segundos
- Por hora: **5.4 - 14.4 MB**
- Por dia: **130 - 345 MB**
- Por mes: **3.9 - 10.4 GB**

**Para reduzir consumo (se plano de dados for limitado):**

```bash
# Opcao A: Aumentar intervalo de captura (10s -> 30s = 1/3 do consumo)
# Editar .env: CAPTURE_INTERVAL=30

# Opcao B: Reduzir qualidade JPEG (70 -> 50)
# Editar .env: JPEG_QUALITY=50

# Opcao C: Reduzir resolucao (640x360 -> 480x270)
# Editar .env: CAM_WIDTH=480 CAM_HEIGHT=270
```

### 6.4 Limite de dados mensal (protecao contra estouro)

Adicionar ao `monitor-4g.sh`:

```bash
# Verificar consumo de dados na interface wlan0
RX_BYTES=$(cat /sys/class/net/wlan0/statistics/rx_bytes)
TX_BYTES=$(cat /sys/class/net/wlan0/statistics/tx_bytes)
TOTAL_MB=$(( (RX_BYTES + TX_BYTES) / 1048576 ))

# Limite: 8GB (ajustar conforme plano)
LIMIT_MB=8192

if [ "$TOTAL_MB" -gt "$LIMIT_MB" ]; then
    log "ALERTA: Consumo de dados atingiu ${TOTAL_MB}MB (limite: ${LIMIT_MB}MB)"
    # Opcional: parar uploads
    # sudo systemctl stop cam-upload.timer
fi
```

> NOTA: Contadores de /sys/class/net resetam no reboot. Para tracking mensal persistente,
> usar vnstat: `sudo apt install vnstat && vnstat -m -i wlan0`

---

## CHECKLIST FINAL DE VALIDACAO

Executar na ordem, **todos devem passar**:

```bash
# 1. Modem ligado e com LED verde/azul fixo
# [VISUAL] Verificar LED do modem

# 2. Pi conectado ao WiFi do modem
nmcli device status | grep wlan0
# Esperado: wlan0  wifi  connected  SSID_DO_MODEM

# 3. Internet funcional
ping -c 4 1.1.1.1
# Esperado: 0% packet loss

# 4. WireGuard funcional sobre 4G
sudo wg show | grep "latest handshake"
# Esperado: handshake recente (< 2 min)

# 5. VPN peer alcancavel
ping -c 4 10.8.0.1
# Esperado: 0% packet loss

# 6. Upload de frame funcional
curl -s -o /dev/null -w "%{http_code}" \
  -X POST -H "X-Device-Id: saira-pi-01" \
  -F "imageFile=@$(ls -t /var/spool/cam/frames/*.jpg 2>/dev/null | head -1)" \
  http://10.8.0.1:5002/upload
# Esperado: 200

# 7. Timers do pipeline ativos
systemctl is-active cam-capture.timer
systemctl is-active cam-upload.timer
systemctl is-active cam-prune-frames.timer
systemctl is-active monitor-4g.timer
# Esperado: todos "active"

# 8. Monitor de conexao funcional
sudo journalctl -u monitor-4g -n 5 --no-pager
# Esperado: "OK: 4G + VPN operacionais."

# 9. Temperatura aceitavel
vcgencmd measure_temp
# Esperado: < 70C
```

---

## RESUMO DAS FASES

| Fase | Descricao | Tempo estimado |
|---|---|---|
| 1 | Preparar modem (SIM, APN, seguranca) | 15 min |
| 2 | Conectar Pi ao WiFi do modem | 10 min |
| 3 | Validar WireGuard sobre 4G | 10 min |
| 4 | Modo USB RNDIS (opcional) | 20 min |
| 5 | Script de monitoramento + systemd | 15 min |
| 6 | Hardening (termico, watchdog, dados) | 20 min |

**Tempo total: ~1h30 (sem USB) ou ~2h (com USB)**

---

## RISCOS E MITIGACOES

| Risco | Probabilidade | Impacto | Mitigacao |
|---|---|---|---|
| Brownout do Pi com modem USB | Alta | Sistema reinicia | Usar modo WiFi (Fase 2) ou hub USB alimentado |
| Operadora bloqueia UDP/WireGuard | Baixa | Sem VPN | Trocar porta WG para 443/53 |
| Sinal 4G fraco no local | Media | Baixa velocidade | Reposicionar modem, verificar cobertura antes |
| Superaquecimento em gabinete | Media | Throttling/desconexao | Dissipador + ventilacao + extensao USB |
| Estouro de franquia de dados | Media | Sem internet | Monitorar com vnstat + limites no script |
| Modem nao suporta banda B7/B28 | Baixa | Cobertura reduzida | Verificar cobertura B1/B3/B5 no local de deploy |
