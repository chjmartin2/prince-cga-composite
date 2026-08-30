@echo off
setlocal
cd /d "%~dp0"

where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0PrinceDATViewer.pyw" %*
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    start "" py -3 "%~dp0PrinceDATViewer.pyw" %*
    exit /b 0
)

echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/windows/
echo Keep the default Tcl/Tk and IDLE feature enabled.
pause
exit /b 1
