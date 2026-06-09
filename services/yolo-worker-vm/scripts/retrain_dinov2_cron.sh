#!/usr/bin/env bash
# Weekly retrain do filtro DINOv2 (cam_10 Imbiribeira et al).
# Chama o módulo dentro do worker; promove o artefato só se passar o gate (AUC>=min,
# n não encolheu). O worker faz hot-reload via mtime — sem restart.
#
# Instalar no host saira-prod (crontab do ubuntu), domingos 04:10 BRT. Invoque via
# `bash` para sobreviver à perda do bit +x num `git reset --hard` (o script é
# versionado 100755, mas o `bash` é cinto-e-suspensório — ver recalibrate_bgsub_cron.sh):
#   (crontab -l 2>/dev/null; echo '10 4 * * 0 bash /home/ubuntu/saira/services/yolo-worker-vm/scripts/retrain_dinov2_cron.sh >> /home/ubuntu/dinov2_retrain.log 2>&1') | crontab -
#
# Log do worker (métricas por retreino) fica em /app/state/dinov2_models/retrain_log.jsonl
# (volume yolo_state_prod). Backup do artefato anterior: dinov2_clf_<device>.npz.bak
set -euo pipefail
CONTAINER="${DINOV2_RETRAIN_CONTAINER:-saira-yolo-worker-prod}"
echo "=== $(date -Is) retrain start (container=$CONTAINER) ==="
docker exec "$CONTAINER" python -m worker.retrain_dinov2
echo "=== $(date -Is) retrain end ==="
