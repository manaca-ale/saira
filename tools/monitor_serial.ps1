# Configurações
$logDir = "C:\saira\logs"
$baudRate = 115200

# 1. Garantir que o diretório de logs existe
if (-not (Test-Path $logDir)) {
    Write-Host "[INFO] Criando diretório de logs em $logDir..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

# 2. Detectar a porta COM via PlatformIO
Write-Host "[INFO] Detectando dispositivos conectados..." -ForegroundColor Cyan
$pioDevices = pio device list --json-output | ConvertFrom-Json

if ($null -eq $pioDevices -or $pioDevices.Count -eq 0) {
    Write-Error "Nenhum dispositivo detectado pelo PlatformIO."
    exit 1
}

# Filtrar para encontrar a porta correta (Ignorar COM1 e Bluetooth, priorizar USB)
$targetDevice = $pioDevices | Where-Object { 
    $_.hwid -like "*USB*" -and 
    $_.description -notlike "*Bluetooth*" -and
    $_.port -ne "COM1"
} | Select-Object -First 1

# Se não encontrar nada com "USB", pega o primeiro que não seja COM1 ou Bluetooth
if ($null -eq $targetDevice) {
    $targetDevice = $pioDevices | Where-Object { 
        $_.port -ne "COM1" -and 
        $_.description -notlike "*Bluetooth*" 
    } | Select-Object -First 1
}

if ($null -eq $targetDevice) {
    Write-Error "Nenhum dispositivo ESP32 válido encontrado (filtros: USB, !Bluetooth, !COM1)."
    exit 1
}

$comPort = $targetDevice.port
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFileName = "serial_$( $comPort.Replace(':', '') )_$timestamp.log"
$logPath = Join-Path $logDir $logFileName

Write-Host "[SUCCESS] Dispositivo encontrado na porta: $comPort" -ForegroundColor Green
Write-Host "[INFO] Iniciando monitoramento (Baud: $baudRate)..." -ForegroundColor Cyan
Write-Host "[INFO] Salvando log em: $logPath" -ForegroundColor Yellow
Write-Host "------------------------------------------------------------"

# 3. Iniciar o monitor e gravar o log simultaneamente
# Nota: Usamos o pio device monitor e redirecionamos via Tee-Object
# O baud rate é passado via parâmetro -b do monitor
pio device monitor --port $comPort --baud $baudRate | Tee-Object -FilePath $logPath
