#!/usr/bin/env bash
set -euo pipefail

FRAMES_DIR="/var/spool/cam/frames"
KEEP="${CAM_KEEP_FRAMES:-40}"
OUTDIR="/tmp"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTFILE="${OUTDIR}/last5min_${TIMESTAMP}.tar"

# Listar os N frames mais recentes
FILES=$(ls -1t "$FRAMES_DIR"/*.jpg 2>/dev/null | head -n "$KEEP")

if [ -z "$FILES" ]; then
    echo "ERRO: nenhum frame disponivel em ${FRAMES_DIR}"
    exit 1
fi

COUNT=$(echo "$FILES" | wc -l)
echo "$FILES" | tar -cf "$OUTFILE" -T -

echo "OK: ${OUTFILE} criado (${COUNT} frames)"
ls -lh "$OUTFILE"
