#!/usr/bin/env bash
# Buffer circular de video (item #3): grava o RTSP da camera em segmentos
# .ts curtos num tmpfs, mantendo so os mais recentes (~1-2 min). Sem reencode
# (-c copy). O saira_agent.py concatena esses segmentos sob CMD_VIDEO_CLIP.
set -euo pipefail

RTSP_URL="${RTSP_URL:?defina RTSP_URL no .env}"
SEG_DIR="${VIDEO_SEG_DIR:-/dev/shm/saira/segments}"
SEG_SECONDS="${VIDEO_SEG_SECONDS:-2}"
SEG_WRAP="${VIDEO_SEG_WRAP:-70}"   # 70 x 2s ~= 140s de janela

mkdir -p "$SEG_DIR"

# -rtsp_transport tcp: mais confiavel em 4G. -an: descarta audio.
# -segment_wrap: ring fixo de arquivos (reutiliza seg_000..seg_NNN).
exec ffmpeg -nostdin -loglevel warning \
    -rtsp_transport tcp \
    -i "$RTSP_URL" \
    -an -c:v copy \
    -f segment \
    -segment_time "$SEG_SECONDS" \
    -segment_format mpegts \
    -segment_wrap "$SEG_WRAP" \
    -reset_timestamps 1 \
    "$SEG_DIR/seg_%03d.ts"
