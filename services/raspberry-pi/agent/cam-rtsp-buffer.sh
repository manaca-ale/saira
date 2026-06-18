#!/usr/bin/env bash
# Buffer circular de vídeo (item #3): grava o RTSP da câmera em segmentos
# .ts curtos num tmpfs, mantendo só os mais recentes (~1-2 min). Sem reencode
# (-c copy). O saira_agent.py concatena esses segmentos sob CMD_VIDEO_CLIP.
#
# Saída lateral (snapshot via RTSP): o mesmo processo decodifica SOMENTE os
# keyframes (-skip_frame nokey ≈ 1 frame a cada 1-2s, barato no Pi 3) e mantém
# um JPEG sempre atual em SNAPSHOT_JPG (escrita atômica: tmp + rename). O
# agente lê esse arquivo em vez do snapshot HTTP da câmera, que é flaky
# (~50% HTTP 404 na pi-cam-001). Desligável com SNAPSHOT_FROM_RTSP=false.
set -euo pipefail

RTSP_URL="${RTSP_URL:?defina RTSP_URL no .env}"
SEG_DIR="${VIDEO_SEG_DIR:-/dev/shm/saira/segments}"
SEG_SECONDS="${VIDEO_SEG_SECONDS:-2}"
SEG_WRAP="${VIDEO_SEG_WRAP:-70}"   # 70 x 2s ~= 140s de janela

SNAPSHOT_FROM_RTSP="${SNAPSHOT_FROM_RTSP:-true}"
SNAPSHOT_JPG="${SNAPSHOT_JPG:-/dev/shm/saira/latest.jpg}"
SNAPSHOT_WIDTH="${SNAPSHOT_WIDTH:-1280}"   # casa com a referência dos polígonos
SNAPSHOT_QUALITY="${SNAPSHOT_QUALITY:-4}"  # -q:v mjpeg (2=melhor, 31=pior)

mkdir -p "$SEG_DIR" "$(dirname "$SNAPSHOT_JPG")"

# -rtsp_transport tcp: mais confiável em 4G. -an: descarta áudio.
# -segment_wrap: ring fixo de arquivos (reutiliza seg_000..seg_NNN).
SEGMENT_ARGS=(
    -an -c:v copy
    -f segment
    -segment_time "$SEG_SECONDS"
    -segment_format mpegts
    -segment_wrap "$SEG_WRAP"
    -reset_timestamps 1
    "$SEG_DIR/seg_%03d.ts"
)

if [[ "$SNAPSHOT_FROM_RTSP" == "true" ]]; then
    # -skip_frame nokey é opção de DECODER (input): o ramo -c copy não decodifica,
    # então só o ramo do JPEG paga decode — e só nos keyframes.
    # -y: o muxer image2 (-update 1) recusa sobrescrever um latest.jpg
    # pré-existente e, com -nostdin, sai com erro em vez de perguntar.
    exec ffmpeg -nostdin -y -loglevel warning \
        -rtsp_transport tcp \
        -skip_frame nokey \
        -i "$RTSP_URL" \
        "${SEGMENT_ARGS[@]}" \
        -an -vf "scale=${SNAPSHOT_WIDTH}:-2" -q:v "$SNAPSHOT_QUALITY" \
        -fps_mode passthrough \
        -f image2 -update 1 -atomic_writing 1 \
        "$SNAPSHOT_JPG"
else
    exec ffmpeg -nostdin -y -loglevel warning \
        -rtsp_transport tcp \
        -i "$RTSP_URL" \
        "${SEGMENT_ARGS[@]}"
fi
