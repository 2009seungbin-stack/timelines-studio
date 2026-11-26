# TIMELINES Studio launcher: installs missing parts on first run, builds the UI if needed, starts the server.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    uv venv .venv --python 3.10 --system-site-packages
    uv pip install --python .venv\Scripts\python.exe -r requirements.txt
}
if (-not (Test-Path "frontend\out\index.html")) {
    Push-Location frontend
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
    Pop-Location
}
$env:PYTHONPATH = "$root\backend"
Start-Process "http://127.0.0.1:8790/"
& .venv\Scripts\python.exe -m timelines.cli serve
