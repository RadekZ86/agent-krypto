param(
    [switch]$ServerMode
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$stopScript = Join-Path $projectRoot 'scripts\stop_agent_krypto.ps1'
$startLocalScript = Join-Path $projectRoot 'scripts\start_agent_krypto_background.ps1'
$startServerScript = Join-Path $projectRoot 'scripts\start_agent_krypto_server.ps1'

$matchingProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and ($_.CommandLine -like '*run_agent_krypto_server.py*--port 8000*' -or $_.CommandLine -like '*uvicorn*app.main:app*--port 8000*')
}

$detectedServerMode = $matchingProcesses | Where-Object { $_.CommandLine -like '*--host 0.0.0.0*' } | Select-Object -First 1
$mode = if ($ServerMode -or $detectedServerMode) { 'server' } else { 'local' }

& $stopScript
Start-Sleep -Seconds 1

if ($mode -eq 'server') {
    & $startServerScript
} else {
    & $startLocalScript
}

Write-Output ("Agent Krypto zrestartowany w trybie: {0}" -f $mode)