#!/usr/bin/env bash
# Buffer circular de vídeo (item #3): grava o RTSP da câmera em segmentos
# .ts curtos num tmpfs, mantendo só os mais recentes (~1-2 min). Sem reencode
# (-c copy). O saira_agent.py concatena esses segmentos sob CMD_VIDEO_CLIP.
#
# Saída lateral (snapshot via RTSP): mantém um JPEG sempre atual em SNAPSHOT_JPG
# (escrita atômica: tmp + rename). O agente lê esse arquivo tanto para o gate de
# movimento quanto para os frames de EVENTO que sobem por 4G, e o painel/ao-vivo.
#
# DUAS FONTES (economia de 4G + CPU):
#   * segmentos de vídeo  -> MAIN  (subtype=0, 1080p HEVC, -c copy)  = evidência
#     em alta, guardada em RAM e persistida no SD só quando o descarte é
#     confirmado (CMD_PERSIST_CLIP). Nunca sobe por 4G a não ser sob demanda.
#   * frames de DECISÃO   -> SUBSTREAM (subtype=1, 704x480 H264)     = o que
#     sobe por 4G para o gate/detail decidir. ~4-5x menos bytes que o main e
#     decode muito mais leve (H264 480p vs keyframe HEVC 1080p) — alívio real
#     numa Pi térmica/throttled. O substream é 16:9 anamórfico, então é forçado
#     a 1280x720 (scale W:H) para casar EXATAMENTE com a referência do polígono.
#
# Reversível sem editar este arquivo: SNAPSHOT_STREAM=main volta a tirar o
# snapshot do main (comportamento legado). SNAPSHOT_FROM_RTSP=false desliga o
# snapshot (só segmentos).
#
# ATENÇÃO: NÃO confundir SNAPSHOT_STREAM (main/sub, qual STREAM da câmera vira
# o JPEG) com SNAPSHOT_SOURCE (auto/rtsp/http) que o saira_agent.py lê para
# decidir se pega o snapshot do RTSP ou do CGI HTTP — são coisas diferentes.
set -euo pipefail

RTSP_URL="${RTSP_URL:?defina RTSP_URL no .env}"
# Substream para os frames de decisão. Derivado do main trocando subtype=0->1,
# ou defina RTSP_SUB_URL no .env explicitamente.
RTSP_SUB_URL="${RTSP_SUB_URL:-${RTSP_URL/subtype=0/subtype=1}}"
# "sub" (padrão, low-q p/ decisão) ou "main" (legado, snapshot do 1080p).
SNAPSHOT_STREAM="${SNAPSHOT_STREAM:-sub}"

SEG_DIR="${VIDEO_SEG_DIR:-/dev/shm/saira/segments}"
SEG_SECONDS="${VIDEO_SEG_SECONDS:-2}"
SEG_WRAP="${VIDEO_SEG_WRAP:-70}"   # 70 x 2s ~= 140s de janela

SNAPSHOT_FROM_RTSP="${SNAPSHOT_FROM_RTSP:-true}"
SNAPSHOT_JPG="${SNAPSHOT_JPG:-/dev/shm/saira/latest.jpg}"
SNAPSHOT_WIDTH="${SNAPSHOT_WIDTH:-1280}"    # casa com a referência dos polígonos
SNAPSHOT_HEIGHT="${SNAPSHOT_HEIGHT:-720}"   # força 16:9 (substream 704x480 é anamórfico)
SNAPSHOT_QUALITY="${SNAPSHOT_QUALITY:-4}"   # -q:v mjpeg (2=melhor, 31=pior)

mkdir -p "$SEG_DIR" "$(dirname "$SNAPSHOT_JPG")"

# -rtsp_transport tcp: mais confiável em 4G. -an: descarta áudio.
# Segmentos SEMPRE do main (input 0), sem reencode. -segment_wrap: ring fixo.
SEGMENT_ARGS=(
    -map 0 -an -c:v copy
    -f segment
    -segment_time "$SEG_SECONDS"
    -segment_format mpegts
    -segment_wrap "$SEG_WRAP"
    -reset_timestamps 1
    "$SEG_DIR/seg_%03d.ts"
)

if [[ "$SNAPSHOT_FROM_RTSP" != "true" ]]; then
    # Só segmentos, sem snapshot.
    exec ffmpeg -nostdin -y -loglevel warning \
        -rtsp_transport tcp -i "$RTSP_URL" \
        "${SEGMENT_ARGS[@]}"
fi

if [[ "$SNAPSHOT_STREAM" == "sub" ]]; then
    # DECISÃO via substream (input 1): -skip_frame nokey decodifica só keyframes
    # (~1 frame/1-2s, barato). scale W:H FORÇADO recupera o 16:9 do 704x480
    # anamórfico e alinha com o polígono. Main (input 0) segue só para segmentos.
    # -y: o muxer image2 (-update 1) recusa sobrescrever um latest.jpg
    # pré-existente e, com -nostdin, sai com erro em vez de perguntar.
    exec ffmpeg -nostdin -y -loglevel warning \
        -rtsp_transport tcp -i "$RTSP_URL" \
        -rtsp_transport tcp -skip_frame nokey -i "$RTSP_SUB_URL" \
        "${SEGMENT_ARGS[@]}" \
        -map 1 -an -vf "scale=${SNAPSHOT_WIDTH}:${SNAPSHOT_HEIGHT}" -q:v "$SNAPSHOT_QUALITY" \
        -fps_mode passthrough \
        -f image2 -update 1 -atomic_writing 1 \
        "$SNAPSHOT_JPG"
else
    # Legado: snapshot do MAIN (input 0), mantém aspecto nativo.
    exec ffmpeg -nostdin -y -loglevel warning \
        -rtsp_transport tcp \
        -skip_frame nokey \
        -i "$RTSP_URL" \
        "${SEGMENT_ARGS[@]}" \
        -map 0 -an -vf "scale=${SNAPSHOT_WIDTH}:-2" -q:v "$SNAPSHOT_QUALITY" \
        -fps_mode passthrough \
        -f image2 -update 1 -atomic_writing 1 \
        "$SNAPSHOT_JPG"
fi
