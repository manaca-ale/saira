# OTA (ESP32 Pull) via EC2

O ESP32 busca periodicamente um manifest e, se houver versao nova, baixa o `latest.bin` e atualiza sozinho.

## Endpoints

- `GET /ota/manifest.txt`
  - Retorna:
    - `version=<...>`
    - `bin_url=<...>` (absoluto se `PUBLIC_BASE_URL` estiver definido; senao, relativo)
    - `sha256=<...>`
- `GET /ota/latest.bin`
- `POST /ota/upload`
  - Multipart form:
    - campo `firmware`: o arquivo `.bin`
    - campo opcional `version`: string da versao (se nao enviar, o servidor usa timestamp UTC)
  - Se `ADMIN_TOKEN` estiver definido no `.env` do container, envie header `X-Admin-Token`.

## Upload (exemplos)

### Sem token

```bash
curl -f \
  -F "firmware=@firmware.bin" \
  -F "version=2026-02-07_1" \
  http://EC2_PUBLIC_IP:5000/ota/upload
```

### Com token

```bash
curl -f \
  -H "X-Admin-Token: SEU_TOKEN" \
  -F "firmware=@firmware.bin" \
  -F "version=2026-02-07_1" \
  http://EC2_PUBLIC_IP:5000/ota/upload
```

Depois confira:

```bash
curl -fsS http://EC2_PUBLIC_IP:5000/ota/manifest.txt
```

## Portas (deploy)

- Producao: `5001` (`esp32-server/docker-compose.prod.yml`)
- Teste: `5002` (`esp32-server/docker-compose.test.yml`)
