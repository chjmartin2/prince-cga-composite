$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "Prince CGA Composite workspace setup" -ForegroundColor Cyan

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found. Install Git for Windows, then run setup again."
}

$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonLauncher -and -not $pythonCommand) {
    throw "Python 3.10 or newer was not found. Install Python, including Tcl/Tk, then run setup again."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if ($pythonLauncher) {
        & py -3 -m venv .venv
    } else {
        & python -m venv .venv
    }
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$versionText = & $venvPython --version 2>&1
Write-Host "Using $versionText"

Write-Host "Running Prince DAT Explorer tests..." -ForegroundColor Cyan
Push-Location (Join-Path $projectRoot "editor")
try {
    & $venvPython -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) {
        throw "Editor tests failed."
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Workspace is ready." -ForegroundColor Green
Write-Host "Next: run OPEN_IN_VSCODE.bat and open the Codex sidebar."

