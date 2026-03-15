param(
    [ValidateSet("test", "prod", "both")]
    [string]$Environment = "test",
    [string]$RemoteAlias = "saira-prod",
    [string]$RemoteServicesDir = "/home/ubuntu/saira/services",
    [string]$OutputDir = "C:\saira\tmp\occurrence_logs",
    [string]$Since = "24h",
    [switch]$IncludeUploads,
    [switch]$KeepRemoteArtifacts
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$msg) {
    Write-Host "[INFO] $msg"
}

function Invoke-RemoteBash([string]$alias, [string]$script) {
    $script | & ssh $alias "tr -d '\r' | bash -s"
    if ($LASTEXITCODE -ne 0) {
        throw "Remote command failed on '$alias'"
    }
}

function Copy-FromRemote([string]$alias, [string]$remotePath, [string]$localPath) {
    & scp "$alias`:$remotePath" $localPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to copy '$remotePath' from '$alias'"
    }
}

$envs = switch ($Environment) {
    "both" { @("test", "prod") }
    default { @($Environment) }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$results = @()

foreach ($envName in $envs) {
    $composeFile = if ($envName -eq "test") { "docker-compose.test.yml" } else { "docker-compose.prod.yml" }
    $projectName = if ($envName -eq "test") { "saira-test" } else { "saira-prod" }

    $runId = "saira_occurrence_logs_${envName}_$timestamp"
    $remoteDir = "/tmp/$runId"
    $remoteTar = "/tmp/$runId.tgz"
    $localTar = Join-Path $OutputDir "$runId.tgz"

    Write-Info "Preparing export for '$envName'..."

    $includeUploadsBool = if ($IncludeUploads.IsPresent) { "true" } else { "false" }

    $remoteScriptTemplate = @'
set -euo pipefail
cd "__REMOTE_SERVICES_DIR__"

REMOTE_DIR="__REMOTE_DIR__"
REMOTE_TAR="__REMOTE_TAR__"
COMPOSE_FILE="__COMPOSE_FILE__"
PROJECT_NAME="__PROJECT_NAME__"
LOGS_SINCE="__LOGS_SINCE__"
INCLUDE_UPLOADS="__INCLUDE_UPLOADS__"
ENV_NAME="__ENV_NAME__"
UPLOADS_SOURCE="none"

dc() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@" < /dev/null
}

rm -rf "$REMOTE_DIR" "$REMOTE_TAR"
mkdir -p "$REMOTE_DIR/state" "$REMOTE_DIR/logs" "$REMOTE_DIR/db"

RUNNING_LIST="$(dc ps --services --status running 2>/dev/null || true)"
if [ -z "$RUNNING_LIST" ]; then
  echo "No running services found for project '$PROJECT_NAME' ($COMPOSE_FILE) in $PWD" >&2
  exit 20
fi

# Export worker state (frames/summaries/audits).
if dc ps --services 2>/dev/null | grep -qx "backend"; then
  for d in detection_summaries detection_frames shadow_audit; do
    if dc exec -T backend sh -lc "[ -d /app/yolo_state/$d ]"; then
      dc cp "backend:/app/yolo_state/$d" "$REMOTE_DIR/state/" || true
    fi
  done
fi

# Export service logs.
for svc in yolo-worker backend esp32-server gateway api-gateway web redis db; do
  if dc ps --services 2>/dev/null | grep -qx "$svc"; then
    if [ "$LOGS_SINCE" = "all" ]; then
      dc logs --no-color "$svc" > "$REMOTE_DIR/logs/$svc.log" || true
    else
      dc logs --no-color --since "$LOGS_SINCE" "$svc" > "$REMOTE_DIR/logs/$svc.log" || true
    fi
  fi
done

# Export DB snapshots (CSV).
if dc ps --services 2>/dev/null | grep -qx "db"; then
  if dc exec -T db \
    psql -U postgres -d saira_db \
    -c "\copy (SELECT id, camera_id, timestamp, status, offenders, image_url, confidence_score, created_at FROM detections ORDER BY created_at DESC) TO STDOUT WITH CSV HEADER" \
    > "$REMOTE_DIR/db/detections.csv"; then :; else rm -f "$REMOTE_DIR/db/detections.csv"; fi

  if dc exec -T db \
    psql -U postgres -d saira_db \
    -c "\copy (SELECT detection_id, offender_type, plate, vehicle_color, waste_type, estimated_volume_m3, confidence_score, notes, created_at FROM detection_offenders ORDER BY created_at DESC) TO STDOUT WITH CSV HEADER" \
    > "$REMOTE_DIR/db/detection_offenders.csv"; then :; else rm -f "$REMOTE_DIR/db/detection_offenders.csv"; fi
fi

# Optional: include uploads volume snapshot (can be very large).
if [ "$INCLUDE_UPLOADS" = "true" ]; then
  if dc ps --services 2>/dev/null | grep -qx "esp32-server"; then
    if dc cp "esp32-server:/app/uploads" "$REMOTE_DIR/"; then
      UPLOADS_SOURCE="esp32-server:/app/uploads"
    fi
  elif dc ps --services 2>/dev/null | grep -qx "yolo-worker"; then
    if dc cp "yolo-worker:/app/uploads" "$REMOTE_DIR/"; then
      UPLOADS_SOURCE="yolo-worker:/app/uploads"
    fi
  elif dc ps --services 2>/dev/null | grep -qx "backend"; then
    if dc cp "backend:/app/uploads" "$REMOTE_DIR/"; then
      UPLOADS_SOURCE="backend:/app/uploads"
    fi
  fi
fi

cat > "$REMOTE_DIR/manifest.txt" <<EOF
environment=$ENV_NAME
generated_at=$(date -Iseconds)
compose_file=$COMPOSE_FILE
compose_project=$PROJECT_NAME
state_source=backend:/app/yolo_state
uploads_source=$UPLOADS_SOURCE
logs_since=$LOGS_SINCE
include_uploads=$INCLUDE_UPLOADS
EOF

tar -czf "$REMOTE_TAR" -C "$REMOTE_DIR" .
'@

    $remoteScript = $remoteScriptTemplate.
        Replace("__REMOTE_SERVICES_DIR__", $RemoteServicesDir).
        Replace("__REMOTE_DIR__", $remoteDir).
        Replace("__REMOTE_TAR__", $remoteTar).
        Replace("__COMPOSE_FILE__", $composeFile).
        Replace("__PROJECT_NAME__", $projectName).
        Replace("__LOGS_SINCE__", $Since).
        Replace("__INCLUDE_UPLOADS__", $includeUploadsBool).
        Replace("__ENV_NAME__", $envName)

    Invoke-RemoteBash -alias $RemoteAlias -script $remoteScript
    Invoke-RemoteBash -alias $RemoteAlias -script "if [ ! -f '$remoteTar' ] && [ -d '$remoteDir' ]; then tar -czf '$remoteTar' -C '$remoteDir' .; fi; test -f '$remoteTar'"
    Write-Info "Downloading archive: $remoteTar"
    Copy-FromRemote -alias $RemoteAlias -remotePath $remoteTar -localPath $localTar

    $localExtractDir = Join-Path $OutputDir $runId
    New-Item -ItemType Directory -Force -Path $localExtractDir | Out-Null
    & tar -xzf $localTar -C $localExtractDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to extract '$localTar'"
    }

    if (-not $KeepRemoteArtifacts.IsPresent) {
        Invoke-RemoteBash -alias $RemoteAlias -script "rm -rf '$remoteDir' '$remoteTar'"
    }

    $results += [PSCustomObject]@{
        environment  = $envName
        archive      = $localTar
        extracted_to = $localExtractDir
    }
}

Write-Host ""
Write-Host "Export completed:"
$results | Format-Table -AutoSize
Write-Host ""
Write-Host "Tip: open 'manifest.txt' inside each extracted folder for metadata."
