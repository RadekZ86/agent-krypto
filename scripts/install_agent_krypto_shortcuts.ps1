$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$desktopPath = [Environment]::GetFolderPath('Desktop')
$startMenuPrograms = Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'Microsoft\Windows\Start Menu\Programs\Agent Krypto'
$shell = New-Object -ComObject WScript.Shell

if (-not (Test-Path $startMenuPrograms)) {
    New-Item -ItemType Directory -Path $startMenuPrograms -Force | Out-Null
}

$shortcuts = @(
    @{
        Path = Join-Path $desktopPath 'Agent Krypto Lokalnie.lnk'
        Target = Join-Path $projectRoot 'scripts\open_agent_krypto.cmd'
        Description = 'Uruchamia Agent Krypto lokalnie i otwiera panel w przegladarce.'
    },
    @{
        Path = Join-Path $desktopPath 'Agent Krypto Serwer.lnk'
        Target = Join-Path $projectRoot 'scripts\open_agent_krypto_server.cmd'
        Description = 'Uruchamia Agent Krypto jako serwer i otwiera panel lokalnie.'
    },
    @{
        Path = Join-Path $startMenuPrograms 'Agent Krypto Lokalnie.lnk'
        Target = Join-Path $projectRoot 'scripts\open_agent_krypto.cmd'
        Description = 'Uruchamia Agent Krypto lokalnie i otwiera panel w przegladarce.'
    },
    @{
        Path = Join-Path $startMenuPrograms 'Agent Krypto Serwer.lnk'
        Target = Join-Path $projectRoot 'scripts\open_agent_krypto_server.cmd'
        Description = 'Uruchamia Agent Krypto jako serwer i otwiera panel lokalnie.'
    },
    @{
        Path = Join-Path $startMenuPrograms 'Agent Krypto Status.lnk'
        Target = Join-Path $projectRoot 'scripts\status_agent_krypto.cmd'
        Description = 'Pokazuje status procesu, schedulera i autostartu Agent Krypto.'
    },
    @{
        Path = Join-Path $startMenuPrograms 'Agent Krypto Restart.lnk'
        Target = Join-Path $projectRoot 'scripts\restart_agent_krypto.cmd'
        Description = 'Restartuje Agent Krypto w ostatnio wykrytym trybie.'
    },
    @{
        Path = Join-Path $startMenuPrograms 'Agent Krypto Stop.lnk'
        Target = Join-Path $projectRoot 'scripts\stop_agent_krypto.cmd'
        Description = 'Zatrzymuje proces Agent Krypto w tle.'
    }
)

foreach ($item in $shortcuts) {
    $shortcut = $shell.CreateShortcut($item.Path)
    $shortcut.TargetPath = $item.Target
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = $item.Description
    $shortcut.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,220"
    $shortcut.Save()
}

Write-Output 'Skroty Agent Krypto zostaly utworzone na pulpicie i w menu Start.'