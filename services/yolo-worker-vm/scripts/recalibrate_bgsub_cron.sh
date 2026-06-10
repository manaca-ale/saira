#!/usr/bin/env bash
# Weekly recalibration of the BGSUB static baseline for frozen-baseline cameras
# (those in BGSUB_ADAPTIVE_DISABLE_DEVICES, e.g. esp32_005 Arruda). Rebuilds the
# .npz from recent sem_ocorrencia frames, then restarts the worker so the fresh
# baseline is loaded (bgsub cache is not hot-reloaded).
#
# Install on host saira-prod (crontab do ubuntu), domingos 04:30 BRT
# (10min após o retrain do DINOv2 pra não competir CPU). Invoque via `bash` para
# sobreviver à perda do bit +x num `git reset --hard` (incidente 2026-06-05: o
# deploy zerou o +x e o cron quebrou silenciosamente com "Permission denied").
# O script também é versionado com mode 100755, mas o `bash` é cinto-e-suspensório:
#   (crontab -l 2>/dev/null; echo '30 4 * * 0 bash /home/ubuntu/saira/services/yolo-worker-vm/scripts/recalibrate_bgsub_cron.sh >> /home/ubuntu/bgsub_recalibrate.log 2>&1') | crontab -
#
# Optional 1st arg = a single device_id: recalibrate ONLY that camera (frequent
# re-anchor). Used for clean-zone-adaptive cameras (BGSUB_ADAPTIVE_CLEAN_ZONE_ONLY_DEVICES,
# e.g. esp32_005 Arruda) whose baseline rarely absorbs on a chronic point and so
# ages out between weekly runs. Re-anchor every 12h (05:00/17:00 BRT):
#   (crontab -l 2>/dev/null; echo '0 5,17 * * * bash /home/ubuntu/saira/services/yolo-worker-vm/scripts/recalibrate_bgsub_cron.sh esp32_005 >> /home/ubuntu/bgsub_recalibrate.log 2>&1') | crontab -
#
# Per-run metrics: /app/state/bgsub_models/recalibrate_log.jsonl (volume yolo_state_prod).
# Previous baseline backed up to {device}.npz.bak before each swap.
set -euo pipefail
CONTAINER="${BGSUB_RECALIBRATE_CONTAINER:-saira-yolo-worker-prod}"
DEVICE="${1:-}"   # optional: recalibrate ONLY this device_id (frequent re-anchor)
DEVICE_ARG=""
TARGET="all frozen/clean-zone devices"
if [ -n "$DEVICE" ]; then DEVICE_ARG="--device $DEVICE"; TARGET="$DEVICE"; fi
echo "=== $(date -Is) bgsub recalibrate start (container=$CONTAINER, target=$TARGET) ==="
docker exec "$CONTAINER" python -m worker.recalibrate_bgsub $DEVICE_ARG
echo "--- restarting $CONTAINER to load fresh baseline ---"
docker restart "$CONTAINER"
echo "=== $(date -Is) bgsub recalibrate end ==="
