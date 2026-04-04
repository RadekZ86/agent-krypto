$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$port = 8000
$pidFiles = @(
    (Join-Path $projectRoot 'logs\agent_krypto_local.pid'),
    (Join-Path $projectRoot 'logs\agent_krypto_server.pid')
)

$matchingProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and ($_.CommandLine -like '*run_agent_krypto_server.py*--port 8000*' -or $_.CommandLine -like '*uvicorn*app.main:app*--port 8000*')
}

if (-not $matchingProcesses) {
    foreach ($pidFile in $pidFiles) {
        if (Test-Path $pidFile) {
            Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Output 'Agent Krypto nie byl uruchomiony.'
    return
}

$stopped = @()
foreach ($process in $matchingProcesses | Sort-Object ProcessId -Descending) {
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        $stopped += [int]$process.ProcessId
    } catch {
    }
}

Start-Sleep -Seconds 2

foreach ($pidFile in $pidFiles) {
    if (Test-Path $pidFile) {
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    throw "Port $port nadal jest zajety przez PID $($listener.OwningProcess)."
}

if ($stopped.Count -eq 0) {
    Write-Output 'Nie udalo sie zatrzymac zadnego procesu Agent Krypto.'
    exit 1
}

Write-Output ("Agent Krypto zatrzymany. PID: {0}" -f (($stopped | Sort-Object) -join ', '))