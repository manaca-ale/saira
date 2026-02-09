#!/usr/bin/env bash
set -euo pipefail

# ---- Configuration (env vars with defaults) ----
UPLOAD_DIR="${UPLOAD_DIR:-/home/ubuntu/saira/esp32-server/uploads}"
MIN_FREE_PERCENT="${MIN_FREE_PERCENT:-30}"
ENABLE_DRIVE_BACKUP="${ENABLE_DRIVE_BACKUP:-false}"
DRIVE_REMOTE="${DRIVE_REMOTE:-gdrive}"
DRIVE_FOLDER_ID="${DRIVE_FOLDER_ID:-1sds3yeef0o9j902X2taxFoEE0iU42sF4}"
LOG_FILE="${LOG_FILE:-/home/ubuntu/saira/esp32-server/backup_uploads.log}"
LOG_MAX_BYTES=$((10 * 1024 * 1024))
BW_LIMIT="${BW_LIMIT:-5M}"
NICE_LEVEL=10
IONICE_CLASS=2
IONICE_LEVEL=7

log() {
  echo "$(date -Is) $*" | tee -a "$LOG_FILE"
}

# ---- Log rotation ----
if [ -f "$LOG_FILE" ]; then
  LOG_SIZE=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
  if [ "$LOG_SIZE" -gt "$LOG_MAX_BYTES" ]; then
    mv "$LOG_FILE" "${LOG_FILE}.$(date -u +%Y%m%dT%H%M%SZ)"
  fi
fi

# ---- Validate ----
if [ ! -d "$UPLOAD_DIR" ]; then
  log "ERROR: upload dir not found: $UPLOAD_DIR"
  exit 1
fi

# ---- Disk space check ----
USED_PCT=$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
FREE_PCT=$((100 - USED_PCT))
log "INFO: disk free ${FREE_PCT}% (threshold: ${MIN_FREE_PERCENT}%)"

if [ "$FREE_PCT" -ge "$MIN_FREE_PERCENT" ]; then
  # Even with enough space, clean up processed images older than 1 hour
  CLEANED=$(find "$UPLOAD_DIR" -name "*.processed" -mmin +60 | wc -l)
  if [ "$CLEANED" -gt 0 ]; then
    # Delete the corresponding .jpg files first
    find "$UPLOAD_DIR" -name "*.processed" -mmin +60 | while read -r marker; do
      jpg="${marker%.processed}"
      [ -f "$jpg" ] && rm -f "$jpg"
    done
    # Then delete the markers
    find "$UPLOAD_DIR" -name "*.processed" -mmin +60 -exec rm -f {} \;
    log "INFO: cleaned $CLEANED old processed images (disk OK)"
  fi
  log "OK: free ${FREE_PCT}% >= ${MIN_FREE_PERCENT}%, routine cleanup done."
  exit 0
fi

# ---- Disk is getting full — clean processed images ----
log "WARNING: disk low (${FREE_PCT}% free). Starting cleanup..."

# Count processed images
PROCESSED_COUNT=$(find "$UPLOAD_DIR" -name "*.processed" 2>/dev/null | wc -l)
log "INFO: found $PROCESSED_COUNT processed image markers"

# Optional: backup to Google Drive before cleaning
if [ "$ENABLE_DRIVE_BACKUP" = "true" ]; then
  if command -v rclone >/dev/null 2>&1; then
    TS=$(date -u +"%Y%m%dT%H%M%SZ")
    DEST_PATH="${DRIVE_REMOTE}:uploads-${TS}"

    IONICE_CMD=""
    if command -v ionice >/dev/null 2>&1; then
      IONICE_CMD="ionice -c $IONICE_CLASS -n $IONICE_LEVEL"
    fi

    log "INFO: backing up to $DEST_PATH ..."
    if $IONICE_CMD nice -n "$NICE_LEVEL" rclone copy "$UPLOAD_DIR" "$DEST_PATH" \
      --drive-root-folder-id "$DRIVE_FOLDER_ID" \
      --create-empty-src-dirs \
      --checksum \
      --fast-list \
      --bwlimit "$BW_LIMIT" \
      --transfers 4 \
      --checkers 4 \
      --log-file "$LOG_FILE" \
      --log-level INFO; then
      log "INFO: backup complete to $DEST_PATH"
    else
      log "WARNING: rclone backup failed, continuing with cleanup anyway"
    fi
  else
    log "WARNING: rclone not installed, skipping backup"
  fi
fi

# Delete processed images (marker + corresponding jpg)
find "$UPLOAD_DIR" -name "*.processed" 2>/dev/null | while read -r marker; do
  jpg="${marker%.processed}"
  [ -f "$jpg" ] && rm -f "$jpg"
  rm -f "$marker"
done

# Delete empty directories
find "$UPLOAD_DIR" -mindepth 2 -type d -empty -delete 2>/dev/null || true

# Report
NEW_USED_PCT=$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
NEW_FREE_PCT=$((100 - NEW_USED_PCT))
log "DONE: cleaned $PROCESSED_COUNT processed images. Disk now ${NEW_FREE_PCT}% free."

# Emergency: if still critically low (<10%), delete ALL images in unknown_device/
if [ "$NEW_FREE_PCT" -lt 10 ]; then
  log "CRITICAL: disk still at ${NEW_FREE_PCT}% free after cleanup!"
  if [ -d "$UPLOAD_DIR/unknown_device" ]; then
    find "$UPLOAD_DIR/unknown_device" -mindepth 1 -delete 2>/dev/null || true
    log "EMERGENCY: deleted all unknown_device images"
  fi
fi
