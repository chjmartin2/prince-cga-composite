@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python 3 was not found.
    pause
    exit /b 1
)

py -3 -m unittest discover -s tests -v
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
echo All tests passed.
pause
