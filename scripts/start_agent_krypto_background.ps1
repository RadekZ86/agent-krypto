$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runnerPath = Join-Path $projectRoot 'scripts\run_agent_krypto_server.py'
$logDir = Join-Path $projectRoot 'logs'
$stdoutLog = Join-Path $logDir 'agent_krypto_stdout.log'
$stderrLog = Join-Path $logDir 'agent_krypto_stderr.log'
$pidFile = Join-Path $logDir 'agent_krypto_local.pid'
$port = 8000

if (-not (Test-Path $pythonPath)) {
    throw "Nie znaleziono interpretera: $pythonPath"
}

if (-not (Test-Path $runnerPath)) {
    throw "Nie znaleziono runnera serwera: $runnerPath"
}

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$matchingProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and ($_.CommandLine -like '*run_agent_krypto_server.py*--port 8000*' -or $_.CommandLine -like '*uvicorn*app.main:app*--port 8000*')
}

$listeningConnection = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$activeProcessIds = @()

if ($listeningConnection) {
    $listenerPid = [int]$listeningConnection.OwningProcess
    $listenerProcess = $matchingProcesses | Where-Object { $_.ProcessId -eq $listenerPid } | Select-Object -First 1
    if (-not $listenerProcess) {
        throw "Port $port jest juz zajety przez inny proces (PID $listenerPid)."
    }

    $activeProcessIds += $listenerPid
    $current = $listenerProcess
    while ($current -and $current.ParentProcessId -gt 0) {
        $parent = $matchingProcesses | Where-Object { $_.ProcessId -eq $current.ParentProcessId } | Select-Object -First 1
        if (-not $parent) {
            break
        }
        $activeProcessIds += [int]$parent.ProcessId
        $current = $parent
    }

    foreach ($duplicate in $matchingProcesses) {
        if ($activeProcessIds -notcontains [int]$duplicate.ProcessId) {
            Stop-Process -Id $duplicate.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }

    Set-Content -Path $pidFile -Value $listenerPid
    Write-Output 'Agent Krypto dziala w tle lub zostal wlasnie uruchomiony.'
    return
}

if ($matchingProcesses) {
    $matchingProcesses | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

$process = Start-Process -FilePath $pythonPath `
    -ArgumentList @("`"$runnerPath`"", '--host', '127.0.0.1', '--port', "$port") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

Start-Sleep -Seconds 3
$listeningConnection = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listeningConnection) {
    Set-Content -Path $pidFile -Value ([int]$listeningConnection.OwningProcess)
} else {
    Set-Content -Path $pidFile -Value $process.Id
}

Write-Output 'Agent Krypto dziala w tle lub zostal wlasnie uruchomiony.'