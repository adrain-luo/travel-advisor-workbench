param([ValidateRange(1024,65535)][int]$Port = 8765, [string]$DataDir = '', [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe') -or -not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
    throw 'Run scripts\setup.ps1 before starting the workbench.'
}
if (-not $DataDir) {
    $DataDir = if ($env:TRAVEL_DATA_DIR) { $env:TRAVEL_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'TravelAdvisorWorkbench\data' }
}
$DataDir = [IO.Path]::GetFullPath($DataDir)
$runtimeDirectory = Join-Path $projectRoot ".local\instances\$Port"
$pidFile = Join-Path $runtimeDirectory 'server.json'
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    if (Test-Path -LiteralPath $pidFile) {
        $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
            if ($health.status -eq 'ok' -and $health.instance_id -eq $record.instanceId -and [IO.Path]::GetFullPath($health.data_dir) -eq $DataDir) {
                Write-Host "Workbench already running at http://127.0.0.1:$Port"
                if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
                exit 0
            }
        } catch { }
    }
    throw "Port $Port is occupied by another instance. Choose an unused port."
}
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
$previousDataDir = $env:TRAVEL_DATA_DIR
try {
    $env:TRAVEL_DATA_DIR = $DataDir
    $server = Start-Process -FilePath $pythonExecutable -ArgumentList @('-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDirectory 'server.log') -RedirectStandardError (Join-Path $runtimeDirectory 'server-error.log') -PassThru
} finally { $env:TRAVEL_DATA_DIR = $previousDataDir }
$record = @{pid=$server.Id; port=$Port; dataDir=$DataDir; executable=$pythonExecutable; startedAt=$server.StartTime.ToUniversalTime().ToString('o'); instanceId=''}
$record | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 400
    if ($server.HasExited) { throw "Startup failed. See $runtimeDirectory\server-error.log" }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($health.status -eq 'ok' -and [IO.Path]::GetFullPath($health.data_dir) -eq $DataDir) { $ready = $true; break }
    } catch { }
}
if (-not $ready) { throw "Server has not become ready. See $runtimeDirectory\server-error.log" }
$record.instanceId = $health.instance_id
$record | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
Write-Host "Workbench: http://127.0.0.1:$Port"
Write-Host "Data directory: $($health.data_dir)"
Write-Host "Live collection enabled: $($health.live_collection_enabled)"
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
