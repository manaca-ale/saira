#!/usr/bin/env bash
set -euo pipefail

FRAMES_DIR="/var/spool/cam/frames"
DEVICE_ID="${DEVICE_ID:-pi-cam-001}"
EC2_UPLOAD_URL="${EC2_UPLOAD_URL:-http://10.8.0.1:5002/upload}"
TIMEOUT="${UPLOAD_TIMEOUT:-30}"

# Encontrar o frame mais recente ainda nao enviado
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

HTTP_CODE=$(curl -fsS --max-time "$TIMEOUT" -o /tmp/upload_response.json -w "%{http_code}"     -X POST "$EC2_UPLOAD_URL"     -H "X-Device-Id: ${DEVICE_ID}"     -F "imageFile=@${LATEST}"     2>/dev/null) || HTTP_CODE="000"

if [ "$HTTP_CODE" = "200" ]; then
    touch "${LATEST}.uploaded"
    echo "OK: ${FILENAME} enviado (HTTP ${HTTP_CODE})"
    cat /tmp/upload_response.json 2>/dev/null || true
else
    echo "ERRO: HTTP ${HTTP_CODE} ao enviar ${FILENAME}"
    cat /tmp/upload_response.json 2>/dev/null || true
    exit 1
fi
