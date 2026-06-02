$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Main = Join-Path $Root "bin\src\main.py"

if (Test-Path $Pythonw) {
    & $Pythonw $Main @args
    exit $LASTEXITCODE
}

if (Test-Path $Python) {
    & $Python $Main @args
    exit $LASTEXITCODE
}

Write-Error "Python environment not found in $Root\.venv"
