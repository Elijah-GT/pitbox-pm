# Start Pit Box. First run creates the venv and installs dependencies.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

# Local run, so no Cloudflare Tunnel is in front: run wide open. Production
# leaves PITBOX_AUTH_MODE unset, which defaults to cloudflare and then
# requires the two PITBOX_ACCESS_* values -- see docs/CLOUDFLARE.md.
$env:PITBOX_AUTH_MODE = "none"

Write-Host "Pit Box running at http://127.0.0.1:8000" -ForegroundColor Green
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
