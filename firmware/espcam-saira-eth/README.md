# ESP32 Relay Ethernet Variant

Este diretório contém a variante do firmware `ipcam_relay` para uso com Ethernet (câmera na LAN da ETH) e Wi-Fi para uplink/OTA.

## Build

```bash
cd firmware/espcam-saira-eth
platformio run -e ipcam-relay-esp32-eth
```

## Upload USB

```bash
cd firmware/espcam-saira-eth
platformio run -e ipcam-relay-esp32-eth -t upload --upload-port COM26
```

Se não conectar no bootloader:
1. Segure `BOOT`
2. Aperte e solte `EN/RESET`
3. Solte `BOOT` quando aparecer `Connecting...`

## OTA (servidor teste :5002)

```bash
cd firmware/espcam-saira-eth
platformio run -e ipcam-relay-esp32-eth
curl -f -F "firmware=@.pio/build/ipcam-relay-esp32-eth/firmware.bin" -F "version=<VERSAO>" http://54.91.172.66:5002/ota/upload
```

Verificação do manifest:

```bash
curl -fsS http://54.91.172.66:5002/ota/manifest.txt
```

## Observações

- Esta variante é separada da versão Wi-Fi legada em `firmware/espcam-saira`.
- Credenciais locais ficam em `.env` (não versionado).
- Para produção, ajuste `SERVER_BASE`, versão OTA e credenciais no `.env`.
