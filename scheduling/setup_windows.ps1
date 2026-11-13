# One-time setup on the always-on PC (the same one that runs the Safety Health Report).
# Run from the project folder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scheduling\setup_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Install Python 3.11+ from python.org first (tick 'Add to PATH')." }
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
New-Item -ItemType Directory -Force logs, out, data | Out-Null
if (-not (Test-Path .env)) {
    $safety = Join-Path (Split-Path (Get-Location) -Parent) "hcs-safety-report\.env"
    if (Test-Path $safety) {
        Copy-Item $safety .env
        Write-Host "Copied Procore credentials from $safety (same service account as the Safety Health Report)." -ForegroundColor Yellow
    } else {
        Copy-Item .env.example .env
        Write-Host "Created .env - open it and fill in the Procore client ID and secret." -ForegroundColor Yellow
    }
}
Write-Host "Setup done. Test with:  .\.venv\Scripts\python.exe -m report --no-email" -ForegroundColor Green
