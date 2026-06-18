<#
  zoom-live.ps1 - Assiste o video AO VIVO da camera Intelbras (SAIRA pi-cam)
  e controla o zoom ao mesmo tempo, da sua maquina Windows.

  A camera (192.168.0.130) so e alcancavel de dentro da LAN da Raspberry Pi,
  entao este script abre um tunel SSH encadeado:

      seu PC  --L-->  EC2 (saira-prod)  --L-->  Pi (saira@10.8.0.3)  -->  camera

  e expoe localmente:
      http://localhost:<porta>   -> interface WEB da camera (live view + zoom)
      rtsp://localhost:<porta>/.. -> stream RTSP (abre no VLC, forcado a TCP)

  3 formas de assistir/controlar (use a que preferir):
    1) VLC mostrando o video  +  digitar o zoom no prompt  (recomendado).
    2) Navegador na interface da camera (painel de zoom embutido).
    3) So o prompt de zoom (status/<0-1>/reset/in/out).

  Uso:   powershell -ExecutionPolicy Bypass -File tools\zoom-live.ps1
  Sair:  digite  q  no prompt (fecha o tunel automaticamente).

  Robustez: usa portas aleatorias altas (nos dois lados do tunel) e limpa
  tuneis orfaos no EC2 com bracket-trick, entao pode rodar varias vezes.
#>
param(
  [string]$Cam = '192.168.0.130'
)
$ErrorActionPreference = 'Stop'

function Get-FreeLocalPort {
  for ($i = 0; $i -lt 50; $i++) {
    $p = Get-Random -Minimum 20000 -Maximum 60000
    $busy = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if (-not $busy) { return $p }
  }
  throw "Nao achei porta local livre."
}

# bracket-trick: o padrao '[1]92...' casa com '192...' mas NAO casa com a
# propria linha de comando do pkill (evita o self-match que matava o pkill
# antes de matar o alvo).
$cleanup = "pkill -f '[1]92.168.0.130:80' 2>/dev/null; pkill -f '[1]92.168.0.130:554' 2>/dev/null; true"

Write-Host "== Limpando tuneis orfaos no EC2 ==" -ForegroundColor Cyan
ssh saira-prod $cleanup | Out-Null

Write-Host "== Lendo credenciais da camera no .env da Pi ==" -ForegroundColor Cyan
$user = (ssh saira-prod "ssh saira@10.8.0.3 'grep ^IP_CAM_USER= /opt/saira/agent/.env | cut -d= -f2-'").Trim()
$pass = (ssh saira-prod "ssh saira@10.8.0.3 'grep ^IP_CAM_PASS= /opt/saira/agent/.env | cut -d= -f2-'").Trim()
if (-not $user -or -not $pass) { throw "Nao consegui ler IP_CAM_USER/PASS da Pi." }

$httpPort = Get-FreeLocalPort
$rtspPort = Get-FreeLocalPort
while ($rtspPort -eq $httpPort) { $rtspPort = Get-FreeLocalPort }
Write-Host "== Portas locais: HTTP=$httpPort  RTSP=$rtspPort ==" -ForegroundColor Cyan

# Tunel encadeado. ssh externo encaminha portas locais -> EC2; ssh interno
# (no EC2) as encaminha -> camera, via Pi. Portas iguais nos dois lados.
$inner = "ssh -o ExitOnForwardFailure=yes -L ${httpPort}:${Cam}:80 -L ${rtspPort}:${Cam}:554 -N saira@10.8.0.3"
$sshArgs = @(
  '-o','ExitOnForwardFailure=yes',
  '-L',"${httpPort}:localhost:${httpPort}",
  '-L',"${rtspPort}:localhost:${rtspPort}",
  'saira-prod', $inner
)
Write-Host "== Abrindo tunel SSH (seu PC -> EC2 -> Pi -> camera) ==" -ForegroundColor Cyan
$tunnel = Start-Process ssh -ArgumentList $sshArgs -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 6
if ($tunnel.HasExited) {
  throw "O tunel caiu ao subir. Rode de novo (as portas sao re-sorteadas a cada execucao)."
}

$rtsp  = "rtsp://${user}:${pass}@localhost:${rtspPort}/cam/realmonitor?channel=1&subtype=0"
$webui = "http://localhost:${httpPort}/"

try {
  # 1) VLC com o stream ao vivo, FORCANDO RTSP sobre TCP (UDP nao passa no tunel).
  $vlc = @(
    "$env:ProgramFiles\VideoLAN\VLC\vlc.exe",
    "${env:ProgramFiles(x86)}\VideoLAN\VLC\vlc.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($vlc) {
    Write-Host "== Abrindo VLC (video ao vivo, RTSP/TCP) ==" -ForegroundColor Green
    Start-Process $vlc -ArgumentList @('--rtsp-tcp','--network-caching=300', $rtsp)
  } else {
    Write-Host "VLC nao encontrado. No seu player, abra (forcando 'RTSP sobre TCP'):" -ForegroundColor Yellow
    Write-Host "   $rtsp"
  }

  # 2) Interface web nativa da camera (live view + painel de zoom).
  Write-Host "== Abrindo a interface da camera: $webui  (login: $user) ==" -ForegroundColor Green
  Start-Process $webui

  # 3) Prompt de zoom (executa o comando 'zoom' instalado na Pi).
  Write-Host ""
  Write-Host "Comandos: <0-1> | reset | in | out | status | snap | q (sair)" -ForegroundColor Cyan
  while ($true) {
    $c = Read-Host 'zoom>'
    if ($c -in @('q','quit','exit')) { break }
    if (-not $c) { $c = 'status' }
    ssh saira-prod "ssh saira@10.8.0.3 'zoom $c'"
  }
}
finally {
  Write-Host "== Fechando tunel ==" -ForegroundColor Cyan
  if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
  ssh saira-prod $cleanup | Out-Null
}
