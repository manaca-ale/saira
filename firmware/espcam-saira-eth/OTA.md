# OTA (HTTP) - Firmware ESP32

Este firmware suporta OTA pull (o ESP32 busca updates via HTTP/HTTPS).

## 1) Criar `.env` para build

Copie `firmware/espcam-saira/.env.ota.example` para `firmware/espcam-saira/.env` e ajuste:

- `WIFI_SSID`, `WIFI_PASSWORD`
- `SERVER_BASE` (ex: `http://54.91.172.66:5000`)
- `OTA_CURRENT_VERSION` (mude a cada build)
- (Opcional) `DEVICE_ID` (se usar remote-config por dispositivo)

## 2) Build (PlatformIO)

O projeto tem 2 environments:

- `ai-thinker-esp32-cam` (compila `src/main.cpp`)
- `ipcam-relay` (compila `src/ipcam_relay.cpp`)

Com o PlatformIO (CLI ou VS Code):

```bash
platformio run -e ipcam-relay
platformio run -e ai-thinker-esp32-cam
```

Os `.bin` saem em:

- `.pio/build/ipcam-relay/firmware.bin`
- `.pio/build/ai-thinker-esp32-cam/firmware.bin`

## 3) Primeira gravacao (USB)

Para OTA funcionar remotamente, o ESP precisa ser gravado uma primeira vez via USB/serial com `OTA_ENABLED=1`.

Depois disso, as proximas atualizacoes podem ser via OTA (servidor na EC2).

## 4) Servidor OTA (EC2)

Veja `esp32-server/OTA.md` para subir o `.bin` no servidor e validar o `manifest.txt`.

