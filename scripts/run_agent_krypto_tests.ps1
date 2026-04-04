$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$requirementsDev = Join-Path $projectRoot 'requirements-dev.txt'
$dashboardUrl = 'http://127.0.0.1:8000/api/dashboard'

if (-not (Test-Path $pythonPath)) {
    throw "Nie znaleziono interpretera: $pythonPath"
}

if (-not (Test-Path $requirementsDev)) {
    throw "Nie znaleziono pliku zaleznosci dev: $requirementsDev"
}

Push-Location $projectRoot
try {
    & (Join-Path $projectRoot 'scripts\start_agent_krypto_background.ps1') | Out-Null

    $deadline = (Get-Date).AddSeconds(60)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest $dashboardUrl -TimeoutSec 10 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }

    if (-not $ready) {
        throw 'Serwer Agent Krypto nie odpowiedzial poprawnie na /api/dashboard w ciagu 60 sekund.'
    }

    & $pythonPath -c "import playwright" 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $pythonPath -m pip install -r $requirementsDev
        if ($LASTEXITCODE -ne 0) {
            throw 'Nie udalo sie zainstalowac zaleznosci dev do testow.'
        }
    }

    & $pythonPath -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw 'Nie udalo sie zainstalowac Chromium dla Playwright.'
    }

    & $pythonPath -m unittest tests.test_dashboard_smoke tests.test_frontend_browser_smoke -v
    exit $LASTEXITCODE
} finally {
    Pop-Location
}