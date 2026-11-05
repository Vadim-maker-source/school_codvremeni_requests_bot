param([switch]$Dev)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$localDir = Join-Path $projectRoot '.local'
$statePath = Join-Path $localDir 'processes.json'
New-Item -ItemType Directory -Force -Path $localDir | Out-Null
foreach ($command in @('node', 'npm.cmd', 'python')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Required command is missing: $command" }
}
function Test-Ready($url) {
    try { return (Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200 } catch { return $false }
}
if (Test-Path -LiteralPath $statePath) {
    $old = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $botEntry = @($old.processes | Where-Object { $_.kind -eq 'bot' }) | Select-Object -First 1
    $botAlive = if ($botEntry) { $process = Get-Process -Id $botEntry.pid -ErrorAction SilentlyContinue; $process -and [Math]::Abs(($process.StartTime.ToUniversalTime() - [DateTime]::Parse($botEntry.started).ToUniversalTime()).TotalSeconds) -lt 1 } else { $true }
    if ($botAlive -and (Test-Ready "$($old.api)/api/health") -and (Test-Ready ($old.site.Replace('localhost','127.0.0.1')))) {
        Write-Host "Already running: $($old.site) | Swagger: $($old.api)/docs"
        Write-Host 'Credentials: backend/data/local_credentials.json'
        exit 0
    }
    & (Join-Path $PSScriptRoot 'stop-local.ps1')
}
function Find-FreePort([int]$preferred) {
    for ($candidate = $preferred; $candidate -lt ($preferred + 100); $candidate++) {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $candidate)
        try { $listener.Start(); $listener.Stop(); return $candidate } catch { $listener.Stop() }
    }
    throw 'No free local port found'
}
$apiPort = Find-FreePort 8000
$webPort = Find-FreePort 3000
$pythonExe = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $pythonExe)) { & python -m venv backend/.venv; if ($LASTEXITCODE) { throw 'venv creation failed' } }
    & $pythonExe -c "import importlib.util, sys; sys.exit(0 if all(importlib.util.find_spec(name) is not None for name in ('fastapi', 'sqlalchemy', 'alembic', 'argon2', 'psycopg', 'aiogram')) else 1)"
    if ($LASTEXITCODE) { & $pythonExe -m pip install -r backend/requirements.txt; if ($LASTEXITCODE) { throw 'Python dependency install failed' } }
    if (-not (Test-Path -LiteralPath 'node_modules/next/package.json')) { & npm.cmd ci --no-fund; if ($LASTEXITCODE) { throw 'npm ci failed' } }
    if (-not (Test-Path -LiteralPath 'backend/.env')) { Copy-Item -LiteralPath 'backend/.env.example' -Destination 'backend/.env' }
    $env:ENVIRONMENT = 'local'
    $env:COOKIE_SECURE = 'false'
    # Notification settings are read from backend/.env by both API and bot.
    $env:ALLOWED_ORIGINS = "http://localhost:$webPort,http://127.0.0.1:$webPort"
    $env:API_INTERNAL_URL = "http://127.0.0.1:$apiPort"
    # Import from backend without depending on caller's current directory.
    Push-Location (Join-Path $projectRoot 'backend')
    try {
        $validateDatabase = @'
from sqlalchemy import make_url
from app.config import settings

url = make_url(settings.database_url_resolved)
if not settings.is_sqlite and not (
    url.drivername == 'postgresql+psycopg' and url.host in ('localhost', '127.0.0.1', '::1')
):
    raise SystemExit('Local startup requires SQLite or PostgreSQL on a loopback address')
'@
        & $pythonExe -c $validateDatabase
        if ($LASTEXITCODE) { throw 'Invalid local configuration' }
        & $pythonExe -m app.bootstrap
        if ($LASTEXITCODE) { throw 'Initialization failed' }
    } finally { Pop-Location }
    $buildMarker = Join-Path $localDir 'build-api.txt'
    if (-not $Dev -and ((-not (Test-Path -LiteralPath '.next/BUILD_ID')) -or (-not (Test-Path -LiteralPath $buildMarker)) -or ((Get-Content -LiteralPath $buildMarker -Raw).Trim() -ne $env:API_INTERNAL_URL))) {
        & npm.cmd run build
        if ($LASTEXITCODE) { throw 'Next.js build failed' }
        Set-Content -LiteralPath $buildMarker -Value $env:API_INTERNAL_URL -Encoding UTF8
    }
    $apiProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$apiPort",'--no-access-log') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $localDir 'api.log') -RedirectStandardError (Join-Path $localDir 'api-error.log') -PassThru
    $state = @{ root=$projectRoot; api="http://127.0.0.1:$apiPort"; site="http://localhost:$webPort"; processes=@(@{pid=$apiProcess.Id;started=$apiProcess.StartTime.ToUniversalTime().ToString('o');kind='api'}) }
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $nextCli = Join-Path $projectRoot 'node_modules/next/dist/bin/next'
    if ($Dev) {
        $webArgs = @("`"$nextCli`"",'dev','--hostname','127.0.0.1','--port',"$webPort")
    } else {
        Copy-Item -LiteralPath (Join-Path $projectRoot '.next/static') -Destination (Join-Path $projectRoot '.next/standalone/.next') -Recurse -Force
        Copy-Item -LiteralPath (Join-Path $projectRoot 'public') -Destination (Join-Path $projectRoot '.next/standalone') -Recurse -Force
        $env:HOSTNAME = '127.0.0.1'
        $env:PORT = "$webPort"
        $webArgs = @("`"$(Join-Path $projectRoot '.next/standalone/server.js')`"")
    }
    $webProcess = Start-Process -FilePath (Get-Command node).Source -ArgumentList $webArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $localDir 'web.log') -RedirectStandardError (Join-Path $localDir 'web-error.log') -PassThru
    $state.processes += @{pid=$webProcess.Id;started=$webProcess.StartTime.ToUniversalTime().ToString('o');kind='web'}
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $ready = $false
    for ($attempt=0; $attempt -lt 45; $attempt++) {
        if ((Test-Ready "$($state.api)/api/health") -and (Test-Ready ($state.site.Replace('localhost','127.0.0.1')))) { $ready=$true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Startup failed. Inspect .local/*-error.log, then run scripts/stop-local.ps1' }
    Push-Location (Join-Path $projectRoot 'backend')
    try {
        $botConfigured = & $pythonExe -c "from app.config import settings; print(int(settings.telegram_configured))"
    } finally { Pop-Location }
    if ($botConfigured -eq '1') {
        $botProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m','app.bot') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $localDir 'bot.log') -RedirectStandardError (Join-Path $localDir 'bot-error.log') -PassThru
        $state.processes += @{pid=$botProcess.Id;started=$botProcess.StartTime.ToUniversalTime().ToString('o');kind='bot'}
        $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath -Encoding UTF8
    }
    Write-Host "Site: $($state.site)"
    Write-Host "Swagger: $($state.api)/docs"
    Write-Host 'Credentials: Get-Content backend/data/local_credentials.json'
    Write-Host 'Stop: powershell -ExecutionPolicy Bypass -File scripts/stop-local.ps1'
} finally { Pop-Location }
