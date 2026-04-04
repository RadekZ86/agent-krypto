$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$port = 8000
$localPidFile = Join-Path $projectRoot 'logs\agent_krypto_local.pid'
$serverPidFile = Join-Path $projectRoot 'logs\agent_krypto_server.pid'
$taskName = 'Agent Krypto Autostart'

$matchingProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and ($_.CommandLine -like '*run_agent_krypto_server.py*--port 8000*' -or $_.CommandLine -like '*uvicorn*app.main:app*--port 8000*')
}

$listeningConnection = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$listenerPid = if ($listeningConnection) { [int]$listeningConnection.OwningProcess } else { $null }
$listenerProcess = if ($listenerPid) {
    $matchingProcesses | Where-Object { $_.ProcessId -eq $listenerPid } | Select-Object -First 1
} else {
    $null
}

$mode = 'offline'
if ($listenerProcess) {
    $mode = if ($listenerProcess.CommandLine -like '*--host 0.0.0.0*') { 'server' } else { 'local' }
} elseif ($matchingProcesses) {
    $serverCandidate = $matchingProcesses | Where-Object { $_.CommandLine -like '*--host 0.0.0.0*' } | Select-Object -First 1
    $mode = if ($serverCandidate) { 'server-starting' } else { 'local-starting' }
}

$dashboard = $null
$dashboardError = $null
try {
    $dashboard = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/dashboard" -TimeoutSec 15
} catch {
    $dashboardError = $_.Exception.Message
}

$autostartTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

Write-Output '=== Agent Krypto Status ==='
Write-Output ("Status procesu: {0}" -f ($(if ($listenerProcess) { 'DZIALA' } elseif ($matchingProcesses) { 'STARTUJE' } else { 'STOP' })))
Write-Output ("Tryb: {0}" -f $mode)
Write-Output ("Port 8000: {0}" -f ($(if ($listeningConnection) { 'LISTEN' } else { 'BRAK' })))
Write-Output ("Procesy python: {0}" -f @($matchingProcesses).Count)

if ($listenerProcess) {
    Write-Output ("Listener PID: {0}" -f $listenerProcess.ProcessId)
    Write-Output ("Komenda: {0}" -f $listenerProcess.CommandLine)
}

if (Test-Path $localPidFile) {
    Write-Output ("PID local file: {0}" -f (Get-Content $localPidFile -ErrorAction SilentlyContinue | Select-Object -First 1))
}
if (Test-Path $serverPidFile) {
    Write-Output ("PID server file: {0}" -f (Get-Content $serverPidFile -ErrorAction SilentlyContinue | Select-Object -First 1))
}

if ($dashboard) {
    $scheduler = $dashboard.system_status.scheduler
    Write-Output ''
    Write-Output '--- Dashboard ---'
    Write-Output ("Scheduler active: {0}" -f $scheduler.active)
    Write-Output ("Scheduler running now: {0}" -f $scheduler.is_running)
    Write-Output ("Scheduler health: {0}" -f $scheduler.health)
    Write-Output ("Total runs: {0}" -f $scheduler.total_runs)
    Write-Output ("Last completed: {0}" -f $scheduler.last_run_completed_at)
    Write-Output ("Last error: {0}" -f ($(if ($scheduler.last_error) { $scheduler.last_error } else { '-' })))
    Write-Output ("Panel: http://127.0.0.1:$port")
} elseif ($dashboardError) {
    Write-Output ''
    Write-Output '--- Dashboard ---'
    Write-Output ("API niedostepne: {0}" -f $dashboardError)
}

Write-Output ''
Write-Output '--- Autostart ---'
if ($autostartTask) {
    Write-Output ("Task Scheduler: {0} ({1})" -f $autostartTask.TaskName, $autostartTask.State)
} else {
    Write-Output 'Task Scheduler: OFF'
}