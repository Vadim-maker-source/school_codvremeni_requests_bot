$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$statePath = Join-Path $projectRoot '.local/processes.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'No project process record found'; exit 0 }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ($state.root -ne $projectRoot) { throw 'Process record belongs to another directory' }
function Stop-Children([int]$parentPid) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $parentPid"
    foreach ($child in $children) {
        Stop-Children $child.ProcessId
        Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
foreach ($entry in $state.processes) {
    $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    $started = [DateTime]::Parse($entry.started).ToUniversalTime()
    if ([Math]::Abs(($process.StartTime.ToUniversalTime() - $started).TotalSeconds) -gt 1) { Write-Warning 'PID was reused; skipping'; continue }
    $details = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.pid)"
    $matches = if ($entry.kind -eq 'api') { $details.CommandLine -like '*uvicorn app.main:app*' -and $details.ExecutablePath -like "$projectRoot\backend\*" } elseif ($entry.kind -eq 'bot') { $details.CommandLine -like '*-m app.bot*' -and $details.ExecutablePath -like "$projectRoot\backend\*" } else { $details.CommandLine.Contains((Join-Path $projectRoot 'node_modules/next/dist/bin/next')) -or $details.CommandLine.Contains((Join-Path $projectRoot '.next/standalone/server.js')) }
    if (-not $matches) { Write-Warning 'Process identity did not match; skipping'; continue }
    Stop-Children $entry.pid
    Stop-Process -Id $entry.pid -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped project $($entry.kind) process $($entry.pid)"
}
Remove-Item -LiteralPath $statePath
