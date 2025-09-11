param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv/Scripts/python.exe')) { python -m venv .venv }
& ./.venv/Scripts/python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
$env:APP_ORIGIN = "http://127.0.0.1:$Port"
Write-Host "Open http://127.0.0.1:$Port after startup. Create accounts in another terminal using the README."
& ./.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
