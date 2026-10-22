param(
    [ValidateSet('ble', 'demo', 'off')]
    [string]$Mode = 'ble',
    [int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run uv sync first.' }
$envPath = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) { throw 'Run python scripts/bootstrap.py first.' }
foreach ($line in Get-Content -LiteralPath $envPath) {
    if ($line -match '^(SENSOGRID_[A-Z0-9_]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
    }
}
& docker compose -f compose.yaml -f compose.windows.yaml up -d --wait influxdb
if ($LASTEXITCODE -ne 0) { throw 'InfluxDB did not start.' }
$env:SENSOGRID_MODE = $Mode
$env:SENSOGRID_DATA_DIR = Join-Path $projectRoot 'data'
$env:SENSOGRID_STATIC_DIR = Join-Path $projectRoot 'frontend/dist'
$env:SENSOGRID_INFLUX_URL = 'http://127.0.0.1:8181'
& $pythonPath -m uvicorn sensogrid.main:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
