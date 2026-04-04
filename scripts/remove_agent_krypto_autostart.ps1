$ErrorActionPreference = 'Stop'

$taskName = 'Agent Krypto Autostart'
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if (-not $existingTask) {
    Write-Output 'Autostart Agent Krypto nie byl wlaczony.'
    return
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Output 'Autostart Agent Krypto zostal wylaczony.'