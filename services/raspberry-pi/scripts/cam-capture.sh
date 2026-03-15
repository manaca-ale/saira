#!/usr/bin/env bash
set -euo pipefail

FRAMES_DIR="/var/spool/cam/frames"
WIDTH="${CAM_WIDTH:-1920}"
HEIGHT="${CAM_HEIGHT:-1080}"
QUALITY="${CAM_QUALITY:-40}"
FONT="/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"

mkdir -p "$FRAMES_DIR"

TIMESTAMP="$(date '+%Y-%m-%d %H\:%M\:%S')"
FILENAME="$(date +%Y%m%d_%H%M%S).jpg"
FILEPATH="${FRAMES_DIR}/${FILENAME}"
TMPFILE="${FILEPATH}.tmp"

rpicam-still -n -t 1 --width "$WIDTH" --height "$HEIGHT" -q "$QUALITY" -o "$TMPFILE" 2>/dev/null

if [ ! -f "$TMPFILE" ]; then
    echo "ERRO: falha na captura"
    exit 1
fi

# Gravar timestamp na imagem (canto inferior esquerdo, fundo semi-transparente)
ffmpeg -y -i "$TMPFILE" -vf "drawtext=fontfile=${FONT}:text='${TIMESTAMP}':x=10:y=h-th-10:fontsize=24:fontcolor=white:borderw=2:bordercolor=black:box=1:boxcolor=black@0.4:boxborderw=6" -update 1 -q:v 2 "$FILEPATH" 2>/dev/null

rm -f "$TMPFILE"

if [ -f "$FILEPATH" ]; then
    SIZE=$(stat -c%s "$FILEPATH")
    if [ "$SIZE" -lt 500 ]; then
        echo "WARN: imagem muito pequena (${SIZE} bytes), descartando"
        rm -f "$FILEPATH"
        exit 1
    fi
    echo "OK: ${FILENAME} (${SIZE} bytes)"
else
    echo "ERRO: falha ao gravar timestamp"
    exit 1
fi
