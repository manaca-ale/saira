#!/usr/bin/env bash
set -euo pipefail

FRAMES_DIR="/var/spool/cam/frames"
KEEP="${CAM_KEEP_FRAMES:-40}"

mapfile -t files < <(ls -1t "$FRAMES_DIR"/*.jpg 2>/dev/null || true)

TOTAL=${#files[@]}
if (( TOTAL <= KEEP )); then
    echo "OK: ${TOTAL} frames (<= ${KEEP}), nada a limpar"
    exit 0
fi

DELETED=0
for f in "${files[@]:KEEP}"; do
    rm -f -- "$f"
    rm -f -- "${f}.uploaded"
    DELETED=$((DELETED + 1))
done

echo "OK: removidos ${DELETED} frames antigos (mantidos ${KEEP})"
