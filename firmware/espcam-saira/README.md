# ESP32 IPCam Relay (Wi-Fi) - Variante S3

Firmware de relay que captura `snap.jpg` de uma camera IP na mesma rede Wi-Fi e envia para o servidor (`/upload`).

## Estrutura

- `src/ipcam_relay.cpp`: fluxo principal de captura e upload
- `platformio.ini`: environments de build/upload
- `.env`: configuracoes locais (nao versionado)
- `OTA.md`: detalhes do fluxo de OTA

## Environment recomendado (S3)

Use o environment:

- `ipcam-relay-esp32s3-devkitc-1-n16r8`

Comandos:

```bash
cd firmware/espcam-saira
platformio run -e ipcam-relay-esp32s3-devkitc-1-n16r8
```

## Upload via USB (S3)

```bash
cd firmware/espcam-saira
platformio run -e ipcam-relay-esp32s3-devkitc-1-n16r8 -t upload --upload-port COM20
```

## OTA (servidor teste em `:5002`)

1. Ajuste `OTA_CURRENT_VERSION` no `.env` a cada release.
2. Gere o binario:

```bash
cd firmware/espcam-saira
platformio run -e ipcam-relay-esp32s3-devkitc-1-n16r8
```

3. Publique no servidor:

```bash
curl -f -F "firmware=@.pio/build/ipcam-relay-esp32s3-devkitc-1-n16r8/firmware.bin" -F "version=<VERSAO>" http://54.91.172.66:5002/ota/upload
```

4. Verifique o manifest:

```bash
curl -fsS http://54.91.172.66:5002/ota/manifest.txt
```

## Monitor serial

Monitor simples:

```bash
platformio device monitor -p COM20 -b 115200
```

Gravar serial em arquivo para auditoria:

```powershell
Set-Location C:\saira
New-Item -ItemType Directory -Path logs -Force | Out-Null
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$log = "logs/serial_COM20_$ts.log"
platformio device monitor -p COM20 -b 115200 | Tee-Object -FilePath $log
```

## Diagnostico rapido

- `OTA: falhou ... mismatch chip ID`: binario do manifest nao corresponde ao chip alvo.
- `Upload ... 200 OK`: envio para servidor OK.
- `Camera IP GET falhou: -1`: falha de conectividade com a camera IP.
- `WiFi timeout`: perda de conexao com AP.
