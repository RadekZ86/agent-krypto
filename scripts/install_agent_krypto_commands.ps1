$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$globalBin = Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'npm'

if (-not (Test-Path $globalBin)) {
    New-Item -ItemType Directory -Path $globalBin -Force | Out-Null
}

$commands = @(
    @{
        Path = Join-Path $globalBin 'agent-krypto.cmd'
        Content = @"
@echo off
call "$projectRoot\scripts\open_agent_krypto.cmd"
"@
    },
    @{
        Path = Join-Path $globalBin 'agent-krypto-server.cmd'
        Content = @"
@echo off
call "$projectRoot\scripts\open_agent_krypto_server.cmd"
"@
    },
    @{
        Path = Join-Path $globalBin 'agent-krypto-test.cmd'
        Content = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$projectRoot\scripts\run_agent_krypto_tests.ps1"
"@
    },
    @{
        Path = Join-Path $globalBin 'agent-krypto-autostart-on.cmd'
        Content = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$projectRoot\scripts\install_agent_krypto_autostart.ps1"
"@
    },
    @{
        Path = Join-Path $globalBin 'agent-krypto-autostart-off.cmd'
        Content = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$projectRoot\scripts\remove_agent_krypto_autostart.ps1"
"@
    },
    @{
        Path = Join-Path $globalBin 'agent-krypto-status.cmd'
        Content = @"
@echo off
powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "$projectRoot\scripts\status_agent_krypto.ps1"
"@
    },
    @{
        Path = Join-Path $globalBin 'agent-krypto-stop.cmd'
        Content = @"
@echo off
powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "$projectRoot\scripts\stop_agent_krypto.ps1"
"@
    },
    @{
        Path = Join-Path $globalBin 'agent-krypto-restart.cmd'
        Content = @"
@echo off
powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "$projectRoot\scripts\restart_agent_krypto.ps1"
"@
    }
)

foreach ($command in $commands) {
    Set-Content -Path $command.Path -Value $command.Content -Encoding ASCII
}

Write-Output "Globalne komendy Agent Krypto zostaly zainstalowane w: $globalBin"
Write-Output 'Dostepne komendy: agent-krypto, agent-krypto-server, agent-krypto-test, agent-krypto-autostart-on, agent-krypto-autostart-off, agent-krypto-status, agent-krypto-stop, agent-krypto-restart'