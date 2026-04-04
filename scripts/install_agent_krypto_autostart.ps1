$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherPath = Join-Path $projectRoot 'scripts\start_agent_krypto_background.ps1'
$taskName = 'Agent Krypto Autostart'
$currentUser = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }

if (-not (Test-Path $launcherPath)) {
    throw "Nie znaleziono launchera: $launcherPath"
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcherPath`""

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances Ignore `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'Uruchamia Agent Krypto w tle po zalogowaniu uzytkownika.' `
    -Force | Out-Null

Write-Output "Autostart Agent Krypto zostal wlaczony dla uzytkownika: $currentUser"
Write-Output "Task Scheduler: $taskName"
Write-Output 'Po nastepnym logowaniu system odpali launcher w tle bez otwierania przegladarki.'
