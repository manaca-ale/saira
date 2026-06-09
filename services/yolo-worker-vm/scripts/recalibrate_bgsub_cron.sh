#!/usr/bin/env bash
# Weekly recalibration of the BGSUB static baseline for frozen-baseline cameras
# (those in BGSUB_ADAPTIVE_DISABLE_DEVICES, e.g. esp32_005 Arruda). Rebuilds the
# .npz from recent sem_ocorrencia frames, then restarts the worker so the fresh
# baseline is loaded (bgsub cache is not hot-reloaded).
#
# Install on host saira-prod (crontab do ubuntu), domingos 04:30 BRT
# (10min após o retrain do DINOv2 pra não competir CPU):
#   (crontab -l 2>/dev/null; echo '30 4 * * 0 /home/ubuntu/saira/services/yolo-worker-vm/scripts/recalibrate_bgsub_cron.sh >> /home/ubuntu/bgsub_recalibrate.log 2>&1') | crontab -
#
# Per-run metrics: /app/state/bgsub_models/recalibrate_log.jsonl (volume yolo_state_prod).
# Previous baseline backed up to {device}.npz.bak before each swap.
set -euo pipefail
CONTAINER="${BGSUB_RECALIBRATE_CONTAINER:-saira-yolo-worker-prod}"
echo "=== $(date -Is) bgsub recalibrate start (container=$CONTAINER) ==="
docker exec "$CONTAINER" python -m worker.recalibrate_bgsub
echo "--- restarting $CONTAINER to load fresh baseline ---"
docker restart "$CONTAINER"
echo "=== $(date -Is) bgsub recalibrate end ==="
