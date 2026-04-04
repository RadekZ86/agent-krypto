$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runnerPath = Join-Path $projectRoot 'scripts\run_agent_krypto_server.py'
$logDir = Join-Path $projectRoot 'logs'
$stdoutLog = Join-Path $logDir 'agent_krypto_server_stdout.log'
$stderrLog = Join-Path $logDir 'agent_krypto_server_stderr.log'
$pidFile = Join-Path $logDir 'agent_krypto_server.pid'
$port = 8000
$hostAddress = '0.0.0.0'

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
$serverModeActive = $false

if ($listeningConnection) {
    $listenerPid = [int]$listeningConnection.OwningProcess
    $listenerProcess = $matchingProcesses | Where-Object { $_.ProcessId -eq $listenerPid } | Select-Object -First 1
    if (-not $listenerProcess) {
        throw "Port $port jest juz zajety przez inny proces (PID $listenerPid)."
    }

    $activeProcessIds += $listenerPid
    if ($listenerProcess.CommandLine -like '*--host 0.0.0.0*') {
        $serverModeActive = $true
    }

    $current = $listenerProcess
    while ($current -and $current.ParentProcessId -gt 0) {
        $parent = $matchingProcesses | Where-Object { $_.ProcessId -eq $current.ParentProcessId } | Select-Object -First 1
        if (-not $parent) {
            break
        }
        $activeProcessIds += [int]$parent.ProcessId
        if ($parent.CommandLine -like '*--host 0.0.0.0*') {
            $serverModeActive = $true
        }
        $current = $parent
    }
}

if ($serverModeActive) {
    foreach ($duplicate in $matchingProcesses) {
        if ($activeProcessIds -notcontains [int]$duplicate.ProcessId) {
            Stop-Process -Id $duplicate.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Set-Content -Path $pidFile -Value $activeProcessIds[0]
} else {
    if ($matchingProcesses) {
        $matchingProcesses | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
    }

    $process = Start-Process -FilePath $pythonPath `
        -ArgumentList @("`"$runnerPath`"", '--host', $hostAddress, '--port', "$port") `
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
}

$ipv4List = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -ne 'WellKnown'
    } |
    Select-Object -ExpandProperty IPAddress -Unique

Write-Output 'Agent Krypto dziala jako serwer w tle.'
Write-Output 'Lokalnie: http://127.0.0.1:8000'
foreach ($ip in $ipv4List) {
    Write-Output ("LAN: http://{0}:{1}" -f $ip, $port)
}
Write-Output 'Poza domem uzyj Tailscale albo Cloudflare Tunnel. Szczegoly: docs\\remote-access.md'