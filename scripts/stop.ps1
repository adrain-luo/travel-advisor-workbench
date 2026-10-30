param([ValidateRange(1024,65535)][int]$Port = 8765, [string]$DataDir = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot ".local\instances\$Port\server.json"
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host 'No managed instance is recorded for this port.'; exit 0 }
$serverInfo = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
if ($DataDir -and [IO.Path]::GetFullPath($DataDir) -ne [IO.Path]::GetFullPath($serverInfo.dataDir)) { throw 'The requested data directory does not match the recorded instance.' }
$server = Get-CimInstance Win32_Process -Filter "ProcessId = $($serverInfo.pid)"
if ($server) {
    $process = Get-Process -Id $serverInfo.pid
    $expectedStart = ([DateTime]$serverInfo.startedAt).ToUniversalTime()
    $portPattern = '--port\s+' + $Port + '(?:\s|$)'
    if ($server.ExecutablePath -ne $serverInfo.executable -or $server.CommandLine -notmatch 'uvicorn backend\.app:app' -or $server.CommandLine -notmatch $portPattern -or [Math]::Abs(($process.StartTime.ToUniversalTime() - $expectedStart).TotalSeconds) -gt 1) {
        throw 'Recorded process identity no longer matches; no process was stopped.'
    }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        if ($serverInfo.instanceId -and $health.instance_id -ne $serverInfo.instanceId) { throw 'Instance identity mismatch.' }
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/api/background/shutdown" -TimeoutSec 50 | Out-Null
    } catch { Write-Host 'Health/shutdown endpoint was unavailable; stopping only the verified owned process tree.' }
    $serverChildren = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($serverInfo.pid)" | Where-Object {
        $_.Name -eq 'python.exe' -and $_.CommandLine -match 'uvicorn backend\.app:app' -and $_.CommandLine -match $portPattern -and
        ([DateTime]$_.CreationDate).ToUniversalTime() -ge $expectedStart.AddSeconds(-1)
    })
    foreach ($serverChild in $serverChildren) { Stop-Process -Id $serverChild.ProcessId -ErrorAction SilentlyContinue }
    Stop-Process -Id $serverInfo.pid -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $pidFile
Write-Host 'The selected workbench instance stopped. Stored data is preserved.'
