param([string]$PythonPath = '', [string]$PnpmPath = 'pnpm.cmd', [switch]$SkipOcr)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not $PythonPath) {
    if (Get-Command py -ErrorAction SilentlyContinue) { $PythonPath = 'py' }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { $PythonPath = 'python' }
    else { throw 'Install Python 3.12 x64, or pass -PythonPath.' }
}
& $PythonPath -c 'import sys; assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32, "Python 3.12 x64 is required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 validation failed.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $PythonPath -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated Python environment.' }
}
$pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
& $pythonExecutable -c 'import sys; assert sys.prefix != sys.base_prefix'
if ($LASTEXITCODE -ne 0) { throw 'The project interpreter is not an isolated virtual environment.' }
& $pythonExecutable -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
if (-not $SkipOcr) {
    & $pythonExecutable -m pip install -r requirements-ocr.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Local OCR dependency installation failed.' }
    & $pythonExecutable (Join-Path $PSScriptRoot 'verify_resources.py')
    if ($LASTEXITCODE -ne 0) { throw 'OCR resource or Chinese font verification failed.' }
}
if (-not (Get-Command $PnpmPath -ErrorAction SilentlyContinue)) { throw 'Install Node.js 24 x64 and pnpm 11.25.0, or pass -PnpmPath.' }
$pnpmVersion = & $PnpmPath --version
if ($LASTEXITCODE -ne 0 -or $pnpmVersion.Trim() -ne '11.25.0') { throw 'pnpm 11.25.0 is required for the verified lockfile.' }
Push-Location frontend
try {
    & $PnpmPath install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    & $PnpmPath build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Host 'Setup complete. Import the dataset, then run scripts\start.ps1 with -DataDir and -Port.'
